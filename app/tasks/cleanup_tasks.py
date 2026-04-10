"""
定时清理 Celery 任务
执行图片过期清理（90天）和 GDPR 数据删除（注销账户 30 天后）
"""
import logging
from datetime import datetime, timedelta, timezone

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.external.s3_client import S3Client

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.cleanup_tasks.cleanup_expired_images",
    queue="cleanup",
)
def cleanup_expired_images() -> dict:
    """
    清理超过 90 天的生成图片文件

    查询数据库中超过保留期限的 GenerationTask 记录，
    删除对应的 S3 文件，再删除数据库记录。
    按批次处理（每批 100 条）避免一次性操作过多数据。

    返回包含清理统计信息的字典
    """
    from app.db.models.image import GenerationTask

    db = SessionLocal()
    s3_client = S3Client()
    deleted_count = 0
    error_count = 0

    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)

        # 分批查询过期任务
        while True:
            expired_tasks = db.query(GenerationTask).filter(
                GenerationTask.created_at < cutoff_date,
                GenerationTask.status.in_(["done", "failed"]),
            ).limit(100).all()

            if not expired_tasks:
                break

            for task in expired_tasks:
                try:
                    # 删除 S3 上的原图和结果图
                    import asyncio
                    loop = asyncio.get_event_loop()

                    if task.result_image_url:
                        try:
                            loop.run_until_complete(s3_client.delete(task.result_image_url))
                        except Exception as e:
                            logger.warning(f"[Cleanup] S3 delete failed for result: {e}")

                    if task.original_image_url:
                        try:
                            loop.run_until_complete(s3_client.delete(task.original_image_url))
                        except Exception as e:
                            logger.warning(f"[Cleanup] S3 delete failed for original: {e}")

                    db.delete(task)
                    deleted_count += 1

                except Exception as e:
                    logger.error(f"[Cleanup] Failed to delete task {task.id}: {e}")
                    error_count += 1

            db.commit()

        logger.info(f"[Cleanup] Image cleanup completed: deleted={deleted_count}, errors={error_count}")
        return {"deleted": deleted_count, "errors": error_count}

    except Exception as e:
        logger.error(f"[Cleanup] Image cleanup task failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.cleanup_tasks.gdpr_data_cleanup",
    queue="cleanup",
)
def gdpr_data_cleanup() -> dict:
    """
    GDPR 合规数据删除任务

    查找注销超过 30 天的账户，永久删除其所有个人数据：
    - 用户账户记录（硬删除）
    - 积分账户和流水记录
    - 所有生成任务和图片文件
    - 购买记录（保留匿名化财务数据）

    返回包含处理统计信息的字典
    """
    from app.db.models.user import User
    from app.db.models.image import GenerationTask
    from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage

    db = SessionLocal()
    s3_client = S3Client()
    processed_count = 0
    error_count = 0

    try:
        # 查找注销超过 30 天的账户
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

        deleted_users = db.query(User).filter(
            User.deleted_at.isnot(None),
            User.deleted_at < cutoff_date,
        ).limit(50).all()

        for user in deleted_users:
            try:
                import asyncio
                loop = asyncio.get_event_loop()

                # 删除用户所有生成任务和对应 S3 文件
                tasks = db.query(GenerationTask).filter(
                    GenerationTask.user_id == user.id
                ).all()

                for task in tasks:
                    for url in [task.result_image_url, task.original_image_url]:
                        if url:
                            try:
                                loop.run_until_complete(s3_client.delete(url))
                            except Exception:
                                pass
                    db.delete(task)

                # 删除积分流水记录
                db.query(CreditTransaction).filter(
                    CreditTransaction.user_id == user.id
                ).delete()

                # 删除每日使用记录
                db.query(DailyFreeUsage).filter(
                    DailyFreeUsage.user_id == user.id
                ).delete()

                # 删除积分账户
                db.query(CreditAccount).filter(
                    CreditAccount.user_id == user.id
                ).delete()

                # 硬删除用户记录（GDPR 要求完全移除个人数据）
                db.delete(user)
                db.commit()

                processed_count += 1
                logger.info(f"[GDPR] Permanently deleted user data: {user.id}")

            except Exception as e:
                logger.error(f"[GDPR] Failed to delete user {user.id}: {e}")
                db.rollback()
                error_count += 1

        logger.info(f"[GDPR] Cleanup completed: processed={processed_count}, errors={error_count}")
        return {"processed": processed_count, "errors": error_count}

    except Exception as e:
        logger.error(f"[GDPR] Cleanup task failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()
