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


# 导入所有模型，确保 Alembic 能够识别（不要删除这些导入）
from app.db.models.user import User  # noqa: E402, F401
from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage  # noqa: E402, F401
from app.db.models.image import GenerationTask  # noqa: E402, F401
from app.db.models.payment import PurchaseRecord  # noqa: E402, F401
