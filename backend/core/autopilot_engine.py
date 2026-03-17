"""
autopilot_engine.py — 全自动下载调度引擎

核心特性：
  - 基于用户配置的时区（默认 Asia/Shanghai）判断活跃/非活跃时段
  - 活跃时段与非活跃时段采用独立的下载参数（会话大小、间隔时间）
  - 非活跃时段可独立开关（关闭则完全休眠到下一活跃时段）
  - 多分类轮转（round-robin）
  - 遵守 HumanBehaviorController 每日总上限
  - 复用 _execute_task，任务记录正常写入 DB / 任务列表

状态机：
  idle → running
           ├── session        （正在执行下载会话）
           ├── waiting        （会话间等待）
           ├── sleeping       （等待活跃时段开始）
           └── daily_limit    （今日配额用尽，等待明天）
  running → idle（手动停止 / 每日上限后无法恢复）
"""

import asyncio
import json
import logging
import os
import random
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 支持的常用时区列表（前端下拉选项）
SUPPORTED_TIMEZONES = [
    "Asia/Shanghai",
    "Asia/Chongqing",
    "Asia/Urumqi",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Asia/Singapore",
    "UTC",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Australia/Sydney",
]


def _now_in_tz(tz_name: str) -> datetime:
    """返回指定时区的当前时间，zoneinfo 不可用时降级为本地时间"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now()


def _is_hour_in_range(hour: int, start: int, end: int) -> bool:
    """
    判断 hour 是否在 [start, end) 内，支持跨午夜。

    Examples:
      start=8,  end=23 → 8:00–22:59（常规白天）
      start=22, end=6  → 22:00–次日 5:59（夜猫子模式）
    """
    if start <= end:
        return start <= hour < end
    # 跨午夜
    return hour >= start or hour < end


class AutoPilotEngine:
    """全自动下载调度引擎（单例，挂载到 app.state.autopilot）"""

    def __init__(self, data_dir: str = "data"):
        self._config_file = os.path.join(data_dir, "autopilot.json")
        self._config: dict = self._default_config()
        self._load_config()

        self._status: str = "idle"   # idle / running
        self._phase: str = "idle"    # idle / session / waiting / sleeping / daily_limit
        self._mode: str = ""         # active / inactive（当前正在使用哪个模式）
        self._loop_task: Optional[asyncio.Task] = None
        self._logs: list[str] = []
        self._app_state = None

        self._today_date: str = ""
        self._today_sessions: int = 0
        self._today_downloaded: int = 0

        self._next_session_at: Optional[datetime] = None
        self._current_task_id: Optional[int] = None
        self._cat_index: int = 0

    # ── 默认配置 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _default_config() -> dict:
        return {
            # ── 时区与活跃时段 ──────────────────────────────────────────────
            "timezone": "Asia/Shanghai",
            "active_start": 8,          # 活跃时段开始（小时 0-23）
            "active_end": 23,           # 活跃时段结束（小时 0-23，不含）

            # ── 活跃时段下载模式 ────────────────────────────────────────────
            "active_session_min": 5,    # 单次最少下载张数
            "active_session_max": 20,   # 单次最多下载张数
            "active_interval_min": 1800,  # 会话间最短等待（秒）= 30 分钟
            "active_interval_max": 7200,  # 会话间最长等待（秒）= 2 小时

            # ── 非活跃时段下载模式 ──────────────────────────────────────────
            "inactive_enabled": False,  # 非活跃时段是否继续下载
            "inactive_session_min": 2,
            "inactive_session_max": 8,
            "inactive_interval_min": 7200,   # 2 小时
            "inactive_interval_max": 14400,  # 4 小时

            # ── 通用下载参数 ────────────────────────────────────────────────
            "use_imgbed_upload": False,
            "wallpaper_type": "static",
            "sort_by": "yesterday_hot",
            "categories": [],
            "color_themes": [],
            "vip_only": False,
            "min_hot_score": 0,
            "tag_blacklist": [],
            "min_width": None,
            "min_height": None,
            "screen_orientation": "all",
        }

    # ── 配置持久化 ───────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for k in self._default_config():
                    if k in saved:
                        self._config[k] = saved[k]
        except Exception as exc:
            logger.warning("[AutoPilot] 配置加载失败: %s", exc)

    def _save_config(self) -> None:
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self._config_file)), exist_ok=True
            )
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("[AutoPilot] 配置保存失败: %s", exc)

    def update_config(self, new_cfg: dict) -> None:
        """更新配置（运行中也可调用，下一次会话生效）"""
        defaults = self._default_config()
        for k, v in new_cfg.items():
            if k in defaults:
                self._config[k] = v
        self._save_config()

    # ── 状态查询 ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        self._refresh_today()
        tz_name = self._config.get("timezone", "Asia/Shanghai")
        now_tz = _now_in_tz(tz_name)
        return {
            "status": self._status,
            "phase": self._phase,
            "mode": self._mode,
            "config": self._config,
            "supported_timezones": SUPPORTED_TIMEZONES,
            "current_tz_time": now_tz.strftime("%H:%M"),
            "current_tz_name": tz_name,
            "is_active_hour": self._is_active_hour(),
            "today": {
                "sessions": self._today_sessions,
                "downloaded": self._today_downloaded,
                "date": self._today_date,
            },
            "next_session_at": (
                self._next_session_at.isoformat() if self._next_session_at else None
            ),
            "current_task_id": self._current_task_id,
            "logs": list(self._logs[-200:]),
        }

    # ── 生命周期 ─────────────────────────────────────────────────────────────

    async def start(self, config: Optional[dict], app_state) -> bool:
        if self._status == "running":
            return False
        if config:
            self.update_config(config)
        self._app_state = app_state
        self._status = "running"
        self._phase = "starting"
        self._loop_task = asyncio.create_task(self._main_loop())
        tz_name = self._config.get("timezone", "Asia/Shanghai")
        self._log(
            f"AutoPilot 已启动 | 时区: {tz_name} "
            f"| 活跃时段: {self._config['active_start']:02d}:00–{self._config['active_end']:02d}:00"
        )
        return True

    async def stop(self) -> None:
        if self._status == "idle":
            return
        prev = self._status
        self._status = "idle"
        self._phase = "idle"
        self._mode = ""
        self._next_session_at = None
        if prev == "running":
            self._log("AutoPilot 已停止")
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None

    # ── 主循环 ───────────────────────────────────────────────────────────────

    async def _main_loop(self) -> None:
        human_ctrl = self._app_state.human_ctrl

        try:
            while self._status == "running":
                self._refresh_today()

                # ── 每日上限 ─────────────────────────────────────────────────
                if human_ctrl.is_daily_limit_reached():
                    self._phase = "daily_limit"
                    self._mode = ""
                    secs = self._secs_until_next_active()
                    self._log(
                        f"今日已达下载上限 {human_ctrl.daily_limit} 张，"
                        f"约 {secs / 3600:.1f} 小时后（{self._config['timezone']} "
                        f"{self._config['active_start']:02d}:00）恢复"
                    )
                    await self._interruptible_sleep(min(secs, 600))
                    continue

                is_active = self._is_active_hour()

                # ── 非活跃时段 ───────────────────────────────────────────────
                if not is_active and not self._config.get("inactive_enabled", False):
                    self._phase = "sleeping"
                    self._mode = ""
                    secs = self._secs_until_next_active()
                    now_str = _now_in_tz(self._config["timezone"]).strftime("%H:%M")
                    self._log(
                        f"当前为非活跃时段（{self._config['timezone']} {now_str}），"
                        f"约 {secs / 60:.0f} 分钟后（{self._config['active_start']:02d}:00）恢复"
                    )
                    await self._interruptible_sleep(min(secs, 600))
                    continue

                # ── 选择本次模式参数 ─────────────────────────────────────────
                if is_active:
                    self._mode = "active"
                    sess_min = self._config["active_session_min"]
                    sess_max = self._config["active_session_max"]
                    int_min  = self._config["active_interval_min"]
                    int_max  = self._config["active_interval_max"]
                    mode_cn  = "活跃"
                else:
                    self._mode = "inactive"
                    sess_min = self._config["inactive_session_min"]
                    sess_max = self._config["inactive_session_max"]
                    int_min  = self._config["inactive_interval_min"]
                    int_max  = self._config["inactive_interval_max"]
                    mode_cn  = "非活跃"

                # ── 计算会话规模 ─────────────────────────────────────────────
                remaining = human_ctrl.remaining_today
                session_size = random.randint(sess_min, sess_max)
                session_size = min(session_size, remaining)
                if session_size <= 0:
                    self._phase = "daily_limit"
                    await asyncio.sleep(10)
                    continue

                # ── 分类轮转 ─────────────────────────────────────────────────
                cats = self._config.get("categories") or []
                cat = cats[self._cat_index % len(cats)] if cats else ""
                if cats:
                    self._cat_index += 1

                # ── 运行会话 ─────────────────────────────────────────────────
                self._phase = "session"
                now_str = _now_in_tz(self._config["timezone"]).strftime("%H:%M")
                cat_label = f"（分类: {cat}）" if cat else ""
                self._log(
                    f"[{mode_cn}] 开始第 {self._today_sessions + 1} 次会话 "
                    f"{now_str} — 计划 {session_size} 张{cat_label}"
                )
                downloaded = await self._run_session(session_size, cat)
                self._today_sessions += 1
                self._today_downloaded += downloaded
                self._log(
                    f"[{mode_cn}] 会话完成 — 本次 {downloaded} 张 | "
                    f"今日 {self._today_sessions} 次 / 累计 {self._today_downloaded} 张"
                )

                if human_ctrl.is_daily_limit_reached():
                    continue

                # ── 会话间等待 ───────────────────────────────────────────────
                interval = random.uniform(int_min, int_max)
                self._next_session_at = datetime.now() + timedelta(seconds=interval)
                self._phase = "waiting"
                self._log(
                    f"[{mode_cn}] 下次会话约 {interval / 60:.0f} 分钟后 "
                    f"（{self._next_session_at.strftime('%H:%M')}）"
                )
                await self._interruptible_sleep(interval)
                self._next_session_at = None

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._log(f"主循环异常: {exc}")
            logger.exception("[AutoPilot] 主循环异常")
        finally:
            self._phase = "idle"
            self._status = "idle"
            self._mode = ""
            self._current_task_id = None
            self._next_session_at = None

    # ── 会话执行 ─────────────────────────────────────────────────────────────

    async def _run_session(self, count: int, category: str) -> int:
        """创建 Task 记录并调用 _execute_task，返回实际下载数"""
        from backend.api.tasks import _execute_task, _running_tasks
        from backend.models.database import SessionLocal
        from backend.models.task import Task as TaskModel

        app = self._app_state
        task_cfg = {
            "wallpaper_type": self._config["wallpaper_type"],
            "categories": [category] if category else [],
            "sort_by": self._config["sort_by"],
            "color_themes": self._config.get("color_themes", []),
            "max_count": count,
            "concurrency": 1,
            "vip_only": self._config["vip_only"],
            "use_proxy": True,
            "use_imgbed_upload": self._config["use_imgbed_upload"],
            "min_hot_score": self._config.get("min_hot_score", 0),
            "tag_blacklist": self._config.get("tag_blacklist", []),
            "min_width": self._config.get("min_width"),
            "min_height": self._config.get("min_height"),
            "screen_orientation": self._config.get("screen_orientation", "all"),
            "min_file_size": 0,
        }

        db = SessionLocal()
        try:
            mode_label = "活跃" if self._mode == "active" else "非活跃"
            task = TaskModel(
                name=f"AutoPilot [{mode_label}] {datetime.now().strftime('%m-%d %H:%M')}",
                status="running",
                total_count=count,
                started_at=datetime.now(),
            )
            task.config = task_cfg
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id
        finally:
            db.close()

        self._current_task_id = task_id
        _uploader = (
            getattr(app, "imgbed", None)
            if self._config.get("use_imgbed_upload") else None
        )

        at = asyncio.create_task(
            _execute_task(task_id, app.anti, app.captcha, _uploader, app.human_ctrl)
        )
        _running_tasks[task_id] = at
        try:
            await at
        except asyncio.CancelledError:
            at.cancel()
            try:
                await at
            except asyncio.CancelledError:
                pass
        finally:
            _running_tasks.pop(task_id, None)
            self._current_task_id = None

        db = SessionLocal()
        try:
            t = db.query(TaskModel).filter(TaskModel.id == task_id).first()
            return t.success_count if t else 0
        finally:
            db.close()

    # ── 时区工具 ─────────────────────────────────────────────────────────────

    def _is_active_hour(self) -> bool:
        """基于配置时区和时段判断当前是否为活跃时段"""
        tz = self._config.get("timezone", "Asia/Shanghai")
        start = self._config.get("active_start", 8)
        end = self._config.get("active_end", 23)
        now = _now_in_tz(tz)
        return _is_hour_in_range(now.hour, start, end)

    def _secs_until_next_active(self) -> float:
        """到下一个活跃时段 active_start 还有多少秒"""
        tz = self._config.get("timezone", "Asia/Shanghai")
        start_h = self._config.get("active_start", 8)
        now = _now_in_tz(tz)
        # 构造今天的 start_h:00（带时区感知）
        target = now.replace(hour=start_h, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return max(60.0, (target - now).total_seconds())

    # ── 内部工具 ─────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self._logs.append(entry)
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]
        logger.info("[AutoPilot] %s", msg)

    def _refresh_today(self) -> None:
        today = date.today().isoformat()
        if self._today_date != today:
            self._today_date = today
            self._today_sessions = 0
            self._today_downloaded = 0

    async def _interruptible_sleep(self, seconds: float) -> None:
        """可中断的 sleep：每 5 秒检查一次 status"""
        remaining = seconds
        while remaining > 0 and self._status == "running":
            await asyncio.sleep(min(remaining, 5.0))
            remaining -= 5.0
