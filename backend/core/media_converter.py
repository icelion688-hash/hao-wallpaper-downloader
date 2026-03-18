"""
core/media_converter.py — 媒体格式转换（流式编码，系统安全优先）

视频（MP4）→ 动态 WebP：使用 pywebp（libwebp AnimEncoder）真正流式逐帧编码
  每帧编码压缩后立即释放原始像素，内存占用恒定 ≈ 1帧原始 + 压缩流。
  imageio-ffmpeg 负责解码输入视频，pywebp 负责编码输出动态 WebP。

视频（MP4）→ GIF：使用 imageio + Pillow，帧数受内存预算严格限制。

静态图（PNG/JPG）→ WebP / JPG / PNG：使用 Pillow。

安全机制（系统稳定第一优先）：
  1. 启动前检查  —— 可用内存 < 512 MB 时拒绝启动（无 swap 机器保护线）
  2. 实时监控    —— 每 10 帧检查一次内存，< 300 MB 立即中止，防止 OOM 卡死
  3. 磁盘预检    —— 输出目录剩余 < 200 MB 时跳过
  4. CPU 降权    —— os.nice(cpu_nice) 后台低优先级，不抢占网络响应
  5. 超时软取消  —— threading.Timer 触发，帧循环主动检测并退出
  6. GIL 让步    —— 每帧 sleep(0) 保证网络线程不饿死
"""

from __future__ import annotations

import gc
import logging
import os
import threading
import time
from dataclasses import dataclass, fields as dc_fields
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# 安全阈值
_MIN_FREE_DISK_MB  = 200   # 磁盘剩余低于此值时拒绝写出
_MIN_START_RAM_MB  = 512   # 启动前可用内存必须 ≥ 此值（无 swap 保护）
_MIN_RUNTIME_RAM_MB = 300  # 运行中低于此值立即中止（防 OOM 卡死）


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


def _estimate_cpu_guard_ms(
    cpu_nice: int,
    cpu_count: int,
    pixel_count: int,
    unlimited: bool,
) -> float:
    """
    估算每帧需要额外让出的 CPU 时间（毫秒）。

    目标不是把编码“变慢”，而是在低核 / 高分辨率 / 全帧模式下
    主动给系统交出时间片，降低机器卡死风险。
    """
    guard_ms = 0.0
    if cpu_nice > 0:
        guard_ms += min(12.0, cpu_nice * 0.7)
    if cpu_count <= 4:
        guard_ms += 8.0
    elif cpu_count <= 8:
        guard_ms += 4.0
    if pixel_count >= 3840 * 2160:
        guard_ms += 6.0
    elif pixel_count >= 1920 * 1080:
        guard_ms += 3.0
    if unlimited:
        guard_ms += 2.0
    return guard_ms


def is_webp_available() -> bool:
    """返回当前环境是否可用 pywebp 动态 WebP 编码依赖。"""
    try:
        import webp  # noqa: F401, import-outside-toplevel
        return True
    except ImportError:
        return False


def _set_low_priority(nice: int) -> None:
    """降低当前进程的 CPU 调度优先级，兼容 Linux / Windows。"""
    if nice <= 0:
        return
    applied = False
    try:
        if os.name != "nt":
            os.nice(nice)
            applied = True
    except (OSError, AttributeError):
        pass
    try:
        import psutil  # noqa: import-outside-toplevel
        proc = psutil.Process()
        if os.name == "nt":
            priority = (
                psutil.IDLE_PRIORITY_CLASS
                if nice >= 10 else
                psutil.BELOW_NORMAL_PRIORITY_CLASS
            )
            proc.nice(priority)
        elif not applied:
            proc.nice(min(19, max(0, nice)))
    except Exception:
        pass


class _CpuGuard:
    """在逐帧编码期间主动让出 CPU，优先保护低配机器可用性。"""

    def __init__(self, cpu_nice: int, pixel_count: int, unlimited: bool):
        self.cpu_nice = max(0, int(cpu_nice or 0))
        self.cpu_count = _get_cpu_count()
        self._base_sleep_ms = _estimate_cpu_guard_ms(
            cpu_nice=self.cpu_nice,
            cpu_count=self.cpu_count,
            pixel_count=max(0, pixel_count),
            unlimited=unlimited,
        )
        self._dynamic_sleep_ms = 0.0
        self._proc = None
        self._psutil = None
        try:
            import psutil  # noqa: import-outside-toplevel
            self._psutil = psutil
            self._proc = psutil.Process()
            self._proc.cpu_percent(None)
            psutil.cpu_percent(None)
        except Exception:
            self._proc = None
            self._psutil = None

    def pause(self, frame_count: int) -> None:
        sleep_ms = self._base_sleep_ms
        if self._proc and self._psutil and frame_count % 12 == 0:
            try:
                system_cpu = self._psutil.cpu_percent(None)
                process_cpu = self._proc.cpu_percent(None)
                dynamic_sleep_ms = 0.0
                if system_cpu >= 92:
                    dynamic_sleep_ms += 18.0
                elif system_cpu >= 85:
                    dynamic_sleep_ms += 10.0
                elif system_cpu >= 75:
                    dynamic_sleep_ms += 4.0
                if self.cpu_count <= 4 and process_cpu >= 90:
                    dynamic_sleep_ms += 8.0
                elif self.cpu_count <= 8 and process_cpu >= 90:
                    dynamic_sleep_ms += 4.0
                self._dynamic_sleep_ms = dynamic_sleep_ms
            except Exception:
                self._dynamic_sleep_ms = 0.0
        sleep_ms += self._dynamic_sleep_ms
        if sleep_ms > 0:
            time.sleep(min(0.04, sleep_ms / 1000.0))
        else:
            time.sleep(0)


def _ceil_div(numerator: int, denominator: int) -> int:
    """正整数向上整除；用于在帧数受限时覆盖完整时间轴。"""
    if denominator <= 0:
        return max(1, numerator)
    return max(1, (numerator + denominator - 1) // denominator)


def _source_frame_timestamp_ms(frame_idx: int, src_fps: float) -> int:
    """把源视频帧序号映射到毫秒时间轴。"""
    return max(0, round(frame_idx * 1000.0 / max(src_fps, 0.1)))


def _source_duration_ms(total_frames: Optional[int], src_fps: float) -> Optional[int]:
    """根据总帧数和源帧率估算源视频总时长。"""
    if not total_frames or total_frames <= 0:
        return None
    return max(1, round(total_frames * 1000.0 / max(src_fps, 0.1)))


def _build_frame_durations_ms(
    frame_timestamps_ms: list[int],
    final_timestamp_ms: Optional[int],
    fallback_frame_dur_ms: int,
) -> list[int]:
    """
    将帧起始时间戳转换成 GIF/Pillow 所需的逐帧 duration 列表。
    最后一帧优先对齐源视频总时长；未知时长时退回固定帧长。
    """
    if not frame_timestamps_ms:
        return []

    last_frame_ts = frame_timestamps_ms[-1]
    safe_final_ts = max(
        last_frame_ts + 1,
        final_timestamp_ms if final_timestamp_ms is not None else last_frame_ts + fallback_frame_dur_ms,
    )

    durations_ms: list[int] = []
    for index, frame_ts in enumerate(frame_timestamps_ms):
        next_ts = frame_timestamps_ms[index + 1] if index + 1 < len(frame_timestamps_ms) else safe_final_ts
        durations_ms.append(max(1, next_ts - frame_ts))
    return durations_ms


def _select_frame_step(
    src_fps: float,
    target_fps: int,
    total_frames: Optional[int],
    max_frames: int,
    unlimited: bool,
) -> int:
    """
    计算抽帧步长。

    1. 先满足目标输出帧率。
    2. 若存在帧数上限，再用向上整除保证采样能覆盖完整源时间轴，
       避免输出只保留前半段、导致成品时长变短。
    """
    target_step = 1 if target_fps == 0 else max(1, round(src_fps / max(float(target_fps), 0.1)))
    if unlimited or not total_frames or total_frames <= 0 or max_frames <= 0:
        return target_step
    return max(target_step, _ceil_div(total_frames, max_frames))


# ──────────────────────────────────────────────────────────
#  配置数据类
# ──────────────────────────────────────────────────────────

@dataclass
class VideoConvertConfig:
    """
    MP4 → 动态 WebP / GIF 配置

    三种内置预设（通过 fps/max_width/max_frames 组合）：
      原图模式：fps=0（保留源帧率）, max_width=0（不缩放）, max_frames=0（全帧）
      标准模式：fps=30, max_width=1280, max_frames=120
      低配模式：fps=8,  max_width=854,  max_frames=30,  quality=65
    """
    enabled: bool = False
    output_format: str = "webp"     # "webp" | "gif"
    fps: int = 0                     # 输出帧率；0 = 保留源帧率（原图模式）
    max_frames: int = 0              # 最多提取帧数；0 = 不限（原图模式全帧转换）
    width: int = 0                   # 目标宽度（0 = 使用 max_width 自动裁剪）
    max_width: int = 0               # 帧宽上限；0 = 不缩放（原图模式）
    quality: int = 100               # WebP 质量（1-100）
    delete_original: bool = False    # 转换完成后删除原 MP4
    timeout_seconds: int = 300       # 单文件最长转换时间；超时已写帧仍保留
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
    quality: int = 100               # JPEG / WebP 质量（1-100）
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
        MP4 → 动态 WebP（pywebp 真流式）或 GIF（Pillow 帧限制）。

        WebP 路径（pywebp AnimEncoder）：
          逐帧编码压缩，每帧处理后立即释放原始像素。
          峰值内存 ≈ 1帧原始（24-100MB@4K）+ 压缩流（几十MB）。
          适合所有模式，尤其原图模式（fps=0, max_width=0, max_frames=0）。

        GIF 路径（Pillow save_all，受内存预算限制）：
          帧数严格按可用内存计算上限，不允许溢出。

        安全保护（机器稳定第一）：
          - 启动前：可用内存 < 512 MB 时拒绝启动
          - 运行中：每 10 帧检查内存，< 300 MB 立即中止
          - 磁盘：剩余 < 200 MB 时跳过
          - 超时：timeout_seconds 到期软取消，已写帧保留
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

        # ── 磁盘预检 ──────────────────────────────────────────────────
        free_mb = _get_free_disk_mb(os.path.dirname(os.path.abspath(dst_path)))
        if free_mb < _MIN_FREE_DISK_MB:
            logger.warning("[Converter] 磁盘空间不足 (%d MB 可用)，跳过: %s", free_mb, src_path)
            return None

        # ── 启动前内存检查（无 swap 机器的关键保护）──────────────────
        gc.collect()
        avail_mb_pre = _get_available_memory_mb()
        if avail_mb_pre < _MIN_START_RAM_MB:
            logger.warning(
                "[Converter] 可用内存不足（%d MB < %d MB 安全线），跳过: %s",
                avail_mb_pre, _MIN_START_RAM_MB, src_path,
            )
            return None

        try:
            reader = imageio.get_reader(src_path, "ffmpeg")
        except Exception as exc:
            logger.warning("[Converter] 打开视频失败: %s — %s", src_path, exc)
            return None

        try:
            meta      = reader.get_meta_data()
            src_fps   = float(meta.get("fps") or 30)
            src_size  = meta.get("size")
            src_w, src_h = src_size if src_size else (3840, 2160)

            # max_width=0 → 不缩放（原图模式）
            target_w = cfg.width or (min(src_w, cfg.max_width) if cfg.max_width else src_w)
            target_h = int(src_h * target_w / max(src_w, 1))

            # max_frames=0 → 全帧（原图模式）
            unlimited  = cfg.max_frames == 0
            actual_max = cfg.max_frames if not unlimited else 10_000_000

            # GIF 模式：帧数必须受内存预算约束（Pillow save_all 需缓冲全部帧）
            if out_ext == "gif" and not unlimited:
                bytes_per_frame = target_w * target_h * 1  # GIF 调色板 1 字节/像素
                encode_overhead = 2.0
                usable_bytes = max(32 << 20, (avail_mb_pre - 256) * 20 // 100 << 20)
                mem_limit = max(10, int(usable_bytes / (bytes_per_frame * encode_overhead)))
                if mem_limit < actual_max:
                    logger.info("[Converter] GIF 内存限制: %d → %d 帧", actual_max, mem_limit)
                    actual_max = mem_limit

            n_total: Optional[int] = None
            try:
                counted_frames = reader.count_frames()
                if counted_frames and counted_frames > 0:
                    n_total = counted_frames
            except Exception:
                pass

            step = _select_frame_step(src_fps, cfg.fps, n_total, actual_max, unlimited)
            source_duration_ms = _source_duration_ms(n_total, src_fps)

            # ── 每帧显示时长：必须基于 step（而非 out_fps），否则跳帧时播速加倍 ──
            # 原理：step=N 意味着每编码 1 帧跳过了源视频的 N 个原始帧，
            #       每帧应显示的时长 = N × (1000ms / src_fps)
            # 示例：src=30fps, step=2 → frame_dur=66ms（15fps播放，覆盖正确时长）
            frame_dur_ms = max(1, round(step * 1000.0 / max(src_fps, 0.1)))
            # 实际输出帧率（用于日志）
            actual_out_fps = 1000.0 / frame_dur_ms

            mode_tag = (
                "原图" if (cfg.fps == 0 and not cfg.max_width and unlimited)
                else "低配" if cfg.fps <= 10 and (cfg.max_width or 9999) <= 1024
                else "标准"
            )
            logger.info(
                "[Converter] %s 转换: %s → %s (%.0ffps→%.1ffps, "
                "%dx%d→%dx%d, step=%d, frame_dur=%dms%s, 可用内存=%dMB)",
                mode_tag, os.path.basename(src_path), out_ext.upper(),
                src_fps, actual_out_fps, src_w, src_h, target_w, target_h, step,
                frame_dur_ms,
                "" if unlimited else f", max={actual_max}帧",
                avail_mb_pre,
            )

            # ── WebP：pywebp 真流式路径 ───────────────────────────────
            if out_ext == "webp":
                return self._encode_webp_streaming(
                    reader, cfg, dst_path,
                    frame_dur_ms, step, src_fps, source_duration_ms, target_w, target_h,
                    actual_max, unlimited,
                )

            # ── GIF：Pillow 帧缓冲路径（已受内存预算限制）──────────────
            return self._encode_gif_buffered(
                reader, cfg, dst_path,
                frame_dur_ms, step, src_fps, source_duration_ms, target_w, target_h,
                actual_max, unlimited,
            )

        finally:
            reader.close()
            gc.collect()

    def _resize_frame(self, frame_np: np.ndarray, target_w: int, cfg_width: int, cfg_max_width: int) -> np.ndarray:
        """按需缩放帧；原图模式（max_width=0）直接返回原帧"""
        h_cur, w_cur = frame_np.shape[:2]
        tw = cfg_width or (min(w_cur, cfg_max_width) if cfg_max_width else w_cur)
        if tw and tw < w_cur:
            new_h = int(h_cur * tw / w_cur)
            tmp = Image.fromarray(frame_np).resize((tw, new_h), Image.LANCZOS)
            frame_np = np.asarray(tmp).copy()
            tmp.close()
        return frame_np

    def _encode_webp_streaming(
        self,
        reader,
        cfg: "VideoConvertConfig",
        dst_path: str,
        frame_dur_ms: int,
        step: int,
        src_fps: float,
        source_duration_ms: Optional[int],
        target_w: int,
        target_h: int,
        actual_max: int,
        unlimited: bool,
    ) -> Optional[str]:
        """
        用 pywebp AnimEncoder 真流式编码动态 WebP。

        原理：每帧经 libwebp 压缩后以 ~几十KB 存入编码器的内部链表，
        原始像素（数十 MB）立即释放。峰值内存恒定 ≈ 1帧原始 + 压缩流累积量。

        frame_dur_ms 为未知总时长时的兜底帧长；正常情况下直接沿用源视频时间轴。
        """
        try:
            import webp as _webp  # noqa: import-outside-toplevel
        except ImportError:
            logger.error("[Converter] pywebp 未安装（pip install webp），WebP 转换不可用")
            return None

        try:
            enc_opts = _webp.WebPAnimEncoderOptions.new()
            enc = _webp.WebPAnimEncoder.new(target_w, target_h, enc_opts)
            webp_cfg = _webp.WebPConfig.new(quality=float(cfg.quality))
        except Exception as exc:
            logger.error("[Converter] 初始化 WebP 编码器失败: %s", exc)
            return None

        frame_count = 0
        aborted     = False
        covered_full_duration = False
        last_frame_ts_ms: Optional[int] = None
        cpu_guard = _CpuGuard(cfg.cpu_nice, target_w * target_h, unlimited)

        # 原图模式（unlimited=全帧）不设超时，保证完整转换
        # 标准/低配模式使用 cfg.timeout_seconds 保护服务器
        effective_timeout = 0 if unlimited else cfg.timeout_seconds

        try:
            with _ConvertTimeout(effective_timeout) as cancel_ev:
                for frame_idx, frame_np in enumerate(reader):
                    # ── 超时检测 ──────────────────────────────────────
                    if cancel_ev.is_set():
                        logger.warning(
                            "[Converter] 超时 (%ds) 停止: %s（已编码 %d 帧）",
                            effective_timeout, os.path.basename(dst_path), frame_count,
                        )
                        break

                    # ── 实时内存监控：每 10 帧检查一次 ────────────────
                    if frame_count % 10 == 0:
                        avail_now = _get_available_memory_mb()
                        if avail_now < _MIN_RUNTIME_RAM_MB:
                            logger.error(
                                "[Converter] 系统内存告警！剩余 %dMB < %dMB 安全线，"
                                "紧急中止（已编码 %d 帧）: %s",
                                avail_now, _MIN_RUNTIME_RAM_MB, frame_count,
                                os.path.basename(dst_path),
                            )
                            aborted = True
                            break

                    if frame_idx % step != 0:
                        time.sleep(0)
                        continue

                    if not unlimited and frame_count >= actual_max:
                        covered_full_duration = source_duration_ms is not None
                        break

                    # ── 缩放 ──────────────────────────────────────────
                    frame_np = self._resize_frame(frame_np, target_w, cfg.width, cfg.max_width)
                    frame_ts_ms = _source_frame_timestamp_ms(frame_idx, src_fps)

                    # ── 编码（原始像素离开此作用域后被 GC 释放）────────
                    try:
                        pic = _webp.WebPPicture.from_numpy(frame_np)
                        enc.encode_frame(pic, frame_ts_ms, webp_cfg)
                    except Exception as exc:
                        logger.warning("[Converter] 第 %d 帧编码失败，跳过: %s", frame_idx, exc)
                        cpu_guard.pause(frame_count)
                        continue

                    last_frame_ts_ms = frame_ts_ms
                    frame_count += 1
                    del frame_np  # 显式释放原始像素
                    cpu_guard.pause(frame_count)
                else:
                    covered_full_duration = True

        except MemoryError:
            logger.error("[Converter] OOM 停止（已编码 %d 帧）: %s", frame_count, dst_path)
            aborted = True
        except Exception as exc:
            logger.error("[Converter] 编码异常: %s — %s", dst_path, exc)
            aborted = True

        if frame_count == 0:
            logger.warning("[Converter] 无帧可编码: %s", dst_path)
            return None

        final_ts_ms = (
            source_duration_ms
            if covered_full_duration and source_duration_ms is not None
            else (last_frame_ts_ms or 0) + frame_dur_ms
        )
        final_ts_ms = max((last_frame_ts_ms or 0) + 1, final_ts_ms)

        # ── 组装并写出文件（仅含压缩流，内存开销极小）────────────────
        try:
            data = enc.assemble(final_ts_ms)
            buf  = data.buffer()
            with open(dst_path, "wb") as fout:
                fout.write(buf)
        except Exception as exc:
            logger.error("[Converter] 写出 WebP 失败: %s — %s", dst_path, exc)
            if os.path.exists(dst_path):
                try:
                    os.remove(dst_path)
                except OSError:
                    pass
            return None

        size_mb = os.path.getsize(dst_path) / (1024 * 1024)
        logger.info(
            "[Converter] 视频→WEBP 完成%s: %s (%d 帧, %.1f MB)",
            "（提前结束）" if aborted else "",
            os.path.basename(dst_path), frame_count, size_mb,
        )
        return dst_path

    def _encode_gif_buffered(
        self,
        reader,
        cfg: "VideoConvertConfig",
        dst_path: str,
        frame_dur_ms: int,
        step: int,
        src_fps: float,
        source_duration_ms: Optional[int],
        target_w: int,
        target_h: int,
        actual_max: int,
        unlimited: bool,
    ) -> Optional[str]:
        """
        GIF 编码（Pillow save_all），帧数已被内存预算限制。
        GIF 每帧调色板 1 字节/像素，相比 RGB 节省 3x，但仍需全部缓冲。

        frame_dur_ms 为未知总时长时的兜底帧长；正常情况下直接沿用源视频时间轴。
        """
        frames_pil: list[Image.Image] = []
        frame_timestamps_ms: list[int] = []
        aborted = False
        covered_full_duration = False
        effective_timeout = 0 if unlimited else cfg.timeout_seconds
        cpu_guard = _CpuGuard(cfg.cpu_nice, target_w * target_h, unlimited)

        try:
            with _ConvertTimeout(effective_timeout) as cancel_ev:
                for frame_idx, frame_np in enumerate(reader):
                    if cancel_ev.is_set():
                        logger.warning(
                            "[Converter] 超时 (%ds) 停止 GIF: %s（已采集 %d 帧）",
                            effective_timeout, os.path.basename(dst_path), len(frames_pil),
                        )
                        break

                    # 实时内存检查
                    if len(frames_pil) % 10 == 0:
                        avail_now = _get_available_memory_mb()
                        if avail_now < _MIN_RUNTIME_RAM_MB:
                            logger.error(
                                "[Converter] 内存告警，中止 GIF（已采集 %d 帧）: %s",
                                len(frames_pil), os.path.basename(dst_path),
                            )
                            aborted = True
                            break

                    if frame_idx % step != 0:
                        time.sleep(0)
                        continue

                    if not unlimited and len(frames_pil) >= actual_max:
                        covered_full_duration = source_duration_ms is not None
                        break

                    frame_np = self._resize_frame(frame_np, target_w, cfg.width, cfg.max_width)
                    frames_pil.append(Image.fromarray(frame_np).convert("P", palette=Image.ADAPTIVE))
                    frame_timestamps_ms.append(_source_frame_timestamp_ms(frame_idx, src_fps))
                    del frame_np
                    cpu_guard.pause(len(frames_pil))
                else:
                    covered_full_duration = True

        except MemoryError:
            logger.error("[Converter] OOM 停止 GIF（已采集 %d 帧）: %s", len(frames_pil), dst_path)
            aborted = True

        if not frames_pil:
            logger.warning("[Converter] 无帧可写入 GIF: %s", dst_path)
            return None

        result = None
        try:
            final_timestamp_ms = source_duration_ms if covered_full_duration else None
            durations_ms = _build_frame_durations_ms(
                frame_timestamps_ms,
                final_timestamp_ms,
                frame_dur_ms,
            )
            frames_pil[0].save(
                dst_path, save_all=True, append_images=frames_pil[1:],
                loop=0, duration=durations_ms, optimize=False,
            )
            size_mb = os.path.getsize(dst_path) / (1024 * 1024)
            logger.info(
                "[Converter] 视频→GIF 完成%s: %s (%d 帧, %.1f MB)",
                "（提前结束）" if aborted else "",
                os.path.basename(dst_path), len(frames_pil), size_mb,
            )
            result = dst_path
        except MemoryError:
            logger.error("[Converter] GIF 编码 OOM（%d 帧）: %s", len(frames_pil), dst_path)
        except Exception as exc:
            logger.error("[Converter] GIF 写出失败: %s — %s", dst_path, exc)
        finally:
            frames_pil.clear()
            gc.collect()

        if result is None and os.path.exists(dst_path):
            try:
                os.remove(dst_path)
            except OSError:
                pass
        return result

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

        # 根据可用内存推荐"标准模式"默认配置（不含原图/低配预设，那些固定值）
        if available_mb >= 4096:
            tier = "high"
            recommend = {
                "max_frames": 200, "max_width": 1920, "fps": 30,
                "quality": 80, "timeout_seconds": 300, "max_concurrent": 2,
            }
        elif available_mb >= 1024:
            tier = "mid"
            recommend = {
                "max_frames": 120, "max_width": 1280, "fps": 30,
                "quality": 80, "timeout_seconds": 600, "max_concurrent": 1,
            }
        else:
            tier = "low"
            recommend = {
                "max_frames": 60, "max_width": 1280, "fps": 15,
                "quality": 70, "timeout_seconds": 900, "max_concurrent": 1,
            }

        # 固定预设定义（前端用于一键切换）
        presets = {
            "original": {
                "label": "原图模式",
                "hint": "保留源帧率/分辨率/全帧，流式写入无内存限制，文件可能很大",
                "fps": 0, "max_width": 0, "max_frames": 0, "quality": 100,
            },
            "standard": {
                "label": "标准模式",
                "hint": "30fps / 1280px 宽，适合绝大多数场景",
                "fps": 30, "max_width": 1280, "max_frames": 120, "quality": 80,
            },
            "lite": {
                "label": "低配模式",
                "hint": "8fps / 854px 宽，文件体积小，内存占用极低",
                "fps": 8, "max_width": 854, "max_frames": 30, "quality": 65,
            },
        }

        return {
            "available_memory_mb": available_mb,
            "cpu_count": cpu_count,
            "tier": tier,
            "recommend": recommend,
            "presets": presets,
            "webp_available": is_webp_available(),
        }
