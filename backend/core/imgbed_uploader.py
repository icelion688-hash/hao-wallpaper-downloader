"""
imgbed_uploader.py - 通用图床上传器。

说明：
1. 保留服务端压缩开关 `serverCompress`
2. `image_processing.format=webp` 时，本地预处理会转 WebP
3. `image_processing.format=original` 时，保持原始格式直接上传
4. 当原图大于 `disable_above_mb` 时，跳过本地预处理
"""

from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

import httpx
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImageProcessingConfig:
    enabled: bool = True
    telegram_only: bool = True
    format: str = "webp"
    quality: int = 86
    min_quality: int = 72
    threshold_mb: float = 5.0
    target_mb: float = 4.0
    disable_above_mb: float = 10.0

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ImageProcessingConfig":
        payload = data or {}
        return cls(
            enabled=bool(payload.get("enabled", True)),
            telegram_only=bool(payload.get("telegram_only", True)),
            format=str(payload.get("format", "webp")).lower(),
            quality=int(payload.get("quality", 86)),
            min_quality=int(payload.get("min_quality", 72)),
            threshold_mb=float(payload.get("threshold_mb", 5.0)),
            target_mb=float(payload.get("target_mb", 4.0)),
            disable_above_mb=float(payload.get("disable_above_mb", 10.0)),
        )


class ImgbedUploader:
    FOLDER_PC = "bg/pc"
    FOLDER_MB = "bg/mb"

    # 上传最大重试次数（首次 + 1 次重试）
    _MAX_RETRIES = 2
    # 重试前等待时间（秒）
    _RETRY_DELAY = 3.0

    def __init__(
        self,
        base_url: str,
        api_token: str,
        compress: bool = True,
        channel: str = "telegram",
        image_processing: Optional[dict] = None,
        profile_key: Optional[str] = None,
        profile_name: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.compress = compress
        self.channel = channel or "telegram"
        self.image_processing = ImageProcessingConfig.from_dict(image_processing)
        self.profile_key = profile_key or ""
        self.profile_name = profile_name or self.profile_key or "upload"
        # 持久 HTTP client：复用连接池，避免每次上传重新握手
        self._client: Optional[httpx.AsyncClient] = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """懒初始化持久 client（连接异常时自动重建）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._client

    async def aclose(self) -> None:
        """关闭持久 client，在应用 lifespan 结束时调用"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _determine_folder(self, width: Optional[int], height: Optional[int]) -> str:
        if width and height and height > width:
            return self.FOLDER_MB
        return self.FOLDER_PC

    async def upload(
        self,
        local_path: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Optional[str]:
        if not os.path.exists(local_path):
            logger.warning("[Imgbed] file not found: %s", local_path)
            return None

        folder = self._determine_folder(width, height)
        upload_url = f"{self.base_url}/upload"
        params = {
            "uploadChannel": self.channel,
            "uploadFolder": folder,
            "serverCompress": "true" if self.compress else "false",
            "returnFormat": "full",
        }
        headers = {"Authorization": f"Bearer {self.api_token}"}

        upload_path = local_path
        upload_name = os.path.basename(local_path)
        temp_path = self._prepare_upload_file(local_path)
        if temp_path:
            upload_path = temp_path
            upload_name = os.path.basename(temp_path)

        try:
            for attempt in range(1, self._MAX_RETRIES + 1):
                try:
                    client = self._ensure_client()
                    # 明确传递 MIME type，否则 httpx 默认 application/octet-stream，
                    # 导致图床以错误类型存储，浏览器收到后只能下载而无法内联显示。
                    # mimetypes 在 Windows 上不含 .webp，需要手动补充。
                    _EXT_MIME = {
                        ".webp": "image/webp",
                        ".jpg":  "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png":  "image/png",
                        ".gif":  "image/gif",
                        ".mp4":  "video/mp4",
                        ".webm": "video/webm",
                    }
                    _ext = os.path.splitext(upload_name)[1].lower()
                    mime_type = _EXT_MIME.get(_ext) or mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
                    with open(upload_path, "rb") as fh:
                        resp = await client.post(
                            upload_url,
                            params=params,
                            headers=headers,
                            files={"file": (upload_name, fh, mime_type)},
                        )
                    resp.raise_for_status()
                    data = resp.json()

                    if isinstance(data, list) and data and data[0].get("src"):
                        src = data[0]["src"]
                        return src if src.startswith("http") else f"{self.base_url}{src}"

                    logger.warning("[Imgbed] unexpected response: %s", data)
                    return None

                except httpx.HTTPStatusError as e:
                    logger.error(
                        "[Imgbed] upload failed status=%s file=%s body=%s (attempt %d/%d)",
                        e.response.status_code, upload_name, e.response.text[:200],
                        attempt, self._MAX_RETRIES,
                    )
                    # 4xx 错误不重试（token 无效、权限问题等）
                    if 400 <= e.response.status_code < 500:
                        return None
                    # 重建 client（服务端关闭了旧连接）
                    self._client = None
                except Exception as e:
                    logger.error(
                        "[Imgbed] upload exception file=%s error=%r (attempt %d/%d)",
                        upload_name, e, attempt, self._MAX_RETRIES,
                    )
                    self._client = None

                if attempt < self._MAX_RETRIES:
                    await asyncio.sleep(self._RETRY_DELAY)

            return None
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.warning("[Imgbed] failed to remove temp file: %s", temp_path)

    def _prepare_upload_file(self, local_path: str) -> Optional[str]:
        cfg = self.image_processing
        if not cfg.enabled:
            return None
        if cfg.telegram_only and self.channel.lower() != "telegram":
            return None
        if cfg.format == "original":
            return None
        if cfg.format != "webp":
            logger.warning("[Imgbed] unsupported local format: %s", cfg.format)
            return None

        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        if size_mb > cfg.disable_above_mb:
            logger.info("[Imgbed] skip local processing over limit: %.2fMB", size_mb)
            return None

        return self._compress_to_webp(local_path, cfg, size_mb)

    def _compress_to_webp(
        self,
        local_path: str,
        cfg: ImageProcessingConfig,
        source_mb: float,
    ) -> Optional[str]:
        """
        将图片压缩为 WebP 并写入临时文件。

        对于大文件（> threshold_mb），在内存中对质量参数做二分搜索，
        找到满足 file_size <= target_bytes 的最高质量，最终只写一次磁盘。
        相比原来的线性扫描多次写磁盘，可减少约 80% 的磁盘 I/O。

        编码 method 使用 4（原为 6），速度约快 2-3×，质量损失可忽略不计。
        """
        target_bytes = int(cfg.target_mb * 1024 * 1024)
        quality = max(cfg.min_quality, min(cfg.quality, 100))
        min_quality = max(10, min(cfg.min_quality, quality))

        filename = os.path.splitext(os.path.basename(local_path))[0]
        fd, temp_path = tempfile.mkstemp(prefix=f"{filename}_", suffix=".webp")
        os.close(fd)

        try:
            with Image.open(local_path) as img:
                img = ImageOps.exif_transpose(img)
                save_image = (
                    img if img.mode in {"RGB", "RGBA"}
                    else img.convert("RGBA" if "A" in img.getbands() else "RGB")
                )

                # 小文件：直接按目标质量写磁盘，只写一次
                if source_mb <= cfg.threshold_mb:
                    save_image.save(temp_path, format="WEBP", quality=quality, method=4)
                    return temp_path

                # 大文件：在内存中二分搜索「满足 target_bytes 的最高质量」
                # quality 越高 → 文件越大，单调递增，二分有效
                lo, hi = min_quality, quality
                best_buf: Optional[bytes] = None

                while lo <= hi:
                    mid = (lo + hi) // 2
                    buf = io.BytesIO()
                    save_image.save(buf, format="WEBP", quality=mid, method=4)
                    size = buf.tell()

                    if size <= target_bytes:
                        # 当前质量满足，记录结果并尝试更高质量
                        best_buf = buf.getvalue()
                        lo = mid + 1
                    else:
                        # 太大，降低质量
                        hi = mid - 1

                if best_buf is None:
                    # 所有质量都超出目标，使用最低质量（文件最小）
                    buf = io.BytesIO()
                    save_image.save(buf, format="WEBP", quality=min_quality, method=4)
                    best_buf = buf.getvalue()

                with open(temp_path, "wb") as f:
                    f.write(best_buf)
                return temp_path

        except Exception as e:
            logger.error("[Imgbed] 压缩转换失败 file=%s error=%r", local_path, e)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return None
