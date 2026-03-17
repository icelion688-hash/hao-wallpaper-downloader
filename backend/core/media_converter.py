"""
core/media_converter.py — 媒体格式转换（性能自适应）

视频（MP4）→ 动态 WebP / GIF：使用 imageio + imageio-ffmpeg
  imageio-ffmpeg 是 pip 包，内含预编译 ffmpeg 二进制，无需系统安装。

静态图（PNG/JPG）→ WebP / JPG / PNG：使用 Pillow（已在 requirements.txt）

性能保护机制：
  1. 内存自适应  —— 读取第一帧后估算内存占用，自动压缩 max_frames 和 max_width
  2. CPU 降权    —— os.nice(cpu_nice) 让转换在后台低优先级运行，不抢占前台任务
  3. 超时保护    —— threading.Timer 触发 cancel_event，帧循环主动检测并退出
  4. 帧间让步    —— 每帧处理后 time.sleep(0) 释放 GIL，保证网络线程正常响应
  5. 磁盘预检    —— 保存前检查剩余磁盘空间
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, fields as dc_fields
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# 磁盘空间预警阈值（转换输出预留）
_MIN_FREE_DISK_MB = 200


# ──────────────────────────────────────────────────────────
#  系统资源探测（无额外依赖）
# ──────────────────────────────────────────────────────────

def _get_available_memory_mb() -> int:
    """
    获取当前可用内存（MB）。
    优先读 /proc/meminfo（Linux），不可用时返回保守估计值 512。
    """
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024  # kB → MB
    except OSError:
        pass
    # 备用：尝试 psutil（可选依赖）
    try:
        import psutil  # noqa: import-outside-toplevel
        return psutil.virtual_memory().available // (1024 * 1024)
    except ImportError:
        pass
    return 512  # 保守默认值


def _get_free_disk_mb(path: str) -> int:
    """获取指定路径所在分区的剩余磁盘空间（MB）"""
    try:
        import shutil
        return shutil.disk_usage(path).free // (1024 * 1024)
    except OSError:
        return 9999


def _get_cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def _set_low_priority(nice: int) -> None:
    """降低当前线程/进程的 CPU 调度优先级（仅 Linux/Unix）"""
    if nice <= 0:
        return
    try:
        os.nice(nice)
    except (OSError, AttributeError):
        pass  # Windows 无 os.nice，忽略


# ──────────────────────────────────────────────────────────
#  配置数据类
# ──────────────────────────────────────────────────────────

@dataclass
class VideoConvertConfig:
    """MP4 → 动态 WebP / GIF 配置"""
    enabled: bool = False
    output_format: str = "webp"     # "webp" | "gif"
    fps: int = 10                    # 输出帧率（降帧节省体积）
    max_frames: int = 120            # 最多提取帧数（会被内存自适应进一步限制）
    width: int = 0                   # 目标宽度（0 = 使用 max_width 自动裁剪）
    max_width: int = 1280            # 帧宽上限（防止 4K 帧耗尽内存）；0 = 不限
    quality: int = 80                # WebP 质量（1-100）
    delete_original: bool = False    # 转换完成后删除原 MP4
    timeout_seconds: int = 300       # 单文件最长转换时间；超时自动取消
    cpu_nice: int = 5                # Linux CPU 优先级降级量（0=不降，19=最低）

    @classmethod
    def from_dict(cls, d: dict) -> "VideoConvertConfig":
        valid = {f.name for f in dc_fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid and v is not None})


@dataclass
class ImageConvertConfig:
    """静态图 PNG/JPG → WebP / JPG / PNG 配置"""
    enabled: bool = False
    output_format: str = "webp"     # "webp" | "jpg" | "png"
    quality: int = 85                # JPEG / WebP 质量（1-100）
    delete_original: bool = False    # 转换完成后删除原文件
    timeout_seconds: int = 120       # 单文件最长转换时间
    cpu_nice: int = 5                # CPU 优先级降级

    @classmethod
    def from_dict(cls, d: dict) -> "ImageConvertConfig":
        valid = {f.name for f in dc_fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid and v is not None})


# ──────────────────────────────────────────────────────────
#  超时上下文管理器
# ──────────────────────────────────────────────────────────

class _ConvertTimeout:
    """
    基于 threading.Timer 的软超时：到时间后设置 cancel_event，
    帧循环主动检测并提前退出，不强杀线程（Python 无法安全强杀线程）。
    """
    def __init__(self, seconds: int):
        self.seconds = seconds
        self.cancel_event = threading.Event()
        self._timer: Optional[threading.Timer] = None

    def __enter__(self) -> threading.Event:
        if self.seconds > 0:
            self._timer = threading.Timer(self.seconds, self.cancel_event.set)
            self._timer.daemon = True
            self._timer.start()
        return self.cancel_event

    def __exit__(self, *_):
        if self._timer:
            self._timer.cancel()

    @property
    def timed_out(self) -> bool:
        return self.cancel_event.is_set()


# ──────────────────────────────────────────────────────────
#  转换器
# ──────────────────────────────────────────────────────────

class MediaConverter:
    """
    媒体格式转换器（性能自适应）。

    所有转换方法均设计为在线程池（run_in_executor）中执行，不会阻塞事件循环。
    """

    def __init__(
        self,
        video_config: Optional[VideoConvertConfig] = None,
        image_config: Optional[ImageConvertConfig] = None,
    ):
        self.video_cfg = video_config or VideoConvertConfig()
        self.image_cfg = image_config or ImageConvertConfig()

    # ── 视频 → 动态 WebP / GIF ────────────────────────────

    def convert_video(self, src_path: str, dst_path: Optional[str] = None) -> Optional[str]:
        """
        MP4 → 动态 WebP 或 GIF。

        性能保护：
        - CPU 降权运行（os.nice）
        - 帧宽硬上限（max_width），4K → 1280px 可将单帧内存从 24MB 降至 2.8MB
        - 首帧探测后自动调整 max_frames（可用内存的 40%）
        - timeout_seconds 超时软取消
        - 每帧后 sleep(0) 让出 GIL，网络线程不饿死
        """
        cfg = self.video_cfg
        if not cfg.enabled:
            return None
        if not os.path.isfile(src_path):
            logger.warning("[Converter] 源文件不存在: %s", src_path)
            return None

        try:
            import imageio  # noqa: import-outside-toplevel
        except ImportError:
            logger.warning("[Converter] imageio 未安装（pip install imageio imageio-ffmpeg）")
            return None

        _set_low_priority(cfg.cpu_nice)

        out_ext = "gif" if cfg.output_format == "gif" else "webp"
        if dst_path is None:
            dst_path = os.path.splitext(src_path)[0] + f".{out_ext}"

        # 磁盘预检
        free_mb = _get_free_disk_mb(os.path.dirname(os.path.abspath(dst_path)))
        if free_mb < _MIN_FREE_DISK_MB:
            logger.warning("[Converter] 磁盘空间不足 (%d MB 可用)，跳过: %s", free_mb, src_path)
            return None

        try:
            reader = imageio.get_reader(src_path, "ffmpeg")
        except Exception as exc:
            logger.warning("[Converter] 打开视频失败: %s — %s", src_path, exc)
            return None

        frames_pil: list[Image.Image] = []
        actual_max_frames = cfg.max_frames

        try:
            meta = reader.get_meta_data()
            src_fps = float(meta.get("fps") or 30)

            # 步长：源帧率 / 目标帧率，确保均匀采样
            step = max(1, round(src_fps / max(cfg.fps, 1)))

            # 若已知总帧数则进一步加大步长，防止超过 max_frames
            try:
                n_total = reader.count_frames()
                if n_total and n_total > 0:
                    step = max(step, n_total // cfg.max_frames)
            except Exception:
                pass

            with _ConvertTimeout(cfg.timeout_seconds) as cancel_ev:
                for frame_idx, frame_np in enumerate(reader):
                    # ── 超时/取消检测 ──────────────────────
                    if cancel_ev.is_set():
                        logger.warning(
                            "[Converter] 超时 (%ds) 已取消: %s（已采集 %d 帧）",
                            cfg.timeout_seconds, os.path.basename(src_path), len(frames_pil),
                        )
                        break

                    if frame_idx % step != 0:
                        time.sleep(0)  # 帧间让步：释放 GIL
                        continue

                    if len(frames_pil) >= actual_max_frames:
                        break

                    # ── 首帧：探测内存，自适应 max_frames ──
                    if len(frames_pil) == 0:
                        h, w, c = frame_np.shape
                        # 应用宽度限制（优先 width 配置，其次 max_width 上限）
                        target_w = cfg.width or (
                            min(w, cfg.max_width) if cfg.max_width else w
                        )
                        bytes_per_frame = (target_w * int(h * target_w / max(w, 1)) * 4)  # RGBA 估算
                        avail_mb = _get_available_memory_mb()
                        budget_mb = max(64, avail_mb * 40 // 100)  # 用可用内存的 40%
                        mem_limit_frames = max(10, budget_mb * 1024 * 1024 // max(bytes_per_frame, 1))
                        actual_max_frames = min(cfg.max_frames, mem_limit_frames)
                        if actual_max_frames < cfg.max_frames:
                            logger.info(
                                "[Converter] 内存自适应: 可用 %dMB，每帧 ~%.1fMB，"
                                "max_frames %d→%d（宽 %d→%dpx）",
                                avail_mb, bytes_per_frame / (1024 * 1024),
                                cfg.max_frames, actual_max_frames, w, target_w,
                            )

                    # ── 帧处理：缩放到目标宽度 ──────────────
                    img = Image.fromarray(frame_np)
                    target_w = cfg.width or (
                        min(img.width, cfg.max_width) if cfg.max_width else img.width
                    )
                    if target_w and target_w < img.width:
                        new_h = int(img.height * target_w / img.width)
                        img = img.resize((target_w, new_h), Image.LANCZOS)

                    frames_pil.append(img)
                    time.sleep(0)  # 帧间 GIL 让步
        finally:
            reader.close()

        if not frames_pil:
            logger.warning("[Converter] 无帧可提取（可能超时）: %s", src_path)
            return None

        # ── 保存输出文件 ──────────────────────────────────
        frame_ms = max(1, int(1000 / max(cfg.fps, 1)))
        try:
            if out_ext == "gif":
                frames_pil[0].save(
                    dst_path, save_all=True, append_images=frames_pil[1:],
                    loop=0, duration=frame_ms, optimize=False,
                )
            else:  # webp
                frames_pil[0].save(
                    dst_path, format="WEBP", save_all=True,
                    append_images=frames_pil[1:],
                    loop=0, duration=frame_ms,
                    quality=cfg.quality, method=4,
                )
            size_mb = os.path.getsize(dst_path) / (1024 * 1024)
            logger.info(
                "[Converter] 视频→%s 完成: %s (%d 帧, %.1f MB)",
                out_ext.upper(), os.path.basename(dst_path), len(frames_pil), size_mb,
            )
            return dst_path
        except Exception as exc:
            logger.error("[Converter] 保存动态图失败: %s — %s", dst_path, exc)
            if os.path.exists(dst_path):
                try:
                    os.remove(dst_path)
                except OSError:
                    pass
            return None
        finally:
            # 主动释放帧列表内存
            frames_pil.clear()

    # ── 静态图格式转换 ─────────────────────────────────────

    def convert_image(self, src_path: str, dst_path: Optional[str] = None) -> Optional[str]:
        """
        PNG / JPEG → WebP / JPG / PNG。

        性能保护：
        - CPU 降权
        - timeout_seconds 超时（通过 threading.Timer 发出警告）
        - 超大图（>50MP）自动裁剪提示
        """
        cfg = self.image_cfg
        if not cfg.enabled:
            return None
        if not os.path.isfile(src_path):
            logger.warning("[Converter] 源文件不存在: %s", src_path)
            return None

        _set_low_priority(cfg.cpu_nice)

        fmt_map = {"webp": "webp", "jpg": "jpg", "jpeg": "jpg", "png": "png"}
        out_ext = fmt_map.get(cfg.output_format.lower(), "webp")

        if dst_path is None:
            dst_path = os.path.splitext(src_path)[0] + f".{out_ext}"

        if os.path.abspath(src_path) == os.path.abspath(dst_path):
            logger.debug("[Converter] 源与目标格式相同，跳过: %s", src_path)
            return None

        # 磁盘预检
        free_mb = _get_free_disk_mb(os.path.dirname(os.path.abspath(dst_path)))
        if free_mb < _MIN_FREE_DISK_MB:
            logger.warning("[Converter] 磁盘空间不足 (%d MB)，跳过: %s", free_mb, src_path)
            return None

        with _ConvertTimeout(cfg.timeout_seconds) as cancel_ev:
            try:
                with Image.open(src_path) as img:
                    if cancel_ev.is_set():
                        logger.warning("[Converter] 超时，跳过图片: %s", src_path)
                        return None

                    # 超大图警告（50 Mpx 以上，Pillow 会非常慢）
                    mpx = (img.width * img.height) / 1_000_000
                    if mpx > 50:
                        logger.warning(
                            "[Converter] 超大图 (%.0fMP)，转换可能较慢: %s", mpx, src_path
                        )

                    if out_ext == "jpg":
                        img = img.convert("RGB")
                        img.save(dst_path, format="JPEG", quality=cfg.quality, optimize=True)
                    elif out_ext == "webp":
                        if img.mode in ("RGBA", "LA", "PA"):
                            img.save(dst_path, format="WEBP", quality=cfg.quality, method=4)
                        else:
                            img.convert("RGB").save(
                                dst_path, format="WEBP", quality=cfg.quality, method=4
                            )
                    else:  # png
                        img.save(dst_path, format="PNG", optimize=True)

                if cancel_ev.is_set():
                    # 转换已完成但超时了——结果仍有效，正常返回
                    logger.debug("[Converter] 图片转换完成（超时警告已忽略）: %s", src_path)

                size_mb = os.path.getsize(dst_path) / (1024 * 1024)
                logger.info(
                    "[Converter] 图片→%s 完成: %s (%.1f MB)",
                    out_ext.upper(), os.path.basename(dst_path), size_mb,
                )
                return dst_path

            except Exception as exc:
                logger.error("[Converter] 图片转换失败: %s — %s", src_path, exc)
                if os.path.exists(dst_path):
                    try:
                        os.remove(dst_path)
                    except OSError:
                        pass
                return None

    # ── 视频时长（imageio 替代 ffprobe）──────────────────

    def get_video_duration(self, src_path: str) -> Optional[float]:
        """
        用 imageio-ffmpeg 提取视频时长（秒）。
        作为 ffprobe 的备用方案；imageio-ffmpeg 未安装时返回 None。
        """
        try:
            import imageio  # noqa: import-outside-toplevel
            reader = imageio.get_reader(src_path, "ffmpeg")
            meta = reader.get_meta_data()
            reader.close()
            dur = meta.get("duration")
            if dur:
                return round(float(dur), 2)
        except Exception:
            pass
        return None

    # ── 系统资源报告（前端展示用）─────────────────────────

    @staticmethod
    def system_info() -> dict:
        """返回当前机器资源概览，供前端展示和自动配置建议使用"""
        available_mb = _get_available_memory_mb()
        cpu_count = _get_cpu_count()

        # 根据可用内存推荐配置
        if available_mb >= 4096:
            tier = "high"
            recommend = {"max_frames": 120, "max_width": 1920, "fps": 15}
        elif available_mb >= 1024:
            tier = "mid"
            recommend = {"max_frames": 60, "max_width": 1280, "fps": 10}
        else:
            tier = "low"
            recommend = {"max_frames": 30, "max_width": 854, "fps": 8}

        return {
            "available_memory_mb": available_mb,
            "cpu_count": cpu_count,
            "tier": tier,           # "high" | "mid" | "low"
            "recommend": recommend,  # 建议配置
        }
