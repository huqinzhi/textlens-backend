# Task 10: 历史记录模块实现

## 任务描述

实现历史记录查询和删除功能，支持分页展示，包含图片资源清理。

## 涉及文件

- `app/features/history/router.py` - 路由处理器
- `app/features/history/service.py` - 业务逻辑

## 详细任务

### 10.1 创建 Pydantic Schema

```python
# app/schemas/history.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Literal

class HistoryItemResponse(BaseModel):
    id: UUID
    type: Literal["ocr", "generation"]
    status: str
    original_image_url: str | None = None
    result_image_url: str | None = None
    credits_cost: int = 0
    created_at: datetime
    
    class Config:
        from_attributes = True

class HistoryListResponse(BaseModel):
    items: list[HistoryItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
```

### 10.2 实现 HistoryService

```python
# app/features/history/service.py
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from app.db.models.image import Image, GenerationTask
from app.external.s3_client import S3Client
from app.core.constants import TaskStatus
from app.core.exceptions import ResourceNotFoundError

class HistoryService:
    """历史记录服务类"""
    
    def __init__(self, db: Session):
        self.db = db
        self.s3_client = S3Client()
    
    def get_history(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        分页获取历史记录列表
        合并 OCR 和 Generation 记录，按时间排序
        """
        # 获取 Generation Tasks
        generation_query = self.db.query(GenerationTask).filter(
            GenerationTask.user_id == user_id
        ).order_by(desc(GenerationTask.created_at))
        
        total = generation_query.count()
        tasks = generation_query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 转换为统一格式
        items = []
        for task in tasks:
            items.append({
                "id": task.id,
                "type": "generation",
                "status": task.status.value,
                "original_image_url": task.original_image_url,
                "result_image_url": task.result_image_url,
                "credits_cost": task.credits_cost,
                "created_at": task.created_at,
            })
        
        total_pages = (total + page_size - 1) // page_size
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
    
    def delete_history_item(self, item_id: str, user_id: str) -> dict:
        """
        删除单条历史记录（含 S3 文件）
        """
        # 只允许删除 Generation Task
        task = self.db.query(GenerationTask).filter(
            GenerationTask.id == item_id,
            GenerationTask.user_id == user_id,
        ).first()
        
        if not task:
            raise ResourceNotFoundError("History item not found")
        
        # 删除 S3 文件
        deleted_files = []
        
        # 删除原图
        if task.original_image_url:
            try:
                storage_key = task.original_image_url.split("/")[-1]
                self.s3_client.delete_file(f"uploads/{storage_key}")
                deleted_files.append(f"uploads/{storage_key}")
            except Exception:
                pass  # S3 删除失败不阻断
        
        # 删除结果图
        if task.result_image_url:
            try:
                storage_key = task.result_image_url.split("/")[-1]
                self.s3_client.delete_file(f"results/{storage_key}")
                deleted_files.append(f"results/{storage_key}")
            except Exception:
                pass
        
        # 软删除数据库记录
        task.deleted_at = datetime.utcnow()
        self.db.commit()
        
        return {
            "deleted": True,
            "deleted_files": deleted_files,
        }
```

### 10.3 实现路由处理器

```python
# app/features/history/router.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.user import User
from app.features.history.service import HistoryService
from app.schemas.history import HistoryListResponse, HistoryItemResponse
from app.core.exceptions import ResourceNotFoundError

router = APIRouter()

@router.get("", response_model=HistoryListResponse)
def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页获取历史记录列表"""
    service = HistoryService(db)
    result = service.get_history(str(current_user.id), page, page_size)
    
    return HistoryListResponse(
        items=[HistoryItemResponse.model_validate(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )

@router.delete("/{item_id}")
def delete_history_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除单条历史记录（含 S3 文件）"""
    service = HistoryService(db)
    
    try:
        result = service.delete_history_item(item_id, str(current_user.id))
        return result
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
```

## 验收标准

- [ ] GET /history 返回分页历史记录
- [ ] 记录包含 OCR 和 Generation 类型
- [ ] DELETE /history/{id} 删除记录
- [ ] 删除时清理 S3 文件

## 前置依赖

- Task 06: OCR 模块实现
- Task 07: AI 生成模块实现

## 后续任务

- Task 11: Celery 异步任务系统
