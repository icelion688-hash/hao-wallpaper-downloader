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

from backend.core.upload_profiles import get_upload_settings, is_upload_profile_available

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

RUNTIME_WAKE_KEYS = {
    "timezone",
    "active_start",
    "active_end",
    "daily_limit_mode",
    "manual_daily_limit",
    "manual_daily_limit_min",
    "manual_daily_limit_max",
    "inactive_enabled",
    "active_interval_min",
    "active_interval_max",
    "inactive_interval_min",
    "inactive_interval_max",
}


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
        self._cursor_file = os.path.join(data_dir, "autopilot_cursor.json")
        self._config: dict = self._default_config()
        self._wake_event = asyncio.Event()
        self._load_config()
        self._cursor_state: dict[str, int] = self._load_cursor_state()

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
        self._last_session_summary: Optional[dict] = None
        self._cat_index: int = 0
        self._storage_cleanup_state: Optional[dict] = None

    # ── 默认配置 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _default_config() -> dict:
        return {
            # ── 时区与活跃时段 ──────────────────────────────────────────────
            "timezone": "Asia/Shanghai",
            "active_start": 8,          # 活跃时段开始（小时 0-23）
            "active_end": 23,           # 活跃时段结束（小时 0-23，不含）

            # ── 每日下载上限 ────────────────────────────────────────────────
            "daily_limit_mode": "auto",     # auto=自动生成今日上限，manual=使用手动值
            "manual_daily_limit": None,      # 手动模式下的每日下载上限
            "manual_daily_limit_min": None,  # 手动模式下的下界
            "manual_daily_limit_max": None,  # 手动模式下的上界

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
            "static_upload_profile": "",
            "dynamic_upload_profile": "",
            "static_upload_channel": "",
            "static_upload_channel_name": "",
            "dynamic_upload_channel": "",
            "dynamic_upload_channel_name": "",
            "strict_original": False,
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

            # ── 本地存储自动清仓 ────────────────────────────────────────────
            # 每次会话结束后，若 storage_auto_clean=True 则自动触发清仓
            "storage_auto_clean": False,
            "storage_max_count": 500,         # keep_count 策略下保留的最新文件数
            "storage_strategy": "keep_count", # keep_count | keep_days | upload_and_delete
            "storage_keep_days": 30,          # keep_days 策略下保留的天数
            "storage_uploaded_only": True,    # True=只删已上传到图床的文件
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
                self._config = self._normalize_config(self._config)
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

    def _load_cursor_state(self) -> dict[str, int]:
        try:
            if os.path.exists(self._cursor_file):
                with open(self._cursor_file, "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
                return {
                    str(key): max(1, int(value))
                    for key, value in raw.items()
                }
        except Exception as exc:
            logger.warning("[AutoPilot] 游标状态加载失败: %s", exc)
        return {}

    def _save_cursor_state(self) -> None:
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self._cursor_file)), exist_ok=True
            )
            with open(self._cursor_file, "w", encoding="utf-8") as f:
                json.dump(self._cursor_state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("[AutoPilot] 游标状态保存失败: %s", exc)

    @staticmethod
    def _build_cursor_key(task_cfg: dict) -> str:
        """为当前筛选条件生成稳定游标键。"""
        cursor_cfg = {
            "wallpaper_type": task_cfg.get("wallpaper_type", "static"),
            "sort_by": task_cfg.get("sort_by", "yesterday_hot"),
            "categories": task_cfg.get("categories", []),
            "color_themes": task_cfg.get("color_themes", []),
            "vip_only": task_cfg.get("vip_only", False),
            "min_hot_score": task_cfg.get("min_hot_score", 0),
            "tag_blacklist": task_cfg.get("tag_blacklist", []),
            "min_width": task_cfg.get("min_width"),
            "min_height": task_cfg.get("min_height"),
            "screen_orientation": task_cfg.get("screen_orientation", "all"),
        }
        return json.dumps(cursor_cfg, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _normalize_pair(min_value: int, max_value: int, lower_bound: int) -> tuple[int, int]:
        safe_min = max(lower_bound, int(min_value))
        safe_max = max(lower_bound, int(max_value))
        return (safe_min, safe_max) if safe_min <= safe_max else (safe_max, safe_min)

    @staticmethod
    def _resolve_available_upload_profile(profile_key: str, fallback_key: str = "") -> str:
        preferred = str(profile_key or "").strip()
        fallback = str(fallback_key or "").strip()
        if preferred and is_upload_profile_available(preferred):
            return preferred
        if fallback and is_upload_profile_available(fallback):
            return fallback
        uploads = get_upload_settings()
        for profile in uploads.get("profiles", []):
            key = str(profile.get("key") or "").strip()
            if key and is_upload_profile_available(key):
                return key
        return fallback or preferred

    @classmethod
    def _normalize_config(cls, raw_cfg: dict) -> dict:
        cfg = {**cls._default_config(), **(raw_cfg or {})}
        cfg["categories"] = [str(item).strip() for item in (cfg.get("categories") or []) if str(item).strip()]
        cfg["color_themes"] = [str(item).strip() for item in (cfg.get("color_themes") or []) if str(item).strip()]
        cfg["tag_blacklist"] = [str(item).strip() for item in (cfg.get("tag_blacklist") or []) if str(item).strip()]
        cfg["active_start"] = max(0, min(23, int(cfg.get("active_start", 8))))
        cfg["active_end"] = max(0, min(23, int(cfg.get("active_end", 23))))
        cfg["daily_limit_mode"] = (
            "manual" if str(cfg.get("daily_limit_mode", "auto")).strip().lower() == "manual" else "auto"
        )
        manual_daily_limit = cfg.get("manual_daily_limit")
        normalized_manual_limit = (
            None if manual_daily_limit in (None, "", 0, "0")
            else max(1, min(500, int(manual_daily_limit)))
        )
        manual_daily_limit_min = cfg.get("manual_daily_limit_min")
        manual_daily_limit_max = cfg.get("manual_daily_limit_max")
        normalized_manual_limit_min = (
            None if manual_daily_limit_min in (None, "", 0, "0")
            else max(1, min(500, int(manual_daily_limit_min)))
        )
        normalized_manual_limit_max = (
            None if manual_daily_limit_max in (None, "", 0, "0")
            else max(1, min(500, int(manual_daily_limit_max)))
        )
        if normalized_manual_limit_min is None and normalized_manual_limit_max is None and normalized_manual_limit is not None:
            normalized_manual_limit_min = normalized_manual_limit
            normalized_manual_limit_max = normalized_manual_limit
        elif normalized_manual_limit_min is None and normalized_manual_limit_max is not None:
            normalized_manual_limit_min = normalized_manual_limit_max
        elif normalized_manual_limit_max is None and normalized_manual_limit_min is not None:
            normalized_manual_limit_max = normalized_manual_limit_min
        if normalized_manual_limit_min is not None and normalized_manual_limit_max is not None:
            normalized_manual_limit_min, normalized_manual_limit_max = cls._normalize_pair(
                normalized_manual_limit_min,
                normalized_manual_limit_max,
                1,
            )
        cfg["manual_daily_limit_min"] = normalized_manual_limit_min
        cfg["manual_daily_limit_max"] = normalized_manual_limit_max
        cfg["manual_daily_limit"] = (
            normalized_manual_limit_min
            if normalized_manual_limit_min is not None and normalized_manual_limit_min == normalized_manual_limit_max
            else None
        )
        cfg["active_session_min"], cfg["active_session_max"] = cls._normalize_pair(
            cfg.get("active_session_min", 5),
            cfg.get("active_session_max", 20),
            1,
        )
        cfg["inactive_session_min"], cfg["inactive_session_max"] = cls._normalize_pair(
            cfg.get("inactive_session_min", 2),
            cfg.get("inactive_session_max", 8),
            1,
        )
        cfg["active_interval_min"], cfg["active_interval_max"] = cls._normalize_pair(
            cfg.get("active_interval_min", 1800),
            cfg.get("active_interval_max", 7200),
            60,
        )
        cfg["inactive_interval_min"], cfg["inactive_interval_max"] = cls._normalize_pair(
            cfg.get("inactive_interval_min", 7200),
            cfg.get("inactive_interval_max", 14400),
            60,
        )
        cfg["inactive_enabled"] = bool(cfg.get("inactive_enabled", False))
        cfg["use_imgbed_upload"] = bool(cfg.get("use_imgbed_upload", False))
        uploads = get_upload_settings()
        default_task_profile = str(uploads.get("task_profile") or "").strip()
        static_profile = str(cfg.get("static_upload_profile") or "").strip()
        dynamic_profile = str(cfg.get("dynamic_upload_profile") or "").strip()
        cfg["static_upload_profile"] = cls._resolve_available_upload_profile(
            static_profile,
            default_task_profile,
        )
        cfg["dynamic_upload_profile"] = cls._resolve_available_upload_profile(
            dynamic_profile or cfg["static_upload_profile"],
            cfg["static_upload_profile"] or default_task_profile,
        )
        cfg["static_upload_channel"] = str(cfg.get("static_upload_channel") or "").strip()
        cfg["static_upload_channel_name"] = str(cfg.get("static_upload_channel_name") or "").strip()
        cfg["dynamic_upload_channel"] = str(cfg.get("dynamic_upload_channel") or "").strip()
        cfg["dynamic_upload_channel_name"] = str(cfg.get("dynamic_upload_channel_name") or "").strip()
        cfg["strict_original"] = bool(cfg.get("strict_original", False))
        cfg["vip_only"] = bool(cfg.get("vip_only", False))
        cfg["min_hot_score"] = max(0, int(cfg.get("min_hot_score", 0)))
        for key in ("min_width", "min_height"):
            value = cfg.get(key)
            cfg[key] = None if value in (None, "", 0) else max(1, int(value))
        # 存储限额规范化
        cfg["storage_auto_clean"] = bool(cfg.get("storage_auto_clean", False))
        cfg["storage_max_count"] = max(1, min(99999, int(cfg.get("storage_max_count") or 500)))
        cfg["storage_keep_days"] = max(1, min(3650, int(cfg.get("storage_keep_days") or 30)))
        cfg["storage_uploaded_only"] = bool(cfg.get("storage_uploaded_only", True))
        strategy = str(cfg.get("storage_strategy") or "keep_count").strip().lower()
        cfg["storage_strategy"] = strategy if strategy in ("keep_count", "keep_days", "upload_and_delete") else "keep_count"
        return cfg

    def update_config(self, new_cfg: dict) -> dict:
        """更新配置（运行中也可调用，等待状态会按新时间设置重算）"""
        merged = {**self._config, **(new_cfg or {})}
        normalized = self._normalize_config(merged)
        wake_needed = any(self._config.get(key) != normalized.get(key) for key in RUNTIME_WAKE_KEYS)
        self._config = normalized
        if wake_needed and self._status == "running":
            self._wake_event.set()
        defaults = self._default_config()
        self._save_config()
        self._sync_human_ctrl_config()
        return {key: self._config[key] for key in defaults}

    def bind_app_state(self, app_state) -> None:
        """绑定应用状态，便于同步人性化下载控制器配置。"""
        self._app_state = app_state
        self._sync_human_ctrl_config()

    def _sync_human_ctrl_config(self) -> None:
        app_state = self._app_state
        human_ctrl = getattr(app_state, "human_ctrl", None) if app_state else None
        if not human_ctrl:
            return
        human_ctrl.apply_daily_limit_config(
            limit_mode=self._config.get("daily_limit_mode", "auto"),
            manual_limit=self._config.get("manual_daily_limit"),
            manual_limit_min=self._config.get("manual_daily_limit_min"),
            manual_limit_max=self._config.get("manual_daily_limit_max"),
        )

    # ── 状态查询 ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        self._refresh_today()
        tz_name = self._config.get("timezone", "Asia/Shanghai")
        now_tz = _now_in_tz(tz_name)
        human_ctrl = getattr(self._app_state, "human_ctrl", None) if self._app_state else None
        if not self._last_session_summary:
            self._last_session_summary = self._load_last_session_summary_from_db()
        today_payload = {
            "sessions": self._today_sessions,
            "downloaded": self._today_downloaded,
            "date": self._today_date,
        }
        if human_ctrl:
            today_payload.update(
                {
                    "daily_limit": human_ctrl.daily_limit,
                    "remaining": human_ctrl.remaining_today,
                    "limit_mode": human_ctrl.daily_limit_mode,
                    "manual_daily_limit": human_ctrl.manual_daily_limit,
                    "manual_daily_limit_min": human_ctrl.manual_daily_limit_min,
                    "manual_daily_limit_max": human_ctrl.manual_daily_limit_max,
                }
            )
        return {
            "status": self._status,
            "phase": self._phase,
            "mode": self._mode,
            "config": self._config,
            "supported_timezones": SUPPORTED_TIMEZONES,
            "current_tz_time": now_tz.strftime("%H:%M"),
            "current_tz_name": tz_name,
            "is_active_hour": self._is_active_hour(),
            "today": today_payload,
            "storage": {
                "enabled": bool(self._config.get("storage_auto_clean")),
                "strategy": self._config.get("storage_strategy", "keep_count"),
                "max_count": self._config.get("storage_max_count", 500),
                "keep_days": self._config.get("storage_keep_days", 30),
                "uploaded_only": bool(self._config.get("storage_uploaded_only", True)),
                "last_cleanup": self._storage_cleanup_state,
            },
            "next_session_at": (
                self._next_session_at.isoformat() if self._next_session_at else None
            ),
            "current_task_id": self._current_task_id,
            "last_session": self._last_session_summary,
            "logs": list(self._logs[-200:]),
            "recent_sessions": self.get_recent_sessions(limit=8),
        }

    @staticmethod
    def _build_session_summary_from_task(task, planned_count: Optional[int] = None) -> dict:
        log_lines = [line.strip() for line in str(task.log_text or "").splitlines() if line.strip()]
        session_reason = "本轮已完成"
        session_reason_type = "completed"
        if any("会话收束:" in line for line in log_lines):
            session_reason = "命中会话结束模拟，本轮提前收束"
            session_reason_type = "session_end_simulated"
        elif any("补齐停止:" in line for line in log_lines):
            line = next((item for item in reversed(log_lines) if "补齐停止:" in item), "")
            session_reason = line.split("补齐停止:", 1)[-1].strip() or "本轮补齐已停止"
            session_reason_type = "replenish_stopped"
        elif any("补齐结束:" in line for line in log_lines):
            session_reason = "当前轮次未找到更多可下载的新图片"
            session_reason_type = "candidate_exhausted"
        elif task.status == "failed":
            session_reason = str(task.error_msg or "任务执行失败").strip()
            session_reason_type = "failed"
        elif task.status == "paused":
            session_reason = "任务被暂停"
            session_reason_type = "paused"
        elif task.status == "cancelled":
            session_reason = "任务已取消"
            session_reason_type = "cancelled"
        task_cfg = task.config if hasattr(task, "config") else {}
        next_page = max(1, int(task_cfg.get("_resume_next_page", 1) or 1))
        planned = int(planned_count if planned_count is not None else (task.total_count or 0))
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": task.status,
            "planned_count": planned,
            "success_count": int(task.success_count or 0),
            "failed_count": int(task.failed_count or 0),
            "skip_count": int(task.skip_count or 0),
            "progress": float(task.progress or 0.0),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "resume_next_page": next_page,
            "reason": session_reason,
            "reason_type": session_reason_type,
        }

    @classmethod
    def _load_last_session_summary_from_db(cls) -> Optional[dict]:
        try:
            from backend.models.database import SessionLocal
            from backend.models.task import Task as TaskModel

            db = SessionLocal()
            try:
                task = (
                    db.query(TaskModel)
                    .filter(TaskModel.name.like("AutoPilot %"))
                    .order_by(TaskModel.created_at.desc(), TaskModel.id.desc())
                    .first()
                )
                if not task:
                    return None
                return cls._build_session_summary_from_task(task)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[AutoPilot] 最近一轮摘要回填失败: %s", exc)
            return None

    @classmethod
    def get_recent_sessions(cls, limit: int = 8) -> list[dict]:
        try:
            from backend.models.database import SessionLocal
            from backend.models.task import Task as TaskModel

            db = SessionLocal()
            try:
                tasks = (
                    db.query(TaskModel)
                    .filter(TaskModel.name.like("AutoPilot %"))
                    .order_by(TaskModel.created_at.desc(), TaskModel.id.desc())
                    .limit(max(1, int(limit)))
                    .all()
                )
                return [cls._build_session_summary_from_task(task) for task in tasks]
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[AutoPilot] 最近会话列表读取失败: %s", exc)
            return []

    @staticmethod
    def get_session_logs(task_id: int) -> list[str]:
        try:
            from backend.models.database import SessionLocal
            from backend.models.task import Task as TaskModel

            db = SessionLocal()
            try:
                task = (
                    db.query(TaskModel)
                    .filter(TaskModel.id == task_id, TaskModel.name.like("AutoPilot %"))
                    .first()
                )
                if not task:
                    return []
                lines = [line.strip() for line in str(task.log_text or "").splitlines() if line.strip()]
                return lines[-500:]
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[AutoPilot] 会话日志读取失败 task_id=%s error=%s", task_id, exc)
            return []

    # ── 生命周期 ─────────────────────────────────────────────────────────────

    async def start(self, config: Optional[dict], app_state) -> bool:
        if self._status == "running":
            return False
        self.bind_app_state(app_state)
        if config:
            self.update_config(config)
        else:
            self._sync_human_ctrl_config()
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
        self._wake_event.set()
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
                    if await self._interruptible_sleep(min(secs, 600)):
                        self._log("调度配置已更新，重新评估今日上限等待时间")
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
                    if await self._interruptible_sleep(min(secs, 600)):
                        self._log("调度配置已更新，重新评估活跃时段等待时间")
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

                # ── 会话后自动清仓 ────────────────────────────────────────
                if self._config.get("storage_auto_clean"):
                    if downloaded > 0:
                        await self._run_storage_cleanup()
                    else:
                        self._record_storage_cleanup_state(
                            trigger="session",
                            skipped=True,
                            reason="本次会话没有新增下载文件，已跳过自动清理",
                        )
                        self._log("[存储] 自动清理已跳过 — 本次会话没有新增下载文件")

                if human_ctrl.is_daily_limit_reached():
                    continue

                # ── 会话间等待 ───────────────────────────────────────────────
                interval = random.uniform(int_min, int_max)
                self._next_session_at = _now_in_tz(self._config["timezone"]) + timedelta(seconds=interval)
                self._phase = "waiting"
                self._log(
                    f"[{mode_cn}] 下次会话约 {interval / 60:.0f} 分钟后 "
                    f"（{self._next_session_at.strftime('%H:%M')}）"
                )
                if await self._interruptible_sleep(interval):
                    self._log(f"[{mode_cn}] 间隔配置已更新，已按新设置重新计算等待时间")
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

    # ── 存储清仓 ─────────────────────────────────────────────────────────────

    def _record_storage_cleanup_state(
        self,
        *,
        trigger: str,
        skipped: bool,
        reason: str,
        result: Optional[dict] = None,
    ) -> None:
        self._storage_cleanup_state = {
            "ran_at": _now_in_tz(self._config.get("timezone", "Asia/Shanghai")).isoformat(),
            "trigger": trigger,
            "skipped": skipped,
            "reason": reason,
            "deleted": int((result or {}).get("deleted") or 0),
            "orphan_cleaned": int((result or {}).get("orphan_cleaned") or 0),
            "remaining": (result or {}).get("remaining"),
            "total_eligible": int((result or {}).get("total_eligible") or 0),
            "file_fail_count": int((result or {}).get("file_fail_count") or 0),
            "strategy": (result or {}).get("strategy") or self._config.get("storage_strategy", "keep_count"),
            "uploaded_only": bool((result or {}).get("uploaded_only", self._config.get("storage_uploaded_only", True))),
        }

    async def _run_storage_cleanup(self) -> None:
        """会话后触发本地存储清仓（在线程池中执行 DB 操作）。"""
        try:
            from backend.api.gallery import _do_cleanup_local
            from backend.models.database import SessionLocal

            strategy = self._config.get("storage_strategy", "keep_count")
            max_count = self._config.get("storage_max_count", 500)
            keep_days = self._config.get("storage_keep_days", 30)
            uploaded_only = self._config.get("storage_uploaded_only", True)

            def _cleanup():
                db = SessionLocal()
                try:
                    return _do_cleanup_local(
                        db,
                        strategy=strategy,
                        max_count=max_count,
                        keep_days=keep_days,
                        uploaded_only=uploaded_only,
                        dry_run=False,
                    )
                finally:
                    db.close()

            result = await asyncio.get_event_loop().run_in_executor(None, _cleanup)
            deleted = result.get("deleted", 0)
            orphan_cleaned = result.get("orphan_cleaned", 0)
            remaining = result.get("remaining", 0)
            reason = str(result.get("reason") or "").strip()
            self._record_storage_cleanup_state(
                trigger="session",
                skipped=False,
                reason=reason or "自动清理已执行",
                result=result,
            )
            if deleted > 0 or orphan_cleaned > 0:
                message = (
                    f"[存储] 自动清仓完成 — 删除 {deleted} 张本地文件，"
                    f"剩余 {remaining} 张（策略: {strategy}，"
                    f"{'仅已上传' if uploaded_only else '全部'}）"
                )
                if orphan_cleaned > 0:
                    message += f"，并清理 {orphan_cleaned} 个残留文件"
                self._log(message)
            else:
                self._log(f"[存储] 自动清理未删除文件 — {reason or '当前没有符合条件的文件'}")
        except Exception as exc:
            self._record_storage_cleanup_state(
                trigger="session",
                skipped=False,
                reason=f"自动清理执行失败: {exc}",
            )
            logger.warning("[AutoPilot] 自动清仓异常: %s", exc)

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
            "static_upload_profile": self._config.get("static_upload_profile", ""),
            "dynamic_upload_profile": self._config.get("dynamic_upload_profile", ""),
            "static_upload_channel": self._config.get("static_upload_channel", ""),
            "static_upload_channel_name": self._config.get("static_upload_channel_name", ""),
            "dynamic_upload_channel": self._config.get("dynamic_upload_channel", ""),
            "dynamic_upload_channel_name": self._config.get("dynamic_upload_channel_name", ""),
            "strict_original": self._config.get("strict_original", False),
            "min_hot_score": self._config.get("min_hot_score", 0),
            "tag_blacklist": self._config.get("tag_blacklist", []),
            "min_width": self._config.get("min_width"),
            "min_height": self._config.get("min_height"),
            "screen_orientation": self._config.get("screen_orientation", "all"),
            "min_file_size": 0,
        }
        cursor_key = self._build_cursor_key(task_cfg)
        resume_start_page = self._cursor_state.get(cursor_key, 1)
        task_cfg["_resume_start_page"] = resume_start_page

        db = SessionLocal()
        try:
            mode_label = "活跃" if self._mode == "active" else "非活跃"
            task = TaskModel(
                name=f"AutoPilot [{mode_label}] {_now_in_tz(self._config.get('timezone', 'Asia/Shanghai')).strftime('%m-%d %H:%M')}",
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
        self._log(f"查询游标: 本次从第 {resume_start_page} 页开始")
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
            if t:
                next_page = max(1, int(t.config.get("_resume_next_page", 1) or 1))
                self._cursor_state[cursor_key] = next_page
                self._save_cursor_state()
                self._log(f"查询游标: 下次从第 {next_page} 页开始")
                self._last_session_summary = self._build_session_summary_from_task(
                    t,
                    planned_count=count,
                )
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
        entry = f"[{_now_in_tz(self._config.get('timezone', 'Asia/Shanghai')).strftime('%H:%M:%S')}] {msg}"
        self._logs.append(entry)
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]
        logger.info("[AutoPilot] %s", msg)

    def _refresh_today(self) -> None:
        today = _now_in_tz(self._config.get("timezone", "Asia/Shanghai")).date().isoformat()
        if self._today_date != today:
            self._today_date = today
            self._today_sessions = 0
            self._today_downloaded = 0

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """可中断的 sleep：停止或调度配置变更时提前唤醒。"""
        deadline = datetime.now() + timedelta(seconds=max(0.0, seconds))
        while self._status == "running":
            if self._wake_event.is_set():
                self._wake_event.clear()
                return True
            remaining = (deadline - datetime.now()).total_seconds()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=min(remaining, 5.0))
            except asyncio.TimeoutError:
                continue
            self._wake_event.clear()
            return True
        return True
