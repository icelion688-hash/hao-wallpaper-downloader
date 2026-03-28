"""
upload_guard.py - 上传覆盖率定时巡检与自动修复。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class UploadConsistencyGuard:
    """周期性对比图床与本地上传记录，并自动补传未上传图片。"""

    def __init__(
        self,
        *,
        session_factory,
        enabled: bool = True,
        interval_seconds: int = 1800,
        initial_delay_seconds: int = 180,
    ):
        self._session_factory = session_factory
        self._enabled = bool(enabled)
        self._interval_seconds = max(300, int(interval_seconds))
        self._initial_delay_seconds = max(0, int(initial_delay_seconds))
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_run_at: Optional[str] = None
        self._last_status = "idle"
        self._last_error = ""
        self._last_summary: Optional[dict] = None

    def get_status(self) -> dict:
        return {
            "enabled": self._enabled,
            "running": self._running,
            "interval_seconds": self._interval_seconds,
            "interval_minutes": max(1, self._interval_seconds // 60),
            "initial_delay_seconds": self._initial_delay_seconds,
            "initial_delay_minutes": self._initial_delay_seconds // 60,
            "last_run_at": self._last_run_at,
            "last_status": self._last_status,
            "last_error": self._last_error,
            "last_summary": self._last_summary,
        }

    async def start(self) -> None:
        if not self._enabled:
            self._running = False
            logger.info("[UploadGuard] 已禁用，跳过启动")
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[UploadGuard] 定时巡检已启动，间隔 %d 秒", self._interval_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("[UploadGuard] 定时巡检已停止")

    async def apply_settings(
        self,
        *,
        enabled: bool,
        interval_seconds: int,
        initial_delay_seconds: int,
    ) -> None:
        next_enabled = bool(enabled)
        next_interval_seconds = max(300, int(interval_seconds))
        next_initial_delay_seconds = max(0, int(initial_delay_seconds))
        changed = (
            self._enabled != next_enabled
            or self._interval_seconds != next_interval_seconds
            or self._initial_delay_seconds != next_initial_delay_seconds
        )
        self._enabled = next_enabled
        self._interval_seconds = next_interval_seconds
        self._initial_delay_seconds = next_initial_delay_seconds
        if not changed:
            return
        await self.stop()
        if self._enabled:
            await self.start()

    async def run_once(self) -> dict:
        from backend.api.stats import run_upload_coverage_maintenance

        db: Session = self._session_factory()
        try:
            result = await run_upload_coverage_maintenance(db)
            audit_before = result.get("audit_before") or {}
            repair_result = (result.get("repair_result") or {}).get("repair") or {}
            remote_missing_reupload = result.get("remote_missing_reupload") or {}
            remote_missing_upload_result = remote_missing_reupload.get("upload_result") or {}
            reupload_result = (result.get("reupload_result") or {}).get("result") or {}
            coverage_after = result.get("coverage_after") or {}
            self._last_run_at = datetime.now().isoformat(timespec="seconds")
            self._last_status = "ok"
            self._last_error = ""
            self._last_summary = {
                "profile_key": audit_before.get("profile_key") or "",
                "total_remote": int(audit_before.get("total_remote") or 0),
                "problem_count": int(audit_before.get("problem_count") or 0),
                "repairable_remote_count": int(audit_before.get("repairable_count") or 0),
                "remote_only_count": int(audit_before.get("remote_only_count") or 0),
                "local_repaired_count": int(repair_result.get("updated_count") or 0),
                "remote_missing_reupload_count": int(remote_missing_reupload.get("prepared_count") or 0),
                "remote_missing_reupload_success_count": int(remote_missing_upload_result.get("success_count") or 0),
                "remote_missing_reupload_failed_count": int(remote_missing_upload_result.get("failed_count") or 0),
                "reupload_success_count": int(reupload_result.get("success_count") or 0),
                "reupload_failed_count": int(reupload_result.get("failed_count") or 0),
                "pending_local_count": int(coverage_after.get("missing_count") or 0),
                "repairable_local_count": int(coverage_after.get("repairable_count") or 0),
            }
            logger.info("[UploadGuard] 巡检完成: %s", self._last_summary)
            return result
        except HTTPException as exc:
            self._last_run_at = datetime.now().isoformat(timespec="seconds")
            self._last_status = "skipped"
            self._last_error = str(exc.detail)
            self._last_summary = None
            logger.info("[UploadGuard] 跳过巡检: %s", exc.detail)
            return {
                "success": False,
                "skipped": True,
                "reason": str(exc.detail),
            }
        except Exception as exc:  # noqa: BLE001
            self._last_run_at = datetime.now().isoformat(timespec="seconds")
            self._last_status = "error"
            self._last_error = str(exc)
            logger.exception("[UploadGuard] 巡检失败")
            raise
        finally:
            db.close()

    async def _loop(self) -> None:
        if self._initial_delay_seconds:
            try:
                await asyncio.sleep(self._initial_delay_seconds)
            except asyncio.CancelledError:
                return

        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            try:
                await asyncio.sleep(self._interval_seconds)
            except asyncio.CancelledError:
                break
