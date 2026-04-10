"""
Celery 应用配置
定义任务队列、Worker 配置和 Beat 定时任务计划
"""
from celery import Celery
from app.config import settings


def create_celery_app() -> Celery:
    """
    创建并配置 Celery 应用实例

    使用 Redis 作为消息 Broker 和 Result Backend，
    配置任务路由、序列化格式和 Beat 定时任务计划。

    返回配置好的 Celery 应用实例
    """
    app = Celery(
        "textlens",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            "app.tasks.generation_tasks",
            "app.tasks.ocr_tasks",
            "app.tasks.cleanup_tasks",
        ],
    )

    app.conf.update(
        # 任务序列化格式
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],

        # 时区配置
        timezone="UTC",
        enable_utc=True,

        # 任务结果保留时间（24小时）
        result_expires=86400,

        # 任务路由：将不同任务分配到不同队列
        task_routes={
            "app.tasks.generation_tasks.*": {"queue": "generation"},
            "app.tasks.ocr_tasks.*": {"queue": "ocr"},
            "app.tasks.cleanup_tasks.*": {"queue": "cleanup"},
        },

        # Worker 并发数（默认按 CPU 核数）
        worker_concurrency=4,

        # 任务超时配置（秒）
        task_soft_time_limit=120,   # 软超时：触发 SoftTimeLimitExceeded 异常
        task_time_limit=180,         # 硬超时：强制终止 Worker 进程

        # 任务重试配置
        task_acks_late=True,         # 任务完成后才确认（防止 Worker 崩溃丢失任务）
        worker_prefetch_multiplier=1,  # 每次只预取 1 个任务（防止积压）

        # Beat 定时任务计划
        beat_schedule={
            # 每天凌晨 2 点清理过期图片（90天以上）
            "cleanup-expired-images": {
                "task": "app.tasks.cleanup_tasks.cleanup_expired_images",
                "schedule": 86400,  # 每24小时
                "options": {"queue": "cleanup"},
            },
            # 每天凌晨 3 点执行 GDPR 数据删除（注销账户 30 天后）
            "gdpr-data-cleanup": {
                "task": "app.tasks.cleanup_tasks.gdpr_data_cleanup",
                "schedule": 86400,
                "options": {"queue": "cleanup"},
            },
        },
    )

    return app


# 全局 Celery 应用实例
celery_app = create_celery_app()
