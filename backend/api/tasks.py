"""
api/tasks.py — 任务管理 API

端点：
  GET    /api/tasks           列出所有任务
  POST   /api/tasks           创建下载任务
  GET    /api/tasks/{id}      任务详情
  POST   /api/tasks/{id}/start   启动任务
  POST   /api/tasks/{id}/pause   暂停任务
  POST   /api/tasks/{id}/cancel  取消任务
  DELETE /api/tasks/{id}      删除任务记录
  GET    /api/tasks/{id}/logs SSE 实时日志流
"""

import asyncio
import json
import logging
import os
import random
import subprocess
from collections import deque
from datetime import datetime
from typing import Optional, AsyncIterator

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.models.database import get_db, SessionLocal
from backend.models.task import Task
from backend.models.wallpaper import Wallpaper
from backend.core.filters import FilterConfig, FilterEngine
from backend.core.account_pool import AccountPool
from backend.core.anti_detection import AntiDetection, HumanBehaviorController
from backend.core.captcha_solver import AltchaSolver
from backend.core.crawler import WallpaperCrawler
from backend.core.downloader import Downloader
from backend.core.dedup import DedupManager
from backend.core.imgbed_uploader import ImgbedUploader
from backend.core.upload_profiles import build_uploader_by_key
from backend.config import load_config
from backend.core.media_converter import MediaConverter
from backend.core.site_auth import probe_login_status
from backend.core.upload_record_helper import (
    build_upload_record,
    dump_upload_records,
    find_reusable_upload_record,
    parse_remote_file_id_from_url,
    sync_remote_record_metadata,
    upsert_upload_registry_record,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 运行中的任务 {task_id: asyncio.Task}
_running_tasks: dict[int, asyncio.Task] = {}
_STATIC_ORIENTATION_SCAN_LIMIT = 400


def _get_convert_queue():
    from backend.core.convert_queue import get_convert_queue
    return get_convert_queue()


def _probe_video_duration(path: str) -> Optional[float]:
    """
    提取视频时长（秒）。
    优先用 ffprobe（本地安装时最快）；未安装则回退到 imageio-ffmpeg（pip 包，已内置）。
    两者均不可用时静默返回 None，不影响下载流程。
    """
    # ── 1. ffprobe（已安装时优先）────────────────────────
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for stream in json.loads(result.stdout).get("streams", []):
                dur = stream.get("duration")
                if dur:
                    return round(float(dur), 2)
    except FileNotFoundError:
        pass  # ffprobe 未安装，走 imageio 回退
    except (subprocess.TimeoutExpired, Exception):
        pass

    # ── 2. imageio-ffmpeg 回退（无需系统 ffprobe）────────
    try:
        from backend.core.media_converter import MediaConverter
        dur = MediaConverter().get_video_duration(path)
        if dur:
            return dur
    except Exception:
        pass

    return None


def _parse_file_mb_to_bytes(file_mb_str: str) -> Optional[int]:
    """将 API 标注的大小字符串（如 '1.54 MB'、'863 KB'）解析为字节数"""
    if not file_mb_str:
        return None
    s = file_mb_str.strip().upper()
    try:
        if "MB" in s:
            return int(float(s.replace("MB", "").strip()) * 1024 * 1024)
        if "KB" in s:
            return int(float(s.replace("KB", "").strip()) * 1024)
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _get_wallpaper_orientation(item: dict) -> str:
    """根据宽高推断壁纸方向。"""
    width = item.get("width") or 0
    height = item.get("height") or 0
    if width <= 0 or height <= 0:
        return "unknown"
    return "landscape" if width >= height else "portrait"


def _should_diversify_static_orientations(cfg: FilterConfig) -> bool:
    """仅在静态图 + 全部方向时启用横竖图补齐。"""
    return cfg.wallpaper_type == "static" and cfg.screen_orientation == "all"


def _resolve_upload_profile_key(
    task_config: dict,
    wallpaper_type: str,
    *,
    fallback_profile_key: str = "",
) -> str:
    static_key = str(task_config.get("static_upload_profile") or "").strip()
    dynamic_key = str(task_config.get("dynamic_upload_profile") or "").strip()
    normalized_type = str(wallpaper_type or "static").strip().lower()
    if normalized_type == "dynamic":
        return dynamic_key or static_key or fallback_profile_key
    return static_key or dynamic_key or fallback_profile_key


def _resolve_source_scopes(cfg: FilterConfig) -> list[str]:
    """
    根据壁纸类型和方向选择需要扫描的站点资源源。

    站点当前使用同一列表接口，但：
      - 电脑横图主要来自 wpType=1,4
      - 手机竖图主要来自 wpType=2,6
      - 动态分别来自 wpType=3 / 5
    """
    if cfg.wallpaper_type == "static":
        if cfg.screen_orientation == "portrait":
            return ["mobile_static"]
        if cfg.screen_orientation == "landscape":
            return ["desktop_static"]
        return ["desktop_static", "mobile_static"]

    if cfg.wallpaper_type == "dynamic":
        if cfg.screen_orientation == "portrait":
            return ["mobile_dynamic"]
        if cfg.screen_orientation == "landscape":
            return ["desktop_dynamic"]
        return ["desktop_dynamic", "mobile_dynamic"]

    if cfg.screen_orientation == "portrait":
        return ["mobile_static", "mobile_dynamic"]
    if cfg.screen_orientation == "landscape":
        return ["desktop_static", "desktop_dynamic"]
    return ["desktop_static", "mobile_static", "desktop_dynamic", "mobile_dynamic"]


def _has_mixed_static_orientations(items: list[dict]) -> bool:
    """候选池中是否同时存在横图和竖图。"""
    seen = {
        _get_wallpaper_orientation(item)
        for item in items
        if item.get("wallpaper_type", "static") == "static"
    }
    return "landscape" in seen and "portrait" in seen


def _select_diversified_candidates(candidates: list[dict], limit: int) -> list[dict]:
    """
    在候选池中尽量混排横图和竖图。

    规则保持简单：
      1. 每个方向内部保持原始热门顺序；
      2. 优先补齐当前较少的一侧；
      3. 若某一侧缺失，则退回原始顺序截断。
    """
    if limit <= 0 or not candidates:
        return []

    portraits: deque[dict] = deque()
    landscapes: deque[dict] = deque()
    unknowns: deque[dict] = deque()

    for item in candidates:
        orientation = _get_wallpaper_orientation(item)
        if orientation == "portrait":
            portraits.append(item)
        elif orientation == "landscape":
            landscapes.append(item)
        else:
            unknowns.append(item)

    if not portraits or not landscapes:
        return candidates[:limit]

    selected: list[dict] = []
    portrait_count = 0
    landscape_count = 0
    first_preferred = _get_wallpaper_orientation(candidates[0])

    while len(selected) < limit:
        if not selected and first_preferred in {"portrait", "landscape"}:
            preferred = first_preferred
        else:
            preferred = "portrait" if portrait_count < landscape_count else "landscape"
        secondary = "landscape" if preferred == "portrait" else "portrait"

        picked = None
        picked_orientation = None
        if preferred == "portrait" and portraits:
            picked = portraits.popleft()
            picked_orientation = "portrait"
        elif preferred == "landscape" and landscapes:
            picked = landscapes.popleft()
            picked_orientation = "landscape"
        elif secondary == "portrait" and portraits:
            picked = portraits.popleft()
            picked_orientation = "portrait"
        elif secondary == "landscape" and landscapes:
            picked = landscapes.popleft()
            picked_orientation = "landscape"
        elif unknowns:
            picked = unknowns.popleft()
        else:
            break

        selected.append(picked)
        if picked_orientation == "portrait":
            portrait_count += 1
        elif picked_orientation == "landscape":
            landscape_count += 1

    return selected


def _format_prefilter_summary(
    label: str,
    batch_count: int,
    total_count: int,
    latest_resource_id: str = "",
    latest_reason: str = "",
) -> str:
    """格式化预筛阶段的批量日志，避免重复细粒度日志刷屏。"""
    parts = [f"{label}: 本轮 {batch_count} 张，累计 {total_count} 张"]
    if latest_resource_id:
        parts.append(f"最近资源 {latest_resource_id}")
    if latest_reason:
        parts.append(f"最近原因 {latest_reason}")
    return " | ".join(parts)


# ------------------------------------------------------------------ #
#  Pydantic 模型
# ------------------------------------------------------------------ #

class CreateTaskRequest(BaseModel):
    name: str = "新建任务"
    wallpaper_type: str = "all"
    screen_orientation: str = "all"
    categories: list[str] = []
    sort_by: str = "yesterday_hot"
    min_width: Optional[int] = None
    max_width: Optional[int] = None
    min_height: Optional[int] = None
    max_height: Optional[int] = None
    color_themes: list[str] = []
    min_hot_score: int = 0
    tag_blacklist: list[str] = []
    max_count: int = 100
    concurrency: int = 3
    vip_only: bool = False
    use_proxy: bool = True
    use_imgbed_upload: bool = False
    upload_with_tags: bool = True


class UpdateTaskNameRequest(BaseModel):
    name: str


def _task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "status": t.status,
        "total_count": t.total_count,
        "success_count": t.success_count,
        "failed_count": t.failed_count,
        "skip_count": t.skip_count,
        "progress": round(t.progress, 1),
        "config": t.config,
        "error_msg": t.error_msg,
        "started_at": t.started_at,
        "finished_at": t.finished_at,
        "created_at": t.created_at,
    }


# ------------------------------------------------------------------ #
#  路由
# ------------------------------------------------------------------ #

@router.get("")
async def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    return {"tasks": [_task_to_dict(t) for t in tasks]}


@router.post("")
async def create_task(body: CreateTaskRequest, db: Session = Depends(get_db)):
    """创建任务（不立即启动）"""
    cfg = FilterConfig(
        wallpaper_type=body.wallpaper_type,
        screen_orientation=body.screen_orientation,
        categories=body.categories,
        sort_by=body.sort_by,
        min_width=body.min_width,
        max_width=body.max_width,
        min_height=body.min_height,
        max_height=body.max_height,
        color_themes=body.color_themes,
        min_hot_score=body.min_hot_score,
        tag_blacklist=body.tag_blacklist,
        max_count=body.max_count,
        concurrency=body.concurrency,
        vip_only=body.vip_only,
        use_proxy=body.use_proxy,
    )
    task = Task(name=body.name, status="pending", total_count=body.max_count)
    task_config = cfg.to_dict()
    task_config["use_imgbed_upload"] = body.use_imgbed_upload
    task_config["upload_with_tags"] = body.upload_with_tags
    task.config = task_config
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(f"[Tasks] 创建任务 id={task.id} name={task.name!r}")
    return {"success": True, "task": _task_to_dict(task)}


@router.get("/{task_id}")
async def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return _task_to_dict(task)


@router.post("/{task_id}/start")
async def start_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """启动任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    if task.status == "running":
        raise HTTPException(400, "任务已在运行中")
    if task_id in _running_tasks and not _running_tasks[task_id].done():
        raise HTTPException(400, "任务已在运行中")

    task.status = "running"
    task.started_at = datetime.now()
    task.success_count = 0
    task.failed_count = 0
    task.skip_count = 0
    task.progress = 0.0
    db.commit()

    # 获取全局组件（从 app.state 或新建）
    anti = getattr(request.app.state, "anti", AntiDetection())
    captcha = getattr(request.app.state, "captcha", AltchaSolver())
    uploader = getattr(request.app.state, "imgbed", None)
    human_ctrl = getattr(request.app.state, "human_ctrl", None)

    async def run():
        await _execute_task(task_id, anti, captcha, uploader, human_ctrl)

    _running_tasks[task_id] = asyncio.create_task(run())
    return {"success": True, "message": f"任务 {task_id} 已启动"}


@router.post("/{task_id}/pause")
async def pause_task(task_id: int, db: Session = Depends(get_db)):
    """暂停任务"""
    if task_id in _running_tasks:
        _running_tasks[task_id].cancel()
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "paused"
        db.commit()
    return {"success": True}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: int, db: Session = Depends(get_db)):
    """取消任务"""
    if task_id in _running_tasks:
        _running_tasks[task_id].cancel()
        del _running_tasks[task_id]
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "cancelled"
        task.finished_at = datetime.now()
        db.commit()
    return {"success": True}


@router.patch("/{task_id}")
async def rename_task(task_id: int, body: UpdateTaskNameRequest, db: Session = Depends(get_db)):
    """重命名任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "任务名称不能为空")
    task.name = name
    db.commit()
    db.refresh(task)
    return {"success": True, "task": _task_to_dict(task)}


@router.delete("/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    """删除任务记录"""
    if task_id in _running_tasks:
        _running_tasks[task_id].cancel()
        del _running_tasks[task_id]
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404)
    db.delete(task)
    db.commit()
    return {"success": True}


@router.get("/{task_id}/logs")
async def stream_logs(task_id: int):
    """SSE 实时日志流"""
    async def event_generator() -> AsyncIterator[str]:
        last_pos = 0
        consecutive_empty = 0
        while True:
            db = SessionLocal()
            try:
                task = db.query(Task).filter(Task.id == task_id).first()
                if not task:
                    yield f"data: {json.dumps({'error': '任务不存在'})}\n\n"
                    break

                log = task.log_text or ""
                if len(log) > last_pos:
                    new_content = log[last_pos:]
                    last_pos = len(log)
                    consecutive_empty = 0
                    for line in new_content.split("\n"):
                        if line.strip():
                            yield f"data: {json.dumps({'log': line})}\n\n"

                if task.status in ("done", "failed", "cancelled"):
                    yield f"data: {json.dumps({'status': task.status, 'done': True})}\n\n"
                    break

                consecutive_empty += 1
            finally:
                db.close()

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ #
#  任务执行逻辑
# ------------------------------------------------------------------ #

async def _execute_task(
    task_id: int,
    anti: AntiDetection,
    captcha: AltchaSolver,
    uploader: Optional[ImgbedUploader] = None,
    human_ctrl: Optional[HumanBehaviorController] = None,
):
    """后台协程：执行下载任务"""
    db = SessionLocal()
    # 任务级唯一共享 client：altcha session 需同一 client 复用，finally 中关闭
    _shared_client = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(30))
    _shared_altcha_verified = False
    # 用列表以便嵌套闭包直接修改（无需 nonlocal）
    # 站点每次 altcha 验证仅允许 2 次 getCompleteUrl，满 2 次须重新验证
    _altcha_use_count = [0]
    _account_clients: dict[int, httpx.AsyncClient] = {}  # 保留兼容，finally 统一关闭

    # 任务级 Session Profile：整个任务使用同一 UA/sec-ch-ua/平台，保持浏览器指纹一致性
    _session_profile = anti.pick_session_profile()

    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        cfg = FilterConfig.from_dict(task.config)
        upload_enabled = task.config.get("use_imgbed_upload", True)
        upload_with_tags = task.config.get(
            "upload_with_tags",
            getattr(uploader, "sync_remote_tags", True) if uploader else True,
        )
        effective_uploader = uploader if upload_enabled else None
        default_profile_key = getattr(effective_uploader, "profile_key", "") if effective_uploader else ""
        created_uploaders: dict[str, ImgbedUploader] = {}
        resume_start_page = max(1, int(task.config.get("_resume_start_page", 1) or 1))

        def log(msg: str):
            task.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            db.commit()

        def update_runtime_config(**kwargs):
            runtime_cfg = task.config
            runtime_cfg.update(kwargs)
            task.config = runtime_cfg
            db.commit()

        # ── 活跃时段感知 ─────────────────────────────────────────────────────
        if human_ctrl and not human_ctrl.is_active_hour():
            log("提示: 当前处于非活跃时段（23:00-08:00），延迟将适当加长以模拟真实浏览节奏")

        # ── 人性化每日限额检查 ───────────────────────────────────────────────
        effective_max = cfg.max_count
        if human_ctrl:
            if human_ctrl.is_daily_limit_reached():
                log(
                    f"⚠️ 今日已达人性化下载上限 {human_ctrl.daily_limit} 张"
                    f"（今日已下 {human_ctrl.downloaded_today} 张），任务跳过"
                )
                task.status = "done"
                task.finished_at = datetime.now()
                db.commit()
                return
            remaining = human_ctrl.remaining_today
            effective_max = min(cfg.max_count, remaining)
            log(
                f"📊 今日上限 {human_ctrl.daily_limit} 张 | "
                f"已下 {human_ctrl.downloaded_today} 张 | "
                f"本次最多 {effective_max} 张"
            )
        task.total_count = effective_max
        db.commit()
        # ────────────────────────────────────────────────────────────────────

        pool = AccountPool(db=db, vip_only=cfg.vip_only)
        crawler = WallpaperCrawler(anti_detection=anti, captcha_solver=captcha)
        downloader = Downloader(anti_detection=anti, captcha_solver=captcha)
        dedup = DedupManager(db=db)
        filter_engine = FilterEngine(cfg)

        log(f"任务启动: {task.name}")
        if resume_start_page > 1:
            log(f"查询游标: 从第 {resume_start_page} 页继续扫描")
        logger.info("[Task] Session Profile UA: %s", _session_profile["ua"][:60])
        if upload_enabled:
            log("图床上传: 已启用")
            static_profile_key = _resolve_upload_profile_key(
                task.config,
                "static",
                fallback_profile_key=default_profile_key,
            )
            dynamic_profile_key = _resolve_upload_profile_key(
                task.config,
                "dynamic",
                fallback_profile_key=default_profile_key,
            )
            if static_profile_key == dynamic_profile_key:
                log(f"上传 Profile: {static_profile_key or '未指定'}")
            else:
                log(
                    f"上传 Profile: 静态图={static_profile_key or '未指定'} / "
                    f"动态图={dynamic_profile_key or '未指定'}"
                )
        else:
            log("图床上传: 已关闭，仅保存到本地")

        sem = asyncio.Semaphore(cfg.concurrency)
        # 动态视频单张 50-100 MB，并发下载占用大量带宽，独立限制最多 2 个并发
        sem_dynamic = asyncio.Semaphore(max(1, min(cfg.concurrency, 2)))

        # 全任务唯一共享 client：altcha session 是 IP 级的，一次验证所有账号共用
        # _shared_client / _shared_altcha_verified 已在函数顶部初始化
        _altcha_lock = asyncio.Lock()

        async def _ensure_altcha_ready(cookie: str) -> bool:
            """确保共享 client 已通过 altcha 验证。
            altcha challenge 有 IP 级频率限制，多账号轮询时不能每账号独立验证。
            返回 True=已验证可用 skip_altcha，False=验证失败只能用 previewFileImg。
            """
            nonlocal _shared_altcha_verified
            if _shared_altcha_verified:
                return True
            async with _altcha_lock:
                if _shared_altcha_verified:  # double-check after lock
                    return True
                verified = await captcha.verify_download(
                    _shared_client, cookie, ua=_session_profile["ua"]
                )
                if verified:
                    _shared_altcha_verified = True
                    _altcha_use_count[0] = 0
                    logger.info("[Task] altcha 验证成功")
                    # 验证成功后稍作等待：模拟浏览器处理 altcha 响应后才发起下载请求
                    # 避免 verify→getCompleteUrl 时序过于精确被 WAF 识别为自动化
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                else:
                    logger.warning("[Task] altcha 验证失败")
                return _shared_altcha_verified

        async def invalidate_altcha() -> None:
            """重置 altcha 会话，下次 _ensure_altcha_ready 将强制重新验证。
            用于：① 成功下载 2 次原图后主动轮换；② getCompleteUrl 返回 305 时兜底重试。
            """
            nonlocal _shared_altcha_verified
            async with _altcha_lock:
                _shared_altcha_verified = False
                _altcha_use_count[0] = 0
            logger.info("[Task] altcha session 已重置，下次将重新验证")

        def resolve_item_uploader(item: dict) -> Optional[ImgbedUploader]:
            if not upload_enabled:
                return None
            profile_key = _resolve_upload_profile_key(
                task.config,
                item.get("wallpaper_type", "static"),
                fallback_profile_key=default_profile_key,
            )
            if not profile_key:
                return effective_uploader
            if effective_uploader and effective_uploader.profile_key == profile_key:
                return effective_uploader
            cached = created_uploaders.get(profile_key)
            if cached:
                return cached
            built = build_uploader_by_key(profile_key)
            if built:
                created_uploaders[profile_key] = built
            return built

        async def process_one(item: dict):
            _is_dynamic = item.get("wallpaper_type") == "dynamic"
            _active_sem = sem_dynamic if _is_dynamic else sem
            async with _active_sem:
                resource_id = item.get("resource_id", "")
                if not resource_id:
                    return

                # ID 去重兜底：正常情况已在预筛阶段拦截，这里只防并发/竞态
                if dedup.is_resource_downloaded(resource_id):
                    task.skip_count += 1
                    task.update_progress()
                    db.commit()
                    log(f"跳过(已存在/兜底): {resource_id}")
                    return

                # 人性化每日上限：任务执行中途达到上限时停止继续下载
                if human_ctrl and human_ctrl.is_daily_limit_reached():
                    task.skip_count += 1
                    task.update_progress()
                    db.commit()
                    log(f"⚠️ 今日下载已达上限 {human_ctrl.daily_limit} 张，跳过: {resource_id}")
                    return

                # 获取账号
                account = await pool.acquire()
                if not account:
                    task.failed_count += 1
                    task.update_progress()
                    db.commit()
                    log(f"失败(无可用账号): {resource_id}")
                    return

                # 初始化在 try 外部，确保 except 块始终能访问到此变量
                _is_original_dl = False
                _queued_convert_msg = None
                _queued_convert_request = None

                try:
                    # 获取下载直链
                    # 视频已在 iter_wallpapers 中预填 download_url（直接用）
                    # 静态图 download_url 为空，走 fetch_detail 完成 altcha 验证 + getCompleteUrl
                    if item.get("download_url"):
                        detail = {
                            "resource_id":  resource_id,
                            "download_url": item["download_url"],
                            "title":        item.get("title", ""),
                            "width":        item.get("width"),
                            "height":       item.get("height"),
                            "is_original":  False,
                        }
                    else:
                        altcha_ok = await _ensure_altcha_ready(account.cookie)
                        detail = await crawler.fetch_detail(
                            _shared_client, account.cookie, resource_id,
                            file_id=item.get("file_id", ""),
                            wallpaper_type_id=1 if item.get("wallpaper_type") == "static" else 3,
                            skip_altcha=altcha_ok,
                            session_profile=_session_profile,
                        )

                    if not detail or not detail.get("download_url"):
                        task.failed_count += 1
                        task.update_progress()
                        db.commit()
                        log(f"失败(无下载地址): {resource_id}")
                        # getCompleteUrl 未成功，网站未计费，consume_quota=False
                        await pool.release(account, success=False, consume_quota=False)
                        return

                    # 动态视频：提前记录预估大小，帮助用户感知耗时
                    if item.get("wallpaper_type") == "dynamic":
                        _est_size = item.get("file_mb", "")
                        log(f"动态图开始下载: {resource_id}"
                            + (f" | API预估大小: {_est_size}" if _est_size else ""))

                    # 构造可读文件名：标签_宽x高.扩展名（如：动漫_二次元_1600x1199.png）
                    _tags = [t.strip() for t in item.get("tags", "").split(",") if t.strip()]
                    _w, _h = item.get("width") or 0, item.get("height") or 0
                    _dl_url = detail["download_url"]
                    _url_ext = os.path.splitext(_dl_url.split("?")[0])[1].lstrip(".")
                    if not _url_ext:
                        # getVideoReduce URL 路径无扩展名，按类型设默认值
                        _url_ext = "mp4" if item.get("wallpaper_type") == "dynamic" else "jpg"
                    # 判断是否为原图：getCompleteUrl 返回的 CDN 签名直链含 zfts.haowallpaper.com
                    _is_original_dl = bool(detail.get("is_original"))
                    # VIP 未拿到原图时，先重置 altcha 重试一次（静态图 + 动态图均适用）
                    # 站点每次 altcha 验证仅允许 2 次 getCompleteUrl（305/3004），重验可恢复
                    _wtype = item.get("wallpaper_type", "static")
                    _wtype_id = 3 if _wtype == "dynamic" else 1
                    if _wtype in ("static", "dynamic") and not _is_original_dl and account.account_type == "vip":
                        log(f"VIP 未获原图（可能 altcha session 耗尽），重置重试: {resource_id}")
                        await invalidate_altcha()
                        altcha_ok_retry = await _ensure_altcha_ready(account.cookie)
                        detail_retry = await crawler.fetch_detail(
                            _shared_client, account.cookie, resource_id,
                            file_id=item.get("file_id", ""),
                            wallpaper_type_id=_wtype_id,
                            skip_altcha=altcha_ok_retry,
                            session_profile=_session_profile,
                        )
                        if detail_retry and detail_retry.get("is_original"):
                            detail = detail_retry
                            _is_original_dl = True
                            _dl_url = detail["download_url"]
                            _url_ext = os.path.splitext(_dl_url.split("?")[0])[1].lstrip(".")
                            if not _url_ext:
                                _url_ext = "mp4" if _wtype == "dynamic" else "jpg"
                            log(f"altcha 重验后成功获原图: {resource_id}")

                    if item.get("wallpaper_type") == "static" and not _is_original_dl:
                        login_valid, login_msg = await probe_login_status(_shared_client, account.cookie)
                        if login_valid is False:
                            account.is_active = False
                            db.commit()
                            task.failed_count += 1
                            task.update_progress()
                            db.commit()
                            log(f"失败(账号登录态失效): {resource_id} | account={account.id} | {login_msg}")
                            await pool.release(account, success=False, consume_quota=False)
                            return
                        if account.account_type == "vip":
                            task.failed_count += 1
                            task.update_progress()
                            db.commit()
                            log(f"失败(VIP重试后仍未拿到原图): {resource_id} | account={account.id}")
                            await pool.release(account, success=False, consume_quota=False)
                            return
                    if _tags:
                        _label = "_".join(_tags[:2])
                        _fname = f"{_label}_{_w}x{_h}.{_url_ext}" if (_w and _h) else f"{_label}.{_url_ext}"
                    else:
                        _fname = None  # 无标签时由 downloader 从 URL 自动提取

                    # 分类名称（如"动漫｜二次元"）：优先使用 API 映射名称，回退到第一个标签
                    _category_name = item.get("category_name") or ""
                    _category = _category_name or (_tags[0] if _tags else item.get("wallpaper_type", "misc"))

                    # 色系 / 分类 UUID（存入 DB 便于精确筛选）
                    _type_id    = item.get("type_id") or None
                    _color_id   = item.get("color_id") or None
                    _color_name = item.get("color_name") or None
                    _favor_count = item.get("favor_count")

                    # 下载文件
                    local_path = await downloader.download(
                        resource_id=resource_id,
                        download_url=_dl_url,
                        cookie=account.cookie,
                        category=_category,
                        filename=_fname,
                        wallpaper_type=item.get("wallpaper_type", "static"),
                        width=item.get("width"),
                        height=item.get("height"),
                        referer_url=item.get("source_url"),
                        session_profile=_session_profile,
                    )

                    if not local_path:
                        task.failed_count += 1
                        task.update_progress()
                        db.commit()
                        log(f"失败(下载失败): {resource_id}")
                        # getCompleteUrl 已成功时网站已计费，需要消耗本地配额保持同步
                        await pool.release(account, success=False, consume_quota=_is_original_dl)
                        return

                    # 计算 hash
                    from backend.core.downloader import DOWNLOAD_ROOT
                    abs_path = os.path.join(DOWNLOAD_ROOT, local_path)
                    md5, sha256 = DedupManager.compute_hashes(abs_path)

                    # 视频时长提取（需要 ffprobe；未安装时静默跳过）
                    _video_duration = None
                    if item.get("wallpaper_type") == "dynamic":
                        _video_duration = _probe_video_duration(abs_path)

                    # 上传到图床（失败不影响下载流程）
                    _imgbed_url = None
                    _upload_records = None
                    item_uploader = resolve_item_uploader(item)
                    if item_uploader:
                        _reused_record = find_reusable_upload_record(
                            db,
                            profile_key=item_uploader.profile_key,
                            sha256=sha256,
                            md5=md5,
                            resource_id=resource_id,
                        ) if item_uploader.profile_key else None
                        if _reused_record and _reused_record.get("url"):
                            _reused_record = dict(_reused_record)
                            if upload_with_tags:
                                _remote_meta = await sync_remote_record_metadata(
                                    item_uploader,
                                    url=_reused_record["url"],
                                    width=item.get("width"),
                                    height=item.get("height"),
                                    wallpaper_type=item.get("wallpaper_type", "static"),
                                    category=_category or "",
                                    color_theme=_color_name or "",
                                    tags=item.get("tags", ""),
                                    sync_tags=True,
                                )
                                if _remote_meta["remote_path"]:
                                    _reused_record["remote_path"] = _remote_meta["remote_path"]
                                if _remote_meta["remote_tags"]:
                                    _reused_record["remote_tags"] = _remote_meta["remote_tags"]
                            else:
                                _reused_record.setdefault(
                                    "remote_path",
                                    parse_remote_file_id_from_url(_reused_record.get("url")) or "",
                                )
                            _imgbed_url = _reused_record["url"]
                            _upload_records = dump_upload_records({
                                item_uploader.profile_key: _reused_record,
                            })
                            upsert_upload_registry_record(
                                db,
                                profile_key=item_uploader.profile_key,
                                format_key=_reused_record.get("format_key"),
                                url=_imgbed_url,
                                resource_id=resource_id,
                                sha256=sha256,
                                md5=md5,
                                profile_name=_reused_record.get("profile_name") or item_uploader.profile_name,
                                channel=_reused_record.get("channel") or item_uploader.channel,
                                uploaded_at=_reused_record.get("uploaded_at"),
                                source_server=_reused_record.get("source_server"),
                            )
                            log(f"图床上传复用成功: {_imgbed_url}")
                        else:
                            _imgbed_url = await item_uploader.upload(
                                abs_path,
                                width=item.get("width"),
                                height=item.get("height"),
                                wallpaper_type=item.get("wallpaper_type", "static"),
                                category=_category or "",
                                type_id=_type_id or "",
                                color_theme=_color_name or "",
                                color_id=_color_id or "",
                                tags=item.get("tags", ""),
                                resource_id=resource_id,
                                is_original=_is_original_dl,
                            )
                            if _imgbed_url:
                                if item_uploader.profile_key:
                                    _remote_meta = await sync_remote_record_metadata(
                                        item_uploader,
                                        url=_imgbed_url,
                                        width=item.get("width"),
                                        height=item.get("height"),
                                        wallpaper_type=item.get("wallpaper_type", "static"),
                                        category=_category or "",
                                        color_theme=_color_name or "",
                                        tags=item.get("tags", ""),
                                        sync_tags=bool(upload_with_tags),
                                    )
                                    _record = build_upload_record(
                                        profile_key=item_uploader.profile_key,
                                        profile_name=item_uploader.profile_name,
                                        channel=item_uploader.channel,
                                        url=_imgbed_url,
                                        remote_path=_remote_meta["remote_path"],
                                        remote_tags=_remote_meta["remote_tags"],
                                    )
                                    _upload_records = dump_upload_records({
                                        item_uploader.profile_key: _record
                                    })
                                    upsert_upload_registry_record(
                                        db,
                                        profile_key=item_uploader.profile_key,
                                        url=_imgbed_url,
                                        resource_id=resource_id,
                                        sha256=sha256,
                                        md5=md5,
                                        profile_name=item_uploader.profile_name,
                                        channel=item_uploader.channel,
                                        uploaded_at=_record.get("uploaded_at"),
                                    )
                                log(f"图床上传成功: {_imgbed_url}")
                            else:
                                log(f"图床上传失败（不影响本地存储）: {resource_id}")

                    # 创建壁纸记录
                    _actual_size = os.path.getsize(abs_path) if os.path.exists(abs_path) else None
                    _file_mb_str = item.get("file_mb", "")
                    # 验证大小：将 API 标注大小与实际下载大小对比，辅助确认原图
                    _expected_bytes = _parse_file_mb_to_bytes(_file_mb_str)
                    if _expected_bytes and _actual_size:
                        _ratio = abs(_actual_size - _expected_bytes) / _expected_bytes
                        _size_match = _ratio < 0.15  # 15% 容差
                    else:
                        _size_match = None
                    wallpaper = Wallpaper(
                        resource_id=resource_id,
                        account_id=account.id,
                        title=detail.get("title") or item.get("title", ""),
                        md5=md5,
                        sha256=sha256,
                        local_path=local_path,
                        file_size=_actual_size,
                        file_mb=_file_mb_str or None,
                        is_original=_is_original_dl,
                        width=detail.get("width") or item.get("width"),
                        height=detail.get("height") or item.get("height"),
                        wallpaper_type=item.get("wallpaper_type", "static"),
                        # 分类：使用可读名称（"动漫｜二次元"）作为目录和显示名，回退到标签名
                        category=_category,
                        # 分类/色系 UUID：存储原始 API ID，用于精确过滤
                        type_id=_type_id,
                        color_id=_color_id,
                        # 色系可读名（"偏蓝"），供画廊筛选
                        color_theme=_color_name,
                        tags=item.get("tags", ""),
                        hot_score=item.get("hot_score"),
                        favor_count=_favor_count,
                        source_url=item.get("source_url", ""),
                        download_url=detail["download_url"],
                        video_duration=_video_duration,
                        imgbed_url=_imgbed_url,
                        upload_records=_upload_records,
                        status="done",
                    )
                    db.add(wallpaper)
                    db.flush()

                    # Hash 去重检查
                    dup = dedup.check_file_duplicate(abs_path)
                    if dup and dup.id != wallpaper.id:
                        dedup.handle_duplicate_file(wallpaper, dup, abs_path)
                        task.skip_count += 1
                        log(f"重复(hash相同): {resource_id}")
                    else:
                        task.success_count += 1
                        _size_info = ""
                        if _file_mb_str and _actual_size:
                            _actual_mb = _actual_size / (1024 * 1024)
                            _size_info = f" | API标注={_file_mb_str} 实际={_actual_mb:.2f}MB"
                            if _size_match is not None:
                                _size_info += " ✓匹配" if _size_match else " ✗不匹配"
                        _quality = "原图" if _is_original_dl else "预览图"
                        log(f"成功({_quality}): {resource_id} → {local_path}{_size_info}")

                        # ── 自动格式转换：统一走全局队列，避免下载 worker 直接重编码 ──
                        _media_cfg = load_config().get("media_convert", {})
                        if _media_cfg.get("auto_convert", False):
                            _is_video = item.get("wallpaper_type") == "dynamic"
                            _conv_key = "video" if _is_video else "image"
                            _conv_dict = dict(_media_cfg.get(_conv_key, {}))
                            if _conv_dict.get("enabled", False):
                                if _is_video:
                                    _queued_convert_msg = "格式转换跳过: 已关闭动态图转换，仅保留静态图转换"
                                else:
                                    _queued_convert_request = {
                                        "id": wallpaper.id,
                                        "abs_path": abs_path,
                                        "wallpaper_type": item.get("wallpaper_type", "static"),
                                        "media_cfg": _media_cfg,
                                    }

                    db.commit()
                    if _queued_convert_msg:
                        log(_queued_convert_msg)
                    elif _queued_convert_request:
                        try:
                            job = _get_convert_queue().submit_batch(
                                items=[{
                                    "id": _queued_convert_request["id"],
                                    "abs_path": _queued_convert_request["abs_path"],
                                    "wallpaper_type": _queued_convert_request["wallpaper_type"],
                                }],
                                media_cfg=_queued_convert_request["media_cfg"],
                                delete_original=None,
                                output_format=None,
                                timeout_override=None,
                                preset=None,
                            )
                            log(
                                f"格式转换已入队: 批次 {job.batch_id} | "
                                f"壁纸 ID {_queued_convert_request['id']}"
                            )
                        except Exception as _conv_err:
                            log(f"格式转换入队失败: {_conv_err}")
                    task.update_progress()
                    db.commit()
                    # 仅原图（getCompleteUrl）消耗配额；previewFileImg 回退不计入每日限额
                    await pool.release(account, success=True, consume_quota=_is_original_dl)

                    # altcha 主动轮换：每成功下载 2 张原图后提前重置 session，
                    # 避免第 3 次 getCompleteUrl 遭遇 305/3004 限流
                    if _is_original_dl:
                        async with _altcha_lock:
                            _altcha_use_count[0] += 1
                            _should_reset = _altcha_use_count[0] >= 2
                        if _should_reset:
                            await invalidate_altcha()

                    # 人性化行为：记录下载 + 分层延迟（模拟用户浏览节奏）
                    # pool.release 在前：账号尽早归还，不因延迟占用
                    if human_ctrl:
                        human_ctrl.record_download()
                        _continue = await human_ctrl.post_download_delay(task.success_count)
                        if not _continue:
                            # 层 4 会话结束模拟：长时间暂停后本次迭代继续（下载已完成，只是等待）
                            log("会话结束模拟完毕，恢复下载")

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    task.failed_count += 1
                    task.update_progress()
                    db.commit()
                    log(f"异常 {resource_id}: {e}")
                    # 仅当已拿到原图签名 URL 时消耗配额（网站已计费）
                    await pool.release(account, success=False, consume_quota=_is_original_dl)

        # 迭代爬取并并发下载
        prefilter_skip_count = 0
        prefilter_existing_count = 0
        pending_prefilter_skip = 0
        pending_prefilter_existing = 0
        last_prefilter_skip_reason = ""
        last_prefilter_skip_resource_id = ""
        last_prefilter_existing_resource_id = ""
        selected_candidates: list[dict] = []
        candidate_pool: list[dict] = []
        diversify_static_orientations = _should_diversify_static_orientations(cfg)
        orientation_scan_limit = max(effective_max, _STATIC_ORIENTATION_SCAN_LIMIT)
        source_scopes = _resolve_source_scopes(cfg)
        primary_source_scope = source_scopes[0]
        last_scanned_page = resume_start_page
        stopped_early = False
        wrapped_scan = False

        def flush_prefilter_logs(force: bool = False) -> None:
            nonlocal pending_prefilter_skip, pending_prefilter_existing
            nonlocal last_prefilter_skip_reason, last_prefilter_skip_resource_id
            nonlocal last_prefilter_existing_resource_id

            if pending_prefilter_skip and (force or pending_prefilter_skip >= 20):
                log(_format_prefilter_summary(
                    label="预筛跳过(不符合筛选)",
                    batch_count=pending_prefilter_skip,
                    total_count=prefilter_skip_count,
                    latest_resource_id=last_prefilter_skip_resource_id,
                    latest_reason=last_prefilter_skip_reason,
                ))
                pending_prefilter_skip = 0
                last_prefilter_skip_reason = ""
                last_prefilter_skip_resource_id = ""

            if pending_prefilter_existing and (force or pending_prefilter_existing >= 20):
                log(_format_prefilter_summary(
                    label="预筛跳过(已存在)",
                    batch_count=pending_prefilter_existing,
                    total_count=prefilter_existing_count,
                    latest_resource_id=last_prefilter_existing_resource_id,
                ))
                pending_prefilter_existing = 0
                last_prefilter_existing_resource_id = ""

        async def scan_candidate_range(
            source_scope: str,
            start_page: int,
            end_page: Optional[int] = None,
            max_candidates_for_scope: Optional[int] = None,
        ) -> bool:
            nonlocal prefilter_skip_count, prefilter_existing_count
            nonlocal pending_prefilter_skip, pending_prefilter_existing
            nonlocal last_prefilter_skip_reason, last_prefilter_skip_resource_id
            nonlocal last_prefilter_existing_resource_id
            nonlocal last_scanned_page, stopped_early
            accepted_in_scope = 0

            async for item in crawler.iter_wallpapers(
                cookie=account_for_crawl.cookie,
                category=cfg.categories[0] if cfg.categories else "",
                sort_by=cfg.sort_by,
                wallpaper_type=cfg.wallpaper_type,
                source_scope=source_scope,
                color_theme=cfg.color_themes[0] if cfg.color_themes else "",
                max_count=None,
                start_page=start_page,
                end_page=end_page,
                session_profile=_session_profile,
            ):
                if task.status != "running":
                    stopped_early = True
                    return False

                resource_id = item.get("resource_id", "")
                if source_scope == primary_source_scope:
                    last_scanned_page = max(1, int(item.get("_list_page") or start_page))
                passed, reason = filter_engine.match(item)
                if not passed:
                    prefilter_skip_count += 1
                    pending_prefilter_skip += 1
                    last_prefilter_skip_resource_id = resource_id
                    last_prefilter_skip_reason = reason
                    flush_prefilter_logs()
                    continue

                if dedup.is_resource_downloaded(resource_id):
                    prefilter_existing_count += 1
                    pending_prefilter_existing += 1
                    last_prefilter_existing_resource_id = resource_id
                    flush_prefilter_logs()
                    continue

                candidate_pool.append(item)
                accepted_in_scope += 1

                if max_candidates_for_scope is not None and accepted_in_scope >= max_candidates_for_scope:
                    stopped_early = True
                    return False

                if not diversify_static_orientations:
                    if len(source_scopes) == 1 and len(candidate_pool) >= effective_max:
                        stopped_early = True
                        return False
                    continue

                if len(candidate_pool) < effective_max:
                    continue

                if _has_mixed_static_orientations(candidate_pool):
                    stopped_early = True
                    return False

                if len(candidate_pool) >= orientation_scan_limit:
                    flush_prefilter_logs(force=True)
                    log(
                        f"方向补齐未命中: 已额外扫描 {len(candidate_pool)} 张候选，"
                        "仍未找到可混排的竖图，将按热门顺序下载"
                    )
                    stopped_early = True
                    return False

            return True

        account_for_crawl = await pool.acquire()
        if not account_for_crawl:
            task.status = "failed"
            task.error_msg = "无可用账号"
            task.finished_at = datetime.now()
            db.commit()
            return

        try:
            if len(source_scopes) > 1:
                log(f"资源入口: 同时扫描 {' / '.join(source_scopes)}")

            for index, source_scope in enumerate(source_scopes):
                scope_resume_page = resume_start_page if index == 0 else 1
                per_scope_limit = effective_max if len(source_scopes) > 1 else None
                fully_scanned = await scan_candidate_range(
                    source_scope=source_scope,
                    start_page=scope_resume_page,
                    max_candidates_for_scope=per_scope_limit,
                )
                if (
                    index == 0
                    and fully_scanned
                    and task.status == "running"
                    and resume_start_page > 1
                    and len(candidate_pool) < effective_max
                ):
                    wrapped_scan = True
                    log(
                        f"查询游标已到末页: 从第 1 页回补到第 {resume_start_page - 1} 页"
                    )
                    await scan_candidate_range(
                        source_scope=source_scope,
                        start_page=1,
                        end_page=resume_start_page - 1,
                        max_candidates_for_scope=per_scope_limit,
                    )
                if task.status != "running":
                    break

            flush_prefilter_logs(force=True)

            next_resume_page = 1 if not stopped_early else max(1, last_scanned_page)
            update_runtime_config(
                _resume_start_page=resume_start_page,
                _resume_next_page=next_resume_page,
                _resume_wrapped=wrapped_scan,
            )

            if diversify_static_orientations:
                selected_candidates = _select_diversified_candidates(candidate_pool, effective_max)
                selected_portraits = sum(
                    1 for item in selected_candidates
                    if _get_wallpaper_orientation(item) == "portrait"
                )
                selected_landscapes = sum(
                    1 for item in selected_candidates
                    if _get_wallpaper_orientation(item) == "landscape"
                )
                if selected_portraits and selected_landscapes:
                    log(
                        f"方向补齐成功: 候选池 {len(candidate_pool)} 张 | "
                        f"已选横图 {selected_landscapes} 张、竖图 {selected_portraits} 张"
                    )
            else:
                selected_candidates = candidate_pool[:effective_max]

            if len(selected_candidates) < effective_max:
                task.total_count = len(selected_candidates)
                db.commit()
                log(
                    f"候选不足: 仅找到 {len(selected_candidates)} 张符合条件且未下载的图片"
                )

            worker_tasks = [
                asyncio.create_task(process_one(item))
                for item in selected_candidates
            ]
            await asyncio.gather(*worker_tasks, return_exceptions=True)

        finally:
            # 爬取列表只读数据，不消耗下载配额
            await pool.release(account_for_crawl, consume_quota=False)

        task.status = "done"
        task.finished_at = datetime.now()
        task.progress = 100.0
        log(
            f"任务完成: 成功={task.success_count} 失败={task.failed_count} "
            f"跳过={task.skip_count} 预筛跳过={prefilter_skip_count} "
            f"预筛已存在={prefilter_existing_count}"
        )
        db.commit()

    except asyncio.CancelledError:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.status == "running":
            task.status = "paused"
            db.commit()
    except Exception as e:
        logger.exception(f"[Tasks] 任务 {task_id} 执行异常: {e}")
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_msg = str(e)
            task.finished_at = datetime.now()
            db.commit()
    finally:
        # 关闭任务级共享 client
        try:
            await _shared_client.aclose()
        except Exception:
            pass
        try:
            for _uploader in created_uploaders.values():
                await _uploader.aclose()
        except Exception:
            pass
        try:
            for _c in _account_clients.values():
                await _c.aclose()
        except Exception:
            pass
        db.close()
