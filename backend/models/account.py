"""
账号 ORM 模型。
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from backend.models.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 账号标识（微信昵称或自定义备注）
    nickname = Column(String(100), nullable=False, default="未命名账号")

    # 扫码登录后提取的完整 cookie 字符串
    cookie = Column(Text, nullable=False)

    # 账号类型: "free" | "vip"
    account_type = Column(String(10), nullable=False, default="free")

    # 今日已使用下载次数（免费账号默认每日限额）
    daily_used = Column(Integer, nullable=False, default=0)

    # 每日配额上限（free=10, vip=0 表示不限）
    daily_limit = Column(Integer, nullable=False, default=10)

    # 当日配额重置时间
    daily_reset_at = Column(DateTime, nullable=True)

    # 账号状态
    is_active = Column(Boolean, nullable=False, default=True)
    is_banned = Column(Boolean, nullable=False, default=False)
    last_active = Column(DateTime, nullable=True)

    # 最近一次验证结果
    last_verify_at = Column(DateTime, nullable=True)
    last_verify_status = Column(String(24), nullable=True)
    last_verify_msg = Column(String(255), nullable=True)
    last_verify_auth_valid = Column(Boolean, nullable=True)
    last_verify_can_original = Column(Boolean, nullable=True)

    # Cookie 有效期
    cookie_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<Account id={self.id} nickname={self.nickname!r} "
            f"type={self.account_type} used={self.daily_used}/{self.daily_limit} "
            f"banned={self.is_banned}>"
        )

    @property
    def is_available(self) -> bool:
        """账号是否可用于下载。"""
        if not self.is_active or self.is_banned:
            return False
        if self.account_type == "vip":
            return True
        return self.daily_used < self.daily_limit

    @property
    def remaining_quota(self) -> int:
        """剩余配额；vip 返回 -1 表示不限。"""
        if self.account_type == "vip":
            return -1
        return max(0, self.daily_limit - self.daily_used)
