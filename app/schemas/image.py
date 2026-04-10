"""
图片处理相关 Pydantic 数据模型
定义OCR识别、AI生成任务的请求与响应数据结构
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
import uuid
from app.core.constants import QualityLevel, TaskStatus


class TextBlock(BaseModel):
    """
    OCR 识别出的单个文字块

    [id] 文字块唯一标识
    [text] 识别出的文字内容
    [x] 文字框左上角 X 坐标（相对图片宽度的比例）
    [y] 文字框左上角 Y 坐标（相对图片高度的比例）
    [width] 文字框宽度（相对图片宽度的比例）
    [height] 文字框高度（相对图片高度的比例）
    [confidence] 识别置信度，0-1 之间
    [font_size_estimate] 估算字体大小（像素）
    """
    id: str
    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float
    font_size_estimate: Optional[float] = None


class OCRResponse(BaseModel):
    """
    OCR 识别结果响应体

    [image_id] 上传图片的 ID
    [text_blocks] 识别出的文字块列表
    [detected_language] 检测到的主要语言
    [processing_time_ms] OCR 处理耗时
    """
    image_id: str
    image_url: str
    text_blocks: List[TextBlock]
    detected_language: Optional[str]
    processing_time_ms: int


class EditBlock(BaseModel):
    """
    用户编辑的单个文字块

    [block_id] 对应 OCR 结果中的文字块 ID
    [original_text] 原始文字内容
    [new_text] 用户输入的新文字内容
    """
    block_id: str
    original_text: str
    new_text: str


class GenerateRequest(BaseModel):
    """
    AI 生图请求体

    [image_id] 原始图片 ID（OCR 识别时返回）
    [edit_blocks] 用户编辑的文字块列表
    [quality] 生成质量等级
    """
    image_id: str
    edit_blocks: List[EditBlock] = Field(..., min_length=1)
    quality: QualityLevel = QualityLevel.LOW


class GenerationTaskResponse(BaseModel):
    """
    AI 生成任务状态响应体

    [task_id] 任务唯一 ID（用于轮询）
    [status] 当前任务状态
    [result_image_url] 生成结果图片 URL（完成时才有）
    [original_image_url] 原始图片 URL
    [credits_cost] 消耗积分数量
    [error_message] 错误信息（失败时）
    [created_at] 任务创建时间
    [completed_at] 任务完成时间
    """
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    status: TaskStatus
    result_image_url: Optional[str] = None
    original_image_url: str
    quality: QualityLevel
    credits_cost: int
    has_watermark: bool = False
    error_message: Optional[str] = None
    estimated_seconds: Optional[int] = None   # 预计剩余时间
    created_at: datetime
    completed_at: Optional[datetime] = None


class HistoryItem(BaseModel):
    """
    历史记录单条响应体
    """
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    original_image_url: str
    result_image_url: Optional[str]
    quality: QualityLevel
    status: TaskStatus
    credits_cost: int
    created_at: datetime
