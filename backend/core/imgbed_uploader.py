"""
imgbed_uploader.py - 通用图床上传器。

说明：
1. 保留服务端压缩开关 `serverCompress`
2. `image_processing.format=webp` 时，本地预处理会转 WebP
3. `image_processing.format=original` 时，保持原始格式直接上传
4. 当原图大于 `disable_above_mb` 时，跳过本地预处理
5. 支持按横/竖/动态图分别配置上传目录，支持路径模板变量
6. 支持上传过滤：最小宽/高、仅上传原图
"""

from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import httpx
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


# ── 路径模板变量说明 ────────────────────────────────────────────────────────
# {type}      壁纸类型（static / dynamic）
# {category}  分类名称（动漫｜二次元 / 风景 …）；含特殊字符会被清理为文件系统安全字符串
# {year}      当前年份（4 位）
# {month}     当前月份（2 位，01-12）
# {date}      当前日期（8 位，20250317）
# 示例：bg/{type}/{year}/{month}  →  bg/static/2025/03
# ────────────────────────────────────────────────────────────────────────────


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


@dataclass(slots=True)
class UploadFilterConfig:
    """上传过滤器：不满足条件的图片跳过上传"""
    min_width: Optional[int] = None    # 最小宽度（像素），None 表示不限
    min_height: Optional[int] = None   # 最小高度（像素），None 表示不限
    only_original: bool = False        # True 时仅上传通过 getCompleteUrl 的原图

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "UploadFilterConfig":
        payload = data or {}
        return cls(
            min_width=int(payload["min_width"]) if payload.get("min_width") else None,
            min_height=int(payload["min_height"]) if payload.get("min_height") else None,
            only_original=bool(payload.get("only_original", False)),
        )

    def check(
        self,
        width: Optional[int],
        height: Optional[int],
        is_original: bool = False,
    ) -> tuple[bool, str]:
        """
        返回 (pass, reason)。
        pass=True 表示允许上传；pass=False 附带跳过原因。
        """
        if self.only_original and not is_original:
            return False, "非原图，跳过上传（only_original=true）"
        if self.min_width and width and width < self.min_width:
            return False, f"宽度 {width} < 最小宽度 {self.min_width}"
        if self.min_height and height and height < self.min_height:
            return False, f"高度 {height} < 最小高度 {self.min_height}"
        return True, ""


# 文件系统不安全字符正则（用于清理 category 中的特殊字符）
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_path_segment(value: str) -> str:
    """将字符串转为文件系统安全的路径段（保留中文、字母、数字、连字符、下划线）"""
    cleaned = _UNSAFE_CHARS.sub("_", value).strip()
    return cleaned or "unknown"


class ImgbedUploader:
    # 默认目录（向后兼容）
    _DEFAULT_LANDSCAPE = "bg/pc"
    _DEFAULT_PORTRAIT  = "bg/mb"
    _DEFAULT_DYNAMIC   = "bg/dynamic"

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
        # ── 目录配置 ──────────────────────────────────────────────────────
        folder_landscape: str = "",   # 横图目录，空 = 使用默认
        folder_portrait: str = "",    # 竖图目录，空 = 使用默认
        folder_dynamic: str = "",     # 动态图目录，空 = 使用默认
        folder_pattern: str = "",     # 路径模板（非空时优先，支持变量）
        # ── 上传过滤 ──────────────────────────────────────────────────────
        upload_filter: Optional[dict] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.compress = compress
        self.channel = channel or "telegram"
        self.image_processing = ImageProcessingConfig.from_dict(image_processing)
        self.profile_key = profile_key or ""
        self.profile_name = profile_name or self.profile_key or "upload"
        # 目录配置
        self.folder_landscape = folder_landscape or self._DEFAULT_LANDSCAPE
        self.folder_portrait  = folder_portrait  or self._DEFAULT_PORTRAIT
        self.folder_dynamic   = folder_dynamic   or self._DEFAULT_DYNAMIC
        self.folder_pattern   = folder_pattern   or ""
        # 上传过滤
        self.upload_filter = UploadFilterConfig.from_dict(upload_filter)
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

    @staticmethod
    def _resolve_pattern(
        pattern: str,
        wallpaper_type: str,
        category: str,
    ) -> str:
        """
        将路径模板中的变量替换为实际值。
        支持：{type} {category} {year} {month} {date}
        """
        now = datetime.now()
        safe_category = _safe_path_segment(category) if category else "uncategorized"
        return (
            pattern
            .replace("{type}", wallpaper_type or "static")
            .replace("{category}", safe_category)
            .replace("{year}", now.strftime("%Y"))
            .replace("{month}", now.strftime("%m"))
            .replace("{date}", now.strftime("%Y%m%d"))
        )

    def _determine_folder(
        self,
        width: Optional[int],
        height: Optional[int],
        wallpaper_type: str = "static",
        category: str = "",
    ) -> str:
        """
        确定上传目录。优先级：
        1. folder_pattern（非空时用模板替换）
        2. 按类型/方向分目录：
           - wallpaper_type == "dynamic" → folder_dynamic
           - height > width（竖图）→ folder_portrait
           - 其他（横图/方图）→ folder_landscape
        """
        if self.folder_pattern:
            return self._resolve_pattern(self.folder_pattern, wallpaper_type, category)

        if wallpaper_type == "dynamic":
            return self.folder_dynamic
        if width and height and height > width:
            return self.folder_portrait
        return self.folder_landscape

    async def upload(
        self,
        local_path: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        wallpaper_type: str = "static",
        category: str = "",
        is_original: bool = False,
    ) -> Optional[str]:
        if not os.path.exists(local_path):
            logger.warning("[Imgbed] file not found: %s", local_path)
            return None

        # 上传过滤检查
        ok, reason = self.upload_filter.check(width, height, is_original)
        if not ok:
            logger.info("[Imgbed] 跳过上传 file=%s reason=%s", os.path.basename(local_path), reason)
            return None

        folder = self._determine_folder(width, height, wallpaper_type, category)
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
