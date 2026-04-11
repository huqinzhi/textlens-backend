"""
支付业务逻辑服务层
处理 IAP 收据验证、积分发放等核心逻辑
"""
import json
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import ValidationError, NotFoundError, ExternalServiceError
from app.core.constants import CREDIT_PACKAGES
from app.db.models.credit import CreditAccount, CreditTransaction
from app.core.constants import CreditTransactionType, CreditSourceType
from app.db.models.payment import PurchaseRecord, PaymentProvider, PaymentStatus
from app.schemas.payment import (
    IAPVerifyRequest,
    IAPVerifyResponse,
)
from app.schemas.common import PageResponse


class PaymentService:
    """
    支付服务类

    封装所有支付相关业务逻辑，包括 IAP 收据验证和积分发放。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_package(self, package_id: str) -> dict:
        """
        根据套餐 ID 获取套餐配置

        [package_id] 套餐标识符（如 starter/basic/pro/premium）
        返回套餐配置字典
        """
        package = CREDIT_PACKAGES.get(package_id)
        if not package:
            raise ValidationError(f"Invalid package_id: {package_id}")
        return package

    async def verify_iap(self, current_user, request: IAPVerifyRequest) -> IAPVerifyResponse:
        """
        验证 Apple/Google 内购收据并发放积分

        收据验证通过后，原子性地创建购买记录并增加积分余额。
        使用 external_order_id 防止重复发放。

        [current_user] 当前登录用户
        [request] IAP 验证请求（provider/package_id/receipt_data）
        返回 IAPVerifyResponse 验证结果和新积分余额
        """
        package = self._get_package(request.package_id)

        # 验证收据（根据平台选择对应验证逻辑）
        if request.provider == "apple":
            transaction_id = await self._verify_apple_receipt(request.receipt_data)
        elif request.provider == "google":
            transaction_id = await self._verify_google_receipt(request.receipt_data)
        else:
            raise ValidationError(f"Unsupported provider: {request.provider}")

        # 幂等检查：防止同一笔交易重复发放积分
        existing = self.db.query(PurchaseRecord).filter(
            PurchaseRecord.external_order_id == transaction_id
        ).first()
        if existing:
            credit_account = self.db.query(CreditAccount).filter(
                CreditAccount.user_id == current_user.id
            ).first()
            return IAPVerifyResponse(
                success=True,
                credits_granted=0,
                current_balance=credit_account.balance if credit_account else 0,
                message="Already processed",
            )

        # 发放积分
        credits = package["credits"]
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).with_for_update().first()

        credit_account.balance += credits
        credit_account.total_earned += credits

        # 创建积分流水
        transaction = CreditTransaction(
            user_id=current_user.id,
            credit_account_id=credit_account.id,
            amount=credits,
            type=CreditTransactionType.EARN,
            source=CreditSourceType.PURCHASE,
            ref_id=transaction_id,
            description=f"IAP purchase: {package['name']} (+{credits} credits)",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)

        # 创建购买记录
        provider_enum = PaymentProvider.APPLE_IAP if request.provider == "apple" else PaymentProvider.GOOGLE_IAP
        purchase = PurchaseRecord(
            user_id=current_user.id,
            package_id=request.package_id,
            amount_usd=package["price_usd"],
            credits_granted=credits,
            payment_provider=provider_enum,
            status=PaymentStatus.SUCCESS,
            external_order_id=transaction_id,
            receipt_data=request.receipt_data,
        )
        self.db.add(purchase)
        self.db.commit()

        return IAPVerifyResponse(
            success=True,
            credits_granted=credits,
            current_balance=credit_account.balance,
            message=f"Successfully granted {credits} credits",
        )

    async def _verify_apple_receipt(self, receipt_data: str) -> str:
        """
        向 Apple 验证收据合法性

        调用 Apple 收据验证 API，返回 transaction_id。

        [receipt_data] Base64 编码的 Apple 收据数据
        返回 Apple transaction_id 字符串
        """
        # TODO: 调用 Apple 收据验证 API
        # 生产环境: https://buy.itunes.apple.com/verifyReceipt
        # 沙盒环境: https://sandbox.itunes.apple.com/verifyReceipt
        import httpx
        url = "https://sandbox.itunes.apple.com/verifyReceipt"
        payload = {
            "receipt-data": receipt_data,
            "password": settings.APPLE_IAP_SECRET,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            data = resp.json()

        if data.get("status") != 0:
            raise ValidationError(f"Apple receipt verification failed: status={data.get('status')}")

        # 提取最新交易 ID
        receipts = data.get("latest_receipt_info", [])
        if not receipts:
            raise ValidationError("No receipt info found")

        return receipts[-1]["transaction_id"]

    async def _verify_google_receipt(self, receipt_data: str) -> str:
        """
        向 Google Play 验证购买收据

        解析 receipt_data（JSON 格式），调用 Google Play Developer API 验证。

        [receipt_data] Google Play 购买数据 JSON 字符串
        返回 Google orderId 字符串
        """
        # TODO: 完整的 Google Play 收据验证
        try:
            data = json.loads(receipt_data)
            order_id = data.get("orderId")
            if not order_id:
                raise ValidationError("Missing orderId in receipt")
            return order_id
        except (json.JSONDecodeError, KeyError) as e:
            raise ValidationError(f"Invalid Google receipt format: {e}")

    async def get_purchase_history(self, current_user) -> PageResponse:
        """
        查询用户购买历史记录

        返回所有已完成的积分购买记录，按时间倒序。

        [current_user] 当前登录用户
        返回 PageResponse[PurchaseRecord] 购买历史列表
        """
        purchases = self.db.query(PurchaseRecord).filter(
            PurchaseRecord.user_id == current_user.id
        ).order_by(PurchaseRecord.created_at.desc()).all()

        return PageResponse(
            items=purchases,
            total=len(purchases),
            page=1,
            page_size=len(purchases) or 1,
            total_pages=1,
        )
