"""
图片相关数据库模型
包含图片元数据、OCR识别结果和AI生成任务记录
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON, Enum, Float, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum
from app.db.base import Base


class ImageStatus(str, enum.Enum):
    """图片状态枚举"""
    UPLOADED = "uploaded"       # 已上传
    OCR_PROCESSING = "ocr_processing"  # OCR处理中
    OCR_DONE = "ocr_done"       # OCR完成
    OCR_FAILED = "ocr_failed"   # OCR失败


class GenerationStatus(str, enum.Enum):
    """AI生成任务状态枚举"""
    PENDING = "pending"         # 等待处理
    PROCESSING = "processing"   # 处理中
    DONE = "done"               # 完成
    FAILED = "failed"           # 失败
    CANCELLED = "cancelled"     # 已取消


class GenerationQuality(str, enum.Enum):
    """生成质量枚举"""
    LOW = "low"         # 低质量 512x512
    MEDIUM = "medium"   # 中质量 1024x1024
    HIGH = "high"       # 高质量 2048x2048


class Image(Base):
    """
    图片表
    存储用户上传的原始图片信息
    """
    __tablename__ = "images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    original_url = Column(String(500), nullable=False, comment="原始图片S3 URL")
    thumbnail_url = Column(String(500), nullable=True, comment="缩略图URL")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    file_format = Column(String(10), nullable=True, comment="文件格式: jpg/png/webp")
    width = Column(Integer, nullable=True, comment="图片宽度（像素）")
    height = Column(Integer, nullable=True, comment="图片高度（像素）")
    status = Column(Enum(ImageStatus), default=ImageStatus.UPLOADED, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    # 关联关系
    user = relationship("User", back_populates="images")
    ocr_result = relationship("OCRResult", back_populates="image", uselist=False)
    generation_tasks = relationship("GenerationTask", back_populates="image")


class OCRResult(Base):
    """
    OCR识别结果表
    存储Google Vision API识别的文字区域信息
    """
    __tablename__ = "ocr_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False, unique=True)
    raw_data = Column(JSON, nullable=True, comment="Google Vision原始返回数据")
    text_blocks = Column(JSON, nullable=True, comment="解析后的文字块列表 [{text, x, y, w, h, confidence}]")
    detected_language = Column(String(10), nullable=True, comment="检测到的主要语言")
    processing_time_ms = Column(Integer, nullable=True, comment="OCR处理耗时（毫秒）")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关联关系
    image = relationship("Image", back_populates="ocr_result")


class GenerationTask(Base):
    """
    AI生成任务表
    记录每次AI图片生成的完整信息
    """
    __tablename__ = "generation_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    original_image_url = Column(String(500), nullable=False, comment="原始图片URL")
    result_image_url = Column(String(500), nullable=True, comment="生成结果图片URL")
    ocr_data = Column(JSON, nullable=True, comment="OCR识别数据快照")
    edit_data = Column(JSON, nullable=True, comment="用户编辑内容 [{block_id, original, new_text}]")
    quality = Column(Enum(GenerationQuality), nullable=False, default=GenerationQuality.LOW)
    status = Column(Enum(GenerationStatus), default=GenerationStatus.PENDING, nullable=False)
    credits_cost = Column(Integer, nullable=False, default=0, comment="消耗积分数量")
    is_free = Column(Integer, default=0, comment="是否使用免费次数: 0否 1是")
    has_watermark = Column(Integer, default=0, comment="是否带水印: 0否 1是")
    error_message = Column(Text, nullable=True, comment="失败错误信息")
    celery_task_id = Column(String(100), nullable=True, comment="Celery任务ID")
    prompt_used = Column(Text, nullable=True, comment="发送给OpenAI的完整提示词")
    generation_time_ms = Column(Integer, nullable=True, comment="AI生成耗时（毫秒）")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    # 关联关系
    user = relationship("User", back_populates="generation_tasks")
    image = relationship("Image", back_populates="generation_tasks")
