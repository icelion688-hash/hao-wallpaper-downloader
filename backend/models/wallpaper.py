"""
wallpaper.py — 壁纸记录 ORM 模型
字段：资源ID、文件hash、本地路径、标签、分辨率等
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, BigInteger, Float
from sqlalchemy.sql import func
from backend.models.database import Base


class Wallpaper(Base):
    __tablename__ = "wallpapers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 网站资源唯一 ID（URL 中的数字部分，如 17603630336822656）
    resource_id = Column(String(64), unique=True, nullable=False, index=True)

    # 壁纸标题
    title = Column(String(255), nullable=True)

    # 文件去重 hash（MD5 + SHA256 双校验）
    md5 = Column(String(32), nullable=True, index=True)
    sha256 = Column(String(64), nullable=True, index=True)

    # 本地存储相对路径（相对于 downloads/ 目录）
    local_path = Column(String(512), nullable=True)

    # 下载该壁纸使用的账号 ID（用于按账号统计今日配额）
    account_id = Column(Integer, nullable=True, index=True)

    # 文件大小（字节）
    file_size = Column(BigInteger, nullable=True)

    # API 标注的原始文件大小（字符串，如 "1.54 MB"、"863 KB"）
    file_mb = Column(String(20), nullable=True)

    # 是否为原图（通过 getCompleteUrl 下载，对比 URL 和文件大小判定）
    is_original = Column(Boolean, nullable=True)

    # 图片尺寸
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    # 壁纸类型: "static" | "dynamic"（动态壁纸）
    wallpaper_type = Column(String(10), nullable=False, default="static")

    # 分类标签（逗号分隔，如 "anime,girl"）
    category = Column(String(255), nullable=True)
    tags = Column(Text, nullable=True)

    # 色系（如 "dark", "light", "colorful"）
    color_theme = Column(String(50), nullable=True)

    # 原始页面 URL
    source_url = Column(String(512), nullable=True)

    # 直链下载 URL
    download_url = Column(String(512), nullable=True)

    # 网站原始分类 ID（typeId UUID，用于 API 级精确过滤与本地文件夹命名）
    type_id = Column(String(64), nullable=True, index=True)

    # 网站原始色系 ID（colorId UUID，对应 category_map.COLOR_MAP）
    color_id = Column(String(64), nullable=True, index=True)

    # 收藏数（来自 API favorCount 字段，下载数已存入 hot_score）
    favor_count = Column(Integer, nullable=True)

    # 图床上传后的完整 URL（None 表示未上传或上传失败）
    imgbed_url = Column(String(512), nullable=True)
    upload_records = Column(Text, nullable=True)
    upload_status = Column(String(32), nullable=True, index=True)
    upload_note = Column(String(255), nullable=True)

    # 下载状态: "pending" | "downloading" | "done" | "failed" | "duplicate"
    status = Column(String(20), nullable=False, default="done", index=True)

    # 是否被标记为重复文件
    is_duplicate = Column(Boolean, nullable=False, default=False)

    # 视频时长（秒，仅 wallpaper_type=dynamic 有效；通过 ffprobe 提取，未安装时为 None）
    video_duration = Column(Float, nullable=True)

    # 转换后文件的相对路径（相对于 downloads/ 目录），None 表示未转换
    converted_path = Column(String(512), nullable=True)

    # 热度/排序分（从网站抓取）
    hot_score = Column(Integer, nullable=True)

    # 创建/下载时间
    downloaded_at = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return (
            f"<Wallpaper id={self.id} resource_id={self.resource_id!r} "
            f"title={self.title!r} status={self.status}>"
        )

    @property
    def resolution(self) -> str:
        """返回分辨率字符串，如 '1920x1080'"""
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "未知"

    @property
    def thumbnail_path(self) -> str | None:
        """缩略图路径（与原图同目录，加 _thumb 后缀）"""
        if not self.local_path:
            return None
        import os
        base, ext = os.path.splitext(self.local_path)
        return f"{base}_thumb{ext}"
