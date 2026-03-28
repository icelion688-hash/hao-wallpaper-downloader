"""
api/stats.py — 系统监控统计 API
"""
import asyncio
from datetime import datetime, timedelta
import os
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from backend.core.downloader import DOWNLOAD_ROOT
from backend.core.upload_profiles import get_upload_profile, get_upload_settings, is_upload_profile_available
from backend.core.upload_record_helper import infer_upload_state
from backend.api.gallery import (
    audit_task_upload_consistency,
    repair_task_upload_consistency,
    reupload_remote_missing_for_task_profile,
)
from backend.models.database import get_db
from backend.models.wallpaper import Wallpaper
from backend.models.task import Task
from backend.models.account import Account

router = APIRouter()
_UPLOAD_COVERAGE_MUTATION_LOCK = asyncio.Lock()


def _local_wallpaper_filter():
    return and_(Wallpaper.local_path.isnot(None), Wallpaper.local_path != "")


def _resolve_task_upload_profile() -> tuple[str, dict | None, bool]:
    uploads = get_upload_settings()
    profile_key = str(uploads.get("task_profile") or "").strip()
    profile = get_upload_profile(profile_key) if profile_key else None
    only_original = bool(((profile or {}).get("upload_filter") or {}).get("only_original", False))
    return profile_key, profile, only_original


def _build_upload_coverage(db: Session) -> dict:
    profile_key, profile, only_original = _resolve_task_upload_profile()
    rows = (
        db.query(Wallpaper)
        .filter(Wallpaper.status == "done")
        .order_by(Wallpaper.downloaded_at.desc(), Wallpaper.id.desc())
        .all()
    )

    historical_total = len(rows)
    historical_uploaded_count = 0
    historical_missing_count = 0
    total_local = 0
    uploaded_count = 0
    missing_count = 0
    repairable_count = 0
    missing_file_count = 0
    no_local_record_count = 0
    broken_local_file_count = 0
    reason_counter = Counter()
    category_counter = Counter()
    uploaded_category_counter = Counter()
    pending_items: list[dict] = []
    repairable_ids: list[int] = []

    for wallpaper in rows:
        inferred_status, inferred_note = infer_upload_state(
            imgbed_url=wallpaper.imgbed_url,
            upload_records=wallpaper.upload_records,
            upload_status=wallpaper.upload_status,
            upload_note=wallpaper.upload_note,
            is_original=wallpaper.is_original,
            current_profile_only_original=only_original,
        )
        local_rel = str(wallpaper.local_path or "").strip()
        local_abs = os.path.join(DOWNLOAD_ROOT, local_rel) if local_rel else ""
        file_exists = bool(local_abs and os.path.exists(local_abs))
        has_local_record = bool(local_rel)

        if has_local_record:
            total_local += 1

        if inferred_status == "uploaded":
            historical_uploaded_count += 1
            uploaded_category_counter[wallpaper.category or "未分类"] += 1
            if has_local_record:
                uploaded_count += 1
            continue

        historical_missing_count += 1
        reason = inferred_note or "未上传到图床"
        reason_counter[reason] += 1
        category = wallpaper.category or "未分类"
        category_counter[category] += 1
        repairable = file_exists and bool(local_rel)

        if has_local_record:
            missing_count += 1

        if repairable:
            repairable_count += 1
            repairable_ids.append(int(wallpaper.id))
        else:
            missing_file_count += 1
            if has_local_record:
                broken_local_file_count += 1
            else:
                no_local_record_count += 1

        pending_items.append({
            "id": wallpaper.id,
            "resource_id": wallpaper.resource_id,
            "title": wallpaper.title or "",
            "category": category,
            "local_path": local_rel,
            "upload_status": inferred_status,
            "reason": reason,
            "file_exists": file_exists,
            "repairable": repairable,
            "downloaded_at": wallpaper.downloaded_at.isoformat() if wallpaper.downloaded_at else None,
            "local_state": "exists" if repairable else ("missing" if has_local_record else "cleaned"),
        })

    return {
        "profile_key": profile_key,
        "profile_name": str((profile or {}).get("name") or profile_key or ""),
        "profile_available": bool(profile_key and is_upload_profile_available(profile_key)),
        "profile_only_original": only_original,
        "historical_total": historical_total,
        "historical_uploaded_count": historical_uploaded_count,
        "historical_missing_count": historical_missing_count,
        "historical_coverage_ratio": round((historical_uploaded_count / historical_total) * 100, 2) if historical_total else 0.0,
        "total_local": total_local,
        "uploaded_count": uploaded_count,
        "missing_count": missing_count,
        "repairable_count": repairable_count,
        "missing_file_count": missing_file_count,
        "no_local_record_count": no_local_record_count,
        "broken_local_file_count": broken_local_file_count,
        "coverage_ratio": round((uploaded_count / total_local) * 100, 2) if total_local else 0.0,
        "reason_breakdown": [
            {"reason": reason, "count": count}
            for reason, count in reason_counter.most_common(5)
        ],
        "missing_categories": [
            {"category": category, "count": count}
            for category, count in category_counter.most_common(8)
        ],
        "uploaded_categories": [
            {"category": category, "count": count}
            for category, count in uploaded_category_counter.most_common()
        ],
        "pending_items": pending_items[:100],
        "repairable_ids": repairable_ids,
    }


async def run_upload_coverage_maintenance(db: Session) -> dict:
    async with _UPLOAD_COVERAGE_MUTATION_LOCK:
        coverage_before = _build_upload_coverage(db)
        audit_before = await audit_task_upload_consistency(db)

        if audit_before.get("repairable_count"):
            repair_result = await repair_task_upload_consistency(db, sync_local_tags=False)
        else:
            repair_result = {
                "success": True,
                "profile_key": audit_before.get("profile_key"),
                "audit": audit_before,
                "repair": {
                    "success": True,
                    "profile_key": audit_before.get("profile_key"),
                    "updated_count": 0,
                    "local_tags_updated_count": 0,
                    "unmatched_count": 0,
                    "failed_count": 0,
                    "items": [],
                    "failed_items": [],
                    "unmatched": [],
                },
            }

        if any(item.get("audit_status") == "remote_missing" for item in (audit_before.get("problem_items") or [])):
            remote_missing_reupload = await reupload_remote_missing_for_task_profile(db)
        else:
            remote_missing_reupload = {
                "success": True,
                "profile_key": audit_before.get("profile_key"),
                "prepared_count": 0,
                "upload_result": None,
                "audit": audit_before,
            }

        if coverage_before.get("repairable_count"):
            reupload_result = await _reupload_missing_wallpapers_internal(db, coverage=coverage_before)
        else:
            reupload_result = {
                "success": True,
                "message": "当前没有可补传的未上传图片",
                "reupload_total": 0,
                "result": None,
                "coverage": coverage_before,
            }

        return {
            "success": True,
            "audit_before": audit_before,
            "repair_result": repair_result,
            "remote_missing_reupload": remote_missing_reupload,
            "reupload_result": reupload_result,
            "coverage_after": _build_upload_coverage(db),
        }


@router.get("/overview")
async def get_overview(db: Session = Depends(get_db)):
    """系统总览统计"""
    coverage = _build_upload_coverage(db)
    historical_downloaded = (
        db.query(func.count(Wallpaper.id))
        .filter(Wallpaper.status == "done")
        .scalar()
    )
    current_local_count = (
        db.query(func.count(Wallpaper.id))
        .filter(Wallpaper.status == "done", _local_wallpaper_filter())
        .scalar()
    )
    current_local_size = (
        db.query(func.sum(Wallpaper.file_size))
        .filter(Wallpaper.status == "done", _local_wallpaper_filter())
        .scalar()
        or 0
    )
    uploaded_gallery_count = int(coverage.get("historical_uploaded_count") or 0)
    total_accounts = db.query(func.count(Account.id)).scalar()
    active_accounts = db.query(func.count(Account.id)).filter(Account.is_active == True).scalar()  # noqa
    total_tasks = db.query(func.count(Task.id)).scalar()
    running_tasks = db.query(func.count(Task.id)).filter(Task.status == "running").scalar()

    return {
        "total_wallpapers": historical_downloaded,
        "historical_downloaded": historical_downloaded,
        "current_local_count": current_local_count,
        "uploaded_gallery_count": uploaded_gallery_count,
        "total_size_bytes": current_local_size,
        "total_size_gb": round(current_local_size / (1024 ** 3), 2),
        "current_local_size_bytes": current_local_size,
        "current_local_size_gb": round(current_local_size / (1024 ** 3), 2),
        "total_accounts": total_accounts,
        "active_accounts": active_accounts,
        "total_tasks": total_tasks,
        "running_tasks": running_tasks,
    }


@router.get("/by-category")
async def stats_by_category(db: Session = Depends(get_db)):
    """按分类统计已上传到图库的数量。"""
    coverage = _build_upload_coverage(db)
    rows = coverage.get("uploaded_categories") or []
    total_uploaded = sum(int(row.get("count") or 0) for row in rows)
    return {
        "source": "uploaded_gallery",
        "total_uploaded": total_uploaded,
        "categories": rows,
    }


@router.get("/by-date")
async def stats_by_date(days: int = 30, db: Session = Depends(get_db)):
    """最近 N 天每日历史下载数量（补齐空日期）。"""
    start = datetime.now() - timedelta(days=days)
    rows = (
        db.query(
            func.date(Wallpaper.downloaded_at).label("date"),
            func.count(Wallpaper.id).label("count"),
        )
        .filter(Wallpaper.downloaded_at >= start, Wallpaper.status == "done")
        .group_by(func.date(Wallpaper.downloaded_at))
        .order_by("date")
        .all()
    )
    counter = {str(row.date): row.count for row in rows}
    daily = []
    base_date = start.date()
    for offset in range(days + 1):
        current = base_date + timedelta(days=offset)
        current_key = current.isoformat()
        daily.append({"date": current_key, "count": int(counter.get(current_key, 0))})
    return {"daily": daily}


@router.get("/upload-coverage")
async def get_upload_coverage(db: Session = Depends(get_db)):
    """对比当前本地图片与已上传图片数量，并列出未上传项。"""
    return _build_upload_coverage(db)


@router.post("/upload-coverage/compare-remote")
async def compare_remote_upload_coverage(db: Session = Depends(get_db)):
    """扫描任务默认图床索引，返回远端图库和本地上传记录的差异。"""
    audit = await audit_task_upload_consistency(db)
    return {
        "success": True,
        "audit": audit,
        "coverage": _build_upload_coverage(db),
    }


@router.get("/upload-coverage/guard-status")
async def get_upload_guard_status(request: Request):
    guard = getattr(request.app.state, "upload_guard", None)
    if not guard:
        return {
            "enabled": False,
            "running": False,
            "interval_seconds": 0,
            "last_run_at": None,
            "last_status": "disabled",
            "last_error": "",
            "last_summary": None,
        }
    return guard.get_status()


async def _reupload_missing_wallpapers_internal(db: Session, *, coverage: dict | None = None) -> dict:
    coverage = coverage or _build_upload_coverage(db)
    profile_key = str(coverage.get("profile_key") or "").strip()
    if not profile_key:
        raise HTTPException(400, "当前未配置任务默认上传 Profile")
    if not coverage.get("profile_available"):
        raise HTTPException(400, f"上传 Profile 不可用: {profile_key}")

    repairable_ids = list(dict.fromkeys(coverage.get("repairable_ids") or []))
    if not repairable_ids:
        return {
            "success": True,
            "message": "当前没有可补传的未上传图片",
            "reupload_total": 0,
            "result": None,
            "coverage": coverage,
        }

    from backend.api.gallery import BatchUploadRequest, batch_upload_wallpapers

    result = await batch_upload_wallpapers(
        BatchUploadRequest(
            profile_key=profile_key,
            upload_format="profile",
            upload_with_tags=None,
            wallpaper_ids=repairable_ids,
            upload_scope="selected",
            only_not_uploaded=True,
        ),
        db,
    )
    refreshed = _build_upload_coverage(db)
    return {
        "success": True,
        "message": f"已尝试补传 {len(repairable_ids)} 张未上传图片",
        "reupload_total": len(repairable_ids),
        "result": result,
        "coverage": refreshed,
    }


@router.post("/upload-coverage/reupload")
async def reupload_missing_wallpapers(db: Session = Depends(get_db)):
    """使用任务默认 Profile 补传当前未上传且本地文件仍存在的图片。"""
    async with _UPLOAD_COVERAGE_MUTATION_LOCK:
        return await _reupload_missing_wallpapers_internal(db)
