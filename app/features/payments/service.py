"""
支付业务逻辑服务层
处理 Stripe Checkout 创建、IAP 收据验证、Webhook 回调处理
"""
import json
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import ValidationError, NotFoundError, ExternalServiceError
from app.core.constants import CREDIT_PACKAGES
from app.db.models.credit import CreditAccount, CreditTransaction, TransactionType, TransactionSource
from app.db.models.payment import PurchaseRecord, PaymentProvider, PaymentStatus
from app.schemas.payment import (
    CreateCheckoutResponse,
    IAPVerifyRequest,
    IAPVerifyResponse,
)
from app.schemas.common import PageResponse
from app.external.stripe_api import StripeClient


class PaymentService:
    """
    支付服务类

    封装所有支付相关业务逻辑，包括 Stripe 订单创建、
    IAP 收据验证、Webhook 处理和积分发放。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db
        self.stripe_client = StripeClient()

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

    async def create_checkout(self, current_user, package_id: str) -> CreateCheckoutResponse:
        """
        创建 Stripe Checkout 支付会话

        根据套餐 ID 创建 Stripe Checkout Session，返回支付页面 URL。

        [current_user] 当前登录用户
        [package_id] 套餐 ID
        返回 CreateCheckoutResponse 含 checkout_url 和 session_id
        """
        package = self._get_package(package_id)

        # 创建 Stripe Checkout Session
        session = await self.stripe_client.create_checkout_session(
            user_id=str(current_user.id),
            user_email=current_user.email,
            package_id=package_id,
            amount_cents=int(package["price_usd"] * 100),
            credits=package["credits"],
            package_name=package["name"],
        )

        # 预创建待支付的购买记录
        purchase = PurchaseRecord(
            user_id=current_user.id,
            package_id=package_id,
            amount_usd=package["price_usd"],
            credits_granted=package["credits"],
            payment_provider=PaymentProvider.STRIPE,
            status=PaymentStatus.PENDING,
            external_order_id=session["id"],
        )
        self.db.add(purchase)
        self.db.commit()

        return CreateCheckoutResponse(
            checkout_url=session["url"],
            session_id=session["id"],
        )

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
            type=TransactionType.earn,
            source=TransactionSource.purchase,
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

    async def handle_stripe_webhook(self, payload: bytes, signature: str) -> dict:
        """
        处理 Stripe Webhook 事件

        验证签名后解析事件类型，目前处理 checkout.session.completed 事件。
        发放积分并更新购买记录状态。

        [payload] Webhook 原始请求体（字节流）
        [signature] Stripe-Signature 请求头
        返回处理结果字典
        """
        # 验证 Stripe 签名
        event = await self.stripe_client.verify_webhook(payload, signature)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            session_id = session["id"]

            # 查找对应的购买记录
            purchase = self.db.query(PurchaseRecord).filter(
                PurchaseRecord.external_order_id == session_id
            ).first()

            if purchase and purchase.status == PaymentStatus.PENDING:
                # 更新购买记录状态
                purchase.status = PaymentStatus.SUCCESS
                purchase.webhook_data = event

                # 发放积分
                credit_account = self.db.query(CreditAccount).filter(
                    CreditAccount.user_id == purchase.user_id
                ).with_for_update().first()

                if credit_account:
                    credits = purchase.credits_granted
                    credit_account.balance += credits
                    credit_account.total_earned += credits

                    transaction = CreditTransaction(
                        user_id=purchase.user_id,
                        credit_account_id=credit_account.id,
                        amount=credits,
                        type=TransactionType.earn,
                        source=TransactionSource.purchase,
                        ref_id=session_id,
                        description=f"Stripe purchase: +{credits} credits",
                        balance_after=credit_account.balance,
                    )
                    self.db.add(transaction)
                    self.db.commit()

        return {"received": True}

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
