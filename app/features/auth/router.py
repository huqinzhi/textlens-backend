"""
认证模块路由
处理用户注册、登录、登出、Token刷新、账号注销等认证相关接口
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    GoogleOAuthRequest,
    AppleOAuthRequest,
)
from app.features.auth.service import AuthService

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    """
    用户邮箱注册接口

    创建新用户账号，发放首次注册奖励积分（+10），
    返回 JWT Access Token 和 Refresh Token。

    [request] 注册请求体，包含邮箱、密码和合规确认
    [db] 数据库会话
    返回 TokenResponse 包含登录所需的 JWT 令牌
    """
    auth_service = AuthService(db)
    return await auth_service.register(request)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: UserLoginRequest,
    db: Session = Depends(get_db),
):
    """
    用户邮箱登录接口

    验证邮箱和密码，登录成功后返回 JWT Token 对。

    [request] 登录请求体，包含邮箱和密码
    [db] 数据库会话
    返回 TokenResponse 包含 JWT 令牌
    """
    auth_service = AuthService(db)
    return await auth_service.login(request)


@router.post("/login/google", response_model=TokenResponse)
async def login_with_google(
    request: GoogleOAuthRequest,
    db: Session = Depends(get_db),
):
    """
    Google OAuth 登录接口

    验证 Google ID Token，首次登录时自动注册账号。

    [request] 包含 Google ID Token 的请求体
    [db] 数据库会话
    返回 TokenResponse 包含 JWT 令牌
    """
    auth_service = AuthService(db)
    return await auth_service.login_with_google(request.id_token)


@router.post("/login/apple", response_model=TokenResponse)
async def login_with_apple(
    request: AppleOAuthRequest,
    db: Session = Depends(get_db),
):
    """
    Apple Sign In 登录接口

    验证 Apple Identity Token，首次登录时自动注册账号。
    iOS 应用强制要求提供 Apple 登录选项。

    [request] 包含 Apple Identity Token 的请求体
    [db] 数据库会话
    返回 TokenResponse 包含 JWT 令牌
    """
    auth_service = AuthService(db)
    return await auth_service.login_with_apple(request)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    刷新 Access Token 接口

    使用有效的 Refresh Token 获取新的 Access Token，
    同时更新 Refresh Token（滚动刷新策略）。

    [request] 包含 Refresh Token 的请求体
    [db] 数据库会话
    返回 TokenResponse 包含新的 JWT 令牌对
    """
    auth_service = AuthService(db)
    return await auth_service.refresh_access_token(request.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    refresh_token: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """
    用户登出接口

    将 Refresh Token 加入黑名单，使其失效。
    客户端应同时清除本地存储的 Token。

    [refresh_token] 需要撤销的 Refresh Token
    [db] 数据库会话
    """
    auth_service = AuthService(db)
    await auth_service.logout(refresh_token)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    db: Session = Depends(get_db),
    current_user=Depends(AuthService.get_current_user_dep),
):
    """
    注销账号接口（GDPR 合规）

    软删除用户账号，标记为待删除状态。
    30天内完成数据彻底清除（由定时任务处理）。

    [current_user] 当前登录用户（通过 JWT 验证）
    [db] 数据库会话
    """
    auth_service = AuthService(db)
    await auth_service.delete_account(current_user)
