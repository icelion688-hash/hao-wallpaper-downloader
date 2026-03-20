"""
FastAPI entrypoint.
Run with: `python -m backend.main`
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api import accounts, autopilot, gallery, schedule, settings, stats, tasks
from backend.config import load_config
from backend.core.account_pool import AccountPool
from backend.core.anti_detection import AntiDetection, HumanBehaviorController
from backend.core.autopilot_engine import AutoPilotEngine
from backend.core.captcha_solver import AltchaSolver
from backend.core.convert_queue import init_convert_queue
from backend.core.filters import FilterConfig
from backend.core.imgbed_uploader import ImgbedUploader
from backend.core.upload_profiles import build_task_uploader
from backend.models.database import SessionLocal, init_db
from backend.models.task import Task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _latest_mtime(path: str) -> float:
    """Return latest modified time under a file or directory."""

    if not os.path.exists(path):
        return 0.0

    if os.path.isfile(path):
        return os.path.getmtime(path)

    latest = 0.0
    for root, _, files in os.walk(path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            latest = max(latest, os.path.getmtime(file_path))
    return latest


def _is_frontend_dist_stale(base_dir: str) -> bool:
    """Check whether frontend dist is older than source files."""

    frontend_dir = os.path.join(base_dir, "frontend")
    dist_dir = os.path.join(frontend_dir, "dist")
    tracked_paths = [
        os.path.join(frontend_dir, "src"),
        os.path.join(frontend_dir, "index.html"),
        os.path.join(frontend_dir, "package.json"),
        os.path.join(frontend_dir, "vite.config.js"),
    ]

    if not os.path.exists(dist_dir):
        return True

    dist_mtime = _latest_mtime(dist_dir)
    source_mtime = max((_latest_mtime(path) for path in tracked_paths), default=0.0)
    return source_mtime > dist_mtime


class SPAStaticFiles(StaticFiles):
    """Return index.html on unknown frontend routes (SPA fallback)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise

            method = scope.get("method", "").upper()
            if method not in {"GET", "HEAD"}:
                raise

            if path.startswith("api/") or path.startswith("downloads/"):
                raise

            return await super().get_response("index.html", scope)


anti_detection: AntiDetection | None = None
account_pool: AccountPool | None = None
captcha_solver: AltchaSolver | None = None
imgbed_uploader: ImgbedUploader | None = None
human_behavior: HumanBehaviorController | None = None
autopilot_engine: AutoPilotEngine | None = None
_reset_task: asyncio.Task | None = None
_scheduler_task: asyncio.Task | None = None
_convert_queue = None


async def _scheduler_loop(app: FastAPI):
    from backend.api.schedule import load_schedule
    from backend.api.tasks import _execute_task, _running_tasks

    last_triggered_date = None
    logger.info("[Scheduler] 定时调度器已就绪")

    while True:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break

        try:
            sched = load_schedule()
            if not sched.get("enabled"):
                continue

            now = datetime.now()
            h, m = [int(x) for x in sched.get("time", "09:00").split(":")]
            if now.hour != h or now.minute != m:
                continue

            today = now.date()
            if last_triggered_date == today:
                continue
            last_triggered_date = today

            cfg = FilterConfig.from_dict(sched.get("task_config", {}))
            db = SessionLocal()
            try:
                task_name = f"定时任务 {now.strftime('%m/%d %H:%M')}"
                task = Task(
                    name=task_name,
                    status="running",
                    total_count=cfg.max_count,
                    started_at=now,
                )
                task.config = cfg.to_dict()
                db.add(task)
                db.commit()
                db.refresh(task)

                _anti = app.state.anti
                _captcha = app.state.captcha
                _uploader = getattr(app.state, "imgbed", None)
                _human = getattr(app.state, "human_ctrl", None)
                _running_tasks[task.id] = asyncio.create_task(
                    _execute_task(task.id, _anti, _captcha, _uploader, _human)
                )
                logger.info("[Scheduler] 已触发定时任务 id=%d name=%s", task.id, task_name)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            logger.error("[Scheduler] 调度异常: %s", exc)

    logger.info("[Scheduler] 定时调度器已停止")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global anti_detection, account_pool, captcha_solver, imgbed_uploader, human_behavior, autopilot_engine, _reset_task, _scheduler_task, _convert_queue

    logger.info("=== HaoWallpaper Downloader 启动 ===")
    init_db()

    if _is_frontend_dist_stale(BASE_DIR):
        logger.warning(
            "检测到前端构建产物已过期，请先执行 'cd frontend && npm run build'，"
            "或使用项目根目录下的 start.sh 重新启动服务"
        )
        app.state.frontend_dist_stale = True
    else:
        app.state.frontend_dist_stale = False

    cfg = load_config()
    anti_detection = AntiDetection(
        proxies=cfg.get("proxies", []),
        min_delay=cfg.get("min_delay", 0.5),
        max_delay=cfg.get("max_delay", 2.0),
        use_proxy=cfg.get("use_proxy", False),
    )
    captcha_solver = AltchaSolver()

    imgbed_uploader = build_task_uploader()
    if imgbed_uploader:
        logger.info("图床上传已启用: %s", imgbed_uploader.base_url)
    else:
        imgbed_uploader = None
        logger.info("图床上传未配置，跳过上传")

    # 人性化下载控制器：每日随机上限 + 下载节奏模拟
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    human_behavior = HumanBehaviorController(data_dir=data_dir)
    logger.info(
        "人性化控制器已启动: 今日上限 %d 张，已下 %d 张",
        human_behavior.daily_limit,
        human_behavior.downloaded_today,
    )

    db = SessionLocal()
    account_pool = AccountPool(db=db)

    # AutoPilot 引擎（单例，配置持久化到 data/autopilot.json）
    autopilot_engine = AutoPilotEngine(data_dir=data_dir)

    app.state.anti = anti_detection
    app.state.pool = account_pool
    app.state.captcha = captcha_solver
    app.state.imgbed = imgbed_uploader
    app.state.human_ctrl = human_behavior
    app.state.autopilot = autopilot_engine
    app.state.db = db
    autopilot_engine.bind_app_state(app.state)

    _reset_task = asyncio.create_task(account_pool.daily_reset_loop())
    _scheduler_task = asyncio.create_task(_scheduler_loop(app))

    # 格式转换队列（后台 worker）
    _convert_queue = init_convert_queue()
    _convert_queue.start()

    logger.info("后台任务已启动：每日配额重置")
    logger.info("定时调度器已启动（每 30 秒检查一次）")
    logger.info("格式转换队列已启动")

    yield

    if _reset_task:
        _reset_task.cancel()
    if _scheduler_task:
        _scheduler_task.cancel()
    if _convert_queue:
        await _convert_queue.stop()
    if autopilot_engine:
        await autopilot_engine.stop()
    if imgbed_uploader:
        await imgbed_uploader.aclose()
    db.close()
    logger.info("=== 服务关闭 ===")


app = FastAPI(
    title="HaoWallpaper Downloader",
    description="好壁纸批量下载管理系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router, prefix="/api/accounts", tags=["账号管理"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["任务管理"])
app.include_router(autopilot.router, prefix="/api/autopilot", tags=["自动驾驶"])
app.include_router(gallery.router, prefix="/api/gallery", tags=["下载画廊"])
app.include_router(stats.router, prefix="/api/stats", tags=["系统监控"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["定时计划"])
app.include_router(settings.router, prefix="/api/settings", tags=["全局设置"])


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "frontend_dist_stale": getattr(app.state, "frontend_dist_stale", False),
    }


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
FRONTEND_DIST = os.path.join(BASE_DIR, "frontend", "dist")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

app.mount("/downloads", StaticFiles(directory=DOWNLOADS_DIR), name="downloads")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    logger.info("已挂载前端静态文件: %s", FRONTEND_DIST)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
