"""
支付相关 Pydantic 数据模型
定义积分购买、IAP收据验证的请求与响应数据结构
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import uuid
from app.core.constants import PaymentProvider, PaymentStatus


class IAPVerifyRequest(BaseModel):
    """
    IAP 收据验证请求体（适用于 Apple/Google）

    [package_id] 套餐 ID
    [receipt_data] IAP 收据数据
    [provider] 支付渠道字符串: apple / google
    [transaction_id] 交易 ID（Google Play 使用）
    """
    package_id: str
    receipt_data: str
    provider: str  # "apple" 或 "google"
    transaction_id: Optional[str] = None


class IAPVerifyResponse(BaseModel):
    """
    IAP 收据验证响应体

    [success] 验证是否成功
    [credits_granted] 本次发放的积分数（重复购买返回 0）
    [current_balance] 验证后的积分余额
    [message] 结果说明
    """
    success: bool
    credits_granted: int
    current_balance: int
    message: str


class PurchaseRecordItem(BaseModel):
    """
    购买记录单条响应体
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: str
    amount_usd: float
    credits_granted: int
    payment_provider: PaymentProvider
    status: PaymentStatus
    created_at: datetime
    paid_at: Optional[datetime]


# 兼容别名：支付记录响应体（供路由使用）
class PurchaseRecord(PurchaseRecordItem):
    """
    购买记录响应体（PurchaseRecordItem 别名）
    """
    pass
