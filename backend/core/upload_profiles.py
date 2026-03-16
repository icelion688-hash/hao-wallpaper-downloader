"""
upload_profiles.py - 上传配置解析与上传器构建。
"""

from __future__ import annotations

from typing import Optional

from backend.config import load_config
from backend.core.imgbed_uploader import ImgbedUploader


def get_upload_settings() -> dict:
    cfg = load_config()
    return cfg.get("uploads", {})


def list_upload_profiles() -> list[dict]:
    return get_upload_settings().get("profiles", [])


def get_upload_profile(profile_key: str) -> Optional[dict]:
    for profile in list_upload_profiles():
        if profile.get("key") == profile_key:
            return profile
    return None


def build_uploader_from_profile(profile: Optional[dict]) -> Optional[ImgbedUploader]:
    if not profile:
        return None
    if not profile.get("enabled", True):
        return None
    if not profile.get("api_token"):
        return None
    return ImgbedUploader(
        base_url=profile.get("base_url", "https://imgbed.lacexr.com"),
        api_token=profile.get("api_token", ""),
        compress=profile.get("server_compress", False),
        channel=profile.get("channel", "telegram"),
        image_processing=profile.get("image_processing", {}),
        profile_key=profile.get("key", ""),
        profile_name=profile.get("name", profile.get("key", "upload")),
    )


def build_uploader_by_key(profile_key: str) -> Optional[ImgbedUploader]:
    return build_uploader_from_profile(get_upload_profile(profile_key))


def build_task_uploader() -> Optional[ImgbedUploader]:
    settings = get_upload_settings()
    return build_uploader_by_key(settings.get("task_profile", "compressed_webp"))
