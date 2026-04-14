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
    [has_free_generation] 是否有免费生成次数
    """
    credit_balance: int = 0
    has_free_generation: bool = True


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


class SendVerifyCodeRequest(BaseModel):
    """
    发送验证码请求体

    [email] 目标邮箱地址
    [scene] 验证场景 (register/login/reset_password)
    """
    email: EmailStr
    scene: str = Field(..., pattern="^(register|login|reset_password)$")


class VerifyCodeRequest(BaseModel):
    """
    验证验证码请求体

    [email] 目标邮箱地址
    [scene] 验证场景
    [code] 用户输入的验证码
    """
    email: EmailStr
    scene: str = Field(..., pattern="^(register|login|reset_password)$")
    code: str = Field(..., min_length=6, max_length=6)


class VerifyCodeResponse(BaseModel):
    """
    验证码验证成功响应

    [valid] 验证是否成功
    [token] 验证成功后返回的临时 Token
    """
    valid: bool
    token: Optional[str] = None


class SendCodeResponse(BaseModel):
    """
    发送验证码响应

    [message] 提示信息
    [expires_in] 验证码有效期（秒）
    """
    message: str
    expires_in: int


class RegisterCompleteRequest(BaseModel):
    """
    完成注册请求体（验证码验证后）

    [verify_token] 验证码验证后获得的临时 Token
    [password] 密码，至少8位
    [username] 用户名（可选）
    [age_verified] 年龄验证（COPPA合规，13岁以上）
    [terms_accepted] 是否同意用户协议
    [privacy_accepted] 是否同意隐私政策
    [invite_code] 邀请码（可选）
    """
    verify_token: str
    password: str = Field(..., min_length=8, max_length=100)
    username: Optional[str] = Field(None, max_length=50)
    age_verified: bool
    terms_accepted: bool
    privacy_accepted: bool
    invite_code: Optional[str] = Field(None, max_length=20)


class LoginCodeRequest(BaseModel):
    """
    请求登录验证码请求体

    [email] 登录邮箱地址
    """
    email: EmailStr


class LoginVerifyRequest(BaseModel):
    """
    验证登录验证码请求体

    [email] 登录邮箱地址
    [code] 验证码
    """
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class PasswordResetSendRequest(BaseModel):
    """
    发送密码重置验证码请求体

    [email] 注册邮箱地址
    """
    email: EmailStr


class PasswordResetConfirmV2Request(BaseModel):
    """
    确认重置密码请求体（验证码模式）

    [verify_token] 验证码验证后获得的临时 Token
    [new_password] 新密码，至少8位
    """
    verify_token: str
    new_password: str = Field(..., min_length=8, max_length=100)
