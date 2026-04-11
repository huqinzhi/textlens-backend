"""
用户相关 Pydantic 数据模型
定义用户注册、登录、响应等数据结构
"""
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from datetime import datetime
import uuid


class UserRegisterRequest(BaseModel):
    """
    用户注册请求体

    [email] 邮箱地址
    [password] 密码，至少8位
    [username] 用户名（可选）
    [age_verified] 年龄验证（COPPA合规，13岁以上）
    [terms_accepted] 是否同意用户协议
    [privacy_accepted] 是否同意隐私政策
    [invite_code] 邀请码（可选，用于邀请好友奖励）
    """
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    username: Optional[str] = Field(None, max_length=50)
    age_verified: bool
    terms_accepted: bool
    privacy_accepted: bool
    invite_code: Optional[str] = Field(None, max_length=20, description="邀请码")


class UserLoginRequest(BaseModel):
    """
    用户邮箱登录请求体

    [email] 邮箱地址
    [password] 登录密码
    """
    email: EmailStr
    password: str


class GoogleOAuthRequest(BaseModel):
    """
    Google OAuth 登录请求体

    [id_token] Google 返回的 ID Token
    """
    id_token: str


class AppleOAuthRequest(BaseModel):
    """
    Apple OAuth 登录请求体

    [identity_token] Apple 返回的身份令牌
    [authorization_code] Apple 授权码
    [full_name] 用户全名（首次登录时 Apple 会提供）
    """
    identity_token: str
    authorization_code: str
    full_name: Optional[str] = None


class TokenResponse(BaseModel):
    """
    登录成功响应，包含 JWT Token

    [access_token] 访问令牌，有效期24小时
    [refresh_token] 刷新令牌，有效期30天
    [token_type] 令牌类型，固定为 "bearer"
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """
    刷新 Token 请求体

    [refresh_token] 有效的 Refresh Token
    """
    refresh_token: str


class UserResponse(BaseModel):
    """
    用户信息响应体
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    username: Optional[str]
    avatar_url: Optional[str]
    is_email_verified: bool
    created_at: datetime


class UserProfileResponse(UserResponse):
    """
    用户个人中心详细信息响应体（包含积分信息）

    [credit_balance] 积分余额
    [daily_free_remaining] 今日剩余免费次数
    """
    credit_balance: int = 0
    daily_free_remaining: int = 0


class UserUpdateRequest(BaseModel):
    """
    更新用户信息请求体

    [username] 新的用户名
    [avatar_url] 新的头像 URL
    """
    username: Optional[str] = Field(None, max_length=50)
    avatar_url: Optional[str] = None


class PasswordResetRequest(BaseModel):
    """
    重置密码请求体

    [email] 接收重置邮件的邮箱地址
    """
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    """
    确认重置密码请求体

    [token] 邮件中的重置令牌
    [new_password] 新密码，至少8位
    """
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)
