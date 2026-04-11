"""
认证模块路由
处理用户注册、登录、登出、Token刷新、账号注销等认证相关接口
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    GoogleOAuthRequest,
    AppleOAuthRequest,
    SendVerifyCodeRequest,
    VerifyCodeRequest,
    VerifyCodeResponse,
    SendCodeResponse,
    RegisterCompleteRequest,
    LoginCodeRequest,
    LoginVerifyRequest,
    PasswordResetSendRequest,
    PasswordResetConfirmV2Request,
)
from app.features.auth.service import AuthService
from app.db.models.user import User

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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


# ── 邮箱验证码接口 ──────────────────────────────────────────────────


@router.post("/verify/send", response_model=SendCodeResponse)
async def send_verification_code(
    request: SendVerifyCodeRequest,
    db: Session = Depends(get_db),
):
    """
    发送邮箱验证码接口

    向指定邮箱发送验证码，支持注册、登录、密码重置三种场景。
    同一邮箱同一场景60秒内不能重复发送，每天最多发送10次。

    [request] 发送验证码请求体
    [db] 数据库会话
    返回 SendCodeResponse 包含发送结果和有效期
    """
    auth_service = AuthService(db)
    await auth_service.send_verification_code(request.email, request.scene)
    expires_in_map = {
        "register": 600,
        "login": 300,
        "reset_password": 900,
    }
    return SendCodeResponse(
        message="验证码已发送至邮箱",
        expires_in=expires_in_map.get(request.scene, 600),
    )


@router.post("/verify/check", response_model=VerifyCodeResponse)
async def check_verification_code(
    request: VerifyCodeRequest,
    db: Session = Depends(get_db),
):
    """
    验证邮箱验证码接口

    校验用户输入的验证码是否正确，验证成功后返回临时 Token。

    [request] 验证请求体
    [db] 数据库会话
    返回 VerifyCodeResponse 验证结果和临时 Token
    """
    auth_service = AuthService(db)
    verified = await auth_service.verify_code(request.email, request.scene, request.code)

    if verified:
        # 验证成功后生成临时 Token
        token = auth_service._create_verify_token(request.email, request.scene)
        return VerifyCodeResponse(valid=True, token=token)

    return VerifyCodeResponse(valid=False)


@router.post("/register/complete", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_complete(
    request: RegisterCompleteRequest,
    db: Session = Depends(get_db),
):
    """
    完成注册接口（验证码验证后）

    使用验证码验证后获得的临时 Token 完成注册，
    创建用户账号并发放首次注册奖励积分。

    [request] 完成注册请求体
    [db] 数据库会话
    返回 TokenResponse 包含登录所需的 JWT 令牌
    """
    auth_service = AuthService(db)
    return await auth_service.register_with_verified_email(request)


@router.post("/login/code", response_model=SendCodeResponse)
async def request_login_code(
    request: LoginCodeRequest,
    db: Session = Depends(get_db),
):
    """
    请求登录验证码接口

    向指定邮箱发送登录验证码（仅限已注册用户）。

    [request] 请求登录验证码请求体
    [db] 数据库会话
    返回 SendCodeResponse 包含发送结果和有效期
    """
    auth_service = AuthService(db)
    await auth_service.send_verification_code(request.email, "login")
    return SendCodeResponse(
        message="验证码已发送至邮箱",
        expires_in=300,
    )


@router.post("/login/verify", response_model=TokenResponse)
async def verify_login_code(
    request: LoginVerifyRequest,
    db: Session = Depends(get_db),
):
    """
    验证登录验证码接口

    校验登录验证码，验证成功后返回 JWT Token。

    [request] 登录验证码验证请求体
    [db] 数据库会话
    返回 TokenResponse 包含登录所需的 JWT 令牌
    """
    auth_service = AuthService(db)
    await auth_service.verify_code(request.email, "login", request.code)
    # 验证成功后直接登录
    return await auth_service.login_with_verified_email(request.email)


@router.post("/password/reset/send", response_model=SendCodeResponse)
async def request_password_reset(
    request: PasswordResetSendRequest,
    db: Session = Depends(get_db),
):
    """
    请求密码重置验证码接口

    向指定邮箱发送密码重置验证码。

    [request] 请求密码重置验证码请求体
    [db] 数据库会话
    返回 SendCodeResponse 包含发送结果和有效期
    """
    auth_service = AuthService(db)
    await auth_service.send_verification_code(request.email, "reset_password")
    return SendCodeResponse(
        message="验证码已发送至邮箱",
        expires_in=900,
    )


@router.post("/password/reset/confirm", response_model=TokenResponse)
async def confirm_password_reset(
    request: PasswordResetConfirmV2Request,
    db: Session = Depends(get_db),
):
    """
    确认密码重置接口

    使用验证码验证后获得的临时 Token 重置密码。

    [request] 确认密码重置请求体
    [db] 数据库会话
    返回 TokenResponse 重置成功后返回登录令牌
    """
    auth_service = AuthService(db)
    return await auth_service.reset_password_with_verified_email(request)
