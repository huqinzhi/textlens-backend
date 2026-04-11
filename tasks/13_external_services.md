# Task 13: 外部服务集成

## 任务描述

完善外部服务客户端，包括 Google Vision、OpenAI、S3/R2、Stripe。实现健康检查端点。

## 涉及文件

- `app/external/google_vision.py` - Google Vision API
- `app/external/openai_api.py` - OpenAI API
- `app/external/s3_client.py` - S3/R2 存储
- `app/external/stripe_api.py` - Stripe API
- `app/main.py` - 添加健康检查端点

## 详细任务

### 13.1 完善 Google Vision 客户端

```python
# app/external/google_vision.py (增强版)
from typing import Any
from google.cloud import vision
from google.cloud.vision_v1 import types
from google.oauth2 import service_account
import json

from app.config import Settings

settings = Settings()

class GoogleVisionClient:
    """Google Cloud Vision API 客户端"""
    
    def __init__(self):
        # 可以使用服务账号或 API Key
        if hasattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON") and settings.GOOGLE_SERVICE_ACCOUNT_JSON:
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self.client = vision.ImageAnnotatorClient(credentials=credentials)
        else:
            self.client = vision.ImageAnnotatorClient()
    
    def detect_text(self, image_content: bytes) -> list[dict[str, Any]]:
        """
        识别图片中的文字
        
        返回格式:
        [
            {
                "id": "block_0",
                "text": "Hello World",
                "x": 0.12,
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
        
        # response.text_annotations 包含所有检测到的文本区域
        # 第一个是完整的检测结果
        for i, annotation in enumerate(response.text_annotations):
            if i == 0:
                continue
            
            vertices = annotation.bounding_poly.vertices
            
            if len(vertices) >= 4:
                x_coords = [v.x for v in vertices]
                y_coords = [v.y for v in vertices]
                
                # 计算归一化坐标（相对于图片尺寸）
                # 注意：需要图片的实际尺寸来计算归一化坐标
                # 这里简化处理，假设坐标已经是相对于图片的
                min_x = min(x_coords)
                min_y = min(y_coords)
                max_x = max(x_coords)
                max_y = max(y_coords)
                
                text_blocks.append({
                    "id": f"block_{i-1}",
                    "text": annotation.description,
                    "x": min_x / 1000.0,  # 需要实际图片尺寸
                    "y": min_y / 1000.0,
                    "width": (max_x - min_x) / 1000.0,
                    "height": (max_y - min_y) / 1000.0,
                    "confidence": annotation.confidence if hasattr(annotation, 'confidence') else 0.9,
                })
        
        return text_blocks
    
    def detect_text_from_uri(self, image_uri: str) -> list[dict[str, Any]]:
        """从 GCS URI 检测文字"""
        image = vision.Image()
        image.source.image_uri = image_uri
        
        response = self.client.text_detection(image=image)
        
        if response.error.message:
            raise Exception(f"Google Vision API Error: {response.error.message}")
        
        # 处理响应...
        return []
```

### 13.2 完善 OpenAI 客户端

```python
# app/external/openai_api.py (增强版)
from typing import BinaryIO, Any
from io import BytesIO

from openai import OpenAI
from openai.types.images_response import ImagesResponse

from app.config import Settings

settings = Settings()

class OpenAIClient:
    """OpenAI API 客户端"""
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    def moderate_content(self, text: str) -> bool:
        """
        使用 OpenAI Moderation API 审核内容
        
        返回 True 表示内容安全，False 表示违规
        """
        response = self.client.moderations.create(input=text)
        result = response.results[0]
        return not result.flagged
    
    def moderate_batch(self, texts: list[str]) -> list[bool]:
        """批量审核内容"""
        response = self.client.moderations.create(input=texts)
        return [not result.flagged for result in response.results]
    
    def edit_image(
        self,
        image_content: bytes,
        edit_instruction: str,
        quality: str = "standard",
        size: str = "1024x1024",
    ) -> str:
        """
        使用 GPT-4o 图片编辑 API 生成图片
        
        返回图片 URL
        """
        response = self.client.images.edit(
            model="gpt-4o",
            image=BytesIO(image_content),
            prompt=edit_instruction,
            quality=quality,
            size=size,
            n=1,
        )
        
        return response.data[0].url
    
    def generate_image_url(
        self,
        prompt: str,
        quality: str = "standard",
        size: str = "1024x1024",
    ) -> str:
        """
        使用 DALL-E 3 生成图片
        """
        response = self.client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            quality=quality,
            size=size,
            n=1,
        )
        return response.data[0].url
    
    def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str = "gpt-4o",
        temperature: float = 0.7,
    ) -> str:
        """
        GPT-4o 对话补全（用于复杂提示词构建）
        """
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content
```

### 13.3 完善 S3 客户端

```python
# app/external/s3_client.py (增强版)
import uuid
from typing import BinaryIO, Optional
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from app.config import Settings

settings = Settings()

class S3Client:
    """AWS S3 / Cloudflare R2 存储客户端"""
    
    def __init__(self):
        config = Config(
            retries={"max_attempts": 3, "mode": "standard"},
        )
        
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            config=config,
        )
        self.bucket = settings.S3_BUCKET_NAME
    
    def upload_file(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str = "image/jpeg",
        metadata: Optional[dict] = None,
    ) -> str:
        """
        上传文件
        
        返回公开访问 URL 或预签名 URL
        """
        extra_args = {"ContentType": content_type}
        if metadata:
            extra_args["Metadata"] = metadata
        
        self.s3.upload_fileobj(
            file_obj,
            self.bucket,
            key,
            ExtraArgs=extra_args,
        )
        
        return self._build_url(key)
    
    def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str = "image/jpeg",
    ) -> str:
        """上传字节数据"""
        return self.upload_file(
            BytesIO(data),
            key,
            content_type,
        )
    
    def delete_file(self, key: str) -> bool:
        """删除文件"""
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
    
    def delete_files(self, keys: list[str]) -> list[str]:
        """批量删除文件"""
        deleted = []
        for key in keys:
            if self.delete_file(key):
                deleted.append(key)
        return deleted
    
    def file_exists(self, key: str) -> bool:
        """检查文件是否存在"""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
    
    def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
    ) -> str:
        """生成预签名 URL（用于下载）"""
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expiration,
        )
    
    def generate_upload_presigned_url(
        self,
        key: str,
        content_type: str = "image/jpeg",
        expiration: int = 3600,
    ) -> str:
        """生成上传预签名 URL（用于客户端直接上传）"""
        return self.s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expiration,
        )
    
    def download_file(self, key: str) -> bytes:
        """下载文件内容"""
        response = self.s3.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()
    
    def _build_url(self, key: str) -> str:
        """构建文件 URL"""
        if settings.S3_ENDPOINT_URL:
            return f"{settings.S3_ENDPOINT_URL}/{self.bucket}/{key}"
        else:
            return f"https://{self.bucket}.s3.amazonaws.com/{key}"
```

### 13.4 添加健康检查端点

```python
# app/main.py (添加健康检查)

from fastapi import FastAPI

@celery_app.get("/health")
def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }

@celery_app.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)):
    """就绪检查（检查数据库和 Redis）"""
    checks = {
        "database": False,
        "redis": False,
    }
    
    # 检查数据库
    try:
        db.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        pass
    
    # 检查 Redis
    try:
        redis_client.ping()
        checks["redis"] = True
    except Exception:
        pass
    
    all_healthy = all(checks.values())
    
    return {
        "status": "ready" if all_healthy else "not_ready",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }
```

## 验收标准

- [ ] 所有外部服务客户端可正常实例化
- [ ] Google Vision 可识别图片文字
- [ ] OpenAI Moderation API 可审核内容
- [ ] S3/R2 可上传下载文件
- [ ] 健康检查端点正常返回

## 前置依赖

- Task 01: 项目基础架构搭建

## 后续任务

- Task 14: Docker 部署配置
