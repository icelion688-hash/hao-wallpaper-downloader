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

from backend.api import accounts, gallery, schedule, settings, stats, tasks
from backend.config import load_config
from backend.core.account_pool import AccountPool
from backend.core.anti_detection import AntiDetection, HumanBehaviorController
from backend.core.captcha_solver import AltchaSolver
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
_reset_task: asyncio.Task | None = None
_scheduler_task: asyncio.Task | None = None


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
    global anti_detection, account_pool, captcha_solver, imgbed_uploader, human_behavior, _reset_task, _scheduler_task

    logger.info("=== HaoWallpaper Downloader 启动 ===")
    init_db()

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

    app.state.anti = anti_detection
    app.state.pool = account_pool
    app.state.captcha = captcha_solver
    app.state.imgbed = imgbed_uploader
    app.state.human_ctrl = human_behavior
    app.state.db = db

    _reset_task = asyncio.create_task(account_pool.daily_reset_loop())
    _scheduler_task = asyncio.create_task(_scheduler_loop(app))

    logger.info("后台任务已启动：每日配额重置")
    logger.info("定时调度器已启动（每 30 秒检查一次）")

    yield

    if _reset_task:
        _reset_task.cancel()
    if _scheduler_task:
        _scheduler_task.cancel()
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
app.include_router(gallery.router, prefix="/api/gallery", tags=["下载画廊"])
app.include_router(stats.router, prefix="/api/stats", tags=["系统监控"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["定时计划"])
app.include_router(settings.router, prefix="/api/settings", tags=["全局设置"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


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
