# Task 02: 数据库模型设计

## 任务描述

根据 PRD 设计所有数据库表结构，包括 User、CreditAccount、CreditTransaction、GenerationTask、PurchaseRecord 等模型，以及数据库会话管理。

## 涉及文件

- `app/db/base.py` - DeclarativeBase 聚合所有模型
- `app/db/session.py` - 数据库引擎和会话工厂
- `app/db/models/user.py` - 用户表
- `app/db/models/credit.py` - 积分账户和流水表
- `app/db/models/image.py` - 图片和任务表
- `app/db/models/payment.py` - 购买记录表

## 详细任务

### 2.1 创建 DeclarativeBase

```python
# app/db/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

# Import all models to register them with Base
from app.db.models.user import User, RefreshToken
from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage
from app.db.models.image import Image, OCRResult, GenerationTask
from app.db.models.payment import PurchaseRecord
```

### 2.2 创建数据库会话管理

```python
# app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config import Settings

settings = Settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    """数据库会话依赖注入"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### 2.3 创建用户模型

```python
# app/db/models/user.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.core.constants import AuthProvider

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    username = Column(String(50), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    auth_provider = Column(SQLEnum(AuthProvider), default=AuthProvider.EMAIL)
    provider_user_id = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    is_email_verified = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)  # 软删除
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    credit_account = relationship("CreditAccount", back_populates="user", uselist=False)
    refresh_tokens = relationship("RefreshToken", back_populates="user")
    generation_tasks = relationship("GenerationTask", back_populates="user")
    purchase_records = relationship("PurchaseRecord", back_populates="user")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique)  # SHA-256 hash
    is_revoked = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="refresh_tokens")
```

### 2.4 创建积分模型

```python
# app/db/models/credit.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.core.constants import CreditType, CreditSource

class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    balance = Column(Integer, default=0, nullable=False)
    total_earned = Column(Integer, default=0, nullable=False)
    total_spent = Column(Integer, default=0, nullable=False)
    
    user = relationship("User", back_populates="credit_account")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)  # 正=获得，负=消耗
    type = Column(SQLEnum(CreditType), nullable=False)
    source = Column(SQLEnum(CreditSource), nullable=False)
    balance_after = Column(Integer, nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyFreeUsage(Base):
    __tablename__ = "daily_free_usage"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    usage_date = Column(String(10), nullable=False)  # "YYYY-MM-DD"
    count = Column(Integer, default=0)
    
    __table_args__ = (
        Index("ix_daily_free_usage_user_date", "user_id", "usage_date", unique=True),
    )
```

### 2.5 创建图片和任务模型

```python
# app/db/models/image.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Enum as SQLEnum, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.core.constants import QualityLevel, TaskStatus

class Image(Base):
    __tablename__ = "images"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    original_image_url = Column(String(500), nullable=False)
    storage_path = Column(String(255), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=True)  # bytes
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # 软删除


class OCRResult(Base):
    __tablename__ = "ocr_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), nullable=False)
    text_blocks = Column(JSON, nullable=False)  # 识别的文字块
    full_text = Column(String, nullable=True)
    language = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    image = relationship("Image")


class GenerationTask(Base):
    __tablename__ = "generation_tasks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    original_image_url = Column(String(500), nullable=False)
    result_image_url = Column(String(500), nullable=True)
    ocr_data = Column(JSON, nullable=True)
    edit_data = Column(JSON, nullable=True)
    quality = Column(SQLEnum(QualityLevel), default=QualityLevel.MEDIUM)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING)
    credits_cost = Column(Integer, default=0)
    celery_task_id = Column(String(255), nullable=True)
    has_watermark = Column(Boolean, default=False)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="generation_tasks")
    
    __table_args__ = (
        Index("ix_generation_tasks_user_status", "user_id", "status"),
        Index("ix_generation_tasks_celery", "celery_task_id"),
    )
```

### 2.6 创建购买记录模型

```python
# app/db/models/payment.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.core.constants import PurchaseStatus, PaymentProvider

class PurchaseRecord(Base):
    __tablename__ = "purchase_records"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    package_id = Column(String(50), nullable=False)
    amount_usd = Column(Float, nullable=False)
    credits_granted = Column(Integer, nullable=False)
    payment_provider = Column(SQLEnum(PaymentProvider), nullable=False)
    status = Column(SQLEnum(PurchaseStatus), default=PurchaseStatus.PENDING)
    external_order_id = Column(String(255), nullable=True)
    receipt_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="purchase_records")
    
    __table_args__ = (
        Index("ix_purchase_records_user", "user_id"),
        Index("ix_purchase_records_external", "external_order_id"),
    )
```

## 验收标准

- [ ] 所有模型正确创建且类型匹配
- [ ] 模型间关系正确配置
- [ ] 软删除字段 `deleted_at` 已添加
- [ ] 必要的索引已创建
- [ ] 数据库会话工厂正常工作

## 前置依赖

- Task 01: 项目基础架构搭建

## 后续任务

- Task 03: 数据库迁移脚本
