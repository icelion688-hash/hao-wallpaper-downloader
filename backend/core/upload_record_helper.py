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


def parse_upload_records(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def dump_upload_records(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_upload_record(profile_key: str, profile_name: str, channel: str, url: str) -> dict:
    return {
        "profile_key": profile_key,
        "profile_name": profile_name,
        "channel": channel,
        "url": url,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def find_reusable_upload_record(
    db: Session,
    profile_key: str,
    sha256: Optional[str] = None,
    md5: Optional[str] = None,
    exclude_wallpaper_id: Optional[int] = None,
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
        record = records.get(profile_key)
        if record and record.get("url"):
            return record
    return None
