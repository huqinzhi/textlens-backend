"""
OCR 识别 Celery 任务
处理 Google Vision API 文字识别的异步任务
"""
import logging
from celery import Task
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.external.google_vision import GoogleVisionClient
from app.external.s3_client import S3Client

# 显式导入所有模型，确保 SQLAlchemy 映射器正确注册
from app.db.models.user import User
from app.db.models.image import Image, OCRResult, GenerationTask, ImageStatus
from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage
from app.db.models.payment import PurchaseRecord

logger = logging.getLogger(__name__)


class OCRTaskBase(Task):
    """
    OCR 任务基类

    提供数据库会话和外部客户端的懒加载。
    """

    _db: Session = None
    _vision_client: GoogleVisionClient = None
    _s3_client: S3Client = None

    @property
    def db(self) -> Session:
        """懒加载数据库会话"""
        if self._db is None or not self._db.is_active:
            self._db = SessionLocal()
        return self._db

    @property
    def vision_client(self) -> GoogleVisionClient:
        """懒加载 Google Vision 客户端"""
        if self._vision_client is None:
            self._vision_client = GoogleVisionClient()
        return self._vision_client

    @property
    def s3_client(self) -> S3Client:
        """懒加载 S3 客户端"""
        if self._s3_client is None:
            self._s3_client = S3Client()
        return self._s3_client


@celery_app.task(
    bind=True,
    base=OCRTaskBase,
    name="app.tasks.ocr_tasks.process_ocr",
    max_retries=3,
    default_retry_delay=5,
    queue="ocr",
)
def process_ocr(self, image_id: str) -> dict:
    """
    执行图片 OCR 文字识别任务

    从数据库加载图片记录 → 下载图片 → 调用 Google Vision API →
    保存识别结果 → 更新图片状态。

    [image_id] Image 数据库记录 ID
    返回包含识别结果的字典
    """
    import asyncio

    logger.info(f"[OCR] Starting OCR task for image: {image_id}")

    image = self.db.query(Image).filter(Image.id == image_id).first()
    if not image:
        logger.error(f"[OCR] Image not found: {image_id}")
        return {"error": "Image not found"}

    try:
        # 执行异步 OCR 识别
        result = asyncio.get_event_loop().run_until_complete(
            _execute_ocr(image, self.vision_client, self.s3_client)
        )

        # 保存 OCR 结果到数据库
        ocr_result = OCRResult(
            image_id=image.id,
            raw_data=result,
            text_blocks=result.get("text_blocks", []),
            confidence=result.get("confidence", 0.0),
        )
        self.db.add(ocr_result)

        # 更新图片状态
        image.status = ImageStatus.OCR_DONE
        self.db.commit()

        logger.info(f"[OCR] Completed for image: {image_id}, blocks: {len(result.get('text_blocks', []))}")
        return {
            "status": "done",
            "image_id": image_id,
            "text_blocks": result.get("text_blocks", []),
            "confidence": result.get("confidence", 0.0),
        }

    except Exception as exc:
        logger.error(f"[OCR] Failed for image {image_id}: {exc}")
        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            image.status = ImageStatus.OCR_FAILED
            self.db.commit()
            return {"status": "failed", "error": str(exc)}


async def _execute_ocr(
    image: Image,
    vision_client: GoogleVisionClient,
    s3_client: S3Client,
) -> dict:
    """
    执行 OCR 识别的核心异步逻辑

    [image] 数据库中的图片记录
    [vision_client] Google Vision 客户端
    [s3_client] S3 存储客户端
    返回包含 raw_text 和 text_blocks 的字典
    """
    # 优先用 URL 识别（无需下载），降级到下载字节后识别
    try:
        result = await vision_client.detect_text(image.original_url)
    except Exception:
        # URL 识别失败时下载图片再识别
        image_bytes = await s3_client.download(image.original_url)
        result = await vision_client.detect_text_from_bytes(image_bytes)

    return result
