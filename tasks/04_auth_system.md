# Task 04: 认证系统实现 (JWT + OAuth)

## 任务描述

实现完整的认证系统，包括邮箱注册/登录、Google OAuth 登录、Apple Sign In、JWT Token 管理、Refresh Token 滚动刷新和账户注销。

## 涉及文件

- `app/features/auth/router.py` - 路由处理器
- `app/features/auth/service.py` - 业务逻辑
- `app/core/security.py` - JWT 和密码工具函数
- `app/schemas/user.py` - Pydantic 请求/响应模型

## 详细任务

### 4.1 创建 Pydantic Schema

```python
# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from uuid import UUID

class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    username: str = Field(..., min_length=1, max_length=50)
    age_verified: bool = True  # COPPA 合规
    terms_accepted: bool = True
    privacy_accepted: bool = True

class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str

class GoogleAuthRequest(BaseModel):
    id_token: str

class AppleAuthRequest(BaseModel):
    id_token: str
    authorization_code: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class UserProfileResponse(BaseModel):
    id: UUID
    email: str | None
    username: str
    avatar_url: str | None
    auth_provider: str
    is_email_verified: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
```

### 4.2 实现 JWT 和密码工具

```python
# app/core/security.py
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

import bcrypt
import jwt
from jwt.exceptions import PyJWTError

from app.config import Settings

settings = Settings()

def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码，cost factor 12"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()

def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """创建 Access Token (24小时)"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=24))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token() -> tuple[str, str]:
    """创建 Refresh Token，返回 (raw_token, hash)"""
    raw = secrets.token_urlsafe(64)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed

def verify_access_token(token: str) -> dict[str, Any] | None:
    """验证 Access Token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except PyJWTError:
        return None

def verify_refresh_token(raw_token: str, stored_hash: str) -> bool:
    """验证 Refresh Token"""
    return hashlib.sha256(raw_token.encode()).hexdigest() == stored_hash
```

### 4.3 实现 AuthService

```python
# app/features/auth/service.py
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import select, update

from app.db.models.user import User, RefreshToken
from app.db.models.credit import CreditAccount
from app.core.security import (
    hash_password, verify_password, 
    create_access_token, create_refresh_token, verify_refresh_token,
)
from app.core.constants import AuthProvider, CreditType, CreditSource
from app.core.exceptions import (
    AuthenticationError, ValidationError, ResourceNotFoundError,
)
from app.config import Settings

settings = Settings()

class AuthService:
    """认证服务类"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def register(self, email: str, password: str, username: str) -> tuple[User, str, str]:
        """
        用户注册
        
        返回 (user, access_token, refresh_token)
        """
        # 检查邮箱是否已存在
        existing = self.db.query(User).filter(User.email == email).first()
        if existing:
            raise ValidationError("Email already registered")
        
        # 创建用户
        user = User(
            email=email,
            password_hash=hash_password(password),
            username=username,
            auth_provider=AuthProvider.EMAIL,
            is_email_verified=True,  # 简化处理
        )
        self.db.add(user)
        self.db.flush()
        
        # 创建积分账户并发放注册奖励
        credit_account = CreditAccount(
            user_id=user.id,
            balance=settings.CREDITS_INITIAL_BONUS,
            total_earned=settings.CREDITS_INITIAL_BONUS,
        )
        self.db.add(credit_account)
        
        # 记录积分变动
        transaction = CreditTransaction(
            user_id=user.id,
            amount=settings.CREDITS_INITIAL_BONUS,
            type=CreditType.EARN,
            source=CreditSource.REGISTER,
            balance_after=settings.CREDITS_INITIAL_BONUS,
            description="注册奖励",
        )
        self.db.add(transaction)
        
        # 生成 Token
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token, refresh_hash = create_refresh_token()
        
        # 存储 Refresh Token
        rt = RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        self.db.add(rt)
        
        self.db.commit()
        return user, access_token, refresh_token
    
    def login(self, email: str, password: str) -> tuple[User, str, str]:
        """
        用户登录
        """
        user = self.db.query(User).filter(
            User.email == email,
            User.deleted_at.is_(None),
        ).first()
        
        if not user or not user.password_hash:
            raise AuthenticationError("Invalid email or password")
        
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        
        if not user.is_active:
            raise AuthenticationError("Account is disabled")
        
        # 生成新 Token
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token, refresh_hash = create_refresh_token()
        
        # 吊销旧的 Refresh Token
        self.db.query(RefreshToken).filter(
            RefreshToken.user_id == user.id,
            RefreshToken.is_revoked == False,
        ).update({"is_revoked": True})
        
        # 存储新 Refresh Token
        rt = RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        self.db.add(rt)
        
        self.db.commit()
        return user, access_token, refresh_token
    
    def google_auth(self, id_token: str) -> tuple[User, str, str]:
        """
        Google OAuth 登录/注册
        """
        # 验证 Google ID Token (简化，实际应使用 google-auth 库)
        payload = verify_google_token(id_token)
        if not payload:
            raise AuthenticationError("Invalid Google token")
        
        email = payload.get("email")
        google_sub = payload.get("sub")
        
        # 查找或创建用户
        user = self.db.query(User).filter(
            User.email == email,
            User.deleted_at.is_(None),
        ).first()
        
        if not user:
            # 创建新用户
            user = User(
                email=email,
                username=payload.get("name", "User"),
                avatar_url=payload.get("picture"),
                auth_provider=AuthProvider.GOOGLE,
                provider_user_id=google_sub,
                is_email_verified=True,
            )
            self.db.add(user)
            self.db.flush()
            
            # 创建积分账户
            credit_account = CreditAccount(
                user_id=user.id,
                balance=settings.CREDITS_INITIAL_BONUS,
                total_earned=settings.CREDITS_INITIAL_BONUS,
            )
            self.db.add(credit_account)
            
            transaction = CreditTransaction(
                user_id=user.id,
                amount=settings.CREDITS_INITIAL_BONUS,
                type=CreditType.EARN,
                source=CreditSource.REGISTER,
                balance_after=settings.CREDITS_INITIAL_BONUS,
                description="注册奖励",
            )
            self.db.add(transaction)
        
        # 生成 Token
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token, refresh_hash = create_refresh_token()
        
        rt = RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        self.db.add(rt)
        
        self.db.commit()
        return user, access_token, refresh_token
    
    def refresh_tokens(self, raw_refresh_token: str) -> tuple[str, str]:
        """
        滚动刷新 Refresh Token
        返回 (new_access_token, new_refresh_token)
        """
        # 查找有效的 Refresh Token
        token_hash = hashlib.sha256(raw_refresh_token.encode()).hexdigest()
        rt = self.db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > datetime.utcnow(),
        ).first()
        
        if not rt:
            raise AuthenticationError("Invalid or expired refresh token")
        
        user_id = rt.user_id
        
        # 吊销旧 Token
        rt.is_revoked = True
        
        # 生成新 Token
        access_token = create_access_token({"sub": str(user_id)})
        new_refresh_token, new_hash = create_refresh_token()
        
        new_rt = RefreshToken(
            user_id=user_id,
            token_hash=new_hash,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        self.db.add(new_rt)
        
        self.db.commit()
        return access_token, new_refresh_token
    
    def logout(self, user_id: str) -> None:
        """
        登出，吊销所有 Refresh Token
        """
        self.db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.is_revoked == False,
        ).update({"is_revoked": True})
        self.db.commit()
    
    def delete_account(self, user_id: str) -> None:
        """
        注销账户 (GDPR 软删除)
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if user:
            user.deleted_at = datetime.utcnow()
            user.is_active = False
            self.db.commit()
```

### 4.4 实现路由处理器

```python
# app/features/auth/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.user import User
from app.features.auth.service import AuthService
from app.schemas.user import (
    UserRegisterRequest, UserLoginRequest, GoogleAuthRequest,
    AppleAuthRequest, TokenResponse, RefreshTokenRequest,
)
from app.core.exceptions import AuthenticationError, ValidationError

router = APIRouter()

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """邮箱注册"""
    # COPPA 合规检查
    if not request.age_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "COPPA_VIOLATION", "message": "Must be 13 or older"},
        )
    
    service = AuthService(db)
    try:
        user, access_token, refresh_token = service.register(
            email=request.email,
            password=request.password,
            username=request.username,
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "VALIDATION_ERROR", "message": str(e)})

@router.post("/login", response_model=TokenResponse)
def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """邮箱密码登录"""
    service = AuthService(db)
    try:
        user, access_token, refresh_token = service.login(
            email=request.email,
            password=request.password,
        )
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": str(e)})

@router.post("/google", response_model=TokenResponse)
def google_auth(request: GoogleAuthRequest, db: Session = Depends(get_db)):
    """Google OAuth 登录"""
    service = AuthService(db)
    try:
        user, access_token, refresh_token = service.google_auth(request.id_token)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": str(e)})

@router.post("/refresh", response_model=TokenResponse)
def refresh(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """刷新 Access Token"""
    service = AuthService(db)
    try:
        access_token, refresh_token = service.refresh_tokens(request.refresh_token)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": str(e)})

@router.post("/logout")
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """登出"""
    service = AuthService(db)
    service.logout(str(current_user.id))
    return {"message": "Logged out successfully"}

@router.delete("/account")
def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """注销账户 (GDPR)"""
    service = AuthService(db)
    service.delete_account(str(current_user.id))
    return {"message": "Account scheduled for deletion"}
```

## 验收标准

- [ ] 邮箱注册成功并返回 Token
- [ ] 注册时正确发放初始积分
- [ ] 邮箱登录返回 Token
- [ ] Google OAuth 登录/注册流程正确
- [ ] Refresh Token 滚动刷新正常工作
- [ ] 登出后 Refresh Token 被吊销
- [ ] 账户注销执行软删除

## 前置依赖

- Task 01: 项目基础架构搭建
- Task 02: 数据库模型设计

## 后续任务

- Task 05: 用户模块实现
