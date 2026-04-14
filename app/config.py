"""
TextLens 后端配置模块

使用 Pydantic Settings 管理所有环境变量配置，支持多环境切换。
"""

from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List, Optional
from functools import lru_cache


class Settings(BaseSettings):
    """
    应用全局配置类

    从环境变量或 .env 文件读取配置项，支持类型验证。
    """

    # ── 应用基础配置 ──────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_LOG_LEVEL: str = "INFO"
    APP_NAME: str = "TextLens API"
    APP_VERSION: str = "1.0.0"
    APP_BASE_URL: str = "http://localhost:3000"  # 前端应用地址
    IMAGE_GENERATION_PROVIDER: str = "stability"  # 图片生成提供商: stability / openai

    # ── 数据库配置 ────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://textlens_user:password@localhost:5432/textlens"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # ── Redis 配置 ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_URL: str = "redis://localhost:6379/1"
    REDIS_BROKER_URL: str = "redis://localhost:6379/2"
    REDIS_RESULT_BACKEND: str = "redis://localhost:6379/3"

    # ── JWT 认证配置 ──────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    JWT_REFRESH_EXPIRATION_DAYS: int = 30

    # ── CORS 配置 ─────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = ["*"]

    # ── 速率限制配置 ──────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 60
    RATE_LIMIT_OCR_PER_MINUTE: int = 10
    RATE_LIMIT_GENERATION_PER_MINUTE: int = 5
    RATE_LIMIT_PAYMENT_PER_MINUTE: int = 20

    # ── Google OAuth 配置 ─────────────────────────────────────────────
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # ── Apple OAuth 配置 ──────────────────────────────────────────────
    APPLE_CLIENT_ID: Optional[str] = None
    APPLE_TEAM_ID: Optional[str] = None
    APPLE_KEY_ID: Optional[str] = None
    APPLE_PRIVATE_KEY: Optional[str] = None
    APPLE_SIGN_IN_VERIFY_SIGNATURE: bool = False  # 生产环境应启用

    # ── Google Cloud Vision API 配置 ──────────────────────────────────
    GOOGLE_CLOUD_PROJECT_ID: Optional[str] = None
    GOOGLE_CLOUD_CREDENTIALS_JSON: Optional[str] = None

    # ── Apple IAP 配置 ─────────────────────────────────────────────────
    APPLE_IAP_SECRET: Optional[str] = None

    # ── Resend 邮件配置 ──────────────────────────────────────────────────
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: str = "TextLens <noreply@textlens.com>"

    # ── AWS S3 / Cloudflare R2 存储配置 ───────────────────────────────
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET_NAME: str = "textlens-images"
    AWS_S3_REGION: str = "us-east-1"
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "textlens-images"
    R2_ENDPOINT_URL: Optional[str] = None
    USE_R2: bool = False  # True 使用 Cloudflare R2，False 使用 AWS S3

    # S3 通用别名（供 S3Client 使用）
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_BUCKET_NAME: str = "textlens-images"
    S3_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: Optional[str] = None
    S3_CUSTOM_DOMAIN: Optional[str] = None

    # ── Google Vision API 配置 ─────────────────────────────────────────
    GOOGLE_VISION_API_KEY: Optional[str] = None

    # ── OCR.space API 配置 ─────────────────────────────────────────────
    OCR_SPACE_API_KEY: Optional[str] = None
    OCR_PROVIDER: str = "ocr_space"  # "google_vision" 或 "ocr_space"

    # ── Google AI 生图配置 ──────────────────────────────────────────
    GOOGLE_AI_API_KEY: Optional[str] = None
    GOOGLE_AI_IMAGE_MODEL: str = "gemini-2.0-flash"  # 图片编辑模型

    # ── MiniMax 生图配置（已弃用）────────────────────────────────────
    MINIMAX_API_KEY: Optional[str] = None
    MINIMAX_IMAGE_MODEL: str = "image-01"  # 默认生图模型: image-01 / image-01-live

    # ── Stability AI 生图配置（已弃用）────────────────────────────────
    STABILITY_API_KEY: Optional[str] = None
    STABILITY_ENGINE_ID: str = "stable-diffusion-xl-1024-v1-0"  # 默认生图引擎

    # ── Celery 任务队列 URL（别名）─────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── 积分系统配置 ──────────────────────────────────────────────────
    FREE_DAILY_LIMIT: int = 3            # 每日免费生成次数
    CREDITS_INITIAL_BONUS: int = 10      # 首次注册赠送积分
    CREDITS_DAILY_CHECKIN: int = 2       # 每日签到积分
    CREDITS_AD_REWARD: int = 3           # 看广告奖励积分
    CREDITS_AD_DAILY_LIMIT: int = 5      # 每日看广告上限次数
    CREDITS_INVITE_REWARD: int = 20      # 邀请好友奖励积分

    # ── 图片存储配置 ──────────────────────────────────────────────────
    IMAGE_MAX_SIZE_MB: int = 10
    IMAGE_RETENTION_DAYS: int = 90       # 图片保留天数

    # ── 监控/日志配置 ─────────────────────────────────────────────────
    SENTRY_DSN: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    @model_validator(mode="after")
    def _resolve_storage_on_init(self):
        """
        Pydantic 模型验证器，在所有字段解析完成后自动调用

        将 R2 凭证映射到 S3 兼容字段，供 S3Client 统一使用。
        """
        if self.USE_R2:
            self.S3_ACCESS_KEY = self.R2_ACCESS_KEY_ID
            self.S3_SECRET_KEY = self.R2_SECRET_ACCESS_KEY
            self.S3_REGION = "auto"
            self.S3_ENDPOINT_URL = self.R2_ENDPOINT_URL
            self.S3_BUCKET_NAME = self.R2_BUCKET_NAME
        elif self.AWS_ACCESS_KEY_ID:
            self.S3_ACCESS_KEY = self.AWS_ACCESS_KEY_ID
            self.S3_SECRET_KEY = self.AWS_SECRET_ACCESS_KEY
            self.S3_BUCKET_NAME = self.AWS_S3_BUCKET_NAME
            self.S3_REGION = self.AWS_S3_REGION
        return self


@lru_cache()
def get_settings() -> Settings:
    """
    获取应用配置单例

    使用 lru_cache 缓存配置对象，避免重复读取环境变量。
    返回 [Settings] 配置对象实例
    """
    return Settings()


settings = get_settings()
