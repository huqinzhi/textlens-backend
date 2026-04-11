"""
用户数据库模型
包含用户账户、认证信息相关的 ORM 模型定义
"""

from sqlalchemy import Column, String, Boolean, DateTime, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.base import Base


class AuthProvider(str, enum.Enum):
    """认证提供商枚举"""
    EMAIL = "email"
    GOOGLE = "google"
    APPLE = "apple"


class User(Base):
    """
    用户主表
    存储用户基本信息、认证状态、账户状态
    """
    __tablename__ = "users"

    # 主键，使用 UUID 避免信息泄露
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # 邮箱地址，唯一且必填
    email = Column(String(255), unique=True, index=True, nullable=False)

    # 密码哈希，第三方登录用户可为空
    password_hash = Column(String(255), nullable=True)

    # 用户显示名称
    username = Column(String(100), nullable=True)

    # 头像 URL（存储在 S3）
    avatar_url = Column(Text, nullable=True)

    # 认证提供商
    auth_provider = Column(Enum(AuthProvider), default=AuthProvider.EMAIL, nullable=False)

    # 第三方登录的 provider 用户 ID
    provider_user_id = Column(String(255), nullable=True)

    # 邮箱是否已验证
    is_email_verified = Column(Boolean, default=False, nullable=False)

    # 账户是否激活（注销后设为 False）
    is_active = Column(Boolean, default=True, nullable=False)

    # 是否为管理员
    is_admin = Column(Boolean, default=False, nullable=False)

    # 年龄验证（COPPA 合规，13岁以上）
    age_verified = Column(Boolean, default=False, nullable=False)

    # 同意隐私政策时间
    privacy_accepted_at = Column(DateTime(timezone=True), nullable=True)

    # 同意用户协议时间
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)

    # 注销申请时间（软删除）
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # 数据删除完成时间（GDPR 合规）
    data_deleted_at = Column(DateTime(timezone=True), nullable=True)

    # 创建时间
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 更新时间
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 最后登录时间
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # 邀请码（用户专属邀请链接）
    invite_code = Column(String(20), unique=True, nullable=True, index=True)

    # 邀请人 ID（记录是谁推荐注册）
    invited_by = Column(UUID(as_uuid=True), nullable=True)

    # 关联关系
    credit_account = relationship("CreditAccount", back_populates="user", uselist=False)
    credit_transactions = relationship("CreditTransaction", back_populates="user")
    generation_tasks = relationship("GenerationTask", back_populates="user")
    daily_free_usages = relationship("DailyFreeUsage", back_populates="user")
    purchase_records = relationship("PurchaseRecord", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} email={self.email}>"


class RefreshToken(Base):
    """
    Refresh Token 存储表
    用于 JWT 刷新令牌的持久化管理，支持 Token 撤销
    """
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 关联用户 ID
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Token 哈希值（不存储原始 token）
    token_hash = Column(String(255), unique=True, nullable=False)

    # 过期时间
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # 是否已撤销
    is_revoked = Column(Boolean, default=False)

    # 创建时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 最后使用时间
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # 客户端信息（设备类型等）
    client_info = Column(String(500), nullable=True)

    def __repr__(self):
        return f"<RefreshToken user_id={self.user_id} expires_at={self.expires_at}>"
