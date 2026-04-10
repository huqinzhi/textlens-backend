"""
积分相关 Pydantic 数据模型
定义积分余额、流水明细、购买套餐等数据结构
"""
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from app.core.constants import CreditTransactionType, CreditSourceType


class CreditBalanceResponse(BaseModel):
    """
    积分余额响应体

    [balance] 当前积分余额
    [total_earned] 累计获得积分
    [total_spent] 累计消费积分
    [daily_free_remaining] 今日剩余免费次数
    [daily_ad_remaining] 今日剩余看广告次数
    """
    balance: int
    total_earned: int
    total_spent: int
    daily_free_remaining: int
    daily_ad_remaining: int


class CreditTransactionItem(BaseModel):
    """
    积分流水单条记录响应体
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: int
    type: CreditTransactionType
    source: CreditSourceType
    description: Optional[str]
    balance_after: int
    created_at: datetime


class CreditTransactionListResponse(BaseModel):
    """
    积分流水列表响应体
    """
    items: List[CreditTransactionItem]
    total: int
    page: int
    page_size: int


class AdRewardRequest(BaseModel):
    """
    广告奖励积分请求体

    [ad_unit_id] 广告单元 ID（用于验证广告观看真实性）
    [ad_provider] 广告提供商（admob）
    """
    ad_unit_id: str
    ad_provider: str = "admob"


class DailyCheckinResponse(BaseModel):
    """
    每日签到响应体

    [credits_earned] 本次签到获得积分
    [current_balance] 签到后积分余额
    [streak_days] 连续签到天数
    """
    credits_earned: int
    current_balance: int
    streak_days: int


class CreditPackageItem(BaseModel):
    """
    积分套餐信息

    [id] 套餐 ID
    [name] 套餐名称
    [price_usd] 价格（美元）
    [credits] 基础积分
    [bonus] 赠送积分
    [total_credits] 实际获得积分（credits + bonus）
    [is_popular] 是否为推荐套餐
    """
    id: str
    name: str
    price_usd: float
    credits: int
    bonus: int
    total_credits: int
    is_popular: bool = False
