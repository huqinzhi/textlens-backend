# Task 06: OCR 模块实现

## 任务描述

实现图片上传和 OCR 识别功能，使用 Google Cloud Vision API。OCR 识别通过 Celery 异步执行。

## 涉及文件

- `app/features/ocr/router.py` - 路由处理器
- `app/features/ocr/service.py` - 业务逻辑
- `app/tasks/ocr_tasks.py` - Celery OCR 任务
- `app/external/google_vision.py` - Google Vision API 客户端
- `app/schemas/image.py` - Pydantic 模型

## 详细任务

### 6.1 创建 Google Vision 客户端

```python
# app/external/google_vision.py
from typing import Any
from google.cloud import vision
from google.cloud.vision_v1 import types

from app.config import Settings

settings = Settings()

class GoogleVisionClient:
    """Google Cloud Vision API 客户端"""
    
    def __init__(self):
        self.client = vision.ImageAnnotatorClient()
    
    def detect_text(self, image_content: bytes) -> list[dict[str, Any]]:
        """
        识别图片中的文字
        
        返回格式:
        [
            {
                "id": "block_0",
                "text": "Hello World",
                "x": 0.12,      # 归一化坐标
                "y": 0.08,
                "width": 0.35,
                "height": 0.06,
                "confidence": 0.98,
            },
            ...
        ]
        """
        image = vision.Image(content=image_content)
        response = self.client.text_detection(image=image)
        
        if response.error.message:
            raise Exception(f"Google Vision API Error: {response.error.message}")
        
        text_blocks = []
        for i, annotation in enumerate(response.text_annotations):
            # 第一个是整段文字，后续是每个单词/字符的详情
            if i == 0:
                continue
            
            vertices = annotation.bounding_poly.vertices
            if len(vertices) >= 4:
                # 计算归一化边界框
                x_coords = [v.x for v in vertices]
                y_coords = [v.y for v in vertices]
                
                text_blocks.append({
                    "id": f"block_{i-1}",
                    "text": annotation.description,
                    "x": min(x_coords) / annotation.bounding_poly.width if annotation.bounding_poly.width > 0 else 0,
                    "y": min(y_coords) / annotation.bounding_poly.height if annotation.bounding_poly.height > 0 else 0,
                    "width": (max(x_coords) - min(x_coords)) / annotation.bounding_poly.width if annotation.bounding_poly.width > 0 else 0,
                    "height": (max(y_coords) - min(y_coords)) / annotation.bounding_poly.height if annotation.bounding_poly.height > 0 else 0,
                    "confidence": annotation.confidence if hasattr(annotation, 'confidence') else 0.9,
                })
        
        return text_blocks
```

### 6.2 创建 S3 客户端

```python
# app/external/s3_client.py
import uuid
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from app.config import Settings

settings = Settings()

class S3Client:
    """AWS S3 / Cloudflare R2 存储客户端"""
    
    def __init__(self):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )
        self.bucket = settings.S3_BUCKET_NAME
    
    def upload_file(self, file_obj: BinaryIO, key: str, content_type: str = "image/jpeg") -> str:
        """上传文件，返回公开访问 URL"""
        self.s3.upload_fileobj(
            file_obj,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        
        # 构建 URL
        if settings.S3_ENDPOINT_URL:
            # R2 或 S3 兼容存储
            return f"{settings.S3_ENDPOINT_URL}/{self.bucket}/{key}"
        else:
            return f"https://{self.bucket}.s3.amazonaws.com/{key}"
    
    def delete_file(self, key: str) -> bool:
        """删除文件"""
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
    
    def generate_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """生成预签名 URL"""
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expiration,
        )
```

### 6.3 创建 Pydantic Schema

```python
# app/schemas/image.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class OCRUploadResponse(BaseModel):
    task_id: UUID
    status: str = "pending"

class OCRResultResponse(BaseModel):
    task_id: UUID
    status: str
    image_id: UUID | None = None
    image_url: str | None = None
    text_blocks: list[dict] | None = None
    error_message: str | None = None

class TextBlock(BaseModel):
    id: str
    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float
```

### 6.4 实现 OCR Service

```python
# app/features/ocr/service.py
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.image import Image, OCRResult
from app.db.models.user import User
from app.external.s3_client import S3Client
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.config import Settings

settings = Settings()

class OCRService:
    """OCR 服务类"""
    
    def __init__(self, db: Session):
        self.db = db
        self.s3_client = S3Client()
    
    def upload_and_create_task(
        self,
        user_id: str,
        file_content: bytes,
        filename: str,
        content_type: str,
    ) -> dict:
        """
        上传图片并创建 OCR 任务
        
        返回任务信息，立即返回 task_id 由 Celery 异步处理
        """
        # 验证用户
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ResourceNotFoundError("User not found")
        
        # 生成存储路径
        image_id = uuid.uuid4()
        ext = filename.split(".")[-1] if "." in filename else "jpg"
        storage_path = f"uploads/{image_id}.{ext}"
        
        # 上传到 S3
        from io import BytesIO
        image_url = self.s3_client.upload_file(
            BytesIO(file_content),
            storage_path,
            content_type,
        )
        
        # 创建 Image 记录
        image = Image(
            id=image_id,
            user_id=user_id,
            original_image_url=image_url,
            storage_path=storage_path,
            file_size=len(file_content),
        )
        self.db.add(image)
        self.db.commit()
        
        # 注意: OCR 任务由 router 直接 enqueue Celery task
        # 这里只负责创建 Image 记录
        
        return {
            "task_id": image_id,  # 使用 image_id 作为 task_id
            "status": "pending",
        }
    
    def process_ocr(self, image_id: str) -> dict:
        """
        处理 OCR 识别 (由 Celery 调用)
        """
        from app.tasks.ocr_tasks import process_ocr_task
        
        # 触发异步任务
        task = process_ocr_task.apply_async(args=[image_id])
        
        return {"celery_task_id": task.id}
    
    def get_ocr_result(self, task_id: str, user_id: str) -> dict:
        """
        获取 OCR 结果
        """
        image = self.db.query(Image).filter(
            Image.id == task_id,
            Image.user_id == user_id,
        ).first()
        
        if not image:
            raise ResourceNotFoundError("Image not found")
        
        ocr_result = self.db.query(OCRResult).filter(
            OCRResult.image_id == task_id
        ).first()
        
        if ocr_result:
            return {
                "task_id": task_id,
                "status": "done",
                "image_id": image.id,
                "image_url": image.original_image_url,
                "text_blocks": ocr_result.text_blocks,
            }
        
        return {
            "task_id": task_id,
            "status": "pending",
            "image_id": image.id,
            "image_url": image.original_image_url,
            "text_blocks": None,
        }
```

### 6.5 实现 Celery OCR 任务

```python
# app/tasks/ocr_tasks.py
from celery import Celery
from celery_app import celery_app
from sqlalchemy.orm import Session

from app.external.google_vision import GoogleVisionClient
from app.db.session import SessionLocal
from app.db.models.image import Image, OCRResult

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def process_ocr_task(self, image_id: str):
    """
    异步 OCR 识别任务
    """
    db = SessionLocal()
    google_vision = GoogleVisionClient()
    
    try:
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image:
            return {"error": "Image not found"}
        
        # 下载图片内容
        from app.external.s3_client import S3Client
        s3 = S3Client()
        
        # 获取图片内容
        import boto3
        from botocore.exceptions import ClientError
        
        s3_client = boto3.client(
            "s3",
            endpoint_url=s3.s3.endpoint_url if hasattr(s3, 's3') else None,
            aws_access_key_id=s3.s3.aws_access_key_id if hasattr(s3, 's3') else None,
            aws_secret_access_key=s3.s3.aws_secret_access_key if hasattr(s3, 's3') else None,
        )
        
        try:
            file_obj = s3_client.get_object(
                Bucket=s3.bucket,
                Key=image.storage_path,
            )["Body"]
            image_content = file_obj.read()
        except ClientError:
            return {"error": "Failed to download image from S3"}
        
        # 调用 Google Vision API
        text_blocks = google_vision.detect_text(image_content)
        
        # 保存 OCR 结果
        ocr_result = OCRResult(
            image_id=image_id,
            text_blocks=text_blocks,
            full_text="\n".join([b["text"] for b in text_blocks]),
        )
        db.add(ocr_result)
        db.commit()
        
        return {"status": "done", "blocks_count": len(text_blocks)}
        
    except Exception as exc:
        db.rollback()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {"error": str(exc)}
    finally:
        db.close()
```

### 6.6 实现路由处理器

```python
# app/features/ocr/router.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.user import User
from app.features.ocr.service import OCRService
from app.schemas.image import OCRUploadResponse, OCRResultResponse
from app.tasks.ocr_tasks import process_ocr_task
from app.core.exceptions import ResourceNotFoundError

router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

@router.post("/upload", response_model=OCRUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传图片并触发 OCR 识别（返回 task_id）"""
    # 验证文件类型
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "Only JPEG, PNG, WebP images are allowed"},
        )
    
    # 读取文件内容
    content = await file.read()
    
    # 验证文件大小
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "File size exceeds 10MB limit"},
        )
    
    service = OCRService(db)
    result = service.upload_and_create_task(
        user_id=str(current_user.id),
        file_content=content,
        filename=file.filename,
        content_type=file.content_type,
    )
    
    # 触发 Celery OCR 任务
    process_ocr_task.apply_async(args=[str(result["task_id"])])
    
    return OCRUploadResponse(
        task_id=result["task_id"],
        status="pending",
    )

@router.get("/{task_id}", response_model=OCRResultResponse)
def get_ocr_result(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询 OCR 识别结果"""
    service = OCRService(db)
    result = service.get_ocr_result(task_id, str(current_user.id))
    
    return OCRResultResponse(**result)
```

## 验收标准

- [ ] POST /ocr/upload 接受图片并返回 task_id
- [ ] 图片正确上传到 S3/R2
- [ ] GET /ocr/{task_id} 返回 OCR 识别结果
- [ ] OCR 使用 Google Vision API
- [ ] OCR 任务异步执行
- [ ] 文字块返回归一化坐标 (0.0-1.0)

## 前置依赖

- Task 04: 认证系统实现
- Task 02: 数据库模型设计

## 后续任务

- Task 07: AI 生成模块实现
