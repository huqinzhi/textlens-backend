"""
认证业务逻辑服务层
处理用户注册、登录、第三方OAuth、Token管理等核心业务逻辑
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.db.models.user import User, RefreshToken, AuthProvider
from app.db.models.credit import CreditAccount, CreditTransaction
from app.db.models.image import GenerationTask, Image, OCRResult  # noqa - 避免 SQLAlchemy relationship 循环引用
from app.db.models.payment import PurchaseRecord  # noqa - 避免 SQLAlchemy relationship 循环引用
from app.core.constants import CreditTransactionType, CreditSourceType
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, verify_refresh_token
from app.core.exceptions import AuthenticationError, ValidationError
from app.schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    AppleOAuthRequest,
    RegisterCompleteRequest,
    PasswordResetConfirmV2Request,
)
from app.config import settings
from jose import jwt as jose_jwt, JWTError
import uuid
import hashlib


class AuthService:
    """
    认证服务类

    封装所有认证相关的业务逻辑，包括邮箱注册登录、OAuth登录、Token管理。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db

    async def register(self, request: UserRegisterRequest) -> TokenResponse:
        """
        用户邮箱注册

        创建新用户账号，初始化积分账户（发放首次注册积分），
        如果提供了邀请码则给邀请人发放奖励。

        [request] 注册请求数据
        返回 TokenResponse JWT 令牌对
        """
        # 验证合规性
        if not request.age_verified:
            raise ValidationError("You must be 13 or older to use TextLens (COPPA compliance)")
        if not request.terms_accepted or not request.privacy_accepted:
            raise ValidationError("You must accept the Terms of Service and Privacy Policy")

        # 检查邮箱是否已注册
        existing_user = self.db.query(User).filter(User.email == request.email).first()
        if existing_user:
            raise ValidationError("Email already registered")

        # 处理邀请码：查找邀请人
        inviter = None
        if request.invite_code:
            inviter = self.db.query(User).filter(User.invite_code == request.invite_code).first()

        # 创建用户
        user = User(
            id=uuid.uuid4(),
            email=request.email,
            password_hash=hash_password(request.password),
            username=request.username,
            auth_provider=AuthProvider.EMAIL,
            age_verified=True,
            terms_accepted_at=datetime.now(timezone.utc),
            privacy_accepted_at=datetime.now(timezone.utc),
            invited_by=inviter.id if inviter else None,
        )
        self.db.add(user)
        self.db.flush()  # 获取 user.id

        # 初始化积分账户，发放注册奖励积分
        credit_account = CreditAccount(
            user_id=user.id,
            balance=settings.CREDITS_INITIAL_BONUS,
            total_earned=settings.CREDITS_INITIAL_BONUS,
            total_spent=0,
        )
        self.db.add(credit_account)
        self.db.flush()

        # 记录积分流水
        transaction = CreditTransaction(
            user_id=user.id,
            credit_account_id=credit_account.id,
            amount=settings.CREDITS_INITIAL_BONUS,
            type=CreditTransactionType.EARN,
            source=CreditSourceType.REGISTER,
            description=f"Welcome bonus: +{settings.CREDITS_INITIAL_BONUS} credits",
            balance_after=settings.CREDITS_INITIAL_BONUS,
        )
        self.db.add(transaction)

        # 如果有邀请人，发放邀请奖励
        if inviter:
            self._award_invite_reward(inviter.id, user.id)

        self.db.commit()

        # 生成 Token 对
        return self._generate_tokens(user)

    async def login(self, request: UserLoginRequest) -> TokenResponse:
        """
        用户邮箱密码登录

        验证邮箱和密码，更新最后登录时间。

        [request] 登录请求数据（邮箱+密码）
        返回 TokenResponse JWT 令牌对
        """
        user = self.db.query(User).filter(
            User.email == request.email,
            User.deleted_at.is_(None),
            User.is_active == True,
        ).first()

        if not user or not verify_password(request.password, user.password_hash or ""):
            raise AuthenticationError("Invalid email or password")

        # 更新最后登录时间
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()

        return self._generate_tokens(user)

    async def login_with_google(self, id_token: str) -> TokenResponse:
        """
        Google OAuth 登录

        验证 Google ID Token，首次登录时自动创建账号。

        [id_token] Google 返回的 ID Token
        返回 TokenResponse JWT 令牌对
        """
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        try:
            # 验证 Google ID Token
            idinfo = google_id_token.verify_oauth2_token(
                id_token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
            google_user_id = idinfo["sub"]
            email = idinfo.get("email")
            name = idinfo.get("name")
            picture = idinfo.get("picture")
        except Exception as e:
            raise AuthenticationError(f"Invalid Google token: {str(e)}")

        # 查找或创建用户
        user = self.db.query(User).filter(
            User.provider_user_id == google_user_id,
            User.auth_provider == AuthProvider.GOOGLE,
        ).first()

        if not user:
            # 首次登录，自动注册
            user = self._create_oauth_user(
                email=email,
                username=name,
                avatar_url=picture,
                provider=AuthProvider.GOOGLE,
                provider_user_id=google_user_id,
            )

        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()

        return self._generate_tokens(user)

    async def login_with_apple(self, request: AppleOAuthRequest) -> TokenResponse:
        """
        Apple Sign In 登录

        验证 Apple Identity Token，首次登录时自动创建账号。
        iOS 应用上架强制要求提供此登录选项。

        [request] Apple 登录请求数据
        返回 TokenResponse JWT 令牌对
        """
        import jwt

        try:
            # 解码 Apple Identity Token
            # 注意：生产环境应启用签名验证，需要从 Apple 获取公钥
            # 参考: https://developer.apple.com/documentation/sign_in_with_apple/sign_in_with_apple_rest_api
            # 实现方案：使用 apple-signin-request 库或手动获取 Apple JWKS 公钥验证
            if settings.APPLE_SIGN_IN_VERIFY_SIGNATURE:
                # 生产环境：验证签名（需要配置完整的 Apple 公钥获取逻辑）
                # 当前为占位实现，生产部署前需完成
                decoded = jwt.decode(
                    request.identity_token,
                    options={"verify_signature": False},  # TODO: 实现完整签名验证
                    algorithms=["RS256"],
                )
            else:
                # 开发环境：仅解码提取信息
                decoded = jwt.decode(
                    request.identity_token,
                    options={"verify_signature": False},
                    algorithms=["RS256"],
                )

            apple_user_id = decoded.get("sub")
            email = decoded.get("email")
            # Apple 可能在首次登录时提供全名
            full_name = getattr(request, 'full_name', None)

            if not apple_user_id:
                raise AuthenticationError("Invalid Apple token: missing subject")

        except jwt.exceptions.DecodeError:
            raise AuthenticationError("Invalid Apple token format")

        # 查找或创建用户
        user = self.db.query(User).filter(
            User.provider_user_id == apple_user_id,
            User.auth_provider == AuthProvider.APPLE,
        ).first()

        if not user:
            # 首次登录，自动注册
            username = full_name if full_name else f"User_{apple_user_id[:8]}"
            user = self._create_oauth_user(
                email=email,
                username=username,
                avatar_url=None,
                provider=AuthProvider.APPLE,
                provider_user_id=apple_user_id,
            )

        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()

        return self._generate_tokens(user)

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        """
        刷新 Access Token

        使用有效的 Refresh Token 获取新的 Access Token。
        采用滚动刷新策略，每次刷新都会生成新的 Refresh Token。

        [refresh_token] 有效的 Refresh Token 字符串
        返回 TokenResponse 新的 JWT 令牌对
        """
        # 验证 Refresh Token 签名
        user_id = verify_refresh_token(refresh_token)
        if not user_id:
            raise AuthenticationError("Invalid or expired refresh token")

        # 检查 Token 是否在黑名单中
        token_hash = self._hash_token(refresh_token)
        stored_token = self.db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,
        ).first()

        if not stored_token:
            raise AuthenticationError("Refresh token has been revoked")

        # 获取用户
        user = self.db.query(User).filter(
            User.id == user_id,
            User.is_active == True,
            User.deleted_at.is_(None),
        ).first()

        if not user:
            raise AuthenticationError("User not found")

        # 撤销旧 Token，生成新 Token 对（滚动刷新）
        stored_token.is_revoked = True
        self.db.commit()

        return self._generate_tokens(user)

    async def logout(self, refresh_token: str) -> None:
        """
        用户登出，撤销 Refresh Token

        [refresh_token] 需要撤销的 Refresh Token
        """
        token_hash = self._hash_token(refresh_token)
        stored_token = self.db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash
        ).first()
        if stored_token:
            stored_token.is_revoked = True
            self.db.commit()

    async def delete_account(self, user: User) -> None:
        """
        软删除用户账号

        标记账号为待删除状态，30天后由定时任务彻底清除数据（GDPR合规）。

        [user] 当前登录用户 ORM 对象
        """
        user.deleted_at = datetime.now(timezone.utc)
        user.is_active = False
        self.db.commit()

    def _generate_tokens(self, user: User) -> TokenResponse:
        """
        为用户生成 JWT Token 对，并持久化 Refresh Token

        [user] 用户 ORM 对象
        返回 TokenResponse 包含 access_token 和 refresh_token
        """
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token = create_refresh_token(str(user.id))

        # 持久化 Refresh Token
        token_hash = self._hash_token(refresh_token)
        stored_token = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        )
        self.db.add(stored_token)
        self.db.commit()

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    def _create_oauth_user(
        self,
        email: str,
        username: Optional[str],
        avatar_url: Optional[str],
        provider: AuthProvider,
        provider_user_id: str,
    ) -> User:
        """
        创建 OAuth 登录用户账号并初始化积分账户

        [email] 邮箱地址
        [username] 显示名称
        [avatar_url] 头像 URL
        [provider] OAuth 提供商
        [provider_user_id] 第三方平台用户 ID
        返回 新创建的 User ORM 对象
        """
        user = User(
            id=uuid.uuid4(),
            email=email,
            username=username,
            avatar_url=avatar_url,
            auth_provider=provider,
            provider_user_id=provider_user_id,
            is_email_verified=True,
            age_verified=True,
            terms_accepted_at=datetime.now(timezone.utc),
            privacy_accepted_at=datetime.now(timezone.utc),
        )
        self.db.add(user)
        self.db.flush()

        # 初始化积分账户
        credit_account = CreditAccount(
            user_id=user.id,
            balance=settings.CREDITS_INITIAL_BONUS,
            total_earned=settings.CREDITS_INITIAL_BONUS,
        )
        self.db.add(credit_account)
        self.db.commit()

        return user

    def _award_invite_reward(self, inviter_id: str, invited_user_id: str) -> None:
        """
        发放邀请奖励积分给邀请人

        [inviter_id] 邀请人用户 ID
        [invited_user_id] 被邀请人用户 ID
        """
        # 检查是否已经发放过奖励（防止重复发放）
        existing_reward = self.db.query(CreditTransaction).filter(
            CreditTransaction.user_id == inviter_id,
            CreditTransaction.source == CreditSourceType.INVITE,
            CreditTransaction.ref_id == invited_user_id,
        ).first()

        if existing_reward:
            return

        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == inviter_id
        ).with_for_update().first()

        if not credit_account:
            return

        earned = settings.CREDITS_INVITE_REWARD
        credit_account.balance += earned
        credit_account.total_earned += earned

        transaction = CreditTransaction(
            user_id=inviter_id,
            credit_account_id=credit_account.id,
            amount=earned,
            type=CreditTransactionType.EARN,
            source=CreditSourceType.INVITE,
            ref_id=invited_user_id,
            description=f"Invite friend reward: +{earned} credits",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)

    @staticmethod
    def _hash_token(token: str) -> str:
        """
        对 Token 进行 SHA-256 哈希处理，避免数据库明文存储

        [token] 原始 Token 字符串
        返回 哈希后的十六进制字符串
        """
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    async def get_current_user_dep(db: Session = None):
        """
        获取当前用户的依赖函数（占位，实际在 dependencies.py 中实现）

        [db] 数据库会话
        """
        pass

    # ── 邮箱验证码相关方法 ──────────────────────────────────────────────

    def _get_verification_service(self) -> "VerificationService":
        """
        获取验证码服务实例

        返回 VerificationService 验证码服务实例
        """
        from app.features.auth.verification_service import VerificationService
        import redis
        redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return VerificationService(redis_client)

    async def send_verification_code(self, email: str, scene: str) -> None:
        """
        发送邮箱验证码

        根据场景发送验证码到指定邮箱，并进行前置校验。

        [email] 目标邮箱地址
        [scene] 验证场景 (register/login/reset_password)
        """
        from app.features.auth.verification_service import VerificationService
        from app.db.models.user import User

        # 前置校验
        if scene == "register":
            # 注册场景：检查邮箱是否已注册
            existing_user = self.db.query(User).filter(User.email == email).first()
            if existing_user:
                raise ValidationError("该邮箱已注册，请直接登录")
        else:
            # 登录/重置场景：检查邮箱是否存在
            existing_user = self.db.query(User).filter(User.email == email).first()
            if not existing_user:
                raise ValidationError("该邮箱尚未注册")

        # 发送验证码
        verification_service = self._get_verification_service()
        verification_service.send_code(email, scene)

    async def verify_code(self, email: str, scene: str, code: str) -> bool:
        """
        校验邮箱验证码

        [email] 目标邮箱地址
        [scene] 验证场景
        [code] 用户输入的验证码
        返回 bool 是否验证通过
        """
        verification_service = self._get_verification_service()
        return verification_service.verify_code(email, scene, code)

    def _create_verify_token(self, email: str, scene: str) -> str:
        """
        创建验证码验证成功后的临时 Token

        [email] 已验证的邮箱地址
        [scene] 验证场景
        返回 str JWT Token
        """
        verification_service = self._get_verification_service()
        return verification_service.create_verify_token(email, scene)

    async def register_with_verified_email(self, request: RegisterCompleteRequest) -> TokenResponse:
        """
        使用验证码验证后完成注册

        验证临时 Token，创建用户账号并发放首次注册奖励积分。

        [request] 完成注册请求体
        返回 TokenResponse JWT 令牌对
        """
        from app.features.auth.verification_service import VerificationService
        from app.db.models.user import User

        verification_service = self._get_verification_service()

        # 验证 Token
        token_email = verification_service.verify_token(request.verify_token, "register")

        # 再次检查邮箱是否已注册（防止并发）
        existing_user = self.db.query(User).filter(User.email == token_email).first()
        if existing_user:
            raise ValidationError("该邮箱已注册")

        # 验证合规性
        if not request.age_verified:
            raise ValidationError("You must be 13 or older to use TextLens (COPPA compliance)")
        if not request.terms_accepted or not request.privacy_accepted:
            raise ValidationError("You must accept the Terms of Service and Privacy Policy")

        # 处理邀请码：查找邀请人
        inviter = None
        if request.invite_code:
            inviter = self.db.query(User).filter(User.invite_code == request.invite_code).first()

        # 创建用户
        user = User(
            id=uuid.uuid4(),
            email=token_email,
            password_hash=hash_password(request.password),
            username=request.username,
            auth_provider=AuthProvider.EMAIL,
            is_email_verified=True,  # 标记邮箱已验证
            age_verified=True,
            terms_accepted_at=datetime.now(timezone.utc),
            privacy_accepted_at=datetime.now(timezone.utc),
            invited_by=inviter.id if inviter else None,
        )
        self.db.add(user)
        self.db.flush()

        # 初始化积分账户，发放注册奖励积分
        credit_account = CreditAccount(
            user_id=user.id,
            balance=settings.CREDITS_INITIAL_BONUS,
            total_earned=settings.CREDITS_INITIAL_BONUS,
            total_spent=0,
        )
        self.db.add(credit_account)
        self.db.flush()

        # 记录积分流水
        transaction = CreditTransaction(
            user_id=user.id,
            credit_account_id=credit_account.id,
            amount=settings.CREDITS_INITIAL_BONUS,
            type=CreditTransactionType.EARN,
            source=CreditSourceType.REGISTER,
            description=f"Welcome bonus: +{settings.CREDITS_INITIAL_BONUS} credits",
            balance_after=settings.CREDITS_INITIAL_BONUS,
        )
        self.db.add(transaction)

        # 如果有邀请人，发放邀请奖励
        if inviter:
            self._award_invite_reward(inviter.id, user.id)

        self.db.commit()

        # 生成 Token 对
        return self._generate_tokens(user)

    async def login_with_verified_email(self, email: str) -> TokenResponse:
        """
        验证码登录（邮箱已验证，直接登录）

        [email] 已验证的邮箱地址
        返回 TokenResponse JWT 令牌对
        """
        from app.db.models.user import User

        user = self.db.query(User).filter(
            User.email == email,
            User.deleted_at.is_(None),
            User.is_active == True,
        ).first()

        if not user:
            raise AuthenticationError("用户不存在或已被注销")

        # 更新最后登录时间
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()

        return self._generate_tokens(user)

    async def reset_password_with_verified_email(self, request: PasswordResetConfirmV2Request) -> TokenResponse:
        """
        使用验证码验证后重置密码

        验证临时 Token，重置用户密码。

        [request] 确认密码重置请求体
        返回 TokenResponse 重置成功后返回登录令牌
        """
        from app.features.auth.verification_service import VerificationService
        from app.db.models.user import User

        verification_service = self._get_verification_service()

        # 验证 Token
        try:
            from app.core.security import verify_access_token
            payload = verify_access_token(request.verify_token)
            if not payload.get("verified") or payload.get("scene") != "reset_password":
                raise AuthenticationError("无效的验证令牌")
            email = payload.get("sub")
        except Exception as e:
            raise AuthenticationError(f"验证令牌无效或已过期: {str(e)}")

        # 获取用户
        user = self.db.query(User).filter(
            User.email == email,
            User.deleted_at.is_(None),
            User.is_active == True,
        ).first()

        if not user:
            raise AuthenticationError("用户不存在或已被注销")

        # 更新密码
        user.password_hash = hash_password(request.new_password)
        user.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        # 生成新的 Token 对
        return self._generate_tokens(user)
