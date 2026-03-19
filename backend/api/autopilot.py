"""
api/autopilot.py — AutoPilot 全自动调度 API

端点：
  GET  /api/autopilot/status   当前状态、配置、今日统计、日志
  POST /api/autopilot/start    启动 AutoPilot（含配置）
  POST /api/autopilot/stop     停止 AutoPilot
  PUT  /api/autopilot/config   更新配置（运行中也可调用，下次会话生效）
"""

from typing import List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class AutoPilotConfigRequest(BaseModel):
    # ── 时区与活跃时段 ──────────────────────────────────────────────────────
    timezone: str = "Asia/Shanghai"
    active_start: int = Field(default=8,  ge=0, le=23)
    active_end:   int = Field(default=23, ge=0, le=23)

    # ── 活跃时段下载模式 ────────────────────────────────────────────────────
    active_session_min: int = Field(default=5,    ge=1, le=200)
    active_session_max: int = Field(default=20,   ge=1, le=200)
    active_interval_min: int = Field(default=1800, ge=60)
    active_interval_max: int = Field(default=7200, ge=60)

    # ── 非活跃时段下载模式 ──────────────────────────────────────────────────
    inactive_enabled: bool = False
    inactive_session_min: int = Field(default=2,    ge=1, le=200)
    inactive_session_max: int = Field(default=8,    ge=1, le=200)
    inactive_interval_min: int = Field(default=7200,  ge=60)
    inactive_interval_max: int = Field(default=14400, ge=60)

    # ── 通用下载参数 ────────────────────────────────────────────────────────
    use_imgbed_upload: bool = False
    wallpaper_type: str = "static"
    sort_by: str = "yesterday_hot"
    categories: List[str] = []
    color_themes: List[str] = []
    vip_only: bool = False
    min_hot_score: int = 0
    tag_blacklist: List[str] = []
    min_width: Optional[int] = None
    min_height: Optional[int] = None
    screen_orientation: str = "all"


@router.get("/status")
async def get_status(request: Request):
    """返回当前运行状态、配置、今日统计和最近日志"""
    engine = request.app.state.autopilot
    return engine.get_status()


@router.post("/start")
async def start(request: Request, body: AutoPilotConfigRequest):
    """启动 AutoPilot，同时保存配置"""
    engine = request.app.state.autopilot
    if engine._status == "running":
        return {"success": False, "message": "AutoPilot 已在运行中", "config": engine.get_status()["config"]}
    ok = await engine.start(body.model_dump(), request.app.state)
    return {
        "success": ok,
        "message": "AutoPilot 已启动" if ok else "启动失败",
        "config": engine.get_status()["config"],
    }


@router.post("/stop")
async def stop(request: Request):
    """停止 AutoPilot"""
    engine = request.app.state.autopilot
    await engine.stop()
    return {"success": True, "message": "AutoPilot 已停止"}


@router.put("/config")
async def update_config(request: Request, body: AutoPilotConfigRequest):
    """更新配置（不影响运行状态，下次会话时生效）"""
    engine = request.app.state.autopilot
    config = engine.update_config(body.model_dump())
    return {"success": True, "message": "配置已更新", "config": config}
