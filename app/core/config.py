from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "TextLens"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    # AWS S3 / R2
    S3_BUCKET_NAME: str
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_ENDPOINT_URL: Optional[str] = None  # Cloudflare R2 endpoint

    # OpenAI
    OPENAI_API_KEY: str

    # Google Cloud Vision
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GOOGLE_CLOUD_PROJECT: Optional[str] = None

    # OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    APPLE_CLIENT_ID: Optional[str] = None
    APPLE_TEAM_ID: Optional[str] = None
    APPLE_KEY_ID: Optional[str] = None

    # Stripe
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Credits Rules
    DAILY_FREE_LOW_QUALITY: int = 3
    CREDIT_LOW_QUALITY: int = 5
    CREDIT_MID_QUALITY: int = 15
    CREDIT_HIGH_QUALITY: int = 25
    CREDIT_DAILY_SIGNIN: int = 2
    CREDIT_AD_REWARD: int = 3
    CREDIT_AD_DAILY_LIMIT: int = 5
    CREDIT_INVITE: int = 20
    CREDIT_REGISTER_BONUS: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
