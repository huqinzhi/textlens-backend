"""
支付相关数据库模型
记录用户购买积分套餐的订单信息
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, JSON, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum
from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    """支付状态枚举"""
    PENDING = "pending"     # 待支付
    SUCCESS = "success"     # 支付成功
    FAILED = "failed"       # 支付失败
    REFUNDED = "refunded"   # 已退款


class PaymentProvider(str, enum.Enum):
    """支付渠道枚举"""
    STRIPE = "stripe"
    APPLE_IAP = "apple_iap"
    GOOGLE_IAP = "google_iap"


class PurchaseRecord(Base):
    """
    购买记录表
    记录用户每次积分充值的完整订单信息
    """
    __tablename__ = "purchase_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # 套餐信息
    package_id = Column(String(50), nullable=False, comment="套餐ID: starter/basic/pro/premium")
    amount_usd = Column(Float, nullable=False, comment="支付金额（美元）")
    credits_granted = Column(Integer, nullable=False, comment="赠送积分数量（含 bonus）")

    # 支付信息
    payment_provider = Column(Enum(PaymentProvider), nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)

    # 第三方支付凭证
    external_order_id = Column(String(255), nullable=True, comment="Stripe PaymentIntent ID / Apple transaction ID")
    receipt_data = Column(Text, nullable=True, comment="IAP 收据原始数据")
    webhook_data = Column(JSON, nullable=True, comment="Stripe Webhook 数据快照")

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at = Column(DateTime, nullable=True, comment="支付成功时间")
    refunded_at = Column(DateTime, nullable=True, comment="退款时间")

    # 关联关系
    user = relationship("User", back_populates="purchase_records")
