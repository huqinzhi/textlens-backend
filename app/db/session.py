"""
数据库会话管理模块
负责创建和管理 SQLAlchemy 数据库会话
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

# 创建数据库引擎
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.APP_DEBUG,
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话的依赖注入函数

    使用 yield 确保会话在请求结束后自动关闭
    返回 Generator[Session, None, None] 数据库会话生成器
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """
    创建所有数据库表

    在应用启动时调用，确保所有表结构存在。
    """
    from app.db.base import Base
    Base.metadata.create_all(bind=engine, checkfirst=True)
