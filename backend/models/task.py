"""
task.py — 下载任务 ORM 模型
字段：任务状态、进度、配置参数、日志
"""

import json
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.sql import func
from backend.models.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 任务名称（用户自定义或自动生成）
    name = Column(String(255), nullable=False, default="未命名任务")

    # 任务状态: "pending" | "running" | "paused" | "done" | "failed" | "cancelled"
    status = Column(String(20), nullable=False, default="pending", index=True)

    # 进度统计
    total_count = Column(Integer, nullable=False, default=0)     # 计划下载总数
    success_count = Column(Integer, nullable=False, default=0)   # 成功下载数
    failed_count = Column(Integer, nullable=False, default=0)    # 失败数
    skip_count = Column(Integer, nullable=False, default=0)      # 跳过（重复）数

    # 进度百分比（0.0 ~ 100.0）
    progress = Column(Float, nullable=False, default=0.0)

    # 任务配置（JSON 字符串存储）
    # 包含：category, sort_by, wallpaper_type, resolution_min/max,
    #        color_theme, use_vip_only, max_count, concurrency 等
    config_json = Column(Text, nullable=True)

    # 实时日志（最近 500 条，超出后滚动截断）
    log_text = Column(Text, nullable=True, default="")

    # 错误信息（失败时记录）
    error_msg = Column(Text, nullable=True)

    # 是否启用代理
    use_proxy = Column(Boolean, nullable=False, default=True)

    # 任务开始/结束时间
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    # 创建时间
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<Task id={self.id} name={self.name!r} status={self.status} "
            f"progress={self.progress:.1f}% ({self.success_count}/{self.total_count})>"
        )

    @property
    def config(self) -> dict:
        """反序列化任务配置"""
        if not self.config_json:
            return {}
        try:
            return json.loads(self.config_json)
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict):
        """序列化任务配置"""
        self.config_json = json.dumps(value, ensure_ascii=False)

    def append_log(self, line: str, max_lines: int = 500):
        """追加一行日志，超出最大行数时截断旧日志"""
        current = self.log_text or ""
        lines = current.split("\n") if current else []
        lines.append(line)
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        self.log_text = "\n".join(lines)

    def update_progress(self):
        """根据计数更新进度百分比"""
        if self.total_count > 0:
            done = self.success_count + self.failed_count + self.skip_count
            self.progress = min(100.0, done / self.total_count * 100)
        else:
            self.progress = 0.0
