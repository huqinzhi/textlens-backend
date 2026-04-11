"""
积分业务逻辑服务层
处理积分余额查询、签到奖励、广告奖励、邀请好友等业务逻辑
"""
import secrets
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import ValidationError, NotFoundError
from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage
from app.core.constants import CreditTransactionType, CreditSourceType
from app.db.models.user import User
from app.schemas.credit import CreditBalanceResponse, CreditTransactionListResponse, DailyCheckinResponse


class CreditService:
    """
    积分服务类

    封装所有积分相关业务逻辑，保证积分操作的原子性。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db

    async def get_balance(self, current_user) -> CreditBalanceResponse:
        """
        查询用户积分余额及今日免费次数

        [current_user] 当前登录用户
        返回 CreditBalanceResponse 积分余额详情
        """
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).first()

        today = date.today()
        daily_usage = self.db.query(DailyFreeUsage).filter(
            DailyFreeUsage.user_id == current_user.id,
            DailyFreeUsage.date == today,
        ).first()

        used_count = daily_usage.used_count if daily_usage else 0
        daily_free_remaining = max(0, settings.FREE_DAILY_LIMIT - used_count)

        # 查询今日看广告次数
        # TODO: 实现广告次数统计
        daily_ad_remaining = settings.CREDITS_AD_DAILY_LIMIT

        return CreditBalanceResponse(
            balance=credit_account.balance if credit_account else 0,
            total_earned=credit_account.total_earned if credit_account else 0,
            total_spent=credit_account.total_spent if credit_account else 0,
            daily_free_remaining=daily_free_remaining,
            daily_ad_remaining=daily_ad_remaining,
        )

    async def get_transactions(
        self,
        current_user,
        page: int,
        page_size: int,
    ) -> CreditTransactionListResponse:
        """
        分页查询积分流水记录

        [current_user] 当前登录用户
        [page] 页码（从1开始）
        [page_size] 每页数量
        返回 CreditTransactionListResponse 分页流水列表
        """
        total = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == current_user.id
        ).count()

        offset = (page - 1) * page_size
        transactions = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == current_user.id
        ).order_by(CreditTransaction.created_at.desc()).offset(offset).limit(page_size).all()

        return CreditTransactionListResponse(
            items=transactions,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def daily_checkin(self, current_user) -> DailyCheckinResponse:
        """
        每日签到，奖励积分

        每天首次调用奖励 CREDITS_DAILY_CHECKIN（默认2积分），
        当天重复调用返回 credits_earned=0。

        [current_user] 当前登录用户
        返回 DailyCheckinResponse 签到结果和积分余额
        """
        today = date.today()

        # 检查今天是否已签到（通过检查今日是否有 daily 来源的积分记录）
        today_checkin = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == current_user.id,
            CreditTransaction.source == CreditSourceType.daily,
        ).filter(
            CreditTransaction.created_at >= datetime.combine(today, datetime.min.time())
        ).first()

        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).with_for_update().first()

        if today_checkin:
            # 今天已签到
            return DailyCheckinResponse(
                credits_earned=0,
                current_balance=credit_account.balance if credit_account else 0,
                streak_days=1,
            )

        # 发放签到积分
        earned = settings.CREDITS_DAILY_CHECKIN
        credit_account.balance += earned
        credit_account.total_earned += earned

        transaction = CreditTransaction(
            user_id=current_user.id,
            credit_account_id=credit_account.id,
            amount=earned,
            type=CreditTransactionType.earn,
            source=CreditSourceType.daily,
            description=f"Daily check-in reward: +{earned} credits",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)
        self.db.commit()

        return DailyCheckinResponse(
            credits_earned=earned,
            current_balance=credit_account.balance,
            streak_days=1,
        )

    async def ad_reward(self, current_user, ad_unit_id: str) -> dict:
        """
        广告奖励积分发放

        用户看完激励视频广告后，发放 CREDITS_AD_REWARD（默认3积分）。
        每日最多 CREDITS_AD_DAILY_LIMIT（默认5）次。

        [current_user] 当前登录用户
        [ad_unit_id] 广告单元 ID
        返回 包含获得积分数和新余额的字典
        """
        today = date.today()

        # 统计今日已看广告次数
        today_ad_count = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == current_user.id,
            CreditTransaction.source == CreditSourceType.ad,
        ).filter(
            CreditTransaction.created_at >= datetime.combine(today, datetime.min.time())
        ).count()

        if today_ad_count >= settings.CREDITS_AD_DAILY_LIMIT:
            raise ValidationError(
                f"Daily ad reward limit reached ({settings.CREDITS_AD_DAILY_LIMIT}/day)"
            )

        earned = settings.CREDITS_AD_REWARD
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).with_for_update().first()

        credit_account.balance += earned
        credit_account.total_earned += earned

        transaction = CreditTransaction(
            user_id=current_user.id,
            credit_account_id=credit_account.id,
            amount=earned,
            type=CreditTransactionType.earn,
            source=CreditSourceType.ad,
            ref_id=ad_unit_id,
            description=f"Ad reward: +{earned} credits",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)
        self.db.commit()

        return {
            "credits_earned": earned,
            "current_balance": credit_account.balance,
            "today_remaining": settings.CREDITS_AD_DAILY_LIMIT - today_ad_count - 1,
        }

    def get_invite_code(self, current_user) -> dict:
        """
        获取用户邀请码

        如果用户还没有邀请码，则自动生成一个。

        [current_user] 当前登录用户
        返回 包含 invite_code 和 invite_url 的字典
        """
        user = self.db.query(User).filter(User.id == current_user.id).first()
        if not user:
            raise NotFoundError("User not found")

        # 如果没有邀请码，自动生成一个
        if not user.invite_code:
            user.invite_code = self._generate_unique_invite_code()
            self.db.commit()

        base_url = settings.APP_BASE_URL.rstrip("/")
        invite_url = f"{base_url}/invite/{user.invite_code}"

        return {
            "invite_code": user.invite_code,
            "invite_url": invite_url,
        }

    def _generate_unique_invite_code(self) -> str:
        """
        生成唯一的邀请码

        返回 8 位唯一邀请码
        """
        while True:
            # 生成 8 位字母数字混合邀请码
            code = secrets.token_urlsafe(6)[:8].upper()
            # 检查是否已存在
            existing = self.db.query(User).filter(User.invite_code == code).first()
            if not existing:
                return code

    def get_invite_history(self, current_user) -> list:
        """
        获取用户邀请记录

        返回所有通过该用户邀请码注册的用户列表。

        [current_user] 当前登录用户
        返回 被邀请用户列表（包含注册时间、是否发放奖励等）
        """
        invited_users = self.db.query(User).filter(
            User.invited_by == current_user.id
        ).order_by(User.created_at.desc()).all()

        # 获取这些用户的积分奖励记录
        result = []
        for user in invited_users:
            # 查询是否已发放邀请奖励
            reward_transaction = self.db.query(CreditTransaction).filter(
                CreditTransaction.user_id == current_user.id,
                CreditTransaction.source == CreditSourceType.invite,
                CreditTransaction.ref_id == str(user.id),
            ).first()

            result.append({
                "user_id": str(user.id),
                "username": user.username,
                "avatar_url": user.avatar_url,
                "registered_at": user.created_at.isoformat() if user.created_at else None,
                "reward_credited": reward_transaction is not None,
                "reward_amount": reward_transaction.amount if reward_transaction else 0,
            })

        return result

    def process_invite_reward(self, inviter_id: str, invited_user_id: str) -> None:
        """
        处理邀请奖励发放

        当被邀请人完成注册时，自动发放邀请奖励积分给邀请人。

        [inviter_id] 邀请人用户 ID
        [invited_user_id] 被邀请人用户 ID
        """
        # 检查是否已经发放过奖励（防止重复发放）
        existing_reward = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == inviter_id,
            CreditTransaction.source == CreditSourceType.invite,
            CreditTransaction.ref_id == invited_user_id,
        ).first()

        if existing_reward:
            return  # 已经发放过奖励

        inviter = self.db.query(User).filter(User.id == inviter_id).first()
        if not inviter:
            return

        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == inviter_id
        ).with_for_update().first()

        if not credit_account:
            return

        # 发放邀请奖励
        earned = settings.CREDITS_INVITE_REWARD
        credit_account.balance += earned
        credit_account.total_earned += earned

        transaction = CreditTransaction(
            user_id=inviter_id,
            credit_account_id=credit_account.id,
            amount=earned,
            type=CreditTransactionType.earn,
            source=CreditSourceType.invite,
            ref_id=invited_user_id,
            description=f"Invite friend reward: +{earned} credits",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)
        self.db.commit()
