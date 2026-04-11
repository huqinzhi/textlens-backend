# Task 08: 积分系统实现

## 任务描述

实现积分余额查询、积分流水分页、每日签到、广告奖励等功能。

## 涉及文件

- `app/features/credits/router.py` - 路由处理器
- `app/features/credits/service.py` - 业务逻辑
- `app/schemas/credit.py` - Pydantic 模型

## 详细任务

### 8.1 创建 Pydantic Schema

```python
# app/schemas/credit.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Literal

class CreditBalanceResponse(BaseModel):
    balance: int
    total_earned: int
    total_spent: int
    today_free_remaining: int
    daily_free_limit: int

class CreditTransactionResponse(BaseModel):
    id: int
    amount: int
    type: Literal["earn", "spend"]
    source: str
    balance_after: int
    description: str | None
    created_at: datetime
    
    class Config:
        from_attributes = True

class PageResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int

class CreditCheckinResponse(BaseModel):
    success: bool
    credits_earned: int = 2
    new_balance: int
    already_checked_in: bool = False

class CreditAdRewardResponse(BaseModel):
    success: bool
    credits_earned: int = 3
    new_balance: int
    remaining_ads: int
```

### 8.2 实现 CreditsService

```python
# app/features/credits/service.py
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage
from app.core.constants import CreditType, CreditSource
from app.core.exceptions import ValidationError
from app.config import Settings

settings = Settings()

class CreditsService:
    """积分服务类"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_balance(self, user_id: str) -> dict:
        """获取积分余额"""
        credit = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()
        
        if not credit:
            return {
                "balance": 0,
                "total_earned": 0,
                "total_spent": 0,
            }
        
        # 计算今日免费剩余次数
        today = datetime.utcnow().strftime("%Y-%m-%d")
        daily_usage = self.db.query(DailyFreeUsage).filter(
            DailyFreeUsage.user_id == user_id,
            DailyFreeUsage.usage_date == today,
        ).first()
        
        used = daily_usage.count if daily_usage else 0
        remaining = max(0, settings.FREE_DAILY_LIMIT - used)
        
        return {
            "balance": credit.balance,
            "total_earned": credit.total_earned,
            "total_spent": credit.total_spent,
            "today_free_remaining": remaining,
            "daily_free_limit": settings.FREE_DAILY_LIMIT,
        }
    
    def get_transactions(self, user_id: str, page: int = 1, page_size: int = 20) -> dict:
        """获取积分流水分页列表"""
        query = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == user_id
        ).order_by(CreditTransaction.created_at.desc())
        
        total = query.count()
        
        transactions = query.offset((page - 1) * page_size).limit(page_size).all()
        
        total_pages = (total + page_size - 1) // page_size
        
        return {
            "items": transactions,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
    
    def checkin(self, user_id: str) -> dict:
        """
        每日签到（+2积分，幂等）
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        # 检查今天是否已签到
        existing = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == user_id,
            CreditTransaction.source == CreditSource.DAILY,
            func.date(CreditTransaction.created_at) == today,
        ).first()
        
        if existing:
            # 已签到，返回当前余额
            credit = self.db.query(CreditAccount).filter(
                CreditAccount.user_id == user_id
            ).first()
            
            return {
                "success": True,
                "credits_earned": 0,
                "new_balance": credit.balance if credit else 0,
                "already_checked_in": True,
            }
        
        # 获取或创建积分账户
        credit = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()
        
        if not credit:
            raise ValidationError("Credit account not found")
        
        credits_to_add = 2
        
        # 更新余额
        credit.balance += credits_to_add
        credit.total_earned += credits_to_add
        
        # 记录流水
        transaction = CreditTransaction(
            user_id=user_id,
            amount=credits_to_add,
            type=CreditType.EARN,
            source=CreditSource.DAILY,
            balance_after=credit.balance,
            description="每日签到",
        )
        self.db.add(transaction)
        self.db.commit()
        
        return {
            "success": True,
            "credits_earned": credits_to_add,
            "new_balance": credit.balance,
            "already_checked_in": False,
        }
    
    def ad_reward(self, user_id: str) -> dict:
        """
        广告奖励（+3积分/次，5次/天上限）
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        # 检查今日广告次数
        today_count = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == user_id,
            CreditTransaction.source == CreditSource.AD,
            func.date(CreditTransaction.created_at) == today,
        ).count()
        
        daily_ad_limit = 5
        
        if today_count >= daily_ad_limit:
            raise ValidationError("Daily ad reward limit exceeded")
        
        # 获取积分账户
        credit = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()
        
        if not credit:
            raise ValidationError("Credit account not found")
        
        credits_to_add = 3
        
        # 更新余额
        credit.balance += credits_to_add
        credit.total_earned += credits_to_add
        
        # 记录流水
        transaction = CreditTransaction(
            user_id=user_id,
            amount=credits_to_add,
            type=CreditType.EARN,
            source=CreditSource.AD,
            balance_after=credit.balance,
            description=f"看广告奖励 ({today_count + 1}/{daily_ad_limit})",
        )
        self.db.add(transaction)
        self.db.commit()
        
        remaining = daily_ad_limit - today_count - 1
        
        return {
            "success": True,
            "credits_earned": credits_to_add,
            "new_balance": credit.balance,
            "remaining_ads": remaining,
        }
```

### 8.3 实现路由处理器

```python
# app/features/credits/router.py
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.user import User
from app.features.credits.service import CreditsService
from app.schemas.credit import (
    CreditBalanceResponse, CreditTransactionResponse, PageResponse,
    CreditCheckinResponse, CreditAdRewardResponse,
)
from app.core.exceptions import ValidationError

router = APIRouter()

@router.get("/balance", response_model=CreditBalanceResponse)
def get_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询积分余额和今日免费次数"""
    service = CreditsService(db)
    return service.get_balance(str(current_user.id))

@router.get("/transactions", response_model=PageResponse)
def get_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """积分流水分页列表"""
    service = CreditsService(db)
    result = service.get_transactions(str(current_user.id), page, page_size)
    
    return PageResponse(
        items=[CreditTransactionResponse.model_validate(t) for t in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )

@router.post("/checkin", response_model=CreditCheckinResponse)
def checkin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """每日签到（+2积分，幂等）"""
    service = CreditsService(db)
    return service.checkin(str(current_user.id))

@router.post("/ad-reward", response_model=CreditAdRewardResponse)
def ad_reward(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """广告奖励（+3积分/次，5次/天上限）"""
    service = CreditsService(db)
    try:
        return service.ad_reward(str(current_user.id))
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
```

## 验收标准

- [ ] GET /credits/balance 返回余额和今日免费次数
- [ ] GET /credits/transactions 返回分页流水
- [ ] POST /credits/checkin 签到成功返回 +2 积分
- [ ] 重复签到幂等返回已签到状态
- [ ] POST /credits/ad-reward 返回 +3 积分
- [ ] 广告奖励达到上限返回错误

## 前置依赖

- Task 04: 认证系统实现

## 后续任务

- Task 09: 支付系统实现
