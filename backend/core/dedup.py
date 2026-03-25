"""
dedup.py — 去重模块

两层去重：
  1. ID 去重：下载前查 DB resource_id 是否已存在
  2. Hash 去重：下载后计算 MD5 + SHA256，与库中已有记录比对
     发现重复文件时自动删除，标记状态为 "duplicate"
"""

import hashlib
import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.wallpaper import Wallpaper

logger = logging.getLogger(__name__)

# Hash 计算缓冲区大小
HASH_BUFFER_SIZE = 1024 * 1024  # 1 MB


class DedupManager:
    """文件去重管理器"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    #  第一层：ID 去重（下载前）
    # ------------------------------------------------------------------ #

    def is_resource_downloaded(self, resource_id: str) -> bool:
        """
        检查资源 ID 是否已在数据库中且已完成落库。

        失败记录会保留给自动重试机制，因此不应阻断后续下载。

        Returns:
            True = 已存在，跳过下载
        """
        exists = (
            self.db.query(Wallpaper.id)
            .filter(
                Wallpaper.resource_id == resource_id,
                Wallpaper.status.in_(("done", "downloading", "duplicate")),
            )
            .first()
        )
        return exists is not None

    def get_existing_record(self, resource_id: str) -> Optional[Wallpaper]:
        """获取已存在的壁纸记录"""
        return (
            self.db.query(Wallpaper)
            .filter(Wallpaper.resource_id == resource_id)
            .first()
        )

    # ------------------------------------------------------------------ #
    #  第二层：Hash 去重（下载后）
    # ------------------------------------------------------------------ #

    def check_file_duplicate(self, file_path: str) -> Optional[Wallpaper]:
        """
        计算文件 hash 并查库，判断是否为重复文件

        Args:
            file_path: 本地文件绝对路径

        Returns:
            如果是重复文件，返回已存在的 Wallpaper 记录；否则返回 None
        """
        if not os.path.exists(file_path):
            return None

        md5, sha256 = self.compute_hashes(file_path)
        if not md5:
            return None

        # 查 MD5 + SHA256 双重匹配（避免 hash 碰撞误判）
        existing = (
            self.db.query(Wallpaper)
            .filter(
                Wallpaper.md5 == md5,
                Wallpaper.sha256 == sha256,
                Wallpaper.is_duplicate == False,  # noqa: E712
                Wallpaper.status == "done",
            )
            .first()
        )
        return existing

    def handle_duplicate_file(
        self,
        new_wallpaper: Wallpaper,
        duplicate_of: Wallpaper,
        file_path: str,
    ) -> None:
        """
        处理重复文件：
          1. 删除新下载的文件
          2. 标记 new_wallpaper 状态为 duplicate

        Args:
            new_wallpaper:  新下载的壁纸记录
            duplicate_of:   已存在的原始记录
            file_path:      新文件的本地路径
        """
        # 删除重复文件
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(
                    f"[Dedup] 删除重复文件: {os.path.basename(file_path)} "
                    f"（重复于 resource_id={duplicate_of.resource_id}）"
                )
            except OSError as e:
                logger.error(f"[Dedup] 删除文件失败: {e}")

        # 更新数据库状态
        new_wallpaper.status = "duplicate"
        new_wallpaper.is_duplicate = True
        new_wallpaper.local_path = None  # 文件已删除
        self.db.commit()

    # ------------------------------------------------------------------ #
    #  全库扫描重复
    # ------------------------------------------------------------------ #

    def scan_duplicates(self) -> list[dict]:
        """
        扫描 downloads 目录中的所有文件，找出重复项
        返回重复组列表，供前端展示

        Returns:
            [
              {
                "original": Wallpaper,
                "duplicates": [Wallpaper, ...]
              },
              ...
            ]
        """
        logger.info("[Dedup] 开始全库重复扫描...")

        # 按 (md5, sha256) 分组
        from sqlalchemy import func
        from sqlalchemy import tuple_

        # 找出有重复 hash 的组
        duplicate_hashes = (
            self.db.query(Wallpaper.md5, Wallpaper.sha256)
            .filter(
                Wallpaper.md5 != None,  # noqa: E711
                Wallpaper.status == "done",
            )
            .group_by(Wallpaper.md5, Wallpaper.sha256)
            .having(func.count(Wallpaper.id) > 1)
            .all()
        )

        results = []
        for md5, sha256 in duplicate_hashes:
            records = (
                self.db.query(Wallpaper)
                .filter(
                    Wallpaper.md5 == md5,
                    Wallpaper.sha256 == sha256,
                    Wallpaper.status == "done",
                )
                .order_by(Wallpaper.downloaded_at.asc())
                .all()
            )
            if len(records) > 1:
                results.append({
                    "original": records[0],
                    "duplicates": records[1:],
                })

        logger.info(f"[Dedup] 扫描完成，发现 {len(results)} 组重复")
        return results

    def clean_duplicates(self, dry_run: bool = False) -> int:
        """
        清理所有重复文件（保留最早的一份）

        Args:
            dry_run: 为 True 时只统计不实际删除

        Returns:
            处理的重复文件数量
        """
        groups = self.scan_duplicates()
        cleaned = 0

        for group in groups:
            for dup in group["duplicates"]:
                if not dry_run:
                    if dup.local_path and os.path.exists(dup.local_path):
                        try:
                            os.remove(dup.local_path)
                        except OSError:
                            pass
                    dup.status = "duplicate"
                    dup.is_duplicate = True
                    dup.local_path = None
                cleaned += 1

        if not dry_run:
            self.db.commit()
            logger.info(f"[Dedup] 清理完成，删除 {cleaned} 个重复文件")

        return cleaned

    # ------------------------------------------------------------------ #
    #  工具方法
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_hashes(file_path: str) -> tuple[Optional[str], Optional[str]]:
        """
        计算文件的 MD5 和 SHA256

        Returns:
            (md5_hex, sha256_hex)，失败时返回 (None, None)
        """
        md5_h = hashlib.md5()
        sha256_h = hashlib.sha256()

        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(HASH_BUFFER_SIZE)
                    if not chunk:
                        break
                    md5_h.update(chunk)
                    sha256_h.update(chunk)
            return md5_h.hexdigest(), sha256_h.hexdigest()
        except OSError as e:
            logger.error(f"[Dedup] 计算 hash 失败 {file_path}: {e}")
            return None, None
