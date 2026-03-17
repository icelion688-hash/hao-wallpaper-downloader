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
    build_upload_record,
    dump_upload_records,
    find_reusable_upload_record,
    parse_upload_records,
)
from backend.models.database import get_db
from backend.models.wallpaper import Wallpaper

logger = logging.getLogger(__name__)
router = APIRouter()

# 全局转换信号量：防止批量转换任务并发过多占满 CPU/内存
# 实际上限从 config media_convert.max_concurrent 读取，首次请求时懒初始化
_convert_sem: Optional[asyncio.Semaphore] = None
_convert_sem_size: int = 0


def _get_convert_sem() -> asyncio.Semaphore:
    global _convert_sem, _convert_sem_size
    from backend.config import load_config as _lc
    size = int(_lc().get("media_convert", {}).get("max_concurrent", 1))
    if _convert_sem is None or _convert_sem_size != size:
        _convert_sem = asyncio.Semaphore(size)
        _convert_sem_size = size
    return _convert_sem


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
        "converted_url": (
            f"/downloads/{w.converted_path.replace(chr(92), '/')}"
            if w.converted_path else None
        ),
    }


class BatchUploadRequest(BaseModel):
    profile_key: str
    wallpaper_ids: list[int] = Field(default_factory=list)
    upload_scope: str = "selected"
    category: Optional[str] = None
    wallpaper_type: Optional[str] = None
    search: Optional[str] = None
    only_not_uploaded: bool = True


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
        existing_self = records.get(body.profile_key, {})
        if existing_self.get("url"):
            skipped_items.append({"id": wallpaper.id, "reason": "该配置已上传"})
            continue

        reusable_record = find_reusable_upload_record(
            db,
            profile_key=body.profile_key,
            sha256=wallpaper.sha256,
            md5=wallpaper.md5,
            exclude_wallpaper_id=wallpaper.id,
        )
        if reusable_record:
            records[body.profile_key] = reusable_record
            wallpaper.upload_records = dump_upload_records(records)
            if not wallpaper.imgbed_url:
                wallpaper.imgbed_url = reusable_record.get("url")
            skipped_items.append({"id": wallpaper.id, "reason": "发现同哈希图片，已复用已有上传链接"})
            continue

        url = await uploader.upload(
            abs_path,
            width=wallpaper.width,
            height=wallpaper.height,
            wallpaper_type=wallpaper.wallpaper_type or "static",
            category=wallpaper.category or "",
            is_original=bool(wallpaper.is_original),
        )
        if not url:
            failed_items.append({"id": wallpaper.id, "reason": "上传失败"})
            continue

        records[body.profile_key] = build_upload_record(
            profile_key=body.profile_key,
            profile_name=profile.get("name", body.profile_key),
            channel=profile.get("channel", ""),
            url=url,
        )
        wallpaper.upload_records = dump_upload_records(records)
        if not wallpaper.imgbed_url:
            wallpaper.imgbed_url = url
        success_items.append({"id": wallpaper.id, "url": url})

    db.commit()

    return {
        "success": True,
        "profile_key": body.profile_key,
        "profile_name": profile.get("name"),
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
        if body.delete_file and w.local_path:
            abs_path = os.path.join(DOWNLOAD_ROOT, w.local_path)
            try:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            except OSError as exc:
                logger.warning("[Gallery] 删除文件失败: %s — %s", abs_path, exc)
                file_failed += 1
        db.delete(w)
        deleted_count += 1
    db.commit()
    return {"success": True, "deleted_count": deleted_count, "file_failed": file_failed}


@router.delete("/{wallpaper_id}")
async def delete_wallpaper(wallpaper_id: int, delete_file: bool = True, db: Session = Depends(get_db)):
    w = db.query(Wallpaper).filter(Wallpaper.id == wallpaper_id).first()
    if not w:
        raise HTTPException(404)
    if delete_file and w.local_path:
        abs_path = os.path.join(DOWNLOAD_ROOT, w.local_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
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

class BatchConvertRequest(BaseModel):
    scope: str = "selected"                # "selected" | "all" | "dynamic" | "static"
    wallpaper_ids: list[int] = Field(default_factory=list)
    # 使用全局 media_convert 配置；以下字段可覆盖
    output_format: Optional[str] = None    # 覆盖输出格式
    delete_original: Optional[bool] = None # 覆盖是否删除原文件


def _do_convert_wallpaper(
    wallpaper_id: int,
    abs_path: str,
    wallpaper_type: str,
    media_cfg: dict,
    delete_original_override: Optional[bool],
    output_format_override: Optional[str],
    timeout_seconds_override: Optional[int] = None,
) -> dict:
    """
    同步转换单张壁纸（在线程池中执行）。
    返回 {"id": ..., "status": "ok"|"skip"|"fail", "converted_path": ...}
    """
    from backend.core.media_converter import MediaConverter, VideoConvertConfig, ImageConvertConfig

    is_video = wallpaper_type == "dynamic"
    cfg_key = "video" if is_video else "image"
    cfg_dict = dict(media_cfg.get(cfg_key, {}))
    cfg_dict["enabled"] = True  # 手动触发时强制 enabled
    if output_format_override is not None:
        cfg_dict["output_format"] = output_format_override
    if delete_original_override is not None:
        cfg_dict["delete_original"] = delete_original_override
    if timeout_seconds_override is not None:
        cfg_dict["timeout_seconds"] = timeout_seconds_override

    if is_video:
        mc = MediaConverter(video_config=VideoConvertConfig.from_dict(cfg_dict))
        converted_abs = mc.convert_video(abs_path)
    else:
        mc = MediaConverter(image_config=ImageConvertConfig.from_dict(cfg_dict))
        converted_abs = mc.convert_image(abs_path)

    if not converted_abs:
        return {"id": wallpaper_id, "status": "fail", "converted_path": None}

    converted_rel = os.path.relpath(converted_abs, DOWNLOAD_ROOT).replace("\\", "/")
    deleted_original = False
    if cfg_dict.get("delete_original") and os.path.abspath(abs_path) != os.path.abspath(converted_abs):
        try:
            os.remove(abs_path)
            deleted_original = True
        except OSError:
            pass

    return {
        "id": wallpaper_id,
        "status": "ok",
        "converted_path": converted_rel,
        "deleted_original": deleted_original,
    }


@router.post("/convert/batch")
async def batch_convert_wallpapers(body: BatchConvertRequest, db: Session = Depends(get_db)):
    """批量格式转换（在线程池中执行，不阻塞事件循环）"""
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

    loop = asyncio.get_event_loop()
    success_items, failed_items, skipped_items = [], [], []
    sem = _get_convert_sem()

    for w in wallpapers:
        if not w.local_path:
            skipped_items.append({"id": w.id, "reason": "缺少本地路径"})
            continue
        abs_path = os.path.join(DOWNLOAD_ROOT, w.local_path)
        if not os.path.exists(abs_path):
            skipped_items.append({"id": w.id, "reason": "本地文件不存在"})
            continue

        async with sem:  # 限制并发转换数，防止 CPU/内存过载
            result = await loop.run_in_executor(
                None,
                _do_convert_wallpaper,
                w.id, abs_path, w.wallpaper_type or "static",
                media_cfg,
                body.delete_original,
                body.output_format,
            )

        if result["status"] == "ok":
            w.converted_path = result["converted_path"]
            if result.get("deleted_original"):
                w.local_path = result["converted_path"]
            success_items.append(result)
        elif result["status"] == "skip":
            skipped_items.append({"id": w.id, "reason": "跳过"})
        else:
            failed_items.append({"id": w.id, "reason": "转换失败"})

    db.commit()

    return {
        "success": True,
        "total": len(wallpapers),
        "success_count": len(success_items),
        "failed_count": len(failed_items),
        "skipped_count": len(skipped_items),
        "items": success_items,
        "failed_items": failed_items,
    }
