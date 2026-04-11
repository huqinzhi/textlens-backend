"""
支付模块路由
处理 Apple/Google IAP 内购、Webhook 回调等接口
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.payment import (
    PurchaseRecord as PurchaseRecordSchema,
    IAPVerifyRequest,
    IAPVerifyResponse,
)
from app.schemas.common import PageResponse
from app.features.payments.service import PaymentService

router = APIRouter()


@router.post("/iap/verify", response_model=IAPVerifyResponse)
async def verify_iap(
    request: IAPVerifyRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    验证 Apple/Google 内购收据接口

    客户端完成内购后提交收据，服务端验证后发放积分。

    [request] 包含 provider、package_id、receipt_data 的请求体
    [current_user] 当前登录用户
    [db] 数据库会话
    返回 IAPVerifyResponse 验证结果和积分变动
    """
    payment_service = PaymentService(db)
    return await payment_service.verify_iap(current_user, request)


@router.get("/history", response_model=PageResponse[PurchaseRecordSchema])
async def get_purchase_history(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    查询购买历史记录接口

    返回用户所有积分购买记录，按时间倒序排列。

    [current_user] 当前登录用户
    [db] 数据库会话
    返回 PageResponse[PurchaseRecord] 购买历史分页列表
    """
    payment_service = PaymentService(db)
    return await payment_service.get_purchase_history(current_user)
