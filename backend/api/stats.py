"""
api/stats.py — 系统监控统计 API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models.database import get_db
from backend.models.wallpaper import Wallpaper
from backend.models.task import Task
from backend.models.account import Account

router = APIRouter()


@router.get("/overview")
async def get_overview(db: Session = Depends(get_db)):
    """系统总览统计"""
    total_wallpapers = db.query(func.count(Wallpaper.id)).filter(Wallpaper.status == "done").scalar()
    total_size = db.query(func.sum(Wallpaper.file_size)).filter(Wallpaper.status == "done").scalar() or 0
    total_accounts = db.query(func.count(Account.id)).scalar()
    active_accounts = db.query(func.count(Account.id)).filter(Account.is_active == True).scalar()  # noqa
    total_tasks = db.query(func.count(Task.id)).scalar()
    running_tasks = db.query(func.count(Task.id)).filter(Task.status == "running").scalar()

    return {
        "total_wallpapers": total_wallpapers,
        "total_size_bytes": total_size,
        "total_size_gb": round(total_size / (1024 ** 3), 2),
        "total_accounts": total_accounts,
        "active_accounts": active_accounts,
        "total_tasks": total_tasks,
        "running_tasks": running_tasks,
    }


@router.get("/by-category")
async def stats_by_category(db: Session = Depends(get_db)):
    """按分类统计下载数量"""
    rows = (
        db.query(Wallpaper.category, func.count(Wallpaper.id))
        .filter(Wallpaper.status == "done")
        .group_by(Wallpaper.category)
        .order_by(func.count(Wallpaper.id).desc())
        .all()
    )
    return {"categories": [{"category": r[0] or "未分类", "count": r[1]} for r in rows]}


@router.get("/by-date")
async def stats_by_date(days: int = 30, db: Session = Depends(get_db)):
    """最近 N 天每日下载数量"""
    from datetime import datetime, timedelta
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
    return {"daily": [{"date": str(r.date), "count": r.count} for r in rows]}
