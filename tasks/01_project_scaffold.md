# Task 01: 项目基础架构搭建

## 任务描述

搭建 FastAPI 应用工厂，注册中间件和路由系统，配置 Pydantic Settings 环境变量管理。

## 涉及文件

- `app/main.py` - FastAPI 应用工厂
- `app/config.py` - Pydantic Settings 配置
- `app/dependencies.py` - 通用依赖注入 (get_current_user)
- `app/core/security.py` - JWT 工具函数
- `app/core/exceptions.py` - 自定义异常层级
- `app/core/constants.py` - 枚举类型、积分规则常量

## 详细任务

### 1.1 创建 Pydantic Settings 配置

创建 `app/config.py` 或 `app/core/config.py`：

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24小时
    
    # OAuth
    GOOGLE_CLIENT_ID: str
    
    # External APIs
    GOOGLE_VISION_API_KEY: str
    OPENAI_API_KEY: str
    
    # Stripe
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    
    # S3/R2
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET_NAME: str
    S3_ENDPOINT_URL: str | None = None  # For R2
    
    # App settings
    CREDITS_INITIAL_BONUS: int = 10
    FREE_DAILY_LIMIT: int = 3
    ALLOWED_ORIGINS: list[str] = ["*"]
    
    class Config:
        env_file = ".env"
        extra = "ignore"
```

### 1.2 创建 FastAPI 应用工厂

在 `app/main.py` 中：

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

def create_app() -> FastAPI:
    settings = Settings()
    
    app = FastAPI(
        title="TextLens API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Custom middlewares
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    
    # Register routers
    from app.features.auth.router import router as auth_router
    from app.features.users.router import router as users_router
    from app.features.credits.router import router as credits_router
    from app.features.ocr.router import router as ocr_router
    from app.features.generation.router import router as generation_router
    from app.features.payments.router import router as payments_router
    from app.features.history.router import router as history_router
    
    api_v1 = FastAPI(prefix="/api/v1")
    api_v1.include_router(auth_router, prefix="/auth", tags=["auth"])
    api_v1.include_router(users_router, prefix="/users", tags=["users"])
    api_v1.include_router(credits_router, prefix="/credits", tags=["credits"])
    api_v1.include_router(ocr_router, prefix="/ocr", tags=["ocr"])
    api_v1.include_router(generation_router, prefix="/generate", tags=["generation"])
    api_v1.include_router(payments_router, prefix="/payments", tags=["payments"])
    api_v1.include_router(history_router, prefix="/history", tags=["history"])
    
    app.mount("/", api_v1)
    
    return app
```

### 1.3 创建依赖注入

在 `app/dependencies.py` 中实现 `get_current_user`：

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import verify_access_token
from app.db.models.user import User

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = verify_access_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or expired token"},
        )
    
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "User not found or inactive"},
        )
    
    return user
```

### 1.4 创建常量定义

在 `app/core/constants.py` 中定义枚举和常量：

```python
from enum import Enum

class AuthProvider(str, Enum):
    EMAIL = "email"
    GOOGLE = "google"
    APPLE = "apple"

class CreditType(str, Enum):
    EARN = "earn"
    SPEND = "spend"

class CreditSource(str, Enum):
    PURCHASE = "purchase"
    AD = "ad"
    DAILY = "daily"
    INVITE = "invite"
    REGISTER = "register"
    REFUND = "refund"

class QualityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

class PurchaseStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

class PaymentProvider(str, Enum):
    STRIPE = "stripe"
    APPLE_IAP = "apple_iap"
    GOOGLE_IAP = "google_iap"

# 积分消耗映射
QUALITY_CREDITS_MAP = {
    QualityLevel.LOW: 0,      # 免费配额
    QualityLevel.MEDIUM: 15,
    QualityLevel.HIGH: 25,
}

# 输出规格
QUALITY_SIZE_MAP = {
    QualityLevel.LOW: (512, 512),
    QualityLevel.MEDIUM: (1024, 1024),
    QualityLevel.HIGH: (1024, 1024),  # HD
}

# 积分套餐
CREDIT_PACKAGES = [
    {"id": "starter", "price_usd": 0.99, "credits": 100},
    {"id": "basic", "price_usd": 2.99, "credits": 320},
    {"id": "pro", "price_usd": 6.99, "credits": 800},
    {"id": "premium", "price_usd": 14.99, "credits": 1800},
]
```

## 验收标准

- [ ] FastAPI 应用可以正常启动
- [ ] 所有环境变量可通过 Settings 读取
- [ ] CORS、中间件正确注册
- [ ] 路由正确挂载到 `/api/v1` 前缀下
- [ ] `get_current_user` 依赖可正确验证 JWT

## 前置依赖

无

## 后续任务

- Task 02: 数据库模型设计
