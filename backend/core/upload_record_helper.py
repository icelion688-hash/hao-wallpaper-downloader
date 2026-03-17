"""
upload_record_helper.py - 上传记录与去重复用辅助函数。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.wallpaper import Wallpaper

DEFAULT_UPLOAD_FORMAT = "profile"
SUPPORTED_UPLOAD_FORMATS = {
    "profile",
    "original",
    "webp",
    "gif",
    "png",
    "jpg",
}
UPLOAD_FORMAT_LABELS = {
    "profile": "跟随 Profile",
    "original": "原始文件",
    "webp": "WebP",
    "gif": "GIF",
    "png": "PNG",
    "jpg": "JPG",
}


def normalize_upload_format(value: Optional[str]) -> str:
    format_key = str(value or DEFAULT_UPLOAD_FORMAT).strip().lower()
    if format_key == "jpeg":
        format_key = "jpg"
    if format_key not in SUPPORTED_UPLOAD_FORMATS:
        return DEFAULT_UPLOAD_FORMAT
    return format_key


def build_upload_record_key(profile_key: str, format_key: Optional[str] = None) -> str:
    normalized = normalize_upload_format(format_key)
    if normalized == DEFAULT_UPLOAD_FORMAT:
        return profile_key
    return f"{profile_key}::{normalized}"


def parse_upload_records(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def dump_upload_records(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def get_upload_record(records: dict, profile_key: str, format_key: Optional[str] = None) -> Optional[dict]:
    record_key = build_upload_record_key(profile_key, format_key)
    record = records.get(record_key)
    if record and record.get("url"):
        return record

    # 兼容旧数据：历史记录没有格式维度，默认视为跟随 Profile。
    normalized = normalize_upload_format(format_key)
    if normalized == DEFAULT_UPLOAD_FORMAT:
        legacy = records.get(profile_key)
        if legacy and legacy.get("url"):
            return legacy
    return None


def build_upload_record(
    profile_key: str,
    profile_name: str,
    channel: str,
    url: str,
    format_key: Optional[str] = None,
) -> dict:
    normalized = normalize_upload_format(format_key)
    return {
        "profile_key": profile_key,
        "profile_name": profile_name,
        "channel": channel,
        "url": url,
        "format_key": normalized,
        "format_label": UPLOAD_FORMAT_LABELS[normalized],
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def find_reusable_upload_record(
    db: Session,
    profile_key: str,
    sha256: Optional[str] = None,
    md5: Optional[str] = None,
    exclude_wallpaper_id: Optional[int] = None,
    format_key: Optional[str] = None,
) -> Optional[dict]:
    filters = []
    if sha256:
        filters.append(Wallpaper.sha256 == sha256)
    if md5:
        filters.append(Wallpaper.md5 == md5)
    if not filters:
        return None

    query = db.query(Wallpaper).filter(or_(*filters))
    if exclude_wallpaper_id is not None:
        query = query.filter(Wallpaper.id != exclude_wallpaper_id)

    candidates = query.order_by(Wallpaper.id.asc()).all()
    for wallpaper in candidates:
        records = parse_upload_records(wallpaper.upload_records)
        record = get_upload_record(records, profile_key, format_key)
        if record and record.get("url"):
            return record
    return None
