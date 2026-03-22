"""
upload_record_helper.py - 上传记录与去重复用辅助函数。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote, unquote, urlparse

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.upload_registry import UploadRegistry
from backend.models.wallpaper import Wallpaper

logger = logging.getLogger(__name__)

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


def build_remote_file_url(base_url: str, remote_path: str) -> str:
    normalized_base = str(base_url or "").rstrip("/")
    normalized_path = str(remote_path or "").strip("/")
    if not normalized_base or not normalized_path:
        return normalized_base or normalized_path
    return f"{normalized_base}/file/{quote(normalized_path, safe='/')}"


def parse_remote_file_id_from_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    parsed = urlparse(text)
    path = parsed.path or text
    marker = "/file/"
    if marker not in path:
        return None

    remote_path = path.split(marker, 1)[1].strip("/")
    if not remote_path:
        return None
    return unquote(remote_path)


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
    remote_path: Optional[str] = None,
    remote_tags: Optional[list[str]] = None,
) -> dict:
    normalized = normalize_upload_format(format_key)
    record = {
        "profile_key": profile_key,
        "profile_name": profile_name,
        "channel": channel,
        "url": url,
        "format_key": normalized,
        "format_label": UPLOAD_FORMAT_LABELS[normalized],
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    if remote_path:
        record["remote_path"] = str(remote_path).strip("/")
    if remote_tags:
        record["remote_tags"] = [str(item).strip() for item in remote_tags if str(item).strip()]
    return record


def split_remote_tags(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[,\n|]+", value)
    else:
        items = list(value)
    return [str(item).strip() for item in items if str(item).strip()]


def unique_remote_tags(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def get_orientation_tag(width: Optional[int], height: Optional[int]) -> str:
    width_value = int(width or 0)
    height_value = int(height or 0)
    if width_value <= 0 or height_value <= 0:
        return "unknown"
    if width_value == height_value:
        return "方图"
    return "竖图" if height_value > width_value else "横图"


def build_remote_tags(
    *,
    width: Optional[int],
    height: Optional[int],
    wallpaper_type: str,
    category: str,
    color_theme: str,
    tags: str | list[str] | tuple[str, ...] | None,
) -> list[str]:
    type_tag = "动态图" if str(wallpaper_type or "").strip().lower() == "dynamic" else "静态图"
    orientation = get_orientation_tag(width, height)
    return unique_remote_tags(
        [
            type_tag,
            orientation,
            str(category or "").strip(),
            str(color_theme or "").strip(),
            *split_remote_tags(tags),
        ]
    )


async def sync_remote_record_metadata(
    uploader,
    *,
    url: str,
    width: Optional[int],
    height: Optional[int],
    wallpaper_type: str,
    category: str,
    color_theme: str,
    tags: str | list[str] | tuple[str, ...] | None,
) -> dict:
    remote_path = parse_remote_file_id_from_url(url) or ""
    remote_tags = build_remote_tags(
        width=width,
        height=height,
        wallpaper_type=wallpaper_type,
        category=category,
        color_theme=color_theme,
        tags=tags,
    )
    synced = False
    error = ""

    if remote_path and remote_tags:
        try:
            await uploader.set_remote_tags(remote_path, remote_tags, action="set")
            synced = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            logger.warning(
                "[Imgbed] 同步远端标签失败 path=%s tags=%s error=%s",
                remote_path,
                remote_tags,
                error,
            )

    return {
        "remote_path": remote_path,
        "remote_tags": remote_tags,
        "tag_sync_success": synced,
        "tag_sync_error": error,
    }


def _parse_uploaded_at(value: Optional[str | datetime]) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _registry_to_upload_record(item: UploadRegistry) -> dict:
    normalized = normalize_upload_format(item.format_key)
    uploaded_at = item.uploaded_at.isoformat(timespec="seconds") if item.uploaded_at else None
    return {
        "profile_key": item.profile_key,
        "profile_name": item.profile_name or item.profile_key,
        "channel": item.channel or "",
        "url": item.url,
        "format_key": normalized,
        "format_label": UPLOAD_FORMAT_LABELS.get(normalized, UPLOAD_FORMAT_LABELS[DEFAULT_UPLOAD_FORMAT]),
        "uploaded_at": uploaded_at,
        "source_server": item.source_server,
    }


def upsert_upload_registry_record(
    db: Session,
    *,
    profile_key: str,
    url: str,
    format_key: Optional[str] = None,
    resource_id: Optional[str] = None,
    sha256: Optional[str] = None,
    md5: Optional[str] = None,
    profile_name: Optional[str] = None,
    channel: Optional[str] = None,
    uploaded_at: Optional[str | datetime] = None,
    source_server: Optional[str] = None,
) -> UploadRegistry:
    normalized = normalize_upload_format(format_key)
    query = db.query(UploadRegistry).filter(
        UploadRegistry.profile_key == profile_key,
        UploadRegistry.format_key == normalized,
    )

    identity_filters = []
    if sha256:
        identity_filters.append(UploadRegistry.sha256 == sha256)
    if md5:
        identity_filters.append(UploadRegistry.md5 == md5)
    if resource_id:
        identity_filters.append(UploadRegistry.resource_id == resource_id)
    if url:
        identity_filters.append(UploadRegistry.url == url)

    existing = query.filter(or_(*identity_filters)).order_by(UploadRegistry.id.asc()).first() if identity_filters else None
    uploaded_dt = _parse_uploaded_at(uploaded_at)

    if existing:
        if not existing.resource_id and resource_id:
            existing.resource_id = resource_id
        if not existing.sha256 and sha256:
            existing.sha256 = sha256
        if not existing.md5 and md5:
            existing.md5 = md5
        if not existing.profile_name and profile_name:
            existing.profile_name = profile_name
        if not existing.channel and channel:
            existing.channel = channel
        if not existing.source_server and source_server:
            existing.source_server = source_server
        if not existing.uploaded_at and uploaded_dt:
            existing.uploaded_at = uploaded_dt
        existing.url = existing.url or url
        return existing

    item = UploadRegistry(
        resource_id=resource_id,
        sha256=sha256,
        md5=md5,
        profile_key=profile_key,
        format_key=normalized,
        profile_name=profile_name,
        channel=channel,
        url=url,
        source_server=source_server,
        uploaded_at=uploaded_dt,
    )
    db.add(item)
    return item


def persist_wallpaper_upload_records_to_registry(
    db: Session,
    wallpaper: Wallpaper,
    source_server: Optional[str] = None,
) -> int:
    records = parse_upload_records(wallpaper.upload_records)
    created_or_updated = 0

    for raw_key, record in records.items():
        if not isinstance(record, dict):
            continue
        url = record.get("url")
        profile_key = record.get("profile_key")
        if not profile_key and isinstance(raw_key, str):
            profile_key = raw_key.split("::", 1)[0]
        if not profile_key or not url:
            continue

        upsert_upload_registry_record(
            db,
            profile_key=profile_key,
            format_key=record.get("format_key"),
            url=url,
            resource_id=wallpaper.resource_id,
            sha256=wallpaper.sha256,
            md5=wallpaper.md5,
            profile_name=record.get("profile_name"),
            channel=record.get("channel"),
            uploaded_at=record.get("uploaded_at"),
            source_server=record.get("source_server") or source_server,
        )
        created_or_updated += 1

    if wallpaper.imgbed_url:
        default_profile_key = None
        if len(records) == 1:
            first = next(iter(records.values()))
            if isinstance(first, dict):
                default_profile_key = first.get("profile_key")

        if default_profile_key:
            upsert_upload_registry_record(
                db,
                profile_key=default_profile_key,
                url=wallpaper.imgbed_url,
                resource_id=wallpaper.resource_id,
                sha256=wallpaper.sha256,
                md5=wallpaper.md5,
                source_server=source_server,
            )
            created_or_updated += 1

    return created_or_updated


def backfill_upload_registry_from_wallpapers(
    db: Session,
    source_server: Optional[str] = None,
) -> int:
    wallpapers = (
        db.query(Wallpaper)
        .filter(
            or_(
                Wallpaper.upload_records.isnot(None),
                Wallpaper.imgbed_url.isnot(None),
            )
        )
        .all()
    )
    total = 0
    for wallpaper in wallpapers:
        total += persist_wallpaper_upload_records_to_registry(db, wallpaper, source_server=source_server)
    return total


def _find_registry_upload_record(
    db: Session,
    profile_key: str,
    sha256: Optional[str] = None,
    md5: Optional[str] = None,
    resource_id: Optional[str] = None,
    format_key: Optional[str] = None,
) -> Optional[dict]:
    filters = []
    if sha256:
        filters.append(UploadRegistry.sha256 == sha256)
    if md5:
        filters.append(UploadRegistry.md5 == md5)
    if resource_id:
        filters.append(UploadRegistry.resource_id == resource_id)
    if not filters:
        return None

    normalized = normalize_upload_format(format_key)
    item = (
        db.query(UploadRegistry)
        .filter(
            UploadRegistry.profile_key == profile_key,
            UploadRegistry.format_key == normalized,
            or_(*filters),
        )
        .order_by(UploadRegistry.id.asc())
        .first()
    )
    if item and item.url:
        return _registry_to_upload_record(item)
    return None


def find_reusable_upload_record(
    db: Session,
    profile_key: str,
    sha256: Optional[str] = None,
    md5: Optional[str] = None,
    resource_id: Optional[str] = None,
    exclude_wallpaper_id: Optional[int] = None,
    format_key: Optional[str] = None,
) -> Optional[dict]:
    registry_record = _find_registry_upload_record(
        db,
        profile_key=profile_key,
        sha256=sha256,
        md5=md5,
        resource_id=resource_id,
        format_key=format_key,
    )
    if registry_record:
        return registry_record

    filters = []
    if sha256:
        filters.append(Wallpaper.sha256 == sha256)
    if md5:
        filters.append(Wallpaper.md5 == md5)
    if resource_id:
        filters.append(Wallpaper.resource_id == resource_id)
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
