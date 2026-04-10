"""
积分模块路由
处理积分余额查询、每日签到、广告奖励、积分明细等接口
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.credit import (
    CreditBalanceResponse,
    CreditTransactionListResponse,
    AdRewardRequest,
    DailyCheckinResponse,
)
from app.features.credits.service import CreditService

router = APIRouter()


@router.get("/balance", response_model=CreditBalanceResponse)
async def get_credit_balance(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    查询积分余额接口

    返回用户当前积分余额、累计数据和今日免费次数剩余。

    [current_user] 当前登录用户
    [db] 数据库会话
    返回 CreditBalanceResponse 积分余额详情
    """
    credit_service = CreditService(db)
    return await credit_service.get_balance(current_user)


@router.get("/transactions", response_model=CreditTransactionListResponse)
async def get_credit_transactions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    查询积分流水明细接口

    分页返回用户所有积分变动记录（获取和消耗）。

    [page] 页码，从 1 开始
    [page_size] 每页记录数，最大 100
    [current_user] 当前登录用户
    [db] 数据库会话
    返回 CreditTransactionListResponse 积分流水分页列表
    """
    credit_service = CreditService(db)
    return await credit_service.get_transactions(current_user, page, page_size)


@router.post("/checkin", response_model=DailyCheckinResponse)
async def daily_checkin(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    每日签到接口

    每天首次签到奖励 +2 积分，培养用户打开习惯。
    当天已签到则返回 credits_earned=0。

    [current_user] 当前登录用户
    [db] 数据库会话
    返回 DailyCheckinResponse 签到结果和当前余额
    """
    credit_service = CreditService(db)
    return await credit_service.daily_checkin(current_user)


@router.post("/ad-reward")
async def ad_reward(
    request: AdRewardRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    广告激励积分奖励接口

    用户观看完整激励视频广告后，奖励 +3 积分。
    每日上限 5 次（即每日最多 +15 积分）。

    [request] 广告奖励请求体（包含广告单元 ID）
    [current_user] 当前登录用户
    [db] 数据库会话
    返回 包含获得积分数和新余额的字典
    """
    credit_service = CreditService(db)
    return await credit_service.ad_reward(current_user, request.ad_unit_id)
