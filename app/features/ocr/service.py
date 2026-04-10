"""
OCR 识别业务逻辑服务层
处理图片上传、Google Vision API调用、OCR结果解析等
"""
import time
import uuid
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import ExternalServiceError, ValidationError
from app.db.models.image import Image, OCRResult, ImageStatus
from app.external.google_vision import GoogleVisionClient
from app.external.s3_client import S3Client
from app.schemas.image import OCRResponse, TextBlock


class OCRService:
    """
    OCR 识别服务类

    编排图片上传、OCR识别、结果存储的完整流程。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db
        self.vision_client = GoogleVisionClient()
        self.s3_client = S3Client()

    async def recognize(self, file: UploadFile, current_user) -> OCRResponse:
        """
        执行 OCR 识别完整流程

        1. 验证文件大小（最大 10MB）
        2. 上传图片至 S3/R2
        3. 调用 Google Cloud Vision API
        4. 解析并存储识别结果
        5. 返回结构化的文字块列表

        [file] 上传的图片文件
        [current_user] 当前登录用户
        返回 OCRResponse 识别结果响应体
        """
        start_time = time.time()

        # 验证文件大小
        file_content = await file.read()
        if len(file_content) > settings.IMAGE_MAX_SIZE_MB * 1024 * 1024:
            raise ValidationError(f"File size exceeds {settings.IMAGE_MAX_SIZE_MB}MB limit")

        # 上传图片到 S3/R2
        image_key = f"uploads/{current_user.id}/{uuid.uuid4()}/{file.filename}"
        try:
            image_url = await self.s3_client.upload(
                content=file_content,
                key=image_key,
                content_type=file.content_type,
            )
        except Exception as e:
            raise ExternalServiceError("S3", str(e))

        # 创建图片记录
        image = Image(
            id=uuid.uuid4(),
            user_id=current_user.id,
            original_url=image_url,
            file_size=len(file_content),
            file_format=file.content_type.split("/")[-1],
            status=ImageStatus.OCR_PROCESSING,
        )
        self.db.add(image)
        self.db.flush()

        # 调用 Google Vision OCR
        try:
            vision_result = await self.vision_client.detect_text(file_content)
        except Exception as e:
            image.status = ImageStatus.OCR_FAILED
            self.db.commit()
            raise ExternalServiceError("Google Vision", str(e))

        # 解析 OCR 结果为标准格式
        text_blocks = self._parse_vision_result(vision_result)
        processing_time_ms = int((time.time() - start_time) * 1000)

        # 存储 OCR 结果
        ocr_result = OCRResult(
            image_id=image.id,
            raw_data=vision_result,
            text_blocks=[block.model_dump() for block in text_blocks],
            processing_time_ms=processing_time_ms,
        )
        self.db.add(ocr_result)

        image.status = ImageStatus.OCR_DONE
        self.db.commit()

        return OCRResponse(
            image_id=str(image.id),
            image_url=image_url,
            text_blocks=text_blocks,
            detected_language=self._detect_language(vision_result),
            processing_time_ms=processing_time_ms,
        )

    def _parse_vision_result(self, vision_result: dict) -> list[TextBlock]:
        """
        将 Google Vision API 原始结果解析为标准 TextBlock 列表

        提取每个文字区域的文字内容、坐标、置信度等信息，
        坐标统一归一化为相对图片尺寸的比例值（0-1范围）。

        [vision_result] Google Vision API 原始响应数据
        返回 List[TextBlock] 标准化文字块列表
        """
        text_blocks = []
        # TODO: 解析 Google Vision API 返回的 textAnnotations 或 fullTextAnnotation
        # 示例结构：
        # vision_result["textAnnotations"][1:] 为每个单词/段落的识别结果
        # 每个元素包含 description（文字内容）和 boundingPoly（坐标多边形）
        return text_blocks

    def _detect_language(self, vision_result: dict) -> str:
        """
        从 Vision API 结果中提取检测到的主要语言

        [vision_result] Google Vision API 原始响应数据
        返回 语言代码字符串（如 "en", "zh", "ja"）
        """
        # TODO: 从 fullTextAnnotation.pages[].property.detectedLanguages 提取
        return "en"
