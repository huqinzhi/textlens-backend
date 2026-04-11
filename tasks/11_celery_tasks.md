# Task 11: Celery 异步任务系统

## 任务描述

配置 Celery 应用、创建任务队列、设置 Celery Beat 定时任务（图片清理、GDPR 数据清理）。

## 涉及文件

- `app/tasks/celery_app.py` - Celery 配置和 Beat 定时任务
- `app/tasks/generation_tasks.py` - AI 生成任务
- `app/tasks/ocr_tasks.py` - OCR 任务
- `app/tasks/cleanup_tasks.py` - 清理任务

## 详细任务

### 11.1 创建 Celery 应用配置

```python
# app/tasks/celery_app.py
from celery import Celery, signals
from celery.schedules import crontab

from app.config import Settings

settings = Settings()

# 创建 Celery 应用
celery_app = Celery(
    "textlens",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.generation_tasks",
        "app.tasks.ocr_tasks",
        "app.tasks.cleanup_tasks",
    ],
)

# Celery 配置
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    date唱="json",
    
    # 时区
    timezone="UTC",
    enable_utc=True,
    
    # 任务过期时间
    result_expires=3600,  # 1小时后过期
    
    # 任务重试
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # 队列配置
    task_routes={
        "app.tasks.generation_tasks.*": {"queue": "generation"},
        "app.tasks.ocr_tasks.*": {"queue": "ocr"},
        "app.tasks.cleanup_tasks.*": {"queue": "cleanup"},
    },
    
    # 默认队列
    task_default_queue="default",
    
    # Beat 定时任务
    beat_schedule={
        "cleanup-expired-images": {
            "task": "app.tasks.cleanup_tasks.cleanup_expired_images",
            "schedule": crontab(hour=2, minute=0),  # 每日 2:00 UTC 执行
            "options": {"queue": "cleanup"},
        },
        "gdpr-data-cleanup": {
            "task": "app.tasks.cleanup_tasks.gdpr_data_cleanup",
            "schedule": crontab(hour=3, minute=0),  # 每日 3:00 UTC 执行
            "options": {"queue": "cleanup"},
        },
    },
)

# Worker 启动时的信号处理
@signals.worker_ready.connect
def worker_ready(**kwargs):
    print("Celery worker is ready")

@signals.worker_shutdown.connect
def worker_shutdown(**kwargs):
    print("Celery worker is shutting down")
```

### 11.2 实现清理任务

```python
# app/tasks/cleanup_tasks.py
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models.user import User
from app.db.models.image import Image, GenerationTask
from app.external.s3_client import S3Client

s3_client = S3Client()

@celery_app.task(name="app.tasks.cleanup_tasks.cleanup_expired_images")
def cleanup_expired_images():
    """
    清理过期图片（90天以上）
    
    删除 S3 文件 + 数据库记录
    """
    db = SessionLocal()
    
    try:
        # 计算过期时间（90天前）
        expired_date = datetime.utcnow() - timedelta(days=90)
        
        # 查找过期图片
        expired_images = db.query(Image).filter(
            and_(
                Image.deleted_at.isnot(None),
                Image.deleted_at < expired_date,
            )
        ).all()
        
        deleted_count = 0
        deleted_files = []
        
        for image in expired_images:
            # 删除 S3 文件
            try:
                if image.storage_path:
                    s3_client.delete_file(image.storage_path)
                    deleted_files.append(image.storage_path)
            except Exception as e:
                print(f"Failed to delete S3 file {image.storage_path}: {e}")
            
            # 删除数据库记录
            db.delete(image)
            deleted_count += 1
        
        # 查找过期 Generation Task
        expired_tasks = db.query(GenerationTask).filter(
            and_(
                GenerationTask.status.in_(["done", "failed", "cancelled"]),
                GenerationTask.created_at < expired_date,
            )
        ).all()
        
        for task in expired_tasks:
            # 删除结果图
            if task.result_image_url:
                try:
                    key = f"results/{task.id}.png"
                    s3_client.delete_file(key)
                except Exception:
                    pass
            
            db.delete(task)
        
        db.commit()
        
        return {
            "deleted_images": deleted_count,
            "deleted_tasks": len(expired_tasks),
            "deleted_files": deleted_files,
        }
        
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup_tasks.gdpr_data_cleanup")
def gdpr_data_cleanup():
    """
    GDPR 数据清理
    
    注销 30 天后的账户永久删除个人数据
    """
    db = SessionLocal()
    
    try:
        # 计算清理时间（30天前）
        cleanup_date = datetime.utcnow() - timedelta(days=30)
        
        # 查找应删除的用户（ deleted_at < 30天前）
        users_to_delete = db.query(User).filter(
            and_(
                User.deleted_at.isnot(None),
                User.deleted_at < cleanup_date,
            )
        ).all()
        
        deleted_users = 0
        
        for user in users_to_delete:
            user_id = str(user.id)
            
            # 1. 删除用户的积分流水
            db.query(CreditTransaction).filter(
                CreditTransaction.user_id == user_id
            ).delete()
            
            # 2. 删除用户的每日免费使用记录
            db.query(DailyFreeUsage).filter(
                DailyFreeUsage.user_id == user_id
            ).delete()
            
            # 3. 删除用户的 Generation Task
            tasks = db.query(GenerationTask).filter(
                GenerationTask.user_id == user_id
            ).all()
            
            for task in tasks:
                # 删除 S3 文件
                try:
                    if task.original_image_url:
                        key = f"uploads/{task.id}.*"
                        # 实际实现需要列出并删除
                    if task.result_image_url:
                        s3_client.delete_file(f"results/{task.id}.png")
                except Exception:
                    pass
                db.delete(task)
            
            # 4. 删除用户的图片
            images = db.query(Image).filter(Image.user_id == user_id).all()
            for image in images:
                try:
                    if image.storage_path:
                        s3_client.delete_file(image.storage_path)
                except Exception:
                    pass
                db.delete(image)
            
            # 5. 删除用户的购买记录
            db.query(PurchaseRecord).filter(
                PurchaseRecord.user_id == user_id
            ).delete()
            
            # 6. 删除用户的积分账户
            db.query(CreditAccount).filter(
                CreditAccount.user_id == user_id
            ).delete()
            
            # 7. 删除 Refresh Token
            db.query(RefreshToken).filter(
                RefreshToken.user_id == user_id
            ).delete()
            
            # 8. 最后删除用户
            db.delete(user)
            deleted_users += 1
        
        db.commit()
        
        return {
            "deleted_users": deleted_users,
        }
        
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
```

## 验收标准

- [ ] Celery 应用正常启动
- [ ] 可分别启动 generation/ocr/cleanup 队列的 Worker
- [ ] Celery Beat 定时任务正确调度
- [ ] cleanup_expired_images 正确删除过期图片
- [ ] gdpr_data_cleanup 正确删除过期用户数据

## 前置依赖

- Task 02: 数据库模型设计
- Task 06: OCR 模块实现
- Task 07: AI 生成模块实现

## 后续任务

- Task 12: 中间件系统实现
