"""
SQLite 初始化与 SQLAlchemy 引擎。
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 数据库文件路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "wallpaper.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入使用的数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表并执行轻量迁移。"""
    from backend.models import account, task, wallpaper  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_db()
    print(f"[DB] 数据库初始化完成: {DB_PATH}")


def _migrate_db():
    """为历史库补充新增字段，字段已存在时自动跳过。"""
    from sqlalchemy import text

    migrations = [
        "ALTER TABLE wallpapers ADD COLUMN imgbed_url VARCHAR(512)",
        "ALTER TABLE wallpapers ADD COLUMN upload_records TEXT",
        "ALTER TABLE wallpapers ADD COLUMN type_id VARCHAR(64)",
        "ALTER TABLE wallpapers ADD COLUMN color_id VARCHAR(64)",
        "ALTER TABLE wallpapers ADD COLUMN favor_count INTEGER",
        "ALTER TABLE accounts ADD COLUMN last_verify_at DATETIME",
        "ALTER TABLE accounts ADD COLUMN last_verify_status VARCHAR(24)",
        "ALTER TABLE accounts ADD COLUMN last_verify_msg VARCHAR(255)",
        "ALTER TABLE accounts ADD COLUMN last_verify_auth_valid BOOLEAN",
        "ALTER TABLE accounts ADD COLUMN last_verify_can_original BOOLEAN",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass
