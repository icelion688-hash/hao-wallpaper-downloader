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


def is_upload_profile_available(profile_key: str) -> bool:
    profile = get_upload_profile(profile_key)
    if not profile:
        return False
    if not profile.get("enabled", True):
        return False
    return bool(str(profile.get("api_token") or "").strip())


def build_uploader_from_profile(
    profile: Optional[dict],
    *,
    overrides: Optional[dict] = None,
) -> Optional[ImgbedUploader]:
    if not profile:
        return None
    merged = {**profile, **(overrides or {})}
    if not merged.get("enabled", True):
        return None
    if not merged.get("api_token"):
        return None
    return ImgbedUploader(
        base_url=merged.get("base_url", "https://imgbed.lacexr.com"),
        api_token=merged.get("api_token", ""),
        compress=merged.get("server_compress", False),
        channel=merged.get("channel", "telegram"),
        channel_name=merged.get("channel_name", ""),
        auto_retry=merged.get("auto_retry", True),
        upload_name_type=merged.get("upload_name_type", "default"),
        sync_remote_tags=merged.get("sync_remote_tags", True),
        image_processing=merged.get("image_processing", {}),
        profile_key=merged.get("key", ""),
        profile_name=merged.get("name", merged.get("key", "upload")),
        folder_landscape=merged.get("folder_landscape", ""),
        folder_portrait=merged.get("folder_portrait", ""),
        folder_dynamic=merged.get("folder_dynamic", ""),
        folder_pattern=merged.get("folder_pattern", ""),
        upload_filter=merged.get("upload_filter", {}),
    )


def build_uploader_by_key(
    profile_key: str,
    *,
    overrides: Optional[dict] = None,
) -> Optional[ImgbedUploader]:
    return build_uploader_from_profile(get_upload_profile(profile_key), overrides=overrides)


def build_task_uploader() -> Optional[ImgbedUploader]:
    settings = get_upload_settings()
    return build_uploader_by_key(settings.get("task_profile", "compressed_webp"))
