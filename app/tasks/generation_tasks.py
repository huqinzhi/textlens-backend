"""
AI 图片生成 Celery 任务
处理 GPT-4o 图片编辑的异步任务：下载原图、调用 API、上传结果、更新状态
"""
import base64
import logging
from celery import Task
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models.image import GenerationTask
from app.external.openai_api import OpenAIClient
from app.external.s3_client import S3Client
from app.core.constants import TaskStatus

logger = logging.getLogger(__name__)


class GenerationTaskBase(Task):
    """
    生成任务基类

    提供数据库会话和外部客户端的懒加载，
    避免每次任务执行都重新创建连接。
    """

    _db: Session = None
    _openai_client: OpenAIClient = None
    _s3_client: S3Client = None

    @property
    def db(self) -> Session:
        """懒加载数据库会话"""
        if self._db is None or not self._db.is_active:
            self._db = SessionLocal()
        return self._db

    @property
    def openai_client(self) -> OpenAIClient:
        """懒加载 OpenAI 客户端"""
        if self._openai_client is None:
            self._openai_client = OpenAIClient()
        return self._openai_client

    @property
    def s3_client(self) -> S3Client:
        """懒加载 S3 客户端"""
        if self._s3_client is None:
            self._s3_client = S3Client()
        return self._s3_client


@celery_app.task(
    bind=True,
    base=GenerationTaskBase,
    name="app.tasks.generation_tasks.process_generation",
    max_retries=2,
    default_retry_delay=10,
    queue="generation",
)
def process_generation(self, task_id: str) -> dict:
    """
    执行 AI 图片文字编辑生成任务

    完整流程：从数据库加载任务 → 下载原图字节 → 构建提示词 →
    调用 GPT-4o 图片编辑 API → 上传结果到 S3 → 更新任务状态为 done。
    任务失败时自动重试最多 2 次，最终失败则标记为 failed 并退还积分。

    [task_id] GenerationTask 数据库记录 ID
    返回包含任务状态和结果 URL 的字典
    """
    import asyncio

    logger.info(f"[Generation] Starting task: {task_id}")

    # 查询任务记录
    task = self.db.query(GenerationTask).filter(
        GenerationTask.id == task_id
    ).first()

    if not task:
        logger.error(f"[Generation] Task not found: {task_id}")
        return {"error": "Task not found"}

    if task.status.value == TaskStatus.cancelled.value:
        logger.info(f"[Generation] Task cancelled, skipping: {task_id}")
        return {"status": "cancelled"}

    # 更新状态为处理中
    task.status = "processing"
    self.db.commit()

    try:
        result_url = asyncio.get_event_loop().run_until_complete(
            _execute_generation(task, self.openai_client, self.s3_client)
        )

        # 更新任务状态为完成
        task.status = "done"
        task.result_image_url = result_url
        self.db.commit()

        logger.info(f"[Generation] Task completed: {task_id}")
        return {"status": "done", "result_image_url": result_url}

    except Exception as exc:
        logger.error(f"[Generation] Task failed: {task_id}, error: {exc}")

        try:
            # 任务重试
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            # 超过最大重试次数，标记为失败
            task.status = "failed"
            self.db.commit()

            # 退还积分（如果扣了积分）
            if task.credits_cost and task.credits_cost > 0:
                _refund_credits(self.db, task)

            return {"status": "failed", "error": str(exc)}


async def _execute_generation(
    task: GenerationTask,
    openai_client: OpenAIClient,
    s3_client: S3Client,
) -> str:
    """
    执行图片生成的核心异步逻辑

    [task] 数据库中的生成任务记录
    [openai_client] OpenAI API 客户端
    [s3_client] S3 存储客户端
    返回生成图片的 S3 URL
    """
    # 下载原始图片
    original_bytes = await s3_client.download(task.original_image_url)

    # 从任务数据中提取 OCR 文字块和编辑指令
    ocr_blocks = task.ocr_data.get("text_blocks", []) if task.ocr_data else []
    edit_blocks = task.edit_data if task.edit_data else []

    # 构建 GPT-4o 提示词
    prompt = await openai_client.generate_edit_prompt(ocr_blocks, edit_blocks)

    # 调用 GPT-4o 执行图片编辑
    quality = task.quality.value if hasattr(task.quality, "value") else str(task.quality)
    result_b64 = await openai_client.edit_image_with_text(
        original_image_url=task.original_image_url,
        original_image_bytes=original_bytes,
        prompt=prompt,
        quality=quality,
    )

    # 将 base64 结果解码为字节
    result_bytes = base64.b64decode(result_b64)

    # 上传结果图片到 S3
    result_url = await s3_client.upload_result(result_bytes, "image/png")

    return result_url


def _refund_credits(db: Session, task: GenerationTask) -> None:
    """
    任务失败时退还已扣除的积分

    [db] 数据库会话
    [task] 失败的生成任务记录
    """
    from app.db.models.credit import CreditAccount, CreditTransaction, TransactionType, TransactionSource

    try:
        credit_account = db.query(CreditAccount).filter(
            CreditAccount.user_id == task.user_id
        ).with_for_update().first()

        if credit_account and task.credits_cost:
            credit_account.balance += task.credits_cost
            credit_account.total_spent -= task.credits_cost

            refund_tx = CreditTransaction(
                user_id=task.user_id,
                credit_account_id=credit_account.id,
                amount=task.credits_cost,
                type=TransactionType.earn,
                source=TransactionSource.refund,
                ref_id=str(task.id),
                description=f"Refund for failed generation task {task.id}",
                balance_after=credit_account.balance,
            )
            db.add(refund_tx)
            db.commit()
            logger.info(f"[Generation] Refunded {task.credits_cost} credits for task {task.id}")
    except Exception as e:
        logger.error(f"[Generation] Failed to refund credits: {e}")
