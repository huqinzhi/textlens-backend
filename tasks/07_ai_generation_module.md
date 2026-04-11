# Task 07: AI 生成模块实现

## 任务描述

实现 AI 图片生成功能，调用 OpenAI GPT-4o 图片编辑 API。包含内容审核、积分扣除、任务状态管理。

## 涉及文件

- `app/features/generation/router.py` - 路由处理器
- `app/features/generation/service.py` - 业务逻辑
- `app/tasks/generation_tasks.py` - Celery 生成任务
- `app/external/openai_api.py` - OpenAI API 客户端
- `app/schemas/image.py` - Pydantic 模型

## 详细任务

### 7.1 创建 OpenAI API 客户端

```python
# app/external/openai_api.py
from typing import Any
from io import BytesIO

from openai import OpenAI

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
        
        # 如果有任何违规类别，标记为不通过
        if result.flagged:
            return False
        return True
    
    def edit_image(
        self,
        image_content: bytes,
        edit_instruction: str,
        quality: str = "standard",
        size: str = "1024x1024",
    ) -> bytes:
        """
        使用 GPT-4o 图片编辑 API 生成图片
        
        Args:
            image_content: 原图字节数据
            edit_instruction: 编辑指令
            quality: quality - "standard" | "hd"
            size: size - "1024x1024" | "1536x1536"
        
        返回生成的图片字节数据
        """
        response = self.client.images.edit(
            model="gpt-4o",
            image=BytesIO(image_content),
            prompt=edit_instruction,
            quality=quality,
            size=size,
        )
        
        # 返回图片 URL (实际使用需要下载)
        return response.data[0].url
    
    def generate_image_url(
        self,
        prompt: str,
        quality: str = "standard",
        size: str = "1024x1024",
    ) -> str:
        """
        使用 DALL-E 3 生成图片（用于模板图）
        """
        response = self.client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            quality=quality,
            size=size,
            n=1,
        )
        return response.data[0].url
```

### 7.2 创建 Pydantic Schema

```python
# app/schemas/image.py (添加)
class GenerationSubmitRequest(BaseModel):
    image_id: UUID
    quality: QualityLevel = QualityLevel.MEDIUM
    edit_blocks: list[EditBlock]

class EditBlock(BaseModel):
    id: str
    new_text: str

class GenerationTaskResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    result_image_url: str | None = None
    credits_cost: int = 0
    estimated_seconds: int = 0
    error_message: str | None = None
```

### 7.3 实现 GenerationService

```python
# app/features/generation/service.py
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, update

from app.db.models.user import User
from app.db.models.image import Image, GenerationTask, OCRResult
from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage
from app.external.s3_client import S3Client
from app.core.constants import (
    QualityLevel, TaskStatus, CreditType, CreditSource,
    QUALITY_CREDITS_MAP, QUALITY_SIZE_MAP,
)
from app.core.exceptions import (
    ResourceNotFoundError, InsufficientCreditsError, ValidationError,
)
from app.config import Settings

settings = Settings()

class GenerationService:
    """AI 生成服务类"""
    
    def __init__(self, db: Session):
        self.db = db
        self.s3_client = S3Client()
    
    def submit_task(
        self,
        user_id: str,
        image_id: str,
        quality: QualityLevel,
        edit_blocks: list[dict],
    ) -> dict:
        """
        提交 AI 生成任务
        
        流程:
        1. 验证图片存在
        2. 检查免费次数/积分余额
        3. 内容安全审核
        4. 扣除积分 (FOR UPDATE 锁)
        5. 创建 GenerationTask
        6. 派发 Celery 任务
        """
        # 1. 验证图片
        image = self.db.query(Image).filter(
            Image.id == image_id,
            Image.user_id == user_id,
            Image.deleted_at.is_(None),
        ).first()
        
        if not image:
            raise ResourceNotFoundError("Image not found")
        
        # 获取 OCR 结果用于构建提示词
        ocr_result = self.db.query(OCRResult).filter(
            OCRResult.image_id == image_id
        ).first()
        
        # 2. 检查免费次数/积分
        credits_cost = QUALITY_CREDITS_MAP[quality]
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        if quality == QualityLevel.LOW:
            # Low 质量优先使用免费次数
            daily_usage = self.db.query(DailyFreeUsage).filter(
                DailyFreeUsage.user_id == user_id,
                DailyFreeUsage.usage_date == today,
            ).with_for_update().first()
            
            used = daily_usage.count if daily_usage else 0
            if used < settings.FREE_DAILY_LIMIT:
                # 使用免费配额
                credits_cost = 0
                has_watermark = True
                
                if daily_usage:
                    daily_usage.count = used + 1
                else:
                    self.db.add(DailyFreeUsage(
                        user_id=user_id,
                        usage_date=today,
                        count=1,
                    ))
            else:
                credits_cost = 5  # 超出免费次数
                has_watermark = True
        else:
            has_watermark = False
        
        # 3. 内容安全审核
        from app.external.openai_api import OpenAIClient
        openai = OpenAIClient()
        
        for block in edit_blocks:
            if not openai.moderate_content(block["new_text"]):
                raise ValidationError(f"Content moderation failed for block {block['id']}")
        
        # 4. 扣除积分 (FOR UPDATE)
        if credits_cost > 0:
            credit_account = self.db.query(CreditAccount).filter(
                CreditAccount.user_id == user_id
            ).with_for_update().first()
            
            if not credit_account or credit_account.balance < credits_cost:
                raise InsufficientCreditsError()
            
            credit_account.balance -= credits_cost
            credit_account.total_spent += credits_cost
            
            # 记录积分变动
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-credits_cost,
                type=CreditType.SPEND,
                source=CreditSource.AD,  # TODO: 区分来源
                balance_after=credit_account.balance,
                description=f"AI 生成 ({quality.value} 质量)",
            )
            self.db.add(transaction)
        
        # 5. 创建 GenerationTask
        task_id = uuid.uuid4()
        task = GenerationTask(
            id=task_id,
            user_id=user_id,
            original_image_url=image.original_image_url,
            ocr_data=ocr_result.text_blocks if ocr_result else None,
            edit_data={"blocks": edit_blocks},
            quality=quality,
            status=TaskStatus.PENDING,
            credits_cost=credits_cost,
            has_watermark=has_watermark,
        )
        self.db.add(task)
        
        # 6. 派发 Celery 任务
        from app.tasks.generation_tasks import process_generation_task
        celery_task = process_generation_task.apply_async(args=[str(task_id)])
        task.celery_task_id = celery_task.id
        
        self.db.commit()
        
        return {
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "credits_cost": credits_cost,
            "estimated_seconds": 30,  # 估算
        }
    
    def get_task_status(self, task_id: str, user_id: str) -> dict:
        """获取生成任务状态"""
        task = self.db.query(GenerationTask).filter(
            GenerationTask.id == task_id,
            GenerationTask.user_id == user_id,
        ).first()
        
        if not task:
            raise ResourceNotFoundError("Task not found")
        
        estimated_seconds = 0
        if task.status == TaskStatus.PENDING:
            estimated_seconds = 30
        elif task.status == TaskStatus.PROCESSING:
            estimated_seconds = 20
        
        return {
            "task_id": task.id,
            "status": task.status,
            "result_image_url": task.result_image_url,
            "credits_cost": task.credits_cost,
            "estimated_seconds": estimated_seconds,
            "error_message": task.error_message,
        }
    
    def cancel_task(self, task_id: str, user_id: str) -> dict:
        """
        取消待处理任务（退还积分）
        """
        task = self.db.query(GenerationTask).filter(
            GenerationTask.id == task_id,
            GenerationTask.user_id == user_id,
            GenerationTask.status == TaskStatus.PENDING,
        ).with_for_update().first()
        
        if not task:
            raise ValidationError("Task not found or cannot be cancelled")
        
        # 退还积分
        if task.credits_cost > 0:
            credit_account = self.db.query(CreditAccount).filter(
                CreditAccount.user_id == user_id
            ).with_for_update().first()
            
            if credit_account:
                credit_account.balance += task.credits_cost
                credit_account.total_spent -= task.credits_cost
                
                transaction = CreditTransaction(
                    user_id=user_id,
                    amount=task.credits_cost,
                    type=CreditType.EARN,
                    source=CreditSource.REFUND,
                    balance_after=credit_account.balance,
                    description="任务取消退款",
                )
                self.db.add(transaction)
        
        # 更新任务状态
        task.status = TaskStatus.CANCELLED
        
        self.db.commit()
        
        return {"status": "cancelled"}
```

### 7.4 实现 Celery 生成任务

```python
# app/tasks/generation_tasks.py
import boto3
from io import BytesIO
from celery import Celery
from celery_app import celery_app
from sqlalchemy.orm import Session

from app.external.openai_api import OpenAIClient
from app.external.s3_client import S3Client
from app.db.session import SessionLocal
from app.db.models.image import GenerationTask
from app.db.models.credit import CreditAccount, CreditTransaction
from app.core.constants import TaskStatus, CreditType, CreditSource, QUALITY_SIZE_MAP

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def process_generation_task(self, task_id: str):
    """
    异步 AI 图片生成任务
    """
    db = SessionLocal()
    openai = OpenAIClient()
    s3_client = S3Client()
    
    try:
        task = db.query(GenerationTask).filter(GenerationTask.id == task_id).first()
        if not task:
            return {"error": "Task not found"}
        
        # 更新状态为处理中
        task.status = TaskStatus.PROCESSING
        db.commit()
        
        # 1. 下载原图
        s3 = boto3.client(
            "s3",
            endpoint_url=s3_client.s3.endpoint_url if hasattr(s3_client.s3, 'endpoint_url') else None,
            aws_access_key_id=s3_client.s3.aws_access_key_id if hasattr(s3_client.s3, 'aws_access_key_id') else None,
            aws_secret_access_key=s3_client.s3.aws_secret_access_key if hasattr(s3_client.s3, 'aws_secret_access_key') else None,
        )
        
        # 提取存储路径
        original_url = task.original_image_url
        storage_key = original_url.split("/")[-1] if "/" in original_url else original_url
        
        try:
            file_obj = s3.get_object(Bucket=s3_client.bucket, Key=f"uploads/{storage_key}")["Body"]
            image_content = file_obj.read()
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = f"Failed to download image: {str(e)}"
            db.commit()
            return {"error": str(e)}
        
        # 2. 构建 GPT-4o 提示词
        edit_blocks = task.edit_data.get("blocks", [])
        ocr_data = task.ocr_data or []
        
        # 构建文字替换指令
        text_replacements = []
        for block in edit_blocks:
            block_id = block["id"]
            new_text = block["new_text"]
            text_replacements.append(f'Replace text in block "{block_id}" with "{new_text}"')
        
        instruction = f"""You are an expert at text editing in images. 
Please edit the image by replacing the text as specified.
The original image contains text that was recognized by OCR.

Instructions:
{chr(10).join(text_replacements)}

Requirements:
- Keep the original font style and background as much as possible
- Only change the specified text, keep everything else exactly the same
- The text should be naturally integrated into the image
"""
        
        # 3. 获取输出规格
        quality = task.quality.value
        size_map = QUALITY_SIZE_MAP.get(task.quality, (1024, 1024))
        size_str = f"{size_map[0]}x{size_map[1]}"
        quality_for_api = "hd" if quality == "high" else "standard"
        
        # 4. 调用 GPT-4o 图片编辑 API
        try:
            result_url = openai.edit_image(
                image_content=image_content,
                edit_instruction=instruction,
                quality=quality_for_api,
                size=size_str,
            )
        except Exception as e:
            # 重试
            if self.request.retries < self.max_retries:
                raise self.retry(exc=e)
            task.status = TaskStatus.FAILED
            task.error_message = f"OpenAI API error: {str(e)}"
            db.commit()
            return {"error": str(e)}
        
        # 5. 下载结果并上传到 S3
        import requests
        result_response = requests.get(result_url)
        result_content = result_response.content
        
        result_key = f"results/{task_id}.png"
        final_url = s3_client.upload_file(
            BytesIO(result_content),
            result_key,
            "image/png",
        )
        
        # 6. 更新任务状态
        task.status = TaskStatus.DONE
        task.result_image_url = final_url
        db.commit()
        
        return {"status": "done", "result_url": final_url}
        
    except Exception as exc:
        db.rollback()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        
        task = db.query(GenerationTask).filter(GenerationTask.id == task_id).first()
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = str(exc)
            db.commit()
        
        return {"error": str(exc)}
    finally:
        db.close()
```

### 7.5 实现路由处理器

```python
# app/features/generation/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.user import User
from app.features.generation.service import GenerationService
from app.schemas.image import (
    GenerationSubmitRequest, GenerationTaskResponse, EditBlock,
)
from app.core.constants import QualityLevel, TaskStatus
from app.core.exceptions import (
    ResourceNotFoundError, InsufficientCreditsError, ValidationError,
)

router = APIRouter()

@router.post("", status_code=status.HTTP_202_ACCEPTED)
def submit_generation(
    request: GenerationSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交 AI 生成任务（202 立即返回）"""
    service = GenerationService(db)
    
    try:
        result = service.submit_task(
            user_id=str(current_user.id),
            image_id=str(request.image_id),
            quality=request.quality,
            edit_blocks=[b.model_dump() for b in request.edit_blocks],
        )
        return GenerationTaskResponse(**result)
    except InsufficientCreditsError:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "INSUFFICIENT_CREDITS", "message": "Insufficient credits balance"},
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": str(e)})
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "VALIDATION_ERROR", "message": str(e)})

@router.get("/{task_id}", response_model=GenerationTaskResponse)
def get_generation_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询生成任务状态和结果"""
    service = GenerationService(db)
    
    try:
        result = service.get_task_status(task_id, str(current_user.id))
        return GenerationTaskResponse(**result)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": str(e)})

@router.delete("/{task_id}")
def cancel_generation(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消待处理任务（退还积分）"""
    service = GenerationService(db)
    
    try:
        result = service.cancel_task(task_id, str(current_user.id))
        return result
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "VALIDATION_ERROR", "message": str(e)})
```

## 验收标准

- [ ] POST /generate 接受请求并返回 202 Accepted
- [ ] Low 质量优先使用免费次数，超出后扣积分
- [ ] Medium/High 质量始终扣积分
- [ ] 内容审核不通过返回 400
- [ ] GET /generate/{task_id} 返回任务状态
- [ ] DELETE /generate/{task_id} 可取消任务并退款
- [ ] 生成任务异步执行
- [ ] 结果图片上传到 S3/R2

## 前置依赖

- Task 06: OCR 模块实现

## 后续任务

- Task 08: 积分系统实现
