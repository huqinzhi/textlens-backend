# Task 05: 用户模块实现

## 任务描述

实现用户个人资料查询和更新功能，提供积分快捷查询接口。

## 涉及文件

- `app/features/users/router.py` - 路由处理器
- `app/features/users/service.py` - 业务逻辑
- `app/schemas/user.py` - Pydantic 模型

## 详细任务

### 5.1 扩展 Pydantic Schema

```python
# app/schemas/user.py (添加)
class UserProfileUpdateRequest(BaseModel):
    username: str | None = Field(None, min_length=1, max_length=50)
    avatar_url: str | None = None

class UserProfileDetailResponse(BaseModel):
    id: UUID
    email: str | None
    username: str
    avatar_url: str | None
    auth_provider: str
    is_email_verified: bool
    created_at: datetime
    credit_balance: int = 0
    credit_total_earned: int = 0
    credit_total_spent: int = 0
    
    class Config:
        from_attributes = True

class CreditsQuickResponse(BaseModel):
    balance: int
    today_free_remaining: int
    daily_free_limit: int = 3
```

### 5.2 实现 UserService

```python
# app/features/users/service.py
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.models.credit import CreditAccount, DailyFreeUsage
from app.core.exceptions import ResourceNotFoundError
from app.config import Settings

settings = Settings()

class UserService:
    """用户服务类"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_profile(self, user_id: str) -> dict:
        """
        获取用户个人资料（含积分信息）
        """
        user = self.db.query(User).filter(
            User.id == user_id,
            User.deleted_at.is_(None),
        ).first()
        
        if not user:
            raise ResourceNotFoundError("User not found")
        
        credit = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()
        
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "avatar_url": user.avatar_url,
            "auth_provider": user.auth_provider.value,
            "is_email_verified": user.is_email_verified,
            "created_at": user.created_at,
            "credit_balance": credit.balance if credit else 0,
            "credit_total_earned": credit.total_earned if credit else 0,
            "credit_total_spent": credit.total_spent if credit else 0,
        }
    
    def update_profile(self, user_id: str, username: str | None = None, avatar_url: str | None = None) -> dict:
        """
        更新用户资料
        """
        user = self.db.query(User).filter(
            User.id == user_id,
            User.deleted_at.is_(None),
        ).first()
        
        if not user:
            raise ResourceNotFoundError("User not found")
        
        if username is not None:
            user.username = username
        if avatar_url is not None:
            user.avatar_url = avatar_url
        
        self.db.commit()
        self.db.refresh(user)
        
        return {
            "id": user.id,
            "username": user.username,
            "avatar_url": user.avatar_url,
        }
    
    def get_credits_quick(self, user_id: str) -> dict:
        """
        快捷获取积分信息
        """
        credit = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()
        
        # 计算今日免费剩余次数
        today = datetime.utcnow().strftime("%Y-%m-%d")
        daily_usage = self.db.query(DailyFreeUsage).filter(
            DailyFreeUsage.user_id == user_id,
            DailyFreeUsage.usage_date == today,
        ).first()
        
        used = daily_usage.count if daily_usage else 0
        remaining = max(0, settings.FREE_DAILY_LIMIT - used)
        
        return {
            "balance": credit.balance if credit else 0,
            "today_free_remaining": remaining,
            "daily_free_limit": settings.FREE_DAILY_LIMIT,
        }
```

### 5.3 实现路由处理器

```python
# app/features/users/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.user import User
from app.features.users.service import UserService
from app.schemas.user import (
    UserProfileDetailResponse, UserProfileUpdateRequest, CreditsQuickResponse,
)

router = APIRouter()

@router.get("/profile", response_model=UserProfileDetailResponse)
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取个人资料（含积分余额）"""
    service = UserService(db)
    return service.get_profile(str(current_user.id))

@router.put("/profile", response_model=UserProfileDetailResponse)
def update_profile(
    request: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新用户名和头像"""
    service = UserService(db)
    return service.update_profile(
        user_id=str(current_user.id),
        username=request.username,
        avatar_url=request.avatar_url,
    )

@router.get("/credits", response_model=CreditsQuickResponse)
def get_credits_quick(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """快捷获取积分信息"""
    service = UserService(db)
    return service.get_credits_quick(str(current_user.id))
```

## 验收标准

- [ ] GET /users/profile 返回完整用户信息和积分余额
- [ ] PUT /users/profile 可更新 username 和 avatar_url
- [ ] GET /users/credits 返回积分余额和今日免费次数

## 前置依赖

- Task 04: 认证系统实现

## 后续任务

- Task 06: OCR 模块实现
