from sqlalchemy import Column, String, Integer, Float, JSON, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
import enum
from app.models.base import BaseModel


class GenerationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class GenerationQuality(str, enum.Enum):
    LOW = "low"        # 5 credits
    MEDIUM = "medium"  # 15 credits
    HIGH = "high"      # 25 credits


QUALITY_CREDITS_MAP = {
    GenerationQuality.LOW: 5,
    GenerationQuality.MEDIUM: 15,
    GenerationQuality.HIGH: 25,
}


class GenerationTask(BaseModel):
    __tablename__ = "generation_tasks"

    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    original_image_url = Column(String, nullable=False)
    result_image_url = Column(String, nullable=True)
    ocr_data = Column(JSON, nullable=True)       # OCR识别结果
    edit_data = Column(JSON, nullable=True)      # 用户编辑内容
    quality = Column(SAEnum(GenerationQuality), nullable=False, default=GenerationQuality.LOW)
    status = Column(SAEnum(GenerationStatus), nullable=False, default=GenerationStatus.PENDING, index=True)
    credits_cost = Column(Integer, nullable=False, default=5)
    error_message = Column(String, nullable=True)
    celery_task_id = Column(String, nullable=True)  # Celery task ID

    # Relationships
    user = relationship("User", back_populates="generation_tasks")


class DailyFreeUsage(BaseModel):
    __tablename__ = "daily_free_usage"

    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(String, nullable=False)  # YYYY-MM-DD
    used_count = Column(Integer, nullable=False, default=0)

    # Relationships
    user = relationship("User", back_populates="daily_free_usages")
