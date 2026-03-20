"""
api/gallery.py - 下载画廊、手动上传与批量格式转换 API。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.config import load_config
from backend.core.dedup import DedupManager
from backend.core.downloader import DOWNLOAD_ROOT
from backend.core.upload_profiles import build_uploader_by_key, list_upload_profiles
from backend.core.upload_record_helper import (
    UPLOAD_FORMAT_LABELS,
    build_upload_record,
    build_upload_record_key,
    dump_upload_records,
    find_reusable_upload_record,
    get_upload_record,
    normalize_upload_format,
    parse_upload_records,
)
from backend.models.database import get_db
from backend.models.wallpaper import Wallpaper

logger = logging.getLogger(__name__)
router = APIRouter()

def _get_convert_queue():
    from backend.core.convert_queue import get_convert_queue
    return get_convert_queue()


def _apply_filters(
    q,
    category: Optional[str] = None,
    type_id: Optional[str] = None,
    color_id: Optional[str] = None,
    wallpaper_type: Optional[str] = None,
    status: Optional[str] = "done",
    search: Optional[str] = None,
    color_theme: Optional[str] = None,
    screen_orientation: Optional[str] = None,
    min_width: Optional[int] = None,
    min_height: Optional[int] = None,
):
    if status:
        q = q.filter(Wallpaper.status == status)
    if type_id:
        q = q.filter(Wallpaper.type_id == type_id)
    elif category:
        q = q.filter(Wallpaper.category.contains(category))
    if color_id:
        q = q.filter(Wallpaper.color_id == color_id)
    if wallpaper_type:
        q = q.filter(Wallpaper.wallpaper_type == wallpaper_type)
    if search:
        q = q.filter(
            or_(
                Wallpaper.title.contains(search),
                Wallpaper.tags.contains(search),
            )
        )
    if color_theme:
        q = q.filter(Wallpaper.color_theme == color_theme)
    if screen_orientation == "landscape":
        q = q.filter(
            Wallpaper.width.isnot(None),
            Wallpaper.height.isnot(None),
            Wallpaper.width >= Wallpaper.height,
        )
    elif screen_orientation == "portrait":
        q = q.filter(
            Wallpaper.width.isnot(None),
            Wallpaper.height.isnot(None),
            Wallpaper.height > Wallpaper.width,
        )
    if min_width:
        q = q.filter(Wallpaper.width >= min_width)
    if min_height:
        q = q.filter(Wallpaper.height >= min_height)
    return q


def _w_to_dict(w: Wallpaper) -> dict:
    rel = w.local_path.replace("\\", "/") if w.local_path else None
    converted_rel = w.converted_path.replace("\\", "/") if w.converted_path else None
    converted_abs = os.path.join(DOWNLOAD_ROOT, w.converted_path) if w.converted_path else None
    converted_exists = bool(converted_abs and os.path.exists(converted_abs))
    return {
        "id": w.id,
        "resource_id": w.resource_id,
        "title": w.title,
        "resolution": w.resolution,
        "width": w.width,
        "height": w.height,
        "wallpaper_type": w.wallpaper_type,
        "category": w.category,
        "type_id": w.type_id,
        "color_id": w.color_id,
        "tags": w.tags,
        "color_theme": w.color_theme,
        "file_size": w.file_size,
        "file_mb": w.file_mb,
        "is_original": w.is_original,
        "hot_score": w.hot_score,
        "favor_count": w.favor_count,
        "local_path": w.local_path,
        "file_url": f"/downloads/{rel}" if rel else None,
        "status": w.status,
        "is_duplicate": w.is_duplicate,
        "downloaded_at": w.downloaded_at,
        "imgbed_url": w.imgbed_url,
        "upload_records": parse_upload_records(w.upload_records),
        "video_duration": w.video_duration,
        "converted_path": w.converted_path,
        "converted_exists": converted_exists,
        "converted_url": (
            f"/downloads/{converted_rel}"
            if converted_rel and converted_exists else None
        ),
    }


class BatchUploadRequest(BaseModel):
    profile_key: str
    upload_format: str = "profile"
    wallpaper_ids: list[int] = Field(default_factory=list)
    upload_scope: str = "selected"
    category: Optional[str] = None
    wallpaper_type: Optional[str] = None
    search: Optional[str] = None
    only_not_uploaded: bool = True


def _path_ext_to_upload_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".webp": "webp",
        ".gif": "gif",
        ".png": "png",
        ".jpg": "jpg",
        ".jpeg": "jpg",
    }.get(ext, "original")


def _resolve_upload_asset(
    wallpaper: Wallpaper,
    upload_format: str,
) -> tuple[Optional[str], Optional[str], str]:
    """
    返回 (upload_path, format_override, reason)。

    format_override:
    - profile: 跟随 Profile 默认行为
    - original: 直接上传给定文件，不做额外本地预处理
    - webp: 对原始静态图强制做一次本地 WebP 预处理
    """
    original_abs = os.path.join(DOWNLOAD_ROOT, wallpaper.local_path) if wallpaper.local_path else None
    converted_abs = (
        os.path.join(DOWNLOAD_ROOT, wallpaper.converted_path)
        if wallpaper.converted_path else None
    )
    normalized = normalize_upload_format(upload_format)

    if normalized == "profile":
        return original_abs, "profile", ""

    if not original_abs or not os.path.exists(original_abs):
        return None, None, "原始文件不存在"

    original_format = _path_ext_to_upload_format(original_abs)
    if normalized == "original" or original_format == normalized:
        return original_abs, "original", ""

    if converted_abs and os.path.exists(converted_abs):
        converted_format = _path_ext_to_upload_format(converted_abs)
        if converted_format == normalized:
            return converted_abs, "original", ""

    if normalized == "webp" and wallpaper.wallpaper_type != "dynamic":
        return original_abs, "webp", ""

    if wallpaper.wallpaper_type == "dynamic":
        return None, None, f"当前是动态图，请先转换出 {UPLOAD_FORMAT_LABELS[normalized]} 再上传"
    return None, None, f"当前未找到可上传的 {UPLOAD_FORMAT_LABELS[normalized]} 文件"


def _delete_wallpaper_files(wallpaper: Wallpaper) -> int:
    """删除原文件和转换产物，返回删除失败次数。"""
    failed = 0
    rel_paths = [wallpaper.local_path, wallpaper.converted_path]
    for rel_path in {path for path in rel_paths if path}:
        abs_path = os.path.join(DOWNLOAD_ROOT, rel_path)
        try:
            if os.path.exists(abs_path):
                os.remove(abs_path)
        except OSError as exc:
            logger.warning("[Gallery] 删除文件失败: %s — %s", abs_path, exc)
            failed += 1
    return failed


def _prune_empty_download_dirs() -> None:
    """删除 downloads/ 下的空目录，保留根目录本身。"""
    for root, dirs, _ in os.walk(DOWNLOAD_ROOT, topdown=False):
        for dir_name in dirs:
            abs_path = os.path.join(root, dir_name)
            try:
                if abs_path != DOWNLOAD_ROOT and not os.listdir(abs_path):
                    os.rmdir(abs_path)
            except OSError:
                continue


def _wipe_download_root() -> tuple[int, int]:
    """
    删除 downloads/ 下全部文件并清理空目录。

    返回:
      (deleted_files, failed_files)
    """
    deleted = 0
    failed = 0

    if not os.path.isdir(DOWNLOAD_ROOT):
        return deleted, failed

    for root, _, files in os.walk(DOWNLOAD_ROOT):
        for file_name in files:
            abs_path = os.path.join(root, file_name)
            try:
                os.remove(abs_path)
                deleted += 1
            except OSError as exc:
                logger.warning("[Gallery] 删除残留文件失败: %s — %s", abs_path, exc)
                failed += 1

    _prune_empty_download_dirs()
    return deleted, failed


class BatchDeleteRequest(BaseModel):
    scope: str = "selected"          # "selected" | "category" | "all"
    wallpaper_ids: list[int] = Field(default_factory=list)
    category: Optional[str] = None   # scope=category 时必填
    delete_file: bool = True          # 是否同时删除本地文件


@router.get("")
async def list_wallpapers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: Optional[str] = None,
    type_id: Optional[str] = None,
    color_id: Optional[str] = None,
    wallpaper_type: Optional[str] = None,
    status: Optional[str] = "done",
    search: Optional[str] = None,
    color_theme: Optional[str] = None,
    screen_orientation: Optional[str] = None,
    min_width: Optional[int] = None,
    min_height: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = _apply_filters(
        db.query(Wallpaper),
        category=category,
        type_id=type_id,
        color_id=color_id,
        wallpaper_type=wallpaper_type,
        status=status,
        search=search,
        color_theme=color_theme,
        screen_orientation=screen_orientation,
        min_width=min_width,
        min_height=min_height,
    )

    total = q.count()
    items = q.order_by(Wallpaper.downloaded_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "wallpapers": [_w_to_dict(w) for w in items],
    }


@router.get("/categories")
async def list_categories(db: Session = Depends(get_db)):
    """返回 DB 中已有壁纸按 category 字段分组的统计（用于画廊筛选芯片）"""
    rows = (
        db.query(Wallpaper.category, func.count(Wallpaper.id).label("cnt"))
        .filter(Wallpaper.status == "done", Wallpaper.category.isnot(None), Wallpaper.category != "")
        .group_by(Wallpaper.category)
        .order_by(func.count(Wallpaper.id).desc())
        .all()
    )
    return {"categories": [{"name": row[0], "count": row[1]} for row in rows if row[0]]}


@router.get("/categories-by-type")
async def list_categories_by_type(db: Session = Depends(get_db)):
    """返回 DB 中已有壁纸按 type_id UUID 分组的统计（含可读名称和十六进制无关颜色）"""
    from backend.core.category_map import get_category_name
    rows = (
        db.query(Wallpaper.type_id, func.count(Wallpaper.id).label("cnt"))
        .filter(Wallpaper.status == "done", Wallpaper.type_id.isnot(None), Wallpaper.type_id != "")
        .group_by(Wallpaper.type_id)
        .order_by(func.count(Wallpaper.id).desc())
        .all()
    )
    return {
        "categories": [
            {"id": row[0], "name": get_category_name(row[0]) or row[0], "count": row[1]}
            for row in rows if row[0]
        ]
    }


@router.get("/color-themes")
async def list_color_themes(db: Session = Depends(get_db)):
    """返回 DB 中已有壁纸按色系名称分组的统计"""
    rows = (
        db.query(Wallpaper.color_theme, func.count(Wallpaper.id).label("cnt"))
        .filter(Wallpaper.status == "done", Wallpaper.color_theme.isnot(None), Wallpaper.color_theme != "")
        .group_by(Wallpaper.color_theme)
        .order_by(func.count(Wallpaper.id).desc())
        .all()
    )
    return {"color_themes": [{"name": row[0], "count": row[1]} for row in rows if row[0]]}


@router.get("/wallpaper-meta")
async def get_wallpaper_meta():
    """
    返回网站壁纸分类 + 色系完整映射表（来自 getTypeAll API，本地静态缓存）。
    前端用于：
      - 任务创建弹窗的分类/色系多选
      - 筛选配置页的快捷选项
      - 画廊色系芯片的颜色渲染
    """
    from backend.core.category_map import list_categories, list_colors
    return {
        "categories": list_categories(),
        "colors": list_colors(),
    }


@router.get("/upload-profiles")
async def get_upload_profiles():
    return {"profiles": list_upload_profiles()}


@router.post("/upload")
async def batch_upload_wallpapers(body: BatchUploadRequest, db: Session = Depends(get_db)):
    uploader = build_uploader_by_key(body.profile_key)
    if not uploader:
        raise HTTPException(400, f"上传配置不可用: {body.profile_key}")

    profile = next((item for item in list_upload_profiles() if item.get("key") == body.profile_key), None)
    if not profile:
        raise HTTPException(404, f"上传配置不存在: {body.profile_key}")
    upload_format = normalize_upload_format(body.upload_format)
    format_label = UPLOAD_FORMAT_LABELS[upload_format]

    if body.upload_scope == "selected":
        if not body.wallpaper_ids:
            raise HTTPException(400, "请选择要上传的图片")
        wallpapers = (
            db.query(Wallpaper)
            .filter(Wallpaper.id.in_(body.wallpaper_ids), Wallpaper.status == "done")
            .order_by(Wallpaper.id.asc())
            .all()
        )
    else:
        q = _apply_filters(
            db.query(Wallpaper),
            category=body.category,
            wallpaper_type=body.wallpaper_type,
            status="done",
            search=body.search,
        )
        wallpapers = q.order_by(Wallpaper.downloaded_at.desc()).all()

    success_items = []
    failed_items = []
    skipped_items = []

    for wallpaper in wallpapers:
        if not wallpaper.local_path:
            failed_items.append({"id": wallpaper.id, "reason": "缺少本地文件路径"})
            continue

        abs_path = os.path.join(DOWNLOAD_ROOT, wallpaper.local_path)
        if not os.path.exists(abs_path):
            failed_items.append({"id": wallpaper.id, "reason": "本地文件不存在"})
            continue

        records = parse_upload_records(wallpaper.upload_records)
        record_key = build_upload_record_key(body.profile_key, upload_format)
        existing_self = get_upload_record(records, body.profile_key, upload_format) or {}
        if existing_self.get("url"):
            skipped_items.append({"id": wallpaper.id, "reason": f"该 Profile 的 {format_label} 已上传"})
            continue

        reusable_record = find_reusable_upload_record(
            db,
            profile_key=body.profile_key,
            sha256=wallpaper.sha256,
            md5=wallpaper.md5,
            exclude_wallpaper_id=wallpaper.id,
            format_key=upload_format,
        )
        if reusable_record:
            records[record_key] = reusable_record
            wallpaper.upload_records = dump_upload_records(records)
            if not wallpaper.imgbed_url:
                wallpaper.imgbed_url = reusable_record.get("url")
            skipped_items.append({"id": wallpaper.id, "reason": f"发现同哈希的 {format_label} 上传记录，已复用现有链接"})
            continue

        upload_path, format_override, reason = _resolve_upload_asset(wallpaper, upload_format)
        if not upload_path or not format_override:
            skipped_items.append({"id": wallpaper.id, "reason": reason or "未找到可上传文件"})
            continue

        url = await uploader.upload(
            upload_path,
            width=wallpaper.width,
            height=wallpaper.height,
            wallpaper_type=wallpaper.wallpaper_type or "static",
            category=wallpaper.category or "",
            is_original=bool(wallpaper.is_original),
            format_override=format_override,
        )
        if not url:
            failed_items.append({"id": wallpaper.id, "reason": f"{format_label} 上传失败"})
            continue

        records[record_key] = build_upload_record(
            profile_key=body.profile_key,
            profile_name=profile.get("name", body.profile_key),
            channel=profile.get("channel", ""),
            url=url,
            format_key=upload_format,
        )
        wallpaper.upload_records = dump_upload_records(records)
        if not wallpaper.imgbed_url:
            wallpaper.imgbed_url = url
        success_items.append({
            "id": wallpaper.id,
            "url": url,
            "format_key": upload_format,
            "format_label": format_label,
        })

    db.commit()

    return {
        "success": True,
        "profile_key": body.profile_key,
        "profile_name": profile.get("name"),
        "upload_format": upload_format,
        "upload_format_label": format_label,
        "total": len(wallpapers),
        "success_count": len(success_items),
        "failed_count": len(failed_items),
        "skipped_count": len(skipped_items),
        "items": success_items,
        "failed_items": failed_items,
        "skipped_items": skipped_items,
    }


@router.delete("/batch")
async def batch_delete_wallpapers(body: BatchDeleteRequest, db: Session = Depends(get_db)):
    if body.scope == "selected":
        if not body.wallpaper_ids:
            raise HTTPException(400, "wallpaper_ids 不能为空")
        wallpapers = db.query(Wallpaper).filter(Wallpaper.id.in_(body.wallpaper_ids)).all()
    elif body.scope == "category":
        if not body.category:
            raise HTTPException(400, "category 不能为空")
        wallpapers = db.query(Wallpaper).filter(Wallpaper.category.contains(body.category)).all()
    elif body.scope == "all":
        wallpapers = db.query(Wallpaper).all()
    else:
        raise HTTPException(400, f"无效的 scope: {body.scope!r}")

    deleted_count = 0
    file_failed = 0
    for w in wallpapers:
        if body.delete_file:
            file_failed += _delete_wallpaper_files(w)
        db.delete(w)
        deleted_count += 1
    db.commit()

    orphan_cleaned = 0
    if body.scope == "all" and body.delete_file:
        orphan_cleaned, orphan_failed = _wipe_download_root()
        file_failed += orphan_failed

    return {
        "success": True,
        "deleted_count": deleted_count,
        "file_failed": file_failed,
        "orphan_cleaned": orphan_cleaned,
    }


@router.delete("/{wallpaper_id}")
async def delete_wallpaper(wallpaper_id: int, delete_file: bool = True, db: Session = Depends(get_db)):
    w = db.query(Wallpaper).filter(Wallpaper.id == wallpaper_id).first()
    if not w:
        raise HTTPException(404)
    if delete_file:
        _delete_wallpaper_files(w)
    db.delete(w)
    db.commit()
    return {"success": True}


@router.post("/scan-duplicates")
async def scan_duplicates(db: Session = Depends(get_db)):
    dedup = DedupManager(db)
    groups = dedup.scan_duplicates()
    return {
        "duplicate_groups": len(groups),
        "total_duplicates": sum(len(g["duplicates"]) for g in groups),
        "groups": [
            {
                "original_id": g["original"].resource_id,
                "original_path": g["original"].local_path,
                "duplicates": [{"id": d.resource_id, "path": d.local_path} for d in g["duplicates"]],
            }
            for g in groups
        ],
    }


@router.post("/clean-duplicates")
async def clean_duplicates(dry_run: bool = False, db: Session = Depends(get_db)):
    dedup = DedupManager(db)
    count = dedup.clean_duplicates(dry_run=dry_run)
    return {"cleaned": count, "dry_run": dry_run}


# ── 批量格式转换 ─────────────────────────────────────────

# 转换预设（覆盖 media_convert 配置中对应字段）
_CONVERT_PRESETS: dict[str, dict] = {
    "original": {"fps": 0, "max_width": 0, "max_frames": 0, "quality": 100},
    "standard": {"fps": 30, "max_width": 1280, "max_frames": 120, "quality": 80},
    "lite":     {"fps": 8,  "max_width": 854,  "max_frames": 30,  "quality": 65},
}


class BatchConvertRequest(BaseModel):
    scope: str = "selected"                # "selected" | "all" | "dynamic" | "static"
    wallpaper_ids: list[int] = Field(default_factory=list)
    # 使用全局 media_convert 配置；以下字段可覆盖
    output_format: Optional[str] = None    # 覆盖输出格式
    delete_original: Optional[bool] = None # 覆盖是否删除原文件
    preset: Optional[str] = None           # "original" | "standard" | "lite"（覆盖 fps/max_width/max_frames/quality）


@router.post("/convert/batch")
async def batch_convert_wallpapers(body: BatchConvertRequest, db: Session = Depends(get_db)):
    """
    批量格式转换：立即入队，返回 {batch_id, queued_count, skipped_count}。
    实际转换由后台 ConvertQueue worker 异步执行，可通过 GET /convert/queue 查询进度。
    """
    media_cfg = load_config().get("media_convert", {})

    # 构建壁纸列表
    if body.scope == "selected":
        if not body.wallpaper_ids:
            raise HTTPException(400, "请选择要转换的壁纸")
        wallpapers = db.query(Wallpaper).filter(
            Wallpaper.id.in_(body.wallpaper_ids), Wallpaper.status == "done"
        ).all()
    elif body.scope == "dynamic":
        wallpapers = db.query(Wallpaper).filter(
            Wallpaper.status == "done", Wallpaper.wallpaper_type == "dynamic"
        ).all()
    elif body.scope == "static":
        wallpapers = db.query(Wallpaper).filter(
            Wallpaper.status == "done", Wallpaper.wallpaper_type == "static"
        ).all()
    elif body.scope == "all":
        wallpapers = db.query(Wallpaper).filter(Wallpaper.status == "done").all()
    else:
        raise HTTPException(400, f"无效的 scope: {body.scope!r}")

    # 过滤无效条目（无路径 / 文件不存在），剩余全部入队
    valid_items: list[dict] = []
    skipped_items: list[dict] = []

    for w in wallpapers:
        if not w.local_path:
            skipped_items.append({"id": w.id, "reason": "缺少本地路径"})
            continue
        if (w.wallpaper_type or "static") == "dynamic":
            skipped_items.append({"id": w.id, "reason": "已关闭动态图转换，仅保留静态图转换"})
            continue
        abs_path = os.path.join(DOWNLOAD_ROOT, w.local_path)
        if not os.path.exists(abs_path):
            skipped_items.append({"id": w.id, "reason": "本地文件不存在"})
            continue
        converted_abs = os.path.join(DOWNLOAD_ROOT, w.converted_path) if w.converted_path else None
        if converted_abs and os.path.exists(converted_abs):
            skipped_items.append({"id": w.id, "reason": "已存在转换文件，请先删除后再重新转换"})
            continue
        valid_items.append({
            "id": w.id,
            "abs_path": abs_path,
            "wallpaper_type": w.wallpaper_type or "static",
        })

    if not valid_items:
        return {
            "success": True,
            "batch_id": None,
            "queued_count": 0,
            "skipped_count": len(skipped_items),
            "skipped_items": skipped_items,
            "message": skipped_items[0]["reason"] if len(skipped_items) == 1 else "没有可转换的壁纸",
        }

    cq = _get_convert_queue()
    job = cq.submit_batch(
        items=valid_items,
        media_cfg=media_cfg,
        delete_original=body.delete_original,
        output_format=body.output_format,
        timeout_override=None,
        preset=body.preset,
    )

    return {
        "success": True,
        "batch_id": job.batch_id,
        "queued_count": job.total,
        "skipped_count": len(skipped_items),
        "skipped_items": skipped_items,
        "message": f"已入队 {job.total} 个任务，后台转换中",
    }


@router.get("/convert/queue")
async def get_convert_queue_status():
    """返回全局转换队列状态及各批次进度。"""
    cq = _get_convert_queue()
    return cq.get_status()


@router.get("/convert/queue/{batch_id}")
async def get_convert_batch_status(batch_id: str):
    """返回指定批次的转换进度。"""
    cq = _get_convert_queue()
    job = cq.get_batch(batch_id)
    if job is None:
        raise HTTPException(404, f"批次 {batch_id} 不存在或已过期")
    result = job.to_dict()
    result["items"] = job.items
    result["failed_items"] = job.failed_items
    return result
