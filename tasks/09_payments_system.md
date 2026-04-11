# Task 09: 支付系统实现

## 任务描述

实现 Stripe Checkout 支付、Apple/Google IAP 收据验证、Webhook 回调处理和购买历史查询。

## 涉及文件

- `app/features/payments/router.py` - 路由处理器
- `app/features/payments/service.py` - 业务逻辑
- `app/external/stripe_api.py` - Stripe API 客户端
- `app/schemas/payment.py` - Pydantic 模型

## 详细任务

### 9.1 创建 Stripe API 客户端

```python
# app/external/stripe_api.py
import stripe

from app.config import Settings

settings = Settings()

stripe.api_key = settings.STRIPE_SECRET_KEY

class StripeClient:
    """Stripe API 客户端"""
    
    CREDIT_PACKAGES = {
        "starter": {"price_usd": 0.99, "credits": 100},
        "basic": {"price_usd": 2.99, "credits": 320},
        "pro": {"price_usd": 6.99, "credits": 800},
        "premium": {"price_usd": 14.99, "credits": 1800},
    }
    
    def create_checkout_session(
        self,
        user_id: str,
        package_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        """
        创建 Stripe Checkout Session
        """
        if package_id not in self.CREDIT_PACKAGES:
            raise ValueError(f"Invalid package_id: {package_id}")
        
        package = self.CREDIT_PACKAGES[package_id]
        
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(package["price_usd"] * 100),  # cents
                        "product_data": {
                            "name": f"TextLens {package_id.capitalize()} Package",
                            "description": f"{package['credits']} credits",
                        },
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "user_id": user_id,
                "package_id": package_id,
                "credits": str(package["credits"]),
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )
        
        return {
            "session_id": session.id,
            "checkout_url": session.url,
        }
    
    def verify_webhook_signature(self, payload: bytes, sig: str) -> dict:
        """验证 Stripe Webhook 签名"""
        try:
            event = stripe.Webhook.construct_event(
                payload, sig, settings.STRIPE_WEBHOOK_SECRET
            )
            return event
        except ValueError:
            raise ValueError("Invalid webhook payload")
        except stripe.error.SignatureVerificationError:
            raise ValueError("Invalid webhook signature")
    
    def retrieve_session(self, session_id: str) -> dict:
        """获取 Checkout Session 详情"""
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            "id": session.id,
            "payment_status": session.payment_status,
            "metadata": session.metadata,
            "customer_email": session.customer_email,
        }
```

### 9.2 创建 Pydantic Schema

```python
# app/schemas/payment.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Literal

class CheckoutRequest(BaseModel):
    package_id: str

class CheckoutResponse(BaseModel):
    checkout_url: str

class IAPVerifyRequest(BaseModel):
    receipt_data: str
    package_id: str
    provider: Literal["apple_iap", "google_iap"]

class IAPVerifyResponse(BaseModel):
    success: bool
    credits_granted: int
    transaction_id: str

class PurchaseRecordResponse(BaseModel):
    id: UUID
    package_id: str
    amount_usd: float
    credits_granted: int
    payment_provider: str
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class StripeWebhookEvent(BaseModel):
    type: str
    data: dict
```

### 9.3 实现 PaymentsService

```python
# app/features/payments/service.py
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.models.payment import PurchaseRecord
from app.db.models.credit import CreditAccount, CreditTransaction
from app.external.stripe_api import StripeClient
from app.core.constants import (
    PurchaseStatus, PaymentProvider, CreditType, CreditSource,
)
from app.core.exceptions import ValidationError, ResourceNotFoundError

stripe_client = StripeClient()

class PaymentsService:
    """支付服务类"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_checkout(self, user_id: str, package_id: str, success_url: str, cancel_url: str) -> dict:
        """创建 Stripe Checkout Session"""
        # 验证用户存在
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ResourceNotFoundError("User not found")
        
        if package_id not in stripe_client.CREDIT_PACKAGES:
            raise ValidationError(f"Invalid package_id: {package_id}")
        
        result = stripe_client.create_checkout_session(
            user_id=user_id,
            package_id=package_id,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        
        # 创建待处理购买记录
        package = stripe_client.CREDIT_PACKAGES[package_id]
        purchase = PurchaseRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            package_id=package_id,
            amount_usd=package["price_usd"],
            credits_granted=package["credits"],
            payment_provider=PaymentProvider.STRIPE,
            status=PurchaseStatus.PENDING,
            external_order_id=result["session_id"],
        )
        self.db.add(purchase)
        self.db.commit()
        
        return {"checkout_url": result["checkout_url"]}
    
    def handle_stripe_webhook(self, event_type: str, data: dict) -> dict:
        """
        处理 Stripe Webhook 事件
        """
        if event_type == "checkout.session.completed":
            return self._handle_checkout_completed(data)
        elif event_type == "charge.refunded":
            return self._handle_refund(data)
        
        return {"status": "ignored"}
    
    def _handle_checkout_completed(self, data: dict) -> dict:
        """处理支付成功"""
        session = data.get("object", {})
        session_id = session.get("id")
        metadata = session.get("metadata", {})
        
        user_id = metadata.get("user_id")
        package_id = metadata.get("package_id")
        credits = int(metadata.get("credits", 0))
        
        if not user_id or not credits:
            return {"status": "error", "message": "Invalid metadata"}
        
        # 更新购买记录状态
        purchase = self.db.query(PurchaseRecord).filter(
            PurchaseRecord.external_order_id == session_id
        ).first()
        
        if purchase:
            purchase.status = PurchaseStatus.SUCCESS
            self.db.commit()
        else:
            # 创建新的购买记录（如果不存在）
            purchase = PurchaseRecord(
                id=uuid.uuid4(),
                user_id=user_id,
                package_id=package_id,
                amount_usd=session.get("amount_total", 0) / 100,
                credits_granted=credits,
                payment_provider=PaymentProvider.STRIPE,
                status=PurchaseStatus.SUCCESS,
                external_order_id=session_id,
            )
            self.db.add(purchase)
            self.db.commit()
        
        # 发放积分
        self._grant_credits(user_id, credits, f"购买 {package_id} 套餐")
        
        return {"status": "success"}
    
    def _handle_refund(self, data: dict) -> dict:
        """处理退款"""
        charge = data.get("object", {})
        payment_intent = charge.get("payment_intent")
        
        # 查找并更新购买记录
        purchase = self.db.query(PurchaseRecord).filter(
            PurchaseRecord.external_order_id == payment_intent,
            PurchaseRecord.status == PurchaseStatus.SUCCESS,
        ).first()
        
        if purchase:
            purchase.status = PurchaseStatus.REFUNDED
            
            # 扣除积分（如果已发放）
            self._deduct_credits(
                purchase.user_id,
                purchase.credits_granted,
                f"退款 - {purchase.package_id}",
            )
            
            self.db.commit()
        
        return {"status": "success"}
    
    def _grant_credits(self, user_id: str, credits: int, description: str):
        """发放积分"""
        credit = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()
        
        if not credit:
            credit = CreditAccount(
                user_id=user_id,
                balance=credits,
                total_earned=credits,
            )
            self.db.add(credit)
        else:
            credit.balance += credits
            credit.total_earned += credits
        
        transaction = CreditTransaction(
            user_id=user_id,
            amount=credits,
            type=CreditType.EARN,
            source=CreditSource.PURCHASE,
            balance_after=credit.balance,
            description=description,
        )
        self.db.add(transaction)
        self.db.commit()
    
    def _deduct_credits(self, user_id: str, credits: int, description: str):
        """扣除积分（退款时）"""
        credit = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()
        
        if credit:
            credit.balance = max(0, credit.balance - credits)
            
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-credits,
                type=CreditType.SPEND,
                source=CreditSource.REFUND,
                balance_after=credit.balance,
                description=description,
            )
            self.db.add(transaction)
            self.db.commit()
    
    def verify_iap(self, user_id: str, receipt_data: str, package_id: str, provider: str) -> dict:
        """
        验证 Apple/Google IAP 收据并发放积分
        """
        # 验证收据
        # 实际实现需要调用 Apple App Store Server API 或 Google Play Developer API
        # 这里简化处理
        
        if provider == "apple_iap":
            # 调用 Apple IAP 验证
            verified = self._verify_apple_receipt(receipt_data)
        else:
            # 调用 Google IAP 验证
            verified = self._verify_google_receipt(receipt_data)
        
        if not verified:
            raise ValidationError("Invalid IAP receipt")
        
        # 获取积分数量
        if package_id not in stripe_client.CREDIT_PACKAGES:
            raise ValidationError(f"Invalid package_id: {package_id}")
        
        credits = stripe_client.CREDIT_PACKAGES[package_id]["credits"]
        
        # 创建购买记录
        purchase = PurchaseRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            package_id=package_id,
            amount_usd=0,  # IAP 价格由客户端确定
            credits_granted=credits,
            payment_provider=PaymentProvider.APPLE_IAP if provider == "apple_iap" else PaymentProvider.GOOGLE_IAP,
            status=PurchaseStatus.SUCCESS,
            external_order_id=receipt_data[:255],  # 截断存储
            receipt_data=receipt_data,
        )
        self.db.add(purchase)
        
        # 发放积分
        self._grant_credits(user_id, credits, f"IAP 购买 {package_id}")
        
        return {
            "success": True,
            "credits_granted": credits,
            "transaction_id": str(purchase.id),
        }
    
    def _verify_apple_receipt(self, receipt_data: str) -> bool:
        """验证 Apple IAP 收据"""
        # 实际实现调用 App Store Server API
        # https://developer.apple.com/documentation/appstoreserverapi
        return True  # 简化
    
    def _verify_google_receipt(self, receipt_data: str) -> bool:
        """验证 Google IAP 收据"""
        # 实际实现调用 Google Play Developer API
        # https://developers.google.com/android-billing
        return True  # 简化
    
    def get_purchase_history(self, user_id: str, page: int = 1, page_size: int = 20) -> dict:
        """获取购买历史"""
        query = self.db.query(PurchaseRecord).filter(
            PurchaseRecord.user_id == user_id
        ).order_by(PurchaseRecord.created_at.desc())
        
        total = query.count()
        purchases = query.offset((page - 1) * page_size).limit(page_size).all()
        total_pages = (total + page_size - 1) // page_size
        
        return {
            "items": purchases,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
```

### 9.4 实现路由处理器

```python
# app/features/payments/router.py
from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.user import User
from app.features.payments.service import PaymentsService
from app.schemas.payment import (
    CheckoutRequest, CheckoutResponse, IAPVerifyRequest, IAPVerifyResponse,
    PurchaseRecordResponse, PageResponse,
)
from app.core.exceptions import ValidationError, ResourceNotFoundError

router = APIRouter()

@router.post("/checkout")
def create_checkout(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建 Stripe Checkout Session"""
    service = PaymentsService(db)
    
    # 动态构建 URL
    success_url = f"https://textlens.app/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = "https://textlens.app/payment/cancel"
    
    try:
        result = service.create_checkout(
            user_id=str(current_user.id),
            package_id=request.package_id,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return CheckoutResponse(checkout_url=result["checkout_url"])
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )

@router.post("/iap/verify", response_model=IAPVerifyResponse)
def verify_iap(
    request: IAPVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """验证 Apple/Google IAP 收据"""
    service = PaymentsService(db)
    
    try:
        result = service.verify_iap(
            user_id=str(current_user.id),
            receipt_data=request.receipt_data,
            package_id=request.package_id,
            provider=request.provider,
        )
        return IAPVerifyResponse(**result)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )

@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Stripe Webhook 回调（不需要 JWT 认证）
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    
    service = PaymentsService(db)
    
    try:
        event = service.stripe_client.verify_webhook_signature(payload, sig)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
    
    result = service.handle_stripe_webhook(event["type"], event["data"])
    
    return result

@router.get("/history", response_model=PageResponse)
def get_purchase_history(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询购买历史"""
    service = PaymentsService(db)
    result = service.get_purchase_history(str(current_user.id), page, page_size)
    
    return PageResponse(
        items=[PurchaseRecordResponse.model_validate(p) for p in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )
```

## 验收标准

- [ ] POST /payments/checkout 创建 Stripe Checkout Session
- [ ] POST /payments/iap/verify 验证 IAP 收据并发放积分
- [ ] POST /payments/webhook/stripe 处理支付成功回调
- [ ] GET /payments/history 返回购买历史
- [ ] 退款处理正确扣除积分

## 前置依赖

- Task 04: 认证系统实现

## 后续任务

- Task 10: 历史记录模块实现
