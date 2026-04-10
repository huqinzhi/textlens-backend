from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # NULL for OAuth users
    avatar_url = Column(Text, nullable=True)
    google_id = Column(String(255), nullable=True, unique=True)
    apple_id = Column(String(255), nullable=True, unique=True)
    is_active = Column(String(10), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    credit_account = relationship("CreditAccount", back_populates="user", uselist=False)
    credit_transactions = relationship("CreditTransaction", back_populates="user")
    generation_tasks = relationship("GenerationTask", back_populates="user")
    daily_free_usages = relationship("DailyFreeUsage", back_populates="user")
    purchase_records = relationship("PurchaseRecord", back_populates="user")
