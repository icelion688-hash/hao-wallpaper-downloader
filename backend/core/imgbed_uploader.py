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
import json
import logging
import mimetypes
import os
import re
import tempfile
from urllib.parse import quote, urlencode
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from PIL import Image, ImageOps
from backend.core.upload_record_helper import normalize_remote_tag

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


def _normalize_tags(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[,\n|]+", value)
    else:
        items = list(value)
    return [str(item).strip() for item in items if str(item).strip()]


def _trim_joined_segment(parts: list[str], fallback: str) -> str:
    if not parts:
        return fallback
    value = "_".join(parts)
    return value[:96] if value else fallback


def _get_orientation(width: Optional[int], height: Optional[int]) -> str:
    if not width or not height:
        return "unknown"
    if width == height:
        return "square"
    return "portrait" if height > width else "landscape"


class ImgbedUploader:
    _MANAGE_TRANSPORT_HINTS: dict[str, str] = {}

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
        channel_name: str = "",
        auto_retry: bool = True,
        upload_name_type: str = "default",
        sync_remote_tags: bool = True,
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
        self.channel_name = str(channel_name or "").strip()
        self.auto_retry = bool(auto_retry)
        self.upload_name_type = str(upload_name_type or "default").strip() or "default"
        self.sync_remote_tags = bool(sync_remote_tags)
        self.image_processing = ImageProcessingConfig.from_dict(image_processing)
        self.profile_key = profile_key or ""
        self.profile_name = profile_name or self.profile_key or "upload"
        # 目录配置
        self.folder_landscape = folder_landscape or self._DEFAULT_LANDSCAPE
        self.folder_portrait  = folder_portrait  or self._DEFAULT_PORTRAIT
        self.folder_dynamic_configured = str(folder_dynamic or "").strip()
        self.folder_dynamic   = folder_dynamic   or self._DEFAULT_DYNAMIC
        self.folder_pattern   = folder_pattern   or ""
        # 上传过滤
        self.upload_filter = UploadFilterConfig.from_dict(upload_filter)
        # 持久 HTTP client：复用连接池，避免每次上传重新握手
        self._client: Optional[httpx.AsyncClient] = None
        self._prefer_curl_manage_api = self._MANAGE_TRANSPORT_HINTS.get(self.base_url) == "curl"

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

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict | list:
        request_url = f"{self.base_url}{path}"
        filtered_params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        if self._prefer_curl_manage_api:
            return await self._request_json_via_curl(
                method,
                request_url,
                params=filtered_params,
                json_body=json_body,
            )
        client = self._ensure_client()
        try:
            response = await client.request(
                method,
                request_url,
                params=filtered_params,
                headers=self._auth_headers(),
                json=json_body,
            )
            response.raise_for_status()
            self._prefer_curl_manage_api = False
            self._MANAGE_TRANSPORT_HINTS[self.base_url] = "httpx"
            return response.json()
        except httpx.ConnectError as exc:
            switched = not self._prefer_curl_manage_api
            self._prefer_curl_manage_api = True
            self._MANAGE_TRANSPORT_HINTS[self.base_url] = "curl"
            logger.warning(
                "[Imgbed] httpx 连接图床失败，%s method=%s path=%s error=%r",
                "切换为 curl 回退" if switched else "继续使用 curl 回退",
                method,
                path,
                exc,
            )
            return await self._request_json_via_curl(
                method,
                request_url,
                params=filtered_params,
                json_body=json_body,
                original_error=exc,
            )

    async def _request_json_via_curl(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        original_error: Optional[Exception] = None,
    ) -> dict | list:
        query = urlencode(params or {}, doseq=True)
        request_url = f"{url}?{query}" if query else url
        marker = "__CURL_HTTP_STATUS__:"
        command = [
            "curl",
            "-sS",
            "-L",
            "--max-time",
            "120",
            "-X",
            method.upper(),
            "-H",
            f"Authorization: Bearer {self.api_token}",
            "-w",
            f"\n{marker}%{{http_code}}",
            request_url,
        ]

        if json_body is not None:
            command[8:8] = [
                "-H",
                "Content-Type: application/json",
                "--data-raw",
                json.dumps(json_body, ensure_ascii=False),
            ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_text = (stderr.decode("utf-8", errors="ignore") or "").strip()
            error_detail = stderr_text or repr(original_error) or "未知连接错误"
            raise RuntimeError(f"图床管理接口连接失败（curl 回退也失败）: {error_detail}")

        payload_text = stdout.decode("utf-8", errors="ignore")
        body_text, _, status_text = payload_text.rpartition(f"\n{marker}")
        status_code = int(status_text.strip() or "0") if status_text else 0
        request = httpx.Request(method.upper(), request_url)

        if status_code >= 400:
            response = httpx.Response(status_code, text=body_text, request=request)
            raise httpx.HTTPStatusError(
                f"图床管理接口返回 HTTP {status_code}",
                request=request,
                response=response,
            )

        try:
            return json.loads(body_text or "null")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"图床管理接口返回了非 JSON 内容: {(body_text or '').strip()[:200]}") from exc

    @staticmethod
    def _build_template_values(
        *,
        width: Optional[int],
        height: Optional[int],
        wallpaper_type: str,
        category: str,
        type_id: str,
        color_theme: str,
        color_id: str,
        tags: str | list[str] | tuple[str, ...] | None,
        is_original: bool,
        resource_id: str,
    ) -> dict[str, str]:
        now = datetime.now()
        orientation = _get_orientation(width, height)
        normalized_tags = [_safe_path_segment(item) for item in _normalize_tags(tags)]
        primary_tag = normalized_tags[0] if normalized_tags else "untagged"
        return {
            "type": wallpaper_type or "static",
            "category": _safe_path_segment(category) if category else "uncategorized",
            "type_id": _safe_path_segment(type_id) if type_id else "unknown-type",
            "color": _safe_path_segment(color_theme) if color_theme else "uncolored",
            "color_id": _safe_path_segment(color_id) if color_id else "unknown-color",
            "orientation": orientation,
            "primary_tag": primary_tag,
            "tags": _trim_joined_segment(normalized_tags[:5], "untagged"),
            "originality": "original" if is_original else "preview",
            "resource_id": _safe_path_segment(resource_id) if resource_id else "unknown-resource",
            "year": now.strftime("%Y"),
            "month": now.strftime("%m"),
            "date": now.strftime("%Y%m%d"),
        }

    @classmethod
    def _resolve_pattern(cls, pattern: str, values: dict[str, str]) -> str:
        folder = pattern
        for key, value in values.items():
            folder = folder.replace(f"{{{key}}}", value)
        return re.sub(r"/{2,}", "/", folder).strip("/")

    def _determine_folder(
        self,
        width: Optional[int],
        height: Optional[int],
        wallpaper_type: str = "static",
        category: str = "",
        type_id: str = "",
        color_theme: str = "",
        color_id: str = "",
        tags: str | list[str] | tuple[str, ...] | None = None,
        is_original: bool = False,
        resource_id: str = "",
    ) -> str:
        if self.folder_pattern:
            return self._resolve_pattern(
                self.folder_pattern,
                self._build_template_values(
                    width=width,
                    height=height,
                    wallpaper_type=wallpaper_type,
                    category=category,
                    type_id=type_id,
                    color_theme=color_theme,
                    color_id=color_id,
                    tags=tags,
                    is_original=is_original,
                    resource_id=resource_id,
                ),
            )

        if wallpaper_type == "dynamic" and self.folder_dynamic_configured:
            return self.folder_dynamic
        if _get_orientation(width, height) == "portrait":
            return self.folder_portrait
        return self.folder_landscape

    async def list_files(
        self,
        *,
        start: int = 0,
        count: int = 50,
        recursive: bool = False,
        directory: str = "",
        search: str = "",
        include_tags: str = "",
        exclude_tags: str = "",
        channel: str = "",
        list_type: str = "",
    ) -> dict | list:
        return await self._request_json(
            "GET",
            "/api/manage/list",
            params={
                "start": start,
                "count": count,
                "recursive": str(bool(recursive)).lower(),
                "dir": directory.strip("/"),
                "search": search,
                "includeTags": include_tags,
                "excludeTags": exclude_tags,
                "channel": channel,
                "listType": list_type,
            },
        )

    async def get_index_info(self, *, directory: str = "") -> dict | list:
        return await self._request_json(
            "GET",
            "/api/manage/list",
            params={"action": "info", "dir": directory.strip("/")},
        )

    async def rebuild_index(self, *, directory: str = "") -> dict | list:
        return await self._request_json(
            "GET",
            "/api/manage/list",
            params={"action": "rebuild", "dir": directory.strip("/")},
        )

    async def delete_remote_path(self, remote_path: str, *, folder: bool = False) -> dict | list:
        normalized = remote_path.strip("/")
        encoded_path = quote(normalized, safe="/")
        return await self._request_json(
            "DELETE",
            f"/api/manage/delete/{encoded_path}",
            params={"folder": str(bool(folder)).lower()},
        )

    async def move_remote_path(
        self,
        remote_path: str,
        *,
        dist: str = "",
        folder: bool = False,
    ) -> dict | list:
        normalized = remote_path.strip("/")
        encoded_path = quote(normalized, safe="/")
        return await self._request_json(
            "POST",
            f"/api/manage/move/{encoded_path}",
            params={
                "dist": dist.strip("/"),
                "folder": str(bool(folder)).lower(),
            },
        )

    async def get_remote_tags(self, remote_path: str) -> dict | list:
        normalized = remote_path.strip("/")
        encoded_path = quote(normalized, safe="/")
        return await self._request_json(
            "GET",
            f"/api/manage/tags/{encoded_path}",
        )

    async def set_remote_tags(
        self,
        remote_path: str,
        tags: list[str],
        *,
        action: str = "set",
    ) -> dict | list:
        normalized = remote_path.strip("/")
        encoded_path = quote(normalized, safe="/")
        cleaned_tags = [normalize_remote_tag(item) for item in tags if normalize_remote_tag(item)]
        return await self._request_json(
            "POST",
            f"/api/manage/tags/{encoded_path}",
            json_body={
                "action": action,
                "tags": cleaned_tags,
            },
        )

    async def set_remote_tags_batch(
        self,
        remote_paths: list[str],
        tags: list[str],
        *,
        action: str = "set",
    ) -> dict | list:
        file_ids = [str(item).strip("/") for item in remote_paths if str(item).strip("/")]
        cleaned_tags = [normalize_remote_tag(item) for item in tags if normalize_remote_tag(item)]
        return await self._request_json(
            "POST",
            "/api/manage/tags/batch",
            json_body={
                "fileIds": file_ids,
                "action": action,
                "tags": cleaned_tags,
            },
        )

    async def list_channels(self) -> dict | list:
        return await self._request_json("GET", "/api/channels")

    async def probe_capabilities(self) -> dict[str, object]:
        checks = {
            "channels": ("channels", self.list_channels),
            "list": ("list", self.get_index_info),
            "manage": ("manage", lambda: self._request_json("GET", "/api/manage/apiTokens")),
        }
        results: dict[str, object] = {}

        for key, (permission, callback) in checks.items():
            try:
                await callback()
                results[key] = {
                    "ok": True,
                    "permission": permission,
                }
            except httpx.HTTPStatusError as exc:
                results[key] = {
                    "ok": False,
                    "permission": permission,
                    "status_code": exc.response.status_code,
                    "detail": (exc.response.text or str(exc))[:200],
                }
            except Exception as exc:  # noqa: BLE001
                results[key] = {
                    "ok": False,
                    "permission": permission,
                    "detail": str(exc),
                }

        return {
            "channels": bool(results.get("channels", {}).get("ok")),
            "list": bool(results.get("list", {}).get("ok")),
            "manage": bool(results.get("manage", {}).get("ok")),
            "checks": results,
        }

    async def upload(
        self,
        local_path: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        wallpaper_type: str = "static",
        category: str = "",
        type_id: str = "",
        color_theme: str = "",
        color_id: str = "",
        tags: str | list[str] | tuple[str, ...] | None = None,
        resource_id: str = "",
        is_original: bool = False,
        format_override: Optional[str] = None,
    ) -> Optional[str]:
        if not os.path.exists(local_path):
            logger.warning("[Imgbed] file not found: %s", local_path)
            return None

        # 上传过滤检查
        ok, reason = self.upload_filter.check(width, height, is_original)
        if not ok:
            logger.info("[Imgbed] 跳过上传 file=%s reason=%s", os.path.basename(local_path), reason)
            return None

        folder = self._determine_folder(
            width,
            height,
            wallpaper_type,
            category,
            type_id=type_id,
            color_theme=color_theme,
            color_id=color_id,
            tags=tags,
            is_original=is_original,
            resource_id=resource_id,
        )
        upload_url = f"{self.base_url}/upload"
        params = {
            "uploadChannel": self.channel,
            "uploadFolder": folder,
            "autoRetry": "true" if self.auto_retry else "false",
            "uploadNameType": self.upload_name_type,
            "serverCompress": "true" if self.compress else "false",
            "returnFormat": "full",
        }
        if self.channel_name:
            params["channelName"] = self.channel_name
        headers = self._auth_headers()

        upload_path = local_path
        upload_name = os.path.basename(local_path)
        temp_path = self._prepare_upload_file(local_path, format_override=format_override)
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

    def _prepare_upload_file(
        self,
        local_path: str,
        format_override: Optional[str] = None,
    ) -> Optional[str]:
        cfg = self.image_processing
        override = str(format_override or "").strip().lower()

        if override == "original":
            return None
        if not cfg.enabled and override != "webp":
            return None
        if not override and cfg.telegram_only and self.channel.lower() != "telegram":
            return None
        target_format = override or cfg.format
        if target_format == "original":
            return None
        if target_format != "webp":
            logger.warning("[Imgbed] unsupported local format: %s", target_format)
            return None
        if os.path.splitext(local_path)[1].lower() == ".webp":
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
