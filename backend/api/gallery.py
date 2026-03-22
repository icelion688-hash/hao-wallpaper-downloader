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
    build_remote_tags,
    build_upload_record,
    build_upload_record_key,
    build_remote_file_url,
    dump_upload_records,
    find_reusable_upload_record,
    get_upload_record,
    normalize_upload_format,
    parse_remote_file_id_from_url,
    parse_upload_records,
    sync_remote_record_metadata,
    upsert_upload_registry_record,
)
from backend.models.database import get_db
from backend.models.upload_registry import UploadRegistry
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


def _get_wallpaper_orientation(wallpaper: Wallpaper) -> str:
    width = wallpaper.width or 0
    height = wallpaper.height or 0
    if width <= 0 or height <= 0:
        return "unknown"
    if width == height:
        return "方图"
    return "竖图" if height > width else "横图"


def _split_remote_tags(value: Optional[str]) -> list[str]:
    if not value:
        return []
    normalized = str(value).replace("，", ",").replace("|", ",").replace("\n", ",")
    parts = [item.strip() for item in normalized.split(",")]
    return [item for item in parts if item]


def _unique_remote_tags(items: list[str]) -> list[str]:
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


def _build_remote_tags(
    *,
    wallpaper_type: str,
    category: str,
    color_theme: str,
    tags: Optional[str],
    orientation: str,
) -> list[str]:
    type_tag = "动态图" if wallpaper_type == "dynamic" else "静态图"
    return _unique_remote_tags(
        [
            type_tag,
            orientation,
            category,
            color_theme,
            *_split_remote_tags(tags),
        ]
    )


def _replace_upload_references(
    db: Session,
    *,
    old_url: str,
    new_url: str,
    remote_path: str,
    remote_tags: list[str],
) -> int:
    affected = 0
    if not old_url or not new_url:
        return affected

    wallpapers = (
        db.query(Wallpaper)
        .filter(
            or_(
                Wallpaper.imgbed_url == old_url,
                Wallpaper.upload_records.contains(old_url),
            )
        )
        .all()
    )

    for wallpaper in wallpapers:
        changed = False
        records = parse_upload_records(wallpaper.upload_records)
        for record in records.values():
            if not isinstance(record, dict) or record.get("url") != old_url:
                continue
            record["url"] = new_url
            record["remote_path"] = remote_path
            record["remote_tags"] = remote_tags
            changed = True
        if wallpaper.imgbed_url == old_url:
            wallpaper.imgbed_url = new_url
            changed = True
        if changed:
            wallpaper.upload_records = dump_upload_records(records)
            affected += 1

    (
        db.query(UploadRegistry)
        .filter(UploadRegistry.url == old_url)
        .update({UploadRegistry.url: new_url}, synchronize_session=False)
    )
    return affected


class BatchUploadRequest(BaseModel):
    profile_key: str
    upload_format: str = "profile"
    wallpaper_ids: list[int] = Field(default_factory=list)
    upload_scope: str = "selected"
    category: Optional[str] = None
    wallpaper_type: Optional[str] = None
    color_theme: Optional[str] = None
    screen_orientation: Optional[str] = None
    search: Optional[str] = None
    only_not_uploaded: bool = True


class ReclassifyUploadRequest(BaseModel):
    record_keys: list[str] = Field(default_factory=list)
    category: Optional[str] = None
    wallpaper_type: Optional[str] = None
    color_theme: Optional[str] = None
    tags: Optional[str] = None
    sync_local_metadata: bool = True


class BatchReclassifyUploadRequest(ReclassifyUploadRequest):
    wallpaper_ids: list[int] = Field(default_factory=list)


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
            color_theme=body.color_theme,
            screen_orientation=body.screen_orientation,
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
            resource_id=wallpaper.resource_id,
            exclude_wallpaper_id=wallpaper.id,
            format_key=upload_format,
        )
        if reusable_record:
            reusable_record = dict(reusable_record)
            remote_meta = await sync_remote_record_metadata(
                uploader,
                url=reusable_record["url"],
                width=wallpaper.width,
                height=wallpaper.height,
                wallpaper_type=wallpaper.wallpaper_type or "static",
                category=wallpaper.category or "",
                color_theme=wallpaper.color_theme or "",
                tags=wallpaper.tags or "",
            )
            if remote_meta["remote_path"]:
                reusable_record["remote_path"] = remote_meta["remote_path"]
            if remote_meta["remote_tags"]:
                reusable_record["remote_tags"] = remote_meta["remote_tags"]
            records[record_key] = reusable_record
            wallpaper.upload_records = dump_upload_records(records)
            if not wallpaper.imgbed_url:
                wallpaper.imgbed_url = reusable_record.get("url")
            upsert_upload_registry_record(
                db,
                profile_key=body.profile_key,
                format_key=upload_format,
                url=reusable_record["url"],
                resource_id=wallpaper.resource_id,
                sha256=wallpaper.sha256,
                md5=wallpaper.md5,
                profile_name=reusable_record.get("profile_name") or profile.get("name", body.profile_key),
                channel=reusable_record.get("channel") or profile.get("channel", ""),
                uploaded_at=reusable_record.get("uploaded_at"),
                source_server=reusable_record.get("source_server"),
            )
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
            type_id=wallpaper.type_id or "",
            color_theme=wallpaper.color_theme or "",
            color_id=wallpaper.color_id or "",
            tags=wallpaper.tags or "",
            resource_id=wallpaper.resource_id or "",
            is_original=bool(wallpaper.is_original),
            format_override=format_override,
        )
        if not url:
            failed_items.append({"id": wallpaper.id, "reason": f"{format_label} 上传失败"})
            continue

        remote_meta = await sync_remote_record_metadata(
            uploader,
            url=url,
            width=wallpaper.width,
            height=wallpaper.height,
            wallpaper_type=wallpaper.wallpaper_type or "static",
            category=wallpaper.category or "",
            color_theme=wallpaper.color_theme or "",
            tags=wallpaper.tags or "",
        )

        record = build_upload_record(
            profile_key=body.profile_key,
            profile_name=profile.get("name", body.profile_key),
            channel=profile.get("channel", ""),
            url=url,
            format_key=upload_format,
            remote_path=remote_meta["remote_path"],
            remote_tags=remote_meta["remote_tags"],
        )
        records[record_key] = record
        wallpaper.upload_records = dump_upload_records(records)
        if not wallpaper.imgbed_url:
            wallpaper.imgbed_url = url
        upsert_upload_registry_record(
            db,
            profile_key=body.profile_key,
            format_key=upload_format,
            url=url,
            resource_id=wallpaper.resource_id,
            sha256=wallpaper.sha256,
            md5=wallpaper.md5,
            profile_name=profile.get("name", body.profile_key),
            channel=profile.get("channel", ""),
            uploaded_at=record.get("uploaded_at"),
        )
        success_items.append({
            "id": wallpaper.id,
            "url": url,
            "format_key": upload_format,
            "format_label": format_label,
            "remote_path": remote_meta["remote_path"],
            "remote_tags": remote_meta["remote_tags"],
            "tag_sync_success": remote_meta["tag_sync_success"],
            "tag_sync_error": remote_meta["tag_sync_error"],
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


@router.post("/{wallpaper_id}/reclassify-upload")
async def reclassify_wallpaper_upload(
    wallpaper_id: int,
    body: ReclassifyUploadRequest,
    db: Session = Depends(get_db),
):
    wallpaper = db.query(Wallpaper).filter(Wallpaper.id == wallpaper_id).first()
    if not wallpaper:
        raise HTTPException(404, "壁纸不存在")

    records = parse_upload_records(wallpaper.upload_records)
    if not records:
        raise HTTPException(400, "当前壁纸没有可调整的上传记录")

    target_keys = set(body.record_keys or records.keys())
    target_entries: list[tuple[str, dict]] = []
    for record_key, record in records.items():
        if record_key not in target_keys:
            continue
        if not isinstance(record, dict) or not record.get("url"):
            continue
        target_entries.append((record_key, record))

    if not target_entries:
        raise HTTPException(400, "未找到可调整的上传记录")

    next_category = str(body.category if body.category is not None else (wallpaper.category or "")).strip()
    next_wallpaper_type = str(body.wallpaper_type if body.wallpaper_type is not None else (wallpaper.wallpaper_type or "static")).strip() or "static"
    next_color_theme = str(body.color_theme if body.color_theme is not None else (wallpaper.color_theme or "")).strip()
    next_tags = str(body.tags if body.tags is not None else (wallpaper.tags or "")).strip()
    remote_tags = build_remote_tags(
        width=wallpaper.width,
        height=wallpaper.height,
        wallpaper_type=next_wallpaper_type,
        category=next_category,
        color_theme=next_color_theme,
        tags=next_tags,
    )

    success_items = []
    failed_items = []

    for record_key, record in target_entries:
        profile_key = str(record.get("profile_key") or record_key.split("::", 1)[0] or "").strip()
        if not profile_key:
            failed_items.append({"record_key": record_key, "reason": "上传记录缺少 profile_key"})
            continue

        uploader = build_uploader_by_key(profile_key)
        if not uploader:
            failed_items.append({"record_key": record_key, "reason": f"上传配置不可用: {profile_key}"})
            continue

        old_url = str(record.get("url") or "").strip()
        old_remote_path = parse_remote_file_id_from_url(old_url)
        if not old_remote_path:
            await uploader.aclose()
            failed_items.append({"record_key": record_key, "reason": "无法从上传链接解析远端路径"})
            continue

        try:
            target_folder = uploader._determine_folder(
                width=wallpaper.width,
                height=wallpaper.height,
                wallpaper_type=next_wallpaper_type,
                category=next_category,
                type_id=wallpaper.type_id or "",
                color_theme=next_color_theme,
                color_id=wallpaper.color_id or "",
                tags=next_tags,
                is_original=bool(wallpaper.is_original),
                resource_id=wallpaper.resource_id or "",
            )
            old_folder = old_remote_path.rsplit("/", 1)[0] if "/" in old_remote_path else ""
            new_remote_path = old_remote_path

            if target_folder.strip("/") != old_folder.strip("/"):
                move_result = await uploader.move_remote_path(old_remote_path, dist=target_folder)
                if isinstance(move_result, dict) and move_result.get("newFileId"):
                    new_remote_path = str(move_result["newFileId"]).strip("/")
                else:
                    new_remote_path = f"{target_folder.strip('/')}/{old_remote_path.split('/')[-1]}".strip("/")

            await uploader.set_remote_tags(new_remote_path, remote_tags, action="set")

            new_url = build_remote_file_url(uploader.base_url, new_remote_path)
            _replace_upload_references(
                db,
                old_url=old_url,
                new_url=new_url,
                remote_path=new_remote_path,
                remote_tags=remote_tags,
            )

            current_record = records.get(record_key)
            if isinstance(current_record, dict):
                current_record["url"] = new_url
                current_record["remote_path"] = new_remote_path
                current_record["remote_tags"] = remote_tags

            success_items.append(
                {
                    "record_key": record_key,
                    "profile_key": profile_key,
                    "old_path": old_remote_path,
                    "new_path": new_remote_path,
                    "url": new_url,
                    "tags": remote_tags,
                }
            )
        except Exception as exc:  # noqa: BLE001
            failed_items.append({"record_key": record_key, "reason": str(exc)})
        finally:
            await uploader.aclose()

    if body.sync_local_metadata:
        wallpaper.category = next_category or None
        wallpaper.wallpaper_type = next_wallpaper_type or "static"
        wallpaper.color_theme = next_color_theme or None
        wallpaper.tags = next_tags or None

    wallpaper.upload_records = dump_upload_records(records)
    if wallpaper.imgbed_url:
        for record in records.values():
            if isinstance(record, dict) and record.get("url"):
                wallpaper.imgbed_url = record["url"]
                break

    db.commit()
    db.refresh(wallpaper)

    return {
        "success": len(success_items) > 0,
        "wallpaper": _w_to_dict(wallpaper),
        "remote_tags": remote_tags,
        "success_count": len(success_items),
        "failed_count": len(failed_items),
        "items": success_items,
        "failed_items": failed_items,
    }


@router.post("/reclassify-upload/batch")
async def batch_reclassify_wallpaper_upload(
    body: BatchReclassifyUploadRequest,
    db: Session = Depends(get_db),
):
    wallpaper_ids = list(dict.fromkeys(body.wallpaper_ids))
    if not wallpaper_ids:
        raise HTTPException(400, "wallpaper_ids 不能为空")

    request = ReclassifyUploadRequest(**body.model_dump(exclude={"wallpaper_ids"}))
    success_items = []
    failed_items = []

    for wallpaper_id in wallpaper_ids:
        try:
            result = await reclassify_wallpaper_upload(wallpaper_id, request, db)
            success_items.append({
                "wallpaper_id": wallpaper_id,
                "wallpaper": result.get("wallpaper"),
                "success_count": result.get("success_count", 0),
                "failed_count": result.get("failed_count", 0),
                "remote_tags": result.get("remote_tags", []),
                "items": result.get("items", []),
                "failed_items": result.get("failed_items", []),
            })
        except HTTPException as exc:
            failed_items.append({
                "wallpaper_id": wallpaper_id,
                "reason": exc.detail,
            })
        except Exception as exc:  # noqa: BLE001
            failed_items.append({
                "wallpaper_id": wallpaper_id,
                "reason": str(exc),
            })

    return {
        "success": len(success_items) > 0,
        "total": len(wallpaper_ids),
        "success_count": len(success_items),
        "failed_count": len(failed_items),
        "items": success_items,
        "failed_items": failed_items,
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
