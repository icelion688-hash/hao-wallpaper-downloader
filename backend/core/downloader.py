"""
downloader.py — 异步下载 + 断点续传 + 文件归档

功能：
  1. 异步下载壁纸文件，支持 Range 断点续传
  2. 按分类自动归档到 downloads/{category}/ 目录
  3. 下载前通过 captcha_solver 解决 altcha 验证
  4. 下载完成后触发 dedup 去重检查
"""

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import httpx

from backend.core.anti_detection import AntiDetection
from backend.core.captcha_solver import AltchaSolver

logger = logging.getLogger(__name__)

# 下载根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOWNLOAD_ROOT = os.path.join(BASE_DIR, "downloads")

# 分片大小
CHUNK_SIZE = 64 * 1024   # 64 KB（静态图）
CHUNK_SIZE_VIDEO = 256 * 1024  # 256 KB（动态视频，减少 write 调用次数）

# 最大重试次数
MAX_RETRIES = 3

# 下载进度日志间隔（仅大文件）
_LOG_PROGRESS_INTERVAL = 20 * 1024 * 1024   # 每 20 MB 打印一次
_LOG_PROGRESS_MIN_SIZE = 10 * 1024 * 1024   # 文件 > 10 MB 才启用进度日志

# 磁盘空间警戒线（低于此值时跳过大文件下载）
_DISK_WARN_FREE_BYTES = 300 * 1024 * 1024   # 300 MB


class Downloader:
    """壁纸异步下载器"""

    def __init__(
        self,
        anti_detection: AntiDetection,
        captcha_solver: AltchaSolver,
        download_root: str = DOWNLOAD_ROOT,
    ):
        self.anti = anti_detection
        self.captcha = captcha_solver
        self.download_root = download_root
        os.makedirs(download_root, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  主下载方法
    # ------------------------------------------------------------------ #

    async def download(
        self,
        resource_id: str,
        download_url: str,
        cookie: str,
        category: str = "uncategorized",
        filename: Optional[str] = None,
        wallpaper_type: str = "static",
        width: Optional[int] = None,
        height: Optional[int] = None,
        referer_url: Optional[str] = None,
        session_profile: Optional[dict] = None,
    ) -> Optional[str]:
        """
        下载单张壁纸

        Args:
            resource_id:  资源 ID（用于命名和日志）
            download_url: 直链下载地址
            cookie:       账号 cookie
            category:     分类目录名（如 "anime", "landscape"）
            filename:     自定义文件名（None 时自动从 URL 提取）
            wallpaper_type: "static" 或 "dynamic"
            width:        宽度（用于动态图按横/竖图归档）
            height:       高度（用于动态图按横/竖图归档）
            referer_url:  来源详情页（电脑/手机页路径不同）

        Returns:
            下载成功时返回本地文件路径（相对于 download_root）
            失败时返回 None
        """
        if not download_url:
            logger.error(f"[Downloader] 资源 {resource_id} 无下载地址")
            return None

        category = self._resolve_save_category(
            category=category,
            wallpaper_type=wallpaper_type,
            width=width,
            height=height,
        )

        save_dir = os.path.join(self.download_root, category or "uncategorized")
        os.makedirs(save_dir, exist_ok=True)

        filename = filename or self._extract_filename(
            download_url, resource_id,
            default_ext="mp4" if wallpaper_type == "dynamic" else "jpg",
        )
        # 过滤文件名中的非法字符（Windows 兼容）
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
        # 同名冲突处理：若已有同名文件但属于不同资源，自动追加计数后缀
        filename = self._resolve_collision(save_dir, filename)
        local_path = os.path.join(save_dir, filename)

        # 已存在且完整时跳过（同一资源重试场景）
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            logger.info(f"[Downloader] {resource_id} 已存在，跳过: {filename}")
            rel = os.path.relpath(local_path, self.download_root)
            return rel

        # 磁盘空间预检（动态视频文件通常 50-100 MB，提前检查避免下载中途磁盘满）
        if wallpaper_type == "dynamic":
            try:
                free_bytes = shutil.disk_usage(self.download_root).free
                if free_bytes < _DISK_WARN_FREE_BYTES:
                    logger.warning(
                        "[Downloader] 磁盘剩余空间不足 (%.1f MB)，跳过动态图下载: %s",
                        free_bytes / (1024 * 1024), resource_id,
                    )
                    return None
            except OSError:
                pass  # 无法获取磁盘信息时继续下载

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await self._download_with_resume(
                    resource_id=resource_id,
                    url=download_url,
                    local_path=local_path,
                    cookie=cookie,
                    referer_url=referer_url,
                    session_profile=session_profile,
                    wallpaper_type=wallpaper_type,
                )
                if result:
                    rel = os.path.relpath(local_path, self.download_root)
                    logger.info(f"[Downloader] {resource_id} 下载成功: {rel}")
                    return rel
                else:
                    logger.warning(f"[Downloader] {resource_id} 第 {attempt} 次下载失败")

            except Exception as e:
                logger.error(f"[Downloader] {resource_id} 第 {attempt} 次异常: {e}")

            if attempt < MAX_RETRIES:
                await self.anti.random_delay(min_s=2, max_s=5)

        logger.error(f"[Downloader] {resource_id} 所有重试均失败")
        return None

    @staticmethod
    def _resolve_orientation_label(width: Optional[int], height: Optional[int]) -> str:
        width_value = int(width or 0)
        height_value = int(height or 0)
        if width_value <= 0 or height_value <= 0:
            return "未定义"
        if height_value > width_value:
            return "竖图"
        if height_value == width_value:
            return "方图"
        return "横图"

    @classmethod
    def _resolve_save_category(
        cls,
        *,
        category: str,
        wallpaper_type: str,
        width: Optional[int],
        height: Optional[int],
    ) -> str:
        normalized_category = str(category or "").strip().strip("/\\")
        if str(wallpaper_type or "").strip().lower() != "dynamic":
            return normalized_category or "uncategorized"

        orientation = cls._resolve_orientation_label(width, height)
        if normalized_category:
            return f"{normalized_category}/{orientation}"
        return orientation

    # ------------------------------------------------------------------ #
    #  断点续传下载
    # ------------------------------------------------------------------ #

    async def _download_with_resume(
        self,
        resource_id: str,
        url: str,
        local_path: str,
        cookie: str,
        referer_url: Optional[str] = None,
        session_profile: Optional[dict] = None,
        wallpaper_type: str = "static",
    ) -> bool:
        """
        支持 Range 断点续传的下载实现

        Returns:
            True = 下载完成，False = 失败
        """
        # 检查是否有临时文件（断点续传）
        tmp_path = local_path + ".tmp"
        existing_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0

        headers = self.anti.build_headers(
            cookie,
            referer=referer_url or f"https://haowallpaper.com/wallpaper/{resource_id}",
            profile=session_profile,
        )

        # CDN 签名直链（down.haowallpaper.com）鉴权已内嵌于 URL 签名，无需额外验证
        # previewFileImg / getVideoReduce 等接口鉴权依赖 cookie（已在 headers 中）

        # Range 续传头
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"
            logger.debug(f"[Downloader] {resource_id} 断点续传，已有 {existing_size} bytes")

        # 动态视频体积大（50-100 MB），使用更长的超时防止慢速 CDN 断链
        _is_video = wallpaper_type == "dynamic"
        _timeout = httpx.Timeout(
            connect=15,
            read=300 if _is_video else 60,   # 视频 5 分钟，静态图 1 分钟
            write=10, pool=15,
        )
        _chunk_size = CHUNK_SIZE_VIDEO if _is_video else CHUNK_SIZE

        async with self.anti.build_client(cookie, profile=session_profile) as client:
            try:
                async with client.stream(
                    "GET", url, headers=headers, timeout=_timeout,
                ) as resp:
                    # 206 Partial Content = 服务端支持续传
                    # 200 OK = 服务端不支持续传，从头开始
                    if resp.status_code == 200:
                        existing_size = 0  # 重新下载
                    elif resp.status_code == 206:
                        pass  # 继续断点
                    else:
                        logger.error(
                            f"[Downloader] {resource_id} 下载请求返回 {resp.status_code}"
                        )
                        return False

                    total = int(resp.headers.get("content-length", 0)) + existing_size
                    mode = "ab" if existing_size > 0 else "wb"

                    downloaded = existing_size
                    _next_log_at = existing_size + _LOG_PROGRESS_INTERVAL  # 下次进度日志的阈值

                    with open(tmp_path, mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size=_chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)

                            # 大文件进度日志（每 20 MB 打印一次）
                            if total >= _LOG_PROGRESS_MIN_SIZE and downloaded >= _next_log_at:
                                pct = downloaded / total * 100 if total else 0
                                logger.info(
                                    "[Downloader] %s 下载进度: %.1f%% (%s / %s)",
                                    resource_id, pct,
                                    _fmt_bytes(downloaded), _fmt_bytes(total),
                                )
                                _next_log_at += _LOG_PROGRESS_INTERVAL

                    # 校验文件大小
                    if total > 0 and downloaded < total * 0.99:
                        logger.warning(
                            f"[Downloader] {resource_id} 文件不完整 "
                            f"({downloaded}/{total} bytes)"
                        )
                        return False

                    # 重命名为正式文件
                    os.replace(tmp_path, local_path)
                    return True

            except httpx.TimeoutException:
                logger.warning(
                    f"[Downloader] {resource_id} 下载超时 "
                    f"(已下载 {_fmt_bytes(downloaded)} / {_fmt_bytes(total)})"
                )
                return False
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"[Downloader] {resource_id} HTTP 错误: {e.response.status_code}"
                )
                return False

    # ------------------------------------------------------------------ #
    #  工具方法
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_filename(url: str, fallback_id: str, default_ext: str = "jpg") -> str:
        """从 URL 提取文件名，失败时用 resource_id + default_ext 作为文件名"""
        try:
            path = urlparse(url).path
            name = os.path.basename(unquote(path))
            name = re.sub(r'[<>:"/\\|?*]', "_", name)
            if name and "." in name:
                return name
        except Exception:
            pass
        return f"{fallback_id}.{default_ext}"

    @staticmethod
    def _resolve_collision(save_dir: str, filename: str) -> str:
        """
        若 save_dir/filename 已存在，追加计数后缀（_2, _3 …）直到找到可用名称。
        保证不同资源不会覆盖彼此的文件。
        """
        if not os.path.exists(os.path.join(save_dir, filename)):
            return filename
        name, ext = os.path.splitext(filename)
        counter = 2
        while True:
            candidate = f"{name}_{counter}{ext}"
            if not os.path.exists(os.path.join(save_dir, candidate)):
                return candidate
            counter += 1

    @staticmethod
    def get_category_dir(category: str, download_root: str) -> str:
        """获取分类目录路径，确保目录存在"""
        safe = re.sub(r'[<>:"/\\|?*]', "_", category or "uncategorized")
        path = os.path.join(download_root, safe)
        os.makedirs(path, exist_ok=True)
        return path


def _fmt_bytes(n: int) -> str:
    """将字节数格式化为可读字符串，用于进度日志"""
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024**3):.1f} GB"
    if n >= 1024 * 1024:
        return f"{n / (1024**2):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"
