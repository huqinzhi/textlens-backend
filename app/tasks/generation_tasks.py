"""
AI 图片生成 Celery 任务
处理阿里云百炼图片编辑的异步任务：下载原图、提取视觉风格、构建提示词、调用wanxiang API、上传结果、更新状态
"""
import base64
import logging
from celery import Task
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models.image import GenerationTask
from app.external.aliyun_client import AliyunClient
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
    _aliyun_client: AliyunClient = None
    _s3_client: S3Client = None

    @property
    def db(self) -> Session:
        """懒加载数据库会话"""
        if self._db is None or not self._db.is_active:
            self._db = SessionLocal()
        return self._db

    @property
    def aliyun_client(self) -> AliyunClient:
        """懒加载阿里云百炼客户端"""
        if self._aliyun_client is None:
            self._aliyun_client = AliyunClient()
        return self._aliyun_client

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
            _execute_generation(task, self.aliyun_client, self.s3_client)
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
    aliyun_client: AliyunClient,
    s3_client: S3Client,
) -> str:
    """
    执行图片生成的核心异步逻辑

    使用阿里云百炼 wanxiang-image-edit 进行图片编辑：
    1. 下载原始图片
    2. 提取每个编辑区域的视觉风格
    3. 构建包含原文→新文和风格信息的提示词
    4. 调用 wanxiang-image-edit 直接生成

    [task] 数据库中的生成任务记录
    [aliyun_client] 阿里云百炼客户端
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

    # 提取每个编辑区域的视觉风格信息
    from app.external.google_vision import extract_text_region_style
    ocr_map = {b.get("id"): b for b in ocr_blocks}
    visual_styles = {}
    for edit in edit_blocks:
        block_id = edit.get("id") or edit.get("block_id")
        block_info = ocr_map.get(block_id, {})
        x_norm = block_info.get("x", 0.0)
        y_norm = block_info.get("y", 0.0)
        w_norm = block_info.get("width", 0.0)
        h_norm = block_info.get("height", 0.0)
        abs_x = int(x_norm * image_width)
        abs_y = int(y_norm * image_height)
        abs_w = int(w_norm * image_width)
        abs_h = int(h_norm * image_height)
        style = await extract_text_region_style(original_bytes, abs_x, abs_y, abs_w, abs_h)
        visual_styles[block_id] = style

    # 构建阿里云百炼提示词（包含原文→新文映射和视觉风格）
    prompt = _build_aliyun_prompt(
        ocr_blocks, edit_blocks, image_width, image_height, detected_language, visual_styles
    )

    # 调用阿里云百炼进行图片编辑
    logger.info(f"[Generation] Using Aliyun wanxiang for task: {task.id}")
    result_b64 = await aliyun_client.edit_image(
        image_bytes=original_bytes,
        prompt=prompt,
        strength=0.4,  # 越小越保真
    )

    # 将 base64 结果解码为字节
    result_bytes = base64.b64decode(result_b64)

    # 上传结果图片到 S3
    result_url = await s3_client.upload_result(result_bytes, "image/png")

    return result_url


def _build_aliyun_prompt(
    ocr_blocks: list[dict],
    edit_blocks: list[dict],
    image_width: int,
    image_height: int,
    detected_language: str,
    visual_styles: dict[str, dict] | None = None,
) -> str:
    """
    构建阿里云百炼图片编辑提示词

    将 OCR 文字块和编辑指令转化为阿里云百炼的提示词格式，
    详细描述原文→新文映射、文字位置、视觉风格等信息。

    [ocr_blocks] 原始 OCR 识别文字块列表
    [edit_blocks] 用户编辑后的文字块列表
    [image_width] 图片宽度
    [image_height] 图片高度
    [detected_language] 检测到的文字语言
    [visual_styles] 文字区域的视觉风格信息
    返回阿里云百炼格式的提示词
    """
    # 构建原文 → 文字块数据的映射
    ocr_map = {b.get("id"): b for b in ocr_blocks}
    visual_styles = visual_styles or {}

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

        # 获取视觉风格描述
        style = visual_styles.get(block_id, {})
        text_color_desc = "浅色文字" if style.get("text_color") == "light" else "深色文字"
        avg_color = style.get("avg_color", [0, 0, 0])
        color_rgb = f"RGB({avg_color[0]}, {avg_color[1]}, {avg_color[2]})"

        region_desc = (
            f'将位置 ({abs_x},{abs_y})，尺寸 {abs_width}x{abs_height}px 的文字 '
            f'"{original_text}" 替换为 "{new_text}"。'
            f'文字颜色：{text_color_desc}（{color_rgb}），'
            f'字体大小与原图保持一致。'
        )
        regions_list.append(region_desc)

    if not regions_list:
        return "Keep the image exactly as it is, maintain all text and visual elements."

    regions_text = "\n".join(regions_list)

    # 阿里云百炼提示词格式
    prompt = f"""将图片中的文字按以下要求修改：

图片信息：
- 尺寸：{image_width}x{image_height} 像素
- 语言：{detected_language}

文字修改详情：
{regions_text}

重要要求：
1. 严格保持原图的构图、布局、光影效果和所有视觉元素
2. 替换后的文字必须与周围环境在颜色、质感、透视上完全一致
3. 文字的字体、大小、间距、倾斜角度必须与原图保持一致
4. 如果原文字有下划线、描边、阴影等效果，新文字必须保留相同的装饰效果
5. 文字位置必须精确对齐，不能有任何偏移
6. 背景、物体、人物等所有非文字区域必须完全不变
7. 生成图片质量要高，文字边缘要清晰锐利，无模糊或锯齿"""

    return prompt


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
