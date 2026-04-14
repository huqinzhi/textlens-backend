"""
用户业务逻辑服务层
处理用户资料的查询、更新和数据导出
"""
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.credit import CreditAccount, DailyFreeUsage, CreditTransaction
from app.db.models.user import User
from app.db.models.image import Image, OCRResult, GenerationTask
from app.db.models.payment import PurchaseRecord
from app.config import settings
from app.schemas.user import UserProfileResponse, UserUpdateRequest
from datetime import date


class UserService:
    """
    用户服务类

    封装用户资料查询和更新的业务逻辑。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db

    async def get_profile(self, current_user) -> UserProfileResponse:
        """
        获取用户完整资料（含积分信息）

        [current_user] 当前登录用户
        返回 UserProfileResponse 用户完整个人资料
        """
        # 查询积分账户
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).first()

        return UserProfileResponse(
            id=current_user.id,
            email=current_user.email,
            username=current_user.username,
            avatar_url=current_user.avatar_url,
            is_email_verified=getattr(current_user, "is_email_verified", False),
            credit_balance=credit_account.balance if credit_account else 0,
            has_free_generation=getattr(current_user, "has_free_generation", False),
            created_at=current_user.created_at,
        )

    async def update_profile(self, current_user, request: UserUpdateRequest) -> UserProfileResponse:
        """
        更新用户个人资料

        支持更新用户名和头像 URL，忽略未传入的字段。

        [current_user] 当前登录用户
        [request] 更新请求体
        返回 UserProfileResponse 更新后的个人资料
        """
        # 仅更新传入的字段
        if request.username is not None:
            current_user.username = request.username
        if request.avatar_url is not None:
            current_user.avatar_url = request.avatar_url

        self.db.commit()
        self.db.refresh(current_user)

        return await self.get_profile(current_user)

    async def export_user_data(self, current_user) -> dict:
        """
        导出用户所有数据（GDPR 合规）

        导出用户的所有个人信息、积分数据、OCR 记录和生成历史。

        [current_user] 当前登录用户
        返回 包含用户所有数据的字典
        """
        # 基本信息
        user_data = {
            "id": str(current_user.id),
            "email": current_user.email,
            "username": current_user.username,
            "avatar_url": current_user.avatar_url,
            "auth_provider": current_user.auth_provider.value if hasattr(current_user.auth_provider, 'value') else str(current_user.auth_provider),
            "is_email_verified": current_user.is_email_verified,
            "is_active": current_user.is_active,
            "age_verified": current_user.age_verified,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
            "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
            "invite_code": current_user.invite_code,
            "privacy_accepted_at": current_user.privacy_accepted_at.isoformat() if current_user.privacy_accepted_at else None,
            "terms_accepted_at": current_user.terms_accepted_at.isoformat() if current_user.terms_accepted_at else None,
        }

        # 积分账户数据
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).first()

        credit_data = None
        if credit_account:
            credit_data = {
                "balance": credit_account.balance,
                "total_earned": credit_account.total_earned,
                "total_spent": credit_account.total_spent,
                "created_at": credit_account.created_at.isoformat() if credit_account.created_at else None,
            }

        # 积分流水记录
        transactions = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == current_user.id
        ).order_by(CreditTransaction.created_at.desc()).all()

        transaction_list = [
            {
                "id": str(t.id),
                "amount": t.amount,
                "type": t.type.value if hasattr(t.type, 'value') else str(t.type),
                "source": t.source.value if hasattr(t.source, 'value') else str(t.source),
                "description": t.description,
                "balance_after": t.balance_after,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ]

        # 图片上传记录（仅元数据，不包含图片文件）
        images = self.db.query(Image).filter(
            Image.user_id == current_user.id
        ).order_by(Image.created_at.desc()).all()

        image_list = [
            {
                "id": str(img.id),
                "original_url": img.original_url,
                "thumbnail_url": img.thumbnail_url,
                "file_size": img.file_size,
                "file_format": img.file_format,
                "width": img.width,
                "height": img.height,
                "status": img.status.value if hasattr(img.status, 'value') else str(img.status),
                "created_at": img.created_at.isoformat() if img.created_at else None,
            }
            for img in images
        ]

        # 生成任务记录
        generations = self.db.query(GenerationTask).filter(
            GenerationTask.user_id == current_user.id
        ).order_by(GenerationTask.created_at.desc()).all()

        generation_list = [
            {
                "id": str(g.id),
                "original_image_url": g.original_image_url,
                "result_image_url": g.result_image_url,
                "status": g.status.value if hasattr(g.status, 'value') else str(g.status),
                "credits_cost": g.credits_cost,
                "is_free": bool(g.is_free),
                "has_watermark": bool(g.has_watermark),
                "error_message": g.error_message,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "completed_at": g.completed_at.isoformat() if g.completed_at else None,
            }
            for g in generations
        ]

        # 购买记录
        purchases = self.db.query(PurchaseRecord).filter(
            PurchaseRecord.user_id == current_user.id
        ).order_by(PurchaseRecord.created_at.desc()).all()

        purchase_list = [
            {
                "id": str(p.id),
                "package_id": p.package_id,
                "amount_usd": p.amount_usd,
                "credits_granted": p.credits_granted,
                "payment_provider": p.payment_provider.value if hasattr(p.payment_provider, 'value') else str(p.payment_provider),
                "status": p.status.value if hasattr(p.status, 'value') else str(p.status),
                "external_order_id": p.external_order_id,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in purchases
        ]

        return {
            "exported_at": date.today().isoformat(),
            "user": user_data,
            "credit_account": credit_data,
            "transactions": transaction_list,
            "images": image_list,
            "generations": generation_list,
            "purchases": purchase_list,
        }
