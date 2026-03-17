"""
api/settings.py - 全局上传 + 媒体转换设置 API。
"""

from typing import List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.config import load_config, update_config
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


class UploadProfilePayload(BaseModel):
    key: str
    name: str
    enabled: bool = True
    base_url: str
    api_token: str
    channel: str = "telegram"
    server_compress: bool = False
    image_processing: ImageProcessingPayload = ImageProcessingPayload()


class UploadSettingsPayload(BaseModel):
    task_profile: str
    profiles: List[UploadProfilePayload]


class ImgbedCompatPayload(BaseModel):
    base_url: str
    api_token: str
    channel: str = "telegram"
    server_compress: bool = True
    image_processing: ImageProcessingPayload = ImageProcessingPayload()


def _current_upload_settings() -> dict:
    return load_config().get("uploads", {})


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
    fps: int = Field(default=10, ge=1, le=60)
    max_frames: int = Field(default=120, ge=10, le=600)
    width: int = Field(default=0, ge=0)
    max_width: int = Field(default=1280, ge=0)
    quality: int = Field(default=80, ge=1, le=100)
    delete_original: bool = False
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    cpu_nice: int = Field(default=5, ge=0, le=19)


class ImageConvertPayload(BaseModel):
    enabled: bool = False
    output_format: str = "webp"
    quality: int = Field(default=85, ge=1, le=100)
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
    return load_config().get("media_convert", MediaConvertPayload().model_dump())


@router.put("/media-convert")
async def save_media_convert_settings(body: MediaConvertPayload):
    cfg = update_config({"media_convert": body.model_dump()})
    return {"success": True, "media_convert": cfg.get("media_convert", {})}


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
