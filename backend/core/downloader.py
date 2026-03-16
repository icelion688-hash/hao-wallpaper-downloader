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

# 每个分片大小（断点续传）
CHUNK_SIZE = 64 * 1024  # 64 KB

# 最大重试次数
MAX_RETRIES = 3


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

        Returns:
            下载成功时返回本地文件路径（相对于 download_root）
            失败时返回 None
        """
        if not download_url:
            logger.error(f"[Downloader] 资源 {resource_id} 无下载地址")
            return None

        # 动态壁纸放独立子目录
        if wallpaper_type == "dynamic":
            category = f"{category}/dynamic" if category else "dynamic"

        save_dir = os.path.join(self.download_root, category or "uncategorized")
        os.makedirs(save_dir, exist_ok=True)

        filename = filename or self._extract_filename(download_url, resource_id)
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

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await self._download_with_resume(
                    resource_id=resource_id,
                    url=download_url,
                    local_path=local_path,
                    cookie=cookie,
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

    # ------------------------------------------------------------------ #
    #  断点续传下载
    # ------------------------------------------------------------------ #

    async def _download_with_resume(
        self,
        resource_id: str,
        url: str,
        local_path: str,
        cookie: str,
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
            referer=f"https://haowallpaper.com/wallpaper/{resource_id}",
        )

        # CDN 签名直链（down.haowallpaper.com）鉴权已内嵌于 URL 签名，无需额外验证
        # previewFileImg / getVideoReduce 等接口鉴权依赖 cookie（已在 headers 中）
        # 两种情况均不需要在此处重做 altcha 验证

        # Range 续传头
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"
            logger.debug(f"[Downloader] {resource_id} 断点续传，已有 {existing_size} bytes")

        async with self.anti.build_client(cookie) as client:
            try:
                async with client.stream(
                    "GET",
                    url,
                    headers=headers,
                    timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10),
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
                    with open(tmp_path, mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size=CHUNK_SIZE):
                            f.write(chunk)
                            downloaded += len(chunk)

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
                logger.warning(f"[Downloader] {resource_id} 下载超时")
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
    def _extract_filename(url: str, fallback_id: str) -> str:
        """从 URL 提取文件名，失败时用 resource_id 作为文件名"""
        try:
            path = urlparse(url).path
            name = os.path.basename(unquote(path))
            name = re.sub(r'[<>:"/\\|?*]', "_", name)
            if name and "." in name:
                return name
        except Exception:
            pass
        return f"{fallback_id}.jpg"

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
