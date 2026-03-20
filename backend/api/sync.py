"""
api/sync.py - 多服务器上传记录同步 API。

目标：
1. 导出/导入图床上传记录
2. 支持从远程服务器一键拉取
3. 与旧版基于 wallpapers 表的同步文件保持兼容
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from time import monotonic
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.config import load_config
from backend.core.upload_record_helper import (
    backfill_upload_registry_from_wallpapers,
    normalize_upload_format,
    parse_upload_records,
    upsert_upload_registry_record,
)
from backend.models.database import get_db
from backend.models.sync_history import SyncHistory
from backend.models.upload_registry import UploadRegistry
from backend.models.wallpaper import Wallpaper

logger = logging.getLogger(__name__)
router = APIRouter()

_EXPORT_VERSION = 3
_SYNC_RATE_LIMIT_BUCKETS: dict[str, list[float]] = {}
_SYNC_RATE_LIMIT_LOCK = threading.Lock()
_SYNC_ACTION_LABELS = {
    "export": "导出",
    "import": "导入",
    "pull": "迁移",
    "probe": "测试",
    "dedupe-scan": "扫描",
    "dedupe-merge": "合并",
}


class ImportResult(BaseModel):
    total: int
    merged: int
    inserted: int
    skipped: int
    errors: list[str]


class PreviewResult(BaseModel):
    version: int
    warning: Optional[str] = None
    raw_record_count: int
    normalized_count: int
    profile_keys: list[str]
    format_keys: list[str]
    source_servers: list[str]
    with_hash_count: int


class DuplicateGroupItem(BaseModel):
    identity_key: str
    identity_type: str
    match_value: str
    profile_key: str
    format_key: str
    count: int
    canonical_id: int
    duplicate_ids: list[int]
    url_count: int
    sample_urls: list[str]
    source_servers: list[str]


class DuplicateScanResult(BaseModel):
    total_groups: int
    total_duplicate_rows: int
    conflict_groups: int
    skipped_without_identity: int
    groups: list[DuplicateGroupItem]


class DuplicateMergeRequest(BaseModel):
    identity_key: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


class DuplicateMergeResult(BaseModel):
    scanned_groups: int
    merged_groups: int
    removed_rows: int
    updated_primary_rows: int
    conflict_groups: int
    skipped_groups: int
    merged_identity_keys: list[str]
    errors: list[str]


class ExportOptionItem(BaseModel):
    key: str
    total: int


class ExportOptionsResult(BaseModel):
    profile_keys: list[ExportOptionItem]
    format_keys: list[ExportOptionItem]


class ExportEstimateResult(BaseModel):
    total: int
    include_all: bool
    profile_keys: list[str]
    format_keys: list[str]


class SyncHistoryItem(BaseModel):
    id: int
    type: str
    type_label: str
    status: str
    summary: str
    detail: Optional[str] = None
    remote_base_url: Optional[str] = None
    source_server: Optional[str] = None
    at: Optional[str] = None


class SyncHistoryListResult(BaseModel):
    items: list[SyncHistoryItem]


class RemotePullRequest(BaseModel):
    remote_base_url: str = Field(..., description="远程服务根地址，如 http://10.0.0.8:8000")
    include_all: bool = False
    remote_sync_token: Optional[str] = None


class RemoteProbeRequest(BaseModel):
    remote_base_url: str = Field(..., description="远程服务根地址，如 http://10.0.0.8:8000")
    remote_sync_token: Optional[str] = None


def _normalize_base_url(value: str) -> str:
    text = (value or "").strip().rstrip("/")
    if not text:
        raise HTTPException(status_code=400, detail="remote_base_url 不能为空")
    if not text.startswith(("http://", "https://")):
        text = f"http://{text}"
    return text.rstrip("/")


def _guess_source_server(remote_base_url: Optional[str]) -> Optional[str]:
    if not remote_base_url:
        return None
    parsed = urlparse(remote_base_url)
    return parsed.netloc or parsed.path or remote_base_url


def _get_sync_auth_token() -> str:
    sync_cfg = load_config().get("sync", {})
    return str(sync_cfg.get("auth_token", "") or "").strip()


def _get_sync_allowed_sources() -> list[str]:
    sync_cfg = load_config().get("sync", {})
    return [str(item).strip() for item in (sync_cfg.get("allowed_sources") or []) if str(item).strip()]


def _get_sync_rate_limit_per_minute() -> int:
    sync_cfg = load_config().get("sync", {})
    return int(sync_cfg.get("export_rate_limit_per_minute", 60) or 0)


def _is_sync_token_valid(provided_token: Optional[str]) -> bool:
    expected = _get_sync_auth_token()
    if not expected:
        return True
    return str(provided_token or "").strip() == expected


def _require_sync_token(provided_token: Optional[str]) -> None:
    if _is_sync_token_valid(provided_token):
        return
    raise HTTPException(status_code=403, detail="同步密钥无效")


def _normalize_source_value(value: Optional[str]) -> str:
    return str(value or "").strip()


def _extract_request_source(request: Request) -> str:
    direct_host = _normalize_source_value(getattr(getattr(request, "client", None), "host", None))
    forwarded_for = _normalize_source_value(request.headers.get("X-Forwarded-For"))
    real_ip = _normalize_source_value(request.headers.get("X-Real-IP"))

    candidate = direct_host
    try:
        direct_ip = ip_address(direct_host) if direct_host else None
    except ValueError:
        direct_ip = None

    # 仅在常见反向代理场景下信任转发头，避免公网直连时被任意伪造。
    if direct_ip and (direct_ip.is_loopback or direct_ip.is_private):
        forwarded_candidate = forwarded_for.split(",")[0].strip() if forwarded_for else real_ip
        if forwarded_candidate:
            candidate = forwarded_candidate

    return candidate or "unknown"


def _is_source_allowed(source: Optional[str], allowed_sources: list[str]) -> bool:
    source_text = _normalize_source_value(source)
    if not allowed_sources:
        return True
    if not source_text:
        return False

    try:
        source_ip = ip_address(source_text)
    except ValueError:
        source_ip = None

    for raw_rule in allowed_sources:
        rule = _normalize_source_value(raw_rule)
        if not rule:
            continue
        try:
            if "/" in rule:
                if source_ip and source_ip in ip_network(rule, strict=False):
                    return True
                continue
            rule_ip = ip_address(rule)
            if source_ip and source_ip == rule_ip:
                return True
            continue
        except ValueError:
            pass

        if source_text.lower() == rule.lower():
            return True

    return False


def _consume_rate_limit(scope_key: str, source: str, limit_per_minute: int, now: Optional[float] = None) -> None:
    if limit_per_minute <= 0:
        return

    current = now if now is not None else monotonic()
    bucket_key = f"{scope_key}:{source}"
    window_start = current - 60

    with _SYNC_RATE_LIMIT_LOCK:
        timestamps = _SYNC_RATE_LIMIT_BUCKETS.get(bucket_key, [])
        timestamps = [value for value in timestamps if value >= window_start]
        if len(timestamps) >= limit_per_minute:
            _SYNC_RATE_LIMIT_BUCKETS[bucket_key] = timestamps
            raise HTTPException(status_code=429, detail="同步接口请求过于频繁，请稍后再试")
        timestamps.append(current)
        _SYNC_RATE_LIMIT_BUCKETS[bucket_key] = timestamps


def _enforce_sync_access(request: Request, scope_key: str) -> str:
    source = _extract_request_source(request)
    allowed_sources = _get_sync_allowed_sources()
    if not _is_source_allowed(source, allowed_sources):
        raise HTTPException(status_code=403, detail=f"来源 {source} 不在同步白名单内")
    _consume_rate_limit(scope_key, source, _get_sync_rate_limit_per_minute())
    return source


def _prepare_registry(db: Session) -> None:
    backfill_upload_registry_from_wallpapers(db)
    db.commit()


def _parse_filter_values(value: Optional[str]) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in str(value).split(","):
        text = raw.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _normalize_format_filters(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        key = normalize_upload_format(value)
        if key not in normalized:
            normalized.append(key)
    return normalized


def _query_export_registry_items(
    db: Session,
    *,
    include_all: bool = False,
    profile_keys: Optional[list[str]] = None,
    format_keys: Optional[list[str]] = None,
):
    query = db.query(UploadRegistry)
    if not include_all:
        query = query.filter(UploadRegistry.url.isnot(None), UploadRegistry.url != "")
    if profile_keys:
        query = query.filter(UploadRegistry.profile_key.in_(profile_keys))
    if format_keys:
        query = query.filter(UploadRegistry.format_key.in_(format_keys))
    return query


def _build_export_options(items: list[UploadRegistry]) -> ExportOptionsResult:
    profile_counts: dict[str, int] = defaultdict(int)
    format_counts: dict[str, int] = defaultdict(int)

    for item in items:
        profile_key = str(item.profile_key or "").strip()
        format_key = normalize_upload_format(item.format_key)
        if profile_key:
            profile_counts[profile_key] += 1
        format_counts[format_key] += 1

    return ExportOptionsResult(
        profile_keys=[
            ExportOptionItem(key=key, total=profile_counts[key])
            for key in sorted(profile_counts)
        ],
        format_keys=[
            ExportOptionItem(key=key, total=format_counts[key])
            for key in sorted(format_counts)
        ],
    )


def _serialize_sync_history_item(item: SyncHistory) -> SyncHistoryItem:
    return SyncHistoryItem(
        id=item.id,
        type=item.action,
        type_label=_SYNC_ACTION_LABELS.get(item.action, item.action),
        status=item.status,
        summary=item.summary,
        detail=item.detail,
        remote_base_url=item.remote_base_url,
        source_server=item.source_server,
        at=item.created_at.isoformat(timespec="seconds") if item.created_at else None,
    )


def _record_sync_history(
    db: Session,
    *,
    action: str,
    summary: str,
    status: str = "success",
    detail: Optional[str] = None,
    remote_base_url: Optional[str] = None,
    source_server: Optional[str] = None,
) -> SyncHistory:
    item = SyncHistory(
        action=action,
        status=status,
        summary=summary,
        detail=detail,
        remote_base_url=remote_base_url,
        source_server=source_server,
    )
    db.add(item)
    return item


def _prune_sync_history(db: Session, keep: int = 80) -> None:
    stale_items = (
        db.query(SyncHistory)
        .order_by(SyncHistory.id.desc())
        .offset(keep)
        .all()
    )
    for item in stale_items:
        db.delete(item)


def _build_export_payload(
    db: Session,
    include_all: bool = False,
    profile_keys: Optional[list[str]] = None,
    format_keys: Optional[list[str]] = None,
) -> dict[str, Any]:
    items = (
        _query_export_registry_items(
            db,
            include_all=include_all,
            profile_keys=profile_keys,
            format_keys=format_keys,
        )
        .order_by(UploadRegistry.id.asc())
        .all()
    )

    records = [
        {
            "resource_id": item.resource_id,
            "sha256": item.sha256,
            "md5": item.md5,
            "profile_key": item.profile_key,
            "format_key": normalize_upload_format(item.format_key),
            "profile_name": item.profile_name,
            "channel": item.channel,
            "url": item.url,
            "uploaded_at": item.uploaded_at.isoformat(timespec="seconds") if item.uploaded_at else None,
            "source_server": item.source_server,
        }
        for item in items
    ]

    return {
        "version": _EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(records),
        "include_all": include_all,
        "filters": {
            "profile_keys": profile_keys or [],
            "format_keys": format_keys or [],
        },
        "records": records,
    }


def _build_sync_stats(db: Session) -> dict[str, Any]:
    _prepare_registry(db)
    return {
        "wallpaper_total": db.query(Wallpaper).count(),
        "wallpaper_uploaded": db.query(Wallpaper).filter(Wallpaper.imgbed_url.isnot(None)).count(),
        "registry_total": db.query(UploadRegistry).count(),
        "registry_exportable": db.query(UploadRegistry).filter(UploadRegistry.url.isnot(None), UploadRegistry.url != "").count(),
        "registry_with_hash": db.query(UploadRegistry).filter(
            or_(UploadRegistry.sha256.isnot(None), UploadRegistry.md5.isnot(None))
        ).count(),
        "export_auth_enabled": bool(_get_sync_auth_token()),
        "export_allowlist_enabled": bool(_get_sync_allowed_sources()),
        "export_rate_limit_per_minute": _get_sync_rate_limit_per_minute(),
    }


def _build_version_warning(remote_version: Optional[int]) -> Optional[str]:
    if remote_version is None:
        return "无法识别远程同步协议版本"
    if remote_version < _EXPORT_VERSION:
        return f"远程协议版本较旧（{remote_version}），当前版本为 {_EXPORT_VERSION}，仍会尝试兼容导入"
    if remote_version > _EXPORT_VERSION:
        return f"远程协议版本较新（{remote_version}），当前版本为 {_EXPORT_VERSION}，请注意兼容性"
    return None


def _iter_records_from_legacy_wallpaper(
    raw_rec: dict[str, Any],
    default_source_server: Optional[str] = None,
) -> list[dict[str, Any]]:
    resource_id = str(raw_rec.get("resource_id") or "").strip() or None
    sha256 = raw_rec.get("sha256")
    md5 = raw_rec.get("md5")
    source_server = raw_rec.get("source_server") or default_source_server

    upload_records = parse_upload_records(raw_rec.get("upload_records"))
    normalized_records: list[dict[str, Any]] = []

    for raw_key, record in upload_records.items():
        if not isinstance(record, dict):
            continue
        url = record.get("url")
        if not url:
            continue
        profile_key = record.get("profile_key")
        if not profile_key and isinstance(raw_key, str):
            profile_key = raw_key.split("::", 1)[0]
        if not profile_key:
            continue

        normalized_records.append(
            {
                "resource_id": resource_id,
                "sha256": sha256,
                "md5": md5,
                "profile_key": profile_key,
                "format_key": record.get("format_key"),
                "profile_name": record.get("profile_name"),
                "channel": record.get("channel"),
                "url": url,
                "uploaded_at": record.get("uploaded_at"),
                "source_server": record.get("source_server") or source_server,
            }
        )

    return normalized_records


def _normalize_import_records(payload: dict[str, Any], source_server: Optional[str] = None) -> list[dict[str, Any]]:
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise HTTPException(status_code=400, detail="records 字段格式错误")

    version = int(payload.get("version", 1) or 1)
    normalized_records: list[dict[str, Any]] = []

    for raw_rec in raw_records:
        if not isinstance(raw_rec, dict):
            continue

        if version >= 3 and raw_rec.get("profile_key") and raw_rec.get("url"):
            normalized_records.append(
                {
                    "resource_id": str(raw_rec.get("resource_id") or "").strip() or None,
                    "sha256": raw_rec.get("sha256"),
                    "md5": raw_rec.get("md5"),
                    "profile_key": raw_rec.get("profile_key"),
                    "format_key": raw_rec.get("format_key"),
                    "profile_name": raw_rec.get("profile_name"),
                    "channel": raw_rec.get("channel"),
                    "url": raw_rec.get("url"),
                    "uploaded_at": raw_rec.get("uploaded_at"),
                    "source_server": raw_rec.get("source_server") or source_server,
                }
            )
            continue

        normalized_records.extend(_iter_records_from_legacy_wallpaper(raw_rec, source_server))

    return normalized_records


def _build_preview_result(payload: dict[str, Any], source_server: Optional[str] = None) -> PreviewResult:
    raw_records = payload.get("records", [])
    version = int(payload.get("version", 1) or 1)
    normalized_records = _normalize_import_records(payload, source_server=source_server)
    profile_keys = sorted({str(item.get("profile_key") or "").strip() for item in normalized_records if item.get("profile_key")})
    format_keys = sorted({normalize_upload_format(item.get("format_key")) for item in normalized_records})
    source_servers = sorted({str(item.get("source_server") or "").strip() for item in normalized_records if item.get("source_server")})
    with_hash_count = sum(1 for item in normalized_records if item.get("sha256") or item.get("md5"))
    warnings: list[str] = []
    version_warning = _build_version_warning(version)
    if version_warning:
        warnings.append(version_warning)
    if isinstance(raw_records, list) and raw_records and not normalized_records:
        warnings.append("文件结构合法，但没有识别到可导入的上传记录，请确认是否为旧格式或字段缺失")
    warning = "；".join(warnings) if warnings else None

    return PreviewResult(
        version=version,
        warning=warning,
        raw_record_count=len(raw_records) if isinstance(raw_records, list) else 0,
        normalized_count=len(normalized_records),
        profile_keys=profile_keys,
        format_keys=format_keys,
        source_servers=source_servers,
        with_hash_count=with_hash_count,
    )


def _build_registry_identity(item: UploadRegistry) -> Optional[tuple[str, str, str]]:
    profile_key = str(item.profile_key or "").strip()
    if not profile_key:
        return None

    format_key = normalize_upload_format(item.format_key)
    if item.sha256:
        match_value = str(item.sha256).strip()
        if match_value:
            return "sha256", match_value, f"sha256:{match_value}|{profile_key}|{format_key}"
    if item.md5:
        match_value = str(item.md5).strip()
        if match_value:
            return "md5", match_value, f"md5:{match_value}|{profile_key}|{format_key}"
    if item.resource_id:
        match_value = str(item.resource_id).strip()
        if match_value:
            return "resource_id", match_value, f"resource_id:{match_value}|{profile_key}|{format_key}"
    return None


def _registry_item_completeness(item: UploadRegistry) -> int:
    return sum(
        1
        for value in [
            item.url,
            item.sha256,
            item.md5,
            item.resource_id,
            item.profile_name,
            item.channel,
            item.source_server,
            item.uploaded_at,
        ]
        if value
    )


def _pick_primary_registry_item(items: list[UploadRegistry]) -> UploadRegistry:
    return sorted(
        items,
        key=lambda item: (-_registry_item_completeness(item), item.id),
    )[0]


def _build_duplicate_group_item(identity_key: str, rows: list[UploadRegistry]) -> DuplicateGroupItem:
    primary = _pick_primary_registry_item(rows)
    identity = _build_registry_identity(primary)
    identity_type = identity[0] if identity else "unknown"
    match_value = identity[1] if identity else ""
    urls = sorted({str(row.url).strip() for row in rows if row.url})
    source_servers = sorted({str(row.source_server).strip() for row in rows if row.source_server})

    return DuplicateGroupItem(
        identity_key=identity_key,
        identity_type=identity_type,
        match_value=match_value,
        profile_key=primary.profile_key,
        format_key=normalize_upload_format(primary.format_key),
        count=len(rows),
        canonical_id=primary.id,
        duplicate_ids=[row.id for row in rows if row.id != primary.id],
        url_count=len(urls),
        sample_urls=urls[:3],
        source_servers=source_servers,
    )


def _collect_duplicate_groups(items: list[UploadRegistry]) -> tuple[list[tuple[str, list[UploadRegistry]]], int]:
    grouped: dict[str, list[UploadRegistry]] = defaultdict(list)
    skipped_without_identity = 0

    for item in items:
        identity = _build_registry_identity(item)
        if not identity:
            skipped_without_identity += 1
            continue
        grouped[identity[2]].append(item)

    duplicate_groups = [
        (identity_key, rows)
        for identity_key, rows in grouped.items()
        if len(rows) > 1
    ]
    duplicate_groups.sort(key=lambda entry: (-len(entry[1]), entry[1][0].id))
    return duplicate_groups, skipped_without_identity


def _build_duplicate_scan_result(items: list[UploadRegistry], limit: int = 10) -> DuplicateScanResult:
    duplicate_groups, skipped_without_identity = _collect_duplicate_groups(items)
    group_items = [_build_duplicate_group_item(identity_key, rows) for identity_key, rows in duplicate_groups[:limit]]
    total_duplicate_rows = sum(len(rows) - 1 for _, rows in duplicate_groups)
    conflict_groups = sum(1 for group in group_items if group.url_count > 1)

    if len(duplicate_groups) > len(group_items):
        conflict_groups += sum(
            1
            for identity_key, rows in duplicate_groups[len(group_items):]
            if len({str(row.url).strip() for row in rows if row.url}) > 1
        )

    return DuplicateScanResult(
        total_groups=len(duplicate_groups),
        total_duplicate_rows=total_duplicate_rows,
        conflict_groups=conflict_groups,
        skipped_without_identity=skipped_without_identity,
        groups=group_items,
    )


def _merge_duplicate_group_rows(db: Session, rows: list[UploadRegistry]) -> tuple[bool, int, bool]:
    primary = _pick_primary_registry_item(rows)
    duplicates = [row for row in rows if row.id != primary.id]
    if not duplicates:
        return False, 0, False

    changed = False
    urls = {str(row.url).strip() for row in rows if row.url}

    if not primary.resource_id:
        for row in duplicates:
            if row.resource_id:
                primary.resource_id = row.resource_id
                changed = True
                break
    if not primary.sha256:
        for row in duplicates:
            if row.sha256:
                primary.sha256 = row.sha256
                changed = True
                break
    if not primary.md5:
        for row in duplicates:
            if row.md5:
                primary.md5 = row.md5
                changed = True
                break
    if not primary.profile_name:
        for row in duplicates:
            if row.profile_name:
                primary.profile_name = row.profile_name
                changed = True
                break
    if not primary.channel:
        for row in duplicates:
            if row.channel:
                primary.channel = row.channel
                changed = True
                break
    if not primary.source_server:
        for row in duplicates:
            if row.source_server:
                primary.source_server = row.source_server
                changed = True
                break
    if not primary.url:
        for row in duplicates:
            if row.url:
                primary.url = row.url
                changed = True
                break

    uploaded_candidates = [row.uploaded_at for row in rows if row.uploaded_at]
    if uploaded_candidates:
        earliest_uploaded_at = min(uploaded_candidates)
        if primary.uploaded_at != earliest_uploaded_at:
            primary.uploaded_at = earliest_uploaded_at
            changed = True

    for row in duplicates:
        db.delete(row)

    return changed, len(duplicates), len(urls) > 1


def _import_records(
    db: Session,
    normalized_records: list[dict[str, Any]],
    source_server: Optional[str] = None,
) -> ImportResult:
    merged = inserted = skipped = 0
    errors: list[str] = []

    for idx, record in enumerate(normalized_records):
        profile_key = str(record.get("profile_key") or "").strip()
        url = str(record.get("url") or "").strip()
        if not profile_key or not url:
            skipped += 1
            continue

        sha256 = record.get("sha256")
        md5 = record.get("md5")
        resource_id = record.get("resource_id")
        format_key = normalize_upload_format(record.get("format_key"))

        identity_filters = []
        if sha256:
            identity_filters.append(UploadRegistry.sha256 == sha256)
        if md5:
            identity_filters.append(UploadRegistry.md5 == md5)
        if resource_id:
            identity_filters.append(UploadRegistry.resource_id == resource_id)
        if url:
            identity_filters.append(UploadRegistry.url == url)

        existing = (
            db.query(UploadRegistry)
            .filter(
                UploadRegistry.profile_key == profile_key,
                UploadRegistry.format_key == format_key,
                or_(*identity_filters),
            )
            .order_by(UploadRegistry.id.asc())
            .first()
        ) if identity_filters else None

        try:
            before_url = existing.url if existing else None
            before_profile_name = existing.profile_name if existing else None
            before_channel = existing.channel if existing else None
            before_source_server = existing.source_server if existing else None
            before_sha256 = existing.sha256 if existing else None
            before_md5 = existing.md5 if existing else None
            before_resource_id = existing.resource_id if existing else None

            upsert_upload_registry_record(
                db,
                profile_key=profile_key,
                format_key=format_key,
                url=url,
                resource_id=resource_id,
                sha256=sha256,
                md5=md5,
                profile_name=record.get("profile_name"),
                channel=record.get("channel"),
                uploaded_at=record.get("uploaded_at"),
                source_server=record.get("source_server") or source_server,
            )

            if not existing:
                inserted += 1
                continue

            changed = any(
                [
                    before_url != existing.url,
                    before_profile_name != existing.profile_name,
                    before_channel != existing.channel,
                    before_source_server != existing.source_server,
                    before_sha256 != existing.sha256,
                    before_md5 != existing.md5,
                    before_resource_id != existing.resource_id,
                ]
            )
            if changed:
                merged += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("导入上传记录失败: index=%d record=%s", idx, record)
            errors.append(f"{profile_key}/{format_key}: {exc}")

    db.commit()
    return ImportResult(
        total=len(normalized_records),
        merged=merged,
        inserted=inserted,
        skipped=skipped,
        errors=errors[:20],
    )


@router.get("/stats")
def get_sync_stats(db: Session = Depends(get_db)):
    return _build_sync_stats(db)


@router.get("/history", response_model=SyncHistoryListResult)
def get_sync_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items = (
        db.query(SyncHistory)
        .order_by(SyncHistory.id.desc())
        .limit(limit)
        .all()
    )
    return SyncHistoryListResult(items=[_serialize_sync_history_item(item) for item in items])


@router.get("/export-options", response_model=ExportOptionsResult)
def get_export_options(
    include_all: bool = False,
    db: Session = Depends(get_db),
):
    _prepare_registry(db)
    items = (
        _query_export_registry_items(db, include_all=include_all)
        .order_by(UploadRegistry.profile_key.asc(), UploadRegistry.format_key.asc(), UploadRegistry.id.asc())
        .all()
    )
    return _build_export_options(items)


@router.get("/export-estimate", response_model=ExportEstimateResult)
def get_export_estimate(
    include_all: bool = False,
    profile_keys: Optional[str] = Query(default=None),
    format_keys: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    _prepare_registry(db)
    normalized_profile_keys = _parse_filter_values(profile_keys)
    normalized_format_keys = _normalize_format_filters(_parse_filter_values(format_keys))
    total = _query_export_registry_items(
        db,
        include_all=include_all,
        profile_keys=normalized_profile_keys or None,
        format_keys=normalized_format_keys or None,
    ).count()
    return ExportEstimateResult(
        total=total,
        include_all=include_all,
        profile_keys=normalized_profile_keys,
        format_keys=normalized_format_keys,
    )


@router.get("/duplicates", response_model=DuplicateScanResult)
def get_registry_duplicates(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _prepare_registry(db)
    items = (
        db.query(UploadRegistry)
        .order_by(UploadRegistry.profile_key.asc(), UploadRegistry.format_key.asc(), UploadRegistry.id.asc())
        .all()
    )
    result = _build_duplicate_scan_result(items, limit=limit)
    _record_sync_history(
        db,
        action="dedupe-scan",
        summary=f"扫描注册表重复项：发现 {result.total_groups} 组，冗余 {result.total_duplicate_rows} 条",
        detail=f"冲突组 {result.conflict_groups}，无身份键 {result.skipped_without_identity}",
    )
    _prune_sync_history(db)
    db.commit()
    return result


@router.post("/duplicates/merge", response_model=DuplicateMergeResult)
def merge_registry_duplicates(body: DuplicateMergeRequest, db: Session = Depends(get_db)):
    _prepare_registry(db)

    items = (
        db.query(UploadRegistry)
        .order_by(UploadRegistry.profile_key.asc(), UploadRegistry.format_key.asc(), UploadRegistry.id.asc())
        .all()
    )
    duplicate_groups, _ = _collect_duplicate_groups(items)
    if body.identity_key:
        duplicate_groups = [group for group in duplicate_groups if group[0] == body.identity_key]
    duplicate_groups = duplicate_groups[: body.limit]

    merged_groups = 0
    removed_rows = 0
    updated_primary_rows = 0
    conflict_groups = 0
    skipped_groups = 0
    merged_identity_keys: list[str] = []
    errors: list[str] = []

    for identity_key, rows in duplicate_groups:
        try:
            changed, removed_count, has_conflict = _merge_duplicate_group_rows(db, rows)
            if removed_count <= 0:
                skipped_groups += 1
                continue
            merged_groups += 1
            removed_rows += removed_count
            if changed:
                updated_primary_rows += 1
            if has_conflict:
                conflict_groups += 1
            merged_identity_keys.append(identity_key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("合并注册表重复项失败: identity_key=%s", identity_key)
            errors.append(f"{identity_key}: {exc}")

    result = DuplicateMergeResult(
        scanned_groups=len(duplicate_groups),
        merged_groups=merged_groups,
        removed_rows=removed_rows,
        updated_primary_rows=updated_primary_rows,
        conflict_groups=conflict_groups,
        skipped_groups=skipped_groups,
        merged_identity_keys=merged_identity_keys[:20],
        errors=errors[:20],
    )
    _record_sync_history(
        db,
        action="dedupe-merge",
        status="partial" if result.errors else "success",
        summary=f"合并重复项完成：处理 {result.merged_groups} 组，移除 {result.removed_rows} 条冗余记录",
        detail=f"补全主记录 {result.updated_primary_rows} 条；冲突组 {result.conflict_groups}",
    )
    _prune_sync_history(db)
    db.commit()
    return result


@router.get("/handshake")
def handshake(
    request: Request,
    sync_token: Optional[str] = Query(default=None),
    x_sync_token: Optional[str] = Header(default=None, alias="X-Sync-Token"),
    db: Session = Depends(get_db),
):
    source = _enforce_sync_access(request, "handshake")
    _require_sync_token(x_sync_token or sync_token)
    return {
        "ok": True,
        "version": _EXPORT_VERSION,
        "server": "hao-wallpaper-downloader",
        "source": source,
        "stats": _build_sync_stats(db),
        "warning": None,
    }


@router.get("/export")
def export_records(
    request: Request,
    include_all: bool = False,
    profile_keys: Optional[str] = Query(default=None),
    format_keys: Optional[str] = Query(default=None),
    sync_token: Optional[str] = Query(default=None),
    x_sync_token: Optional[str] = Header(default=None, alias="X-Sync-Token"),
    db: Session = Depends(get_db),
):
    source = _enforce_sync_access(request, "export")
    _require_sync_token(x_sync_token or sync_token)
    _prepare_registry(db)
    normalized_profile_keys = _parse_filter_values(profile_keys)
    normalized_format_keys = _normalize_format_filters(_parse_filter_values(format_keys))
    payload = _build_export_payload(
        db,
        include_all=include_all,
        profile_keys=normalized_profile_keys or None,
        format_keys=normalized_format_keys or None,
    )
    detail_parts = []
    if normalized_profile_keys:
        detail_parts.append(f"profile={','.join(normalized_profile_keys)}")
    if normalized_format_keys:
        detail_parts.append(f"format={','.join(normalized_format_keys)}")
    _record_sync_history(
        db,
        action="export",
        summary=f"导出 {payload['total']} 条上传记录",
        detail="；".join(detail_parts) if detail_parts else None,
        source_server=source,
    )
    _prune_sync_history(db)
    db.commit()
    json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"upload-registry-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ImportResult)
async def import_records(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        _record_sync_history(
            db,
            action="import",
            status="error",
            summary="导入失败：同步包 JSON 解析失败",
            detail=str(exc),
        )
        _prune_sync_history(db)
        db.commit()
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {exc}")

    normalized_records = _normalize_import_records(payload)
    result = _import_records(db, normalized_records)
    _record_sync_history(
        db,
        action="import",
        status="partial" if result.errors else "success",
        summary=f"导入完成：新增 {result.inserted}，合并 {result.merged}，跳过 {result.skipped}",
        detail=f"总记录 {result.total}",
    )
    _prune_sync_history(db)
    db.commit()
    return result


@router.post("/preview", response_model=PreviewResult)
async def preview_import_file(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {exc}")

    return _build_preview_result(payload)


@router.post("/pull", response_model=ImportResult)
async def pull_remote_records(body: RemotePullRequest, db: Session = Depends(get_db)):
    remote_base_url = _normalize_base_url(body.remote_base_url)
    export_url = f"{remote_base_url}/api/sync/export"
    source_server = _guess_source_server(remote_base_url)
    headers = {}
    if body.remote_sync_token:
        headers["X-Sync-Token"] = body.remote_sync_token.strip()

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(
                export_url,
                params={"include_all": str(bool(body.include_all)).lower()},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        _record_sync_history(
            db,
            action="pull",
            status="error",
            summary=f"{remote_base_url} 迁移失败",
            detail=str(exc),
            remote_base_url=remote_base_url,
            source_server=source_server,
        )
        _prune_sync_history(db)
        db.commit()
        raise HTTPException(status_code=502, detail=f"拉取远程同步数据失败: {exc}")
    except json.JSONDecodeError as exc:
        _record_sync_history(
            db,
            action="pull",
            status="error",
            summary=f"{remote_base_url} 迁移失败：远程返回非法 JSON",
            detail=str(exc),
            remote_base_url=remote_base_url,
            source_server=source_server,
        )
        _prune_sync_history(db)
        db.commit()
        raise HTTPException(status_code=502, detail=f"远程返回的同步数据不是合法 JSON: {exc}")

    normalized_records = _normalize_import_records(payload, source_server=source_server)
    result = _import_records(db, normalized_records, source_server=source_server)
    _record_sync_history(
        db,
        action="pull",
        status="partial" if result.errors else "success",
        summary=f"{remote_base_url} 迁移完成：新增 {result.inserted}，合并 {result.merged}，跳过 {result.skipped}",
        detail=f"总记录 {result.total}",
        remote_base_url=remote_base_url,
        source_server=source_server,
    )
    _prune_sync_history(db)
    db.commit()
    return result


@router.post("/probe")
async def probe_remote_records(body: RemoteProbeRequest, db: Session = Depends(get_db)):
    remote_base_url = _normalize_base_url(body.remote_base_url)
    probe_url = f"{remote_base_url}/api/sync/handshake"
    source_server = _guess_source_server(remote_base_url)
    headers = {}
    if body.remote_sync_token:
        headers["X-Sync-Token"] = body.remote_sync_token.strip()

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(probe_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200] if exc.response is not None else str(exc)
        _record_sync_history(
            db,
            action="probe",
            status="error",
            summary=f"{remote_base_url} 测试失败",
            detail=detail,
            remote_base_url=remote_base_url,
            source_server=source_server,
        )
        _prune_sync_history(db)
        db.commit()
        raise HTTPException(status_code=502, detail=f"远程探测失败: {detail}")
    except httpx.HTTPError as exc:
        _record_sync_history(
            db,
            action="probe",
            status="error",
            summary=f"{remote_base_url} 测试失败",
            detail=str(exc),
            remote_base_url=remote_base_url,
            source_server=source_server,
        )
        _prune_sync_history(db)
        db.commit()
        raise HTTPException(status_code=502, detail=f"远程探测失败: {exc}")
    except json.JSONDecodeError as exc:
        _record_sync_history(
            db,
            action="probe",
            status="error",
            summary=f"{remote_base_url} 测试失败：握手响应不是合法 JSON",
            detail=str(exc),
            remote_base_url=remote_base_url,
            source_server=source_server,
        )
        _prune_sync_history(db)
        db.commit()
        raise HTTPException(status_code=502, detail=f"远程握手响应不是合法 JSON: {exc}")

    result = {
        "ok": bool(payload.get("ok")),
        "remote_base_url": remote_base_url,
        "source_server": source_server,
        "request_source": payload.get("source"),
        "version": payload.get("version"),
        "server": payload.get("server"),
        "stats": payload.get("stats") or {},
        "warning": payload.get("warning") or _build_version_warning(payload.get("version")),
    }
    _record_sync_history(
        db,
        action="probe",
        summary=f"{remote_base_url} 连接正常，可导出 {result['stats'].get('registry_exportable', 0)} 条",
        detail=f"协议版本 {result.get('version') or 'unknown'}",
        remote_base_url=remote_base_url,
        source_server=source_server,
    )
    _prune_sync_history(db)
    db.commit()
    return result
