"""
backend/core/convert_queue.py - 全局格式转换队列

设计原则：
- 单例 ConvertQueue，后台 asyncio worker 持续消费
- 视频转换信号量上限 1（防止同时多路 4K MP4 压垮内存）
- 图片转换信号量上限 = config.max_concurrent（默认 1）
- 每个 item 转换完成后立即写 DB，不等整批结束
- POST /gallery/convert/batch 立即返回 {batch_id, queued_count}
- GET  /gallery/convert/queue 返回队列全局状态 + 各批次进度
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class ConvertItem:
    """队列中一个转换任务单元"""
    wallpaper_id: int
    abs_path: str
    wallpaper_type: str          # "static" | "dynamic"
    media_cfg: dict
    delete_original: Optional[bool]
    output_format: Optional[str]
    timeout_override: Optional[int]
    preset: Optional[str]
    batch_id: str
    item_index: int              # 在批次内的序号（用于日志）


@dataclass
class BatchJob:
    """一次 batch_convert 提交对应一个 BatchJob"""
    batch_id: str
    total: int
    queued_at: float = field(default_factory=time.time)
    success: int = 0
    failed: int = 0
    skipped: int = 0
    done: int = 0                # success + failed + skipped（完成数）
    items: list[dict] = field(default_factory=list)  # 成功 item 结果
    failed_items: list[dict] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.done >= self.total

    def to_dict(self) -> dict:
        return {
            "batch_id":    self.batch_id,
            "total":       self.total,
            "done":        self.done,
            "success":     self.success,
            "failed":      self.failed,
            "skipped":     self.skipped,
            "is_complete": self.is_complete,
            "queued_at":   self.queued_at,
        }


# ──────────────────────────────────────────────
# 队列单例
# ──────────────────────────────────────────────

class ConvertQueue:
    """
    全局格式转换队列单例。
    - _queue:      asyncio.Queue[ConvertItem]
    - _batches:    {batch_id: BatchJob}，仅保留最近 50 个批次
    - _video_sem:  视频并发信号量（上限 1）
    - _image_sem:  图片并发信号量（上限 = max_concurrent）
    - _worker_task: 后台消费协程
    """

    _MAX_HISTORY = 50  # 最多保留多少个历史批次

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ConvertItem] = asyncio.Queue()
        self._batches: dict[str, BatchJob] = {}
        self._video_sem: asyncio.Semaphore = asyncio.Semaphore(1)
        self._image_sem: asyncio.Semaphore = asyncio.Semaphore(1)
        self._image_sem_size: int = 1
        self._worker_task: Optional[asyncio.Task] = None
        self._running_item: Optional[ConvertItem] = None  # 当前正在转换的 item

    # ── 生命周期 ────────────────────────────────

    def start(self) -> None:
        """在 app lifespan 中调用，启动后台消费协程。"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("[ConvertQueue] 后台转换 worker 已启动")

    async def stop(self) -> None:
        """在 app shutdown 中调用，优雅停止 worker。"""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("[ConvertQueue] 后台转换 worker 已停止")

    # ── 提交批次 ────────────────────────────────

    def submit_batch(
        self,
        items: list[dict],       # 已过滤好的 {id, abs_path, wallpaper_type} 列表
        media_cfg: dict,
        delete_original: Optional[bool],
        output_format: Optional[str],
        timeout_override: Optional[int],
        preset: Optional[str],
    ) -> BatchJob:
        """
        将一批壁纸入队，立即返回 BatchJob（不阻塞）。
        items 中无效条目（缺路径等）已在调用方过滤，这里全部入队。
        """
        batch_id = uuid.uuid4().hex[:12]
        job = BatchJob(batch_id=batch_id, total=len(items))
        self._batches[batch_id] = job

        for idx, it in enumerate(items):
            ci = ConvertItem(
                wallpaper_id=it["id"],
                abs_path=it["abs_path"],
                wallpaper_type=it["wallpaper_type"],
                media_cfg=media_cfg,
                delete_original=delete_original,
                output_format=output_format,
                timeout_override=timeout_override,
                preset=preset,
                batch_id=batch_id,
                item_index=idx,
            )
            self._queue.put_nowait(ci)

        # 淘汰旧批次（保留最近 N 个）
        self._evict_old_batches()

        logger.info(
            "[ConvertQueue] 批次 %s 已入队 %d 个任务（队列深度=%d）",
            batch_id, len(items), self._queue.qsize(),
        )
        return job

    # ── 状态查询 ────────────────────────────────

    def get_status(self) -> dict:
        """返回队列全局状态。"""
        batches_list = [j.to_dict() for j in self._batches.values()]
        running_info = None
        if self._running_item:
            ri = self._running_item
            running_info = {
                "wallpaper_id": ri.wallpaper_id,
                "wallpaper_type": ri.wallpaper_type,
                "batch_id": ri.batch_id,
                "item_index": ri.item_index,
            }
        return {
            "queue_size": self._queue.qsize(),
            "running": running_info,
            "batch_count": len(self._batches),
            "batches": batches_list,
        }

    def get_batch(self, batch_id: str) -> Optional[BatchJob]:
        return self._batches.get(batch_id)

    # ── 后台 worker ─────────────────────────────

    async def _worker(self) -> None:
        """持续从队列取 ConvertItem 并执行转换。"""
        from backend.models.database import SessionLocal

        loop = asyncio.get_event_loop()

        while True:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                break

            job = self._batches.get(item.batch_id)
            if job is None:
                # 批次已被淘汰，丢弃
                self._queue.task_done()
                continue

            self._running_item = item
            is_video = item.wallpaper_type == "dynamic"
            sem = self._video_sem if is_video else self._image_sem_for_cfg(item.media_cfg)

            try:
                async with sem:
                    logger.info(
                        "[ConvertQueue] 开始转换 id=%d (%s) batch=%s [%d/%d]",
                        item.wallpaper_id,
                        item.wallpaper_type,
                        item.batch_id,
                        item.item_index + 1,
                        job.total,
                    )
                    result = await loop.run_in_executor(
                        None,
                        _do_convert,
                        item,
                    )

                # 写 DB
                db = SessionLocal()
                try:
                    from backend.models.wallpaper import Wallpaper
                    w = db.query(Wallpaper).filter(Wallpaper.id == item.wallpaper_id).first()
                    if w and result["status"] == "ok":
                        w.converted_path = result["converted_path"]
                        if result.get("deleted_original"):
                            w.local_path = result["converted_path"]
                        db.commit()
                except Exception as db_exc:  # noqa: BLE001
                    logger.warning("[ConvertQueue] DB 更新失败 id=%d: %s", item.wallpaper_id, db_exc)
                finally:
                    db.close()

                # 更新 BatchJob
                if result["status"] == "ok":
                    job.success += 1
                    job.items.append(result)
                    logger.info(
                        "[ConvertQueue] 转换成功 id=%d -> %s",
                        item.wallpaper_id, result.get("converted_path"),
                    )
                elif result["status"] == "skip":
                    job.skipped += 1
                    logger.info("[ConvertQueue] 跳过 id=%d: %s", item.wallpaper_id, result.get("reason", ""))
                else:
                    job.failed += 1
                    job.failed_items.append({"id": item.wallpaper_id, "reason": result.get("reason", "转换失败")})
                    logger.warning("[ConvertQueue] 转换失败 id=%d", item.wallpaper_id)

                job.done += 1

            except asyncio.CancelledError:
                job.failed += 1
                job.done += 1
                self._queue.task_done()
                raise
            except Exception as exc:  # noqa: BLE001
                job.failed += 1
                job.done += 1
                job.failed_items.append({"id": item.wallpaper_id, "reason": str(exc)})
                logger.error("[ConvertQueue] worker 异常 id=%d: %s", item.wallpaper_id, exc)
            finally:
                self._running_item = None
                self._queue.task_done()

    def _image_sem_for_cfg(self, media_cfg: dict) -> asyncio.Semaphore:
        """按 max_concurrent 动态调整图片信号量（配置变更时重建）。"""
        size = int(media_cfg.get("max_concurrent", 1))
        if self._image_sem_size != size:
            self._image_sem = asyncio.Semaphore(size)
            self._image_sem_size = size
        return self._image_sem

    def _evict_old_batches(self) -> None:
        if len(self._batches) <= self._MAX_HISTORY:
            return
        # 按 queued_at 升序淘汰最旧的
        sorted_ids = sorted(self._batches, key=lambda k: self._batches[k].queued_at)
        for bid in sorted_ids[: len(self._batches) - self._MAX_HISTORY]:
            del self._batches[bid]


# ──────────────────────────────────────────────
# 同步转换函数（在线程池中运行）
# ──────────────────────────────────────────────

def _do_convert(item: ConvertItem) -> dict[str, Any]:
    """
    实际转换逻辑，在 executor 线程中执行。
    返回 {"status": "ok"|"skip"|"fail", ...}
    """
    from backend.core.media_converter import (
        ImageConvertConfig,
        MediaConverter,
        VideoConvertConfig,
    )

    # 预设常量（与 gallery.py 保持一致）
    _PRESETS: dict[str, dict] = {
        "original": {"fps": 0, "max_width": 0, "max_frames": 0, "quality": 90},
        "standard": {"fps": 30, "max_width": 1280, "max_frames": 120, "quality": 80},
        "lite":     {"fps": 8,  "max_width": 854,  "max_frames": 30,  "quality": 65},
    }

    is_video = item.wallpaper_type == "dynamic"
    cfg_key = "video" if is_video else "image"
    cfg_dict = dict(item.media_cfg.get(cfg_key, {}))
    cfg_dict["enabled"] = True

    if item.preset and item.preset in _PRESETS and is_video:
        cfg_dict.update(_PRESETS[item.preset])
    if item.output_format is not None:
        cfg_dict["output_format"] = item.output_format
    if item.delete_original is not None:
        cfg_dict["delete_original"] = item.delete_original
    if item.timeout_override is not None:
        cfg_dict["timeout_seconds"] = item.timeout_override

    try:
        if is_video:
            mc = MediaConverter(video_config=VideoConvertConfig.from_dict(cfg_dict))
            converted_abs = mc.convert_video(item.abs_path)
        else:
            mc = MediaConverter(image_config=ImageConvertConfig.from_dict(cfg_dict))
            converted_abs = mc.convert_image(item.abs_path)
    except Exception as exc:  # noqa: BLE001
        return {"id": item.wallpaper_id, "status": "fail", "converted_path": None, "reason": str(exc)}

    if not converted_abs:
        return {"id": item.wallpaper_id, "status": "fail", "converted_path": None, "reason": "转换返回空路径"}

    from backend.core.downloader import DOWNLOAD_ROOT

    converted_rel = os.path.relpath(converted_abs, DOWNLOAD_ROOT).replace("\\", "/")
    deleted_original = False
    if cfg_dict.get("delete_original") and os.path.abspath(item.abs_path) != os.path.abspath(converted_abs):
        try:
            os.remove(item.abs_path)
            deleted_original = True
        except OSError:
            pass

    return {
        "id":               item.wallpaper_id,
        "status":           "ok",
        "converted_path":   converted_rel,
        "deleted_original": deleted_original,
    }


# ──────────────────────────────────────────────
# 全局单例（由 main.py 在 lifespan 中初始化）
# ──────────────────────────────────────────────

_convert_queue: Optional[ConvertQueue] = None


def get_convert_queue() -> ConvertQueue:
    global _convert_queue
    if _convert_queue is None:
        raise RuntimeError("ConvertQueue 尚未初始化，请在 lifespan 中调用 init_convert_queue()")
    return _convert_queue


def init_convert_queue() -> ConvertQueue:
    global _convert_queue
    _convert_queue = ConvertQueue()
    return _convert_queue
