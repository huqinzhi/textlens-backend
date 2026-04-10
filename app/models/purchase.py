from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class PaymentProvider(str, enum.Enum):
    STRIPE = "stripe"
    APPLE_IAP = "apple_iap"
    GOOGLE_IAP = "google_iap"


class PurchaseStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class PurchaseRecord(Base):
    __tablename__ = "purchase_records"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    package_id = Column(String, nullable=False)  # e.g., "credits_100", "credits_500"
    amount_usd = Column(Float, nullable=False)
    credits_granted = Column(Integer, nullable=False)
    payment_provider = Column(Enum(PaymentProvider), nullable=False)
    receipt_data = Column(Text, nullable=True)  # IAP receipt / Stripe session ID
    status = Column(Enum(PurchaseStatus), default=PurchaseStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="purchase_records")
