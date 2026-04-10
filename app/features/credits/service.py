"""
积分业务逻辑服务层
处理积分余额查询、签到奖励、广告奖励等业务逻辑
"""
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import ValidationError
from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage, TransactionType, TransactionSource
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
            CreditTransaction.source == TransactionSource.daily,
        ).filter(
            CreditTransaction.created_at >= datetime.combine(today, datetime.min.time())
        ).first()

        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == current_user.id
        ).first()

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
            type=TransactionType.earn,
            source=TransactionSource.daily,
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
            CreditTransaction.source == TransactionSource.ad,
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
            type=TransactionType.earn,
            source=TransactionSource.ad,
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
