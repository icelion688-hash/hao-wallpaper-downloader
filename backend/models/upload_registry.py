"""
upload_registry.py - 跨实例复用的图床上传记录注册表。
"""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from backend.models.database import Base


class UploadRegistry(Base):
    __tablename__ = "upload_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)

    resource_id = Column(String(64), nullable=True, index=True)
    sha256 = Column(String(64), nullable=True, index=True)
    md5 = Column(String(32), nullable=True, index=True)

    profile_key = Column(String(64), nullable=False, index=True)
    format_key = Column(String(32), nullable=False, default="profile", index=True)
    profile_name = Column(String(128), nullable=True)
    channel = Column(String(64), nullable=True)

    url = Column(String(512), nullable=False)
    source_server = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
