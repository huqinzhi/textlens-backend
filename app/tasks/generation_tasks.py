"""
AI 图片生成 Celery 任务
处理 Stability AI 图片编辑的异步任务：下载原图、调用 API、上传结果、更新状态
"""
import base64
import logging
from celery import Task
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models.image import GenerationTask
from app.external.stability_api import StabilityAIClient
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
    _stability_client: StabilityAIClient = None
    _s3_client: S3Client = None

    @property
    def db(self) -> Session:
        """懒加载数据库会话"""
        if self._db is None or not self._db.is_active:
            self._db = SessionLocal()
        return self._db

    @property
    def stability_client(self) -> StabilityAIClient:
        """懒加载 Stability AI 客户端"""
        if self._stability_client is None:
            self._stability_client = StabilityAIClient()
        return self._stability_client

    @property
    def s3_client(self) -> S3Client:
        """懒加载 S3 客户端"""
        if self._s3_client is None:
            self._s3_client = S3Client()
        return self._s3_client
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
            _execute_generation(task, self.stability_client, self.s3_client)
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
    stability_client: StabilityAIClient,
    s3_client: S3Client,
) -> str:
    """
    执行图片生成的核心异步逻辑

    使用 Stability AI 进行图片编辑。

    [task] 数据库中的生成任务记录
    [stability_client] Stability AI 客户端
    [s3_client] S3 存储客户端
    返回生成图片的 S3 URL
    """
    # 下载原始图片
    original_bytes = await s3_client.download(task.original_image_url)

    # 从任务数据中提取 OCR 文字块和编辑指令
    ocr_data = task.ocr_data or {}
    ocr_blocks = ocr_data.get("text_blocks", [])
    edit_blocks = task.edit_data if task.edit_data else []

    # 提取图片尺寸和语言信息
    image_width = ocr_data.get("image_width", 1024)
    image_height = ocr_data.get("image_height", 1024)
    detected_language = ocr_data.get("detected_language", "en")

    # 使用 Stability AI 生成
    logger.info(f"[Generation] Using Stability AI provider for task: {task.id}")

    # 构建 Stability AI 提示词
    prompt = _build_stability_prompt(ocr_blocks, edit_blocks, image_width, image_height, detected_language)

    # 根据编辑区域创建 mask
    mask_bytes = _build_edit_mask(edit_blocks, ocr_blocks, image_width, image_height)

    result_b64 = await stability_client.edit_image(
        image_bytes=original_bytes,
        prompt=prompt,
        mask_bytes=mask_bytes,
    )

    # 将 base64 结果解码为字节
    result_bytes = base64.b64decode(result_b64)

    # 上传结果图片到 S3
    result_url = await s3_client.upload_result(result_bytes, "image/png")

    return result_url


def _build_stability_prompt(
    ocr_blocks: list[dict],
    edit_blocks: list[dict],
    image_width: int,
    image_height: int,
    detected_language: str,
) -> str:
    """
    构建 Stability AI 图片编辑提示词

    将 OCR 文字块和编辑指令转化为 Stability AI 专用的提示词格式。
    Stability AI 不支持直接传入图片编辑，需要在提示词中描述期望的修改。

    [ocr_blocks] 原始 OCR 识别文字块列表
    [edit_blocks] 用户编辑后的文字块列表
    [image_width] 图片宽度
    [image_height] 图片高度
    [detected_language] 检测到的文字语言
    返回 Stability AI 格式的提示词
    """
    from app.core.constants import GENERATION_PROMPT_TEMPLATE

    # 构建原文 → 文字块数据的映射
    ocr_map = {b.get("id"): b for b in ocr_blocks}

    # 构建替换指令列表
    regions_list = []

    for edit in edit_blocks:
        block_id = edit.get("id") or edit.get("block_id")
        new_text = edit.get("new_text", "").strip()
        original_text = edit.get("original_text", "")

        if not original_text and block_id and block_id in ocr_map:
            original_text = ocr_map[block_id].get("text", "")

        if not new_text:
            continue

        block_info = ocr_map.get(block_id, {})
        x = block_info.get("x", 0.0)
        y = block_info.get("y", 0.0)
        width = block_info.get("width", 0.0)
        height = block_info.get("height", 0.0)

        abs_x = int(x * image_width)
        abs_y = int(y * image_height)
        abs_width = int(width * image_width)
        abs_height = int(height * image_height)

        region_desc = f"""[{len(regions_list) + 1}] Replace text "{original_text}" with "{new_text}" at position ({abs_x},{abs_y}) with size {abs_width}x{abs_height}px. Keep the same font style, size, color, and position."""
        regions_list.append(region_desc)

    if not regions_list:
        return "Keep the image exactly as is."

    regions_text = "\n".join(regions_list)

    # Stability AI 提示词格式
    prompt = f"""Text replacement only. You are doing precise text inpainting - ONLY replace the text, nothing else.

Image dimensions: {image_width}x{image_height} pixels, Language: {detected_language}

Text modifications:
{regions_text}

STRICT requirements:
1. Replace ONLY the exact text specified above with the new text
2. NO background color - the text area must be transparent/clear, same as surrounding area
3. NO new elements, shapes, or decorations - only the text itself
4. Text must be clean, crisp, sharp - not blurry or distorted
5. Preserve the exact same font style, size, weight as the original text would have had
6. Do NOT change, modify, or affect ANY other part of the image
7. The result should look exactly as if only the text characters were swapped"""

    return prompt


def _build_edit_mask(
    edit_blocks: list[dict],
    ocr_blocks: list[dict],
    image_width: int,
    image_height: int,
) -> bytes | None:
    """
    根据编辑区域构建 mask 蒙版

    将所有需要编辑的文字区域合并为一个 mask，白色区域表示需要 AI 重新生成。

    [edit_blocks] 用户编辑后的文字块列表
    [ocr_blocks] 原始 OCR 识别文字块列表
    [image_width] 图片宽度
    [image_height] 图片高度
    返回 mask 字节数据，如果没有编辑区域则返回 None
    """
    from PIL import Image, ImageDraw

    # 构建原文 → 文字块数据的映射
    ocr_map = {b.get("id"): b for b in ocr_blocks}

    # 收集所有需要编辑的区域
    regions = []
    for edit in edit_blocks:
        block_id = edit.get("id") or edit.get("block_id")
        block_info = ocr_map.get(block_id, {})

        x = block_info.get("x", 0.0)
        y = block_info.get("y", 0.0)
        width = block_info.get("width", 0.0)
        height = block_info.get("height", 0.0)

        abs_x = int(x * image_width)
        abs_y = int(y * image_height)
        abs_width = int(width * image_width)
        abs_height = int(height * image_height)

        if abs_width > 0 and abs_height > 0:
            regions.append((abs_x, abs_y, abs_width, abs_height))

    if not regions:
        return None

    # 创建 mask（黑色背景）
    mask = Image.new("L", (image_width, image_height), 0)
    draw = ImageDraw.Draw(mask)

    # 绘制所有编辑区域（白色）
    for x, y, w, h in regions:
        draw.rectangle([x, y, x + w, y + h], fill=255)

    import io
    output = io.BytesIO()
    mask.save(output, format="PNG")
    return output.getvalue()


def _refund_credits(db: Session, task: GenerationTask) -> None:
    """
    任务失败时退还已扣除的积分

    [db] 数据库会话
    [task] 失败的生成任务记录
    """
    from app.db.models.credit import CreditAccount, CreditTransaction
    from app.core.constants import CreditTransactionType, CreditSourceType

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
                type=CreditTransactionType.EARN,
                source=CreditSourceType.REFUND,
                ref_id=str(task.id),
                description=f"Refund for failed generation task {task.id}",
                balance_after=credit_account.balance,
            )
            db.add(refund_tx)
            db.commit()
            logger.info(f"[Generation] Refunded {task.credits_cost} credits for task {task.id}")
    except Exception as e:
        logger.error(f"[Generation] Failed to refund credits: {e}")
