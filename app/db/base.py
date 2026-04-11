"""
SQLAlchemy ORM 基础配置模块

定义所有 ORM 模型的基类，确保 Alembic 迁移可以发现所有模型。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    ORM 模型基类

    所有数据库模型都必须继承此类，以便 Alembic 自动检测表变更。
    """
    pass
