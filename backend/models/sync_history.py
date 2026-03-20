"""
sync_history.py - 同步与迁移操作历史记录。
"""

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from backend.models.database import Base


class SyncHistory(Base):
    __tablename__ = "sync_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    action = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="success", index=True)
    summary = Column(String(255), nullable=False)
    detail = Column(Text, nullable=True)

    remote_base_url = Column(String(255), nullable=True)
    source_server = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)
