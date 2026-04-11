"""
积分相关数据库模型
包含积分账户、积分流水、每日免费使用次数等表
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
from app.core.constants import CreditTransactionType, CreditSourceType


class CreditAccount(Base):
    """
    积分账户表
    每个用户对应一个积分账户，记录余额和累计数据
    """
    __tablename__ = "credit_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Integer, default=0, nullable=False)           # 当前余额（积分）
    total_earned = Column(Integer, default=0, nullable=False)      # 累计获得
    total_spent = Column(Integer, default=0, nullable=False)       # 累计消费
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关联关系
    user = relationship("User", back_populates="credit_account")
    transactions = relationship("CreditTransaction", back_populates="credit_account")


class CreditTransaction(Base):
    """
    积分流水表
    记录每一笔积分的变动明细，用于对账和审计
    """
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    credit_account_id = Column(Integer, ForeignKey("credit_accounts.id"), nullable=False)
    amount = Column(Integer, nullable=False)                        # 变动数量（正为获得，负为消费）
    type = Column(Enum(CreditTransactionType), nullable=False)            # 流水类型
    source = Column(Enum(CreditSourceType), nullable=False)        # 来源
    ref_id = Column(String(100), nullable=True)                     # 关联单据ID
    description = Column(String(255), nullable=True)                # 备注说明
    balance_after = Column(Integer, nullable=False)                 # 变动后余额
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关联关系
    user = relationship("User", back_populates="credit_transactions")
    credit_account = relationship("CreditAccount", back_populates="transactions")


class DailyFreeUsage(Base):
    """
    每日免费次数表
    记录用户每天的免费生成使用情况
    """
    __tablename__ = "daily_free_usage"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)                             # 使用日期
    used_count = Column(Integer, default=0, nullable=False)         # 已使用次数
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关联关系
    user = relationship("User", back_populates="daily_free_usages")
