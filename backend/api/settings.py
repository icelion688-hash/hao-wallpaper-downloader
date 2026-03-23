"""
api/settings.py - 全局上传 + 媒体转换设置 API。
"""

from typing import List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.config import default_media_convert_config, load_config, update_config
from backend.core.upload_profiles import build_task_uploader

router = APIRouter()


class ImageProcessingPayload(BaseModel):
    enabled: bool = True
    telegram_only: bool = False
    format: str = "webp"
    quality: int = Field(default=86, ge=1, le=100)
    min_quality: int = Field(default=72, ge=1, le=100)
    threshold_mb: float = Field(default=5, gt=0)
    target_mb: float = Field(default=4, gt=0)
    disable_above_mb: float = Field(default=10, gt=0)


class UploadFilterPayload(BaseModel):
    min_width: Optional[int] = Field(default=None, ge=0)
    min_height: Optional[int] = Field(default=None, ge=0)
    only_original: bool = False


class UploadProfilePayload(BaseModel):
    key: str
    name: str
    enabled: bool = True
    base_url: str
    api_token: str
    channel: str = "telegram"
    channel_name: str = ""
    auto_retry: bool = True
    upload_name_type: str = "default"
    sync_remote_tags: bool = True
    server_compress: bool = False
    folder_landscape: str = ""
    folder_portrait: str = ""
    folder_dynamic: str = ""
    folder_pattern: str = ""
    upload_filter: UploadFilterPayload = UploadFilterPayload()
    image_processing: ImageProcessingPayload = ImageProcessingPayload()


class UploadSettingsPayload(BaseModel):
    task_profile: str
    gallery_default_format: str = "profile"
    profiles: List[UploadProfilePayload]


class ImgbedCompatPayload(BaseModel):
    base_url: str
    api_token: str
    channel: str = "telegram"
    server_compress: bool = True
    image_processing: ImageProcessingPayload = ImageProcessingPayload()


class SyncSettingsPayload(BaseModel):
    auth_token: str = ""
    allowed_sources: List[str] = Field(default_factory=list)
    export_rate_limit_per_minute: int = Field(default=60, ge=0, le=600)


def _current_upload_settings() -> dict:
    return load_config().get("uploads", {})


def _current_sync_settings() -> dict:
    sync = load_config().get("sync", {}) or {}
    return {
        "auth_token": str(sync.get("auth_token", "") or ""),
        "allowed_sources": [str(item).strip() for item in (sync.get("allowed_sources") or []) if str(item).strip()],
        "export_rate_limit_per_minute": int(sync.get("export_rate_limit_per_minute", 60) or 0),
    }


def _sanitize_media_convert_settings(data: Optional[dict] = None) -> dict:
    settings = {**default_media_convert_config(), **(data or {})}
    video = {**default_media_convert_config()["video"], **(settings.get("video") or {})}
    image = {**default_media_convert_config()["image"], **(settings.get("image") or {})}
    video["enabled"] = False
    settings["video"] = video
    settings["image"] = image
    return settings


@router.get("/uploads")
async def get_upload_settings():
    return _current_upload_settings()


@router.put("/uploads")
async def save_upload_settings(body: UploadSettingsPayload, request: Request):
    cfg = update_config({"uploads": body.model_dump()})
    request.app.state.imgbed = build_task_uploader()
    return {"success": True, "uploads": cfg.get("uploads", {})}


@router.get("/imgbed")
async def get_imgbed_settings_compat():
    uploads = _current_upload_settings()
    task_key = uploads.get("task_profile")
    profile = next((item for item in uploads.get("profiles", []) if item.get("key") == task_key), {})
    return profile


class VideoConvertPayload(BaseModel):
    enabled: bool = False
    output_format: str = "webp"
    fps: int = Field(default=0, ge=0, le=120)       # 0 = 保留源帧率（原图模式）
    max_frames: int = Field(default=0, ge=0, le=9999)  # 0 = 不限帧数（原图模式）
    width: int = Field(default=0, ge=0)
    max_width: int = Field(default=0, ge=0)        # 0 = 不缩放（原图模式）
    quality: int = Field(default=100, ge=1, le=100)
    delete_original: bool = False
    timeout_seconds: int = Field(default=300, ge=30, le=7200)
    cpu_nice: int = Field(default=5, ge=0, le=19)


class ImageConvertPayload(BaseModel):
    enabled: bool = False
    output_format: str = "webp"
    quality: int = Field(default=100, ge=1, le=100)
    delete_original: bool = False
    timeout_seconds: int = Field(default=120, ge=10, le=600)
    cpu_nice: int = Field(default=5, ge=0, le=19)


class MediaConvertPayload(BaseModel):
    auto_convert: bool = False
    max_concurrent: int = Field(default=1, ge=1, le=4)
    video: VideoConvertPayload = VideoConvertPayload()
    image: ImageConvertPayload = ImageConvertPayload()


@router.get("/media-convert")
async def get_media_convert_settings():
    return _sanitize_media_convert_settings(load_config().get("media_convert"))


@router.put("/media-convert")
async def save_media_convert_settings(body: MediaConvertPayload):
    payload = _sanitize_media_convert_settings(body.model_dump())
    cfg = update_config({"media_convert": payload})
    return {"success": True, "media_convert": _sanitize_media_convert_settings(cfg.get("media_convert"))}


@router.get("/sync")
async def get_sync_settings():
    return _current_sync_settings()


@router.put("/sync")
async def save_sync_settings(body: SyncSettingsPayload):
    cfg = update_config({"sync": body.model_dump()})
    sync = cfg.get("sync", {}) or {}
    return {
        "success": True,
        "sync": {
            "auth_token": str(sync.get("auth_token", "") or ""),
            "allowed_sources": [str(item).strip() for item in (sync.get("allowed_sources") or []) if str(item).strip()],
            "export_rate_limit_per_minute": int(sync.get("export_rate_limit_per_minute", 60) or 0),
        },
    }


@router.get("/system-info")
async def get_system_info():
    """返回服务器资源概况与推荐转换配置（不含敏感信息）"""
    from backend.core.media_converter import MediaConverter
    return MediaConverter.system_info()


@router.put("/imgbed")
async def save_imgbed_settings_compat(body: ImgbedCompatPayload, request: Request):
    uploads = _current_upload_settings()
    profiles = uploads.get("profiles", [])
    payload = {
        "key": uploads.get("task_profile", "compressed_webp"),
        "name": "壁纸压缩图床",
        "enabled": True,
        **body.model_dump(),
    }
    updated = False
    for index, profile in enumerate(profiles):
        if profile.get("key") == uploads.get("task_profile"):
            profiles[index] = {**profile, **payload}
            updated = True
            break
    if not updated:
        profiles.append(payload)
        uploads["task_profile"] = payload["key"]

    cfg = update_config({"uploads": uploads})
    request.app.state.imgbed = build_task_uploader()
    return {"success": True, "imgbed": cfg.get("imgbed", {})}
