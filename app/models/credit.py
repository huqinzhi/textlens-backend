from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Enum, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.models.base import Base


class TransactionType(str, enum.Enum):
    earn = "earn"
    spend = "spend"


class TransactionSource(str, enum.Enum):
    purchase = "purchase"
    ad = "ad"
    daily = "daily"
    invite = "invite"
    register = "register"
    generation = "generation"


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Integer, default=0, nullable=False)
    total_earned = Column(Integer, default=0, nullable=False)
    total_spent = Column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="credit_account")
    transactions = relationship("CreditTransaction", back_populates="account")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("credit_accounts.id"), nullable=False)
    amount = Column(Integer, nullable=False)  # positive=earn, negative=spend
    type = Column(Enum(TransactionType), nullable=False)
    source = Column(Enum(TransactionSource), nullable=False)
    ref_id = Column(String(255), nullable=True)  # 关联ID（任务ID、购买ID等）
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="credit_transactions")
    account = relationship("CreditAccount", back_populates="transactions")


class DailyFreeUsage(Base):
    __tablename__ = "daily_free_usage"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    used_count = Column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="daily_usages")
