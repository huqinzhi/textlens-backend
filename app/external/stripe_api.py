"""
Stripe 支付 API 客户端封装
负责 Checkout Session 创建和 Webhook 签名验证
"""
import stripe
from typing import Any

from app.config import settings
from app.core.exceptions import ExternalServiceError, ValidationError


class StripeClient:
    """
    Stripe 支付客户端

    封装 Stripe SDK 调用，提供 Checkout 会话创建
    和 Webhook 事件验证功能。
    """

    def __init__(self):
        stripe.api_key = settings.STRIPE_SECRET_KEY

    async def create_checkout_session(
        self,
        user_id: str,
        user_email: str,
        package_id: str,
        amount_cents: int,
        credits: int,
        package_name: str,
    ) -> dict[str, Any]:
        """
        创建 Stripe Checkout 支付会话

        生成用于跳转的 Checkout URL，支付成功后 Stripe 发送 Webhook 通知。

        [user_id] 用户 ID（存入元数据用于 Webhook 追踪）
        [user_email] 用户邮箱（预填 Checkout 表单）
        [package_id] 积分套餐 ID
        [amount_cents] 支付金额（美分，如 $4.99 = 499）
        [credits] 套餐积分数量
        [package_name] 套餐名称（显示在支付页面）
        返回 Stripe Session 字典（含 id 和 url）
        """
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                customer_email=user_email,
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": f"TextLens {package_name}",
                                "description": f"{credits} credits for AI image editing",
                            },
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                # 支付成功跳转页面
                success_url=f"{settings.APP_BASE_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                # 支付取消跳转页面
                cancel_url=f"{settings.APP_BASE_URL}/payment/cancel",
                metadata={
                    "user_id": user_id,
                    "package_id": package_id,
                    "credits": str(credits),
                },
            )
            return {"id": session.id, "url": session.url}
        except stripe.error.StripeError as e:
            raise ExternalServiceError(f"Stripe checkout creation failed: {e}")

    async def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        """
        验证 Stripe Webhook 签名并解析事件

        使用 Webhook Secret 验证请求来源合法性，防止伪造事件。

        [payload] 请求原始字节体
        [signature] Stripe-Signature 请求头值
        返回解析后的 Stripe 事件字典
        """
        if not signature:
            raise ValidationError("Missing Stripe-Signature header")

        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature,
                secret=settings.STRIPE_WEBHOOK_SECRET,
            )
            return event
        except stripe.error.SignatureVerificationError:
            raise ValidationError("Invalid Stripe webhook signature")
        except stripe.error.StripeError as e:
            raise ExternalServiceError(f"Stripe webhook verification failed: {e}")

    async def refund_payment(self, payment_intent_id: str, amount_cents: int = None) -> dict:
        """
        退款处理（部分退款或全额退款）

        [payment_intent_id] Stripe PaymentIntent ID
        [amount_cents] 退款金额（美分），None 表示全额退款
        返回 Stripe Refund 对象字典
        """
        try:
            refund_params = {"payment_intent": payment_intent_id}
            if amount_cents is not None:
                refund_params["amount"] = amount_cents

            refund = stripe.Refund.create(**refund_params)
            return {"id": refund.id, "status": refund.status, "amount": refund.amount}
        except stripe.error.StripeError as e:
            raise ExternalServiceError(f"Stripe refund failed: {e}")
