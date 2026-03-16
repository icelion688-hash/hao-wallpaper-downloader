"""
schedule.py — 定时任务配置 API

端点：
  GET  /api/schedule   获取当前定时配置
  POST /api/schedule   保存定时配置
"""

import json
import logging
import os

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

# 配置文件存储路径
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEDULE_FILE = os.path.join(_BASE, "data", "schedule.json")

_DEFAULT: dict = {
    "enabled": False,
    "time": "09:00",
    "task_config": {
        "wallpaper_type": "all",
        "sort_by": "yesterday_hot",
        "categories": [],
        "max_count": 100,
        "concurrency": 3,
        "min_width": None,
        "min_height": None,
        "min_hot_score": 0,
        "color_themes": [],
        "tag_blacklist": [],
        "vip_only": False,
        "use_proxy": True,
    },
}


def load_schedule() -> dict:
    """从文件加载定时配置，文件不存在时返回默认值"""
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("[Schedule] 读取配置失败，使用默认值: %s", e)
    return dict(_DEFAULT)


def save_schedule(data: dict) -> None:
    """持久化定时配置到文件"""
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("")
async def get_schedule():
    """获取当前定时任务配置"""
    return load_schedule()


@router.post("")
async def set_schedule(body: dict):
    """保存定时任务配置"""
    save_schedule(body)
    logger.info("[Schedule] 配置已更新: enabled=%s time=%s",
                body.get("enabled"), body.get("time"))
    return {"success": True}
