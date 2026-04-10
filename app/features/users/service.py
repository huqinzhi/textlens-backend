"""
用户业务逻辑服务层
处理用户资料的查询和更新
"""
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.credit import CreditAccount, DailyFreeUsage
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
        获取用户完整资料（含积分和免费次数）

        [current_user] 当前登录用户
        返回 UserProfileResponse 用户完整个人资料
        """
        # 查询积分账户
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).first()

        # 查询今日免费使用次数
        today = date.today()
        daily_usage = self.db.query(DailyFreeUsage).filter(
            DailyFreeUsage.user_id == current_user.id,
            DailyFreeUsage.date == today,
        ).first()

        used_count = daily_usage.used_count if daily_usage else 0
        daily_free_remaining = max(0, settings.FREE_DAILY_LIMIT - used_count)

        return UserProfileResponse(
            id=current_user.id,
            email=current_user.email,
            username=current_user.username,
            avatar_url=current_user.avatar_url,
            is_email_verified=getattr(current_user, "is_email_verified", False),
            credit_balance=credit_account.balance if credit_account else 0,
            daily_free_remaining=daily_free_remaining,
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
