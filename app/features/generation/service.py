"""
AI 生图业务逻辑服务层
处理积分验证、图片生成同步调用等核心逻辑
"""
import uuid
import asyncio
import base64
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.constants import TaskStatus
from app.core.exceptions import InsufficientCreditsError, NotFoundError
from app.db.models.image import GenerationTask, GenerationStatus
from app.db.models.credit import CreditAccount, CreditTransaction
from app.core.constants import CreditTransactionType, CreditSourceType
from app.schemas.image import GenerateRequest, GenerationTaskResponse
from app.config import settings


class GenerationService:
    """
    AI 生图服务类

    编排积分验证、图片生成（同步调用阿里云百炼API）的完整流程。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db

    async def submit(self, request: GenerateRequest, current_user) -> GenerationTaskResponse:
        """
        同步执行 AI 生图任务

        执行完整流程：
        1. 检查是否有免费生成次数（新用户1次）
        2. 检查积分是否充足
        3. 扣除积分
        4. 调用阿里云百炼 API 生成图片（同步）
        5. 上传结果到 R2
        6. 创建 GenerationTask 记录
        7. 返回结果

        [request] 生图请求数据
        [current_user] 当前登录用户
        返回 GenerationTaskResponse 包含结果图片 URL
        """
        credits_cost = settings.GENERATION_CREDITS_COST
        is_free = False

        # 检查是否有免费生成次数（新用户首次生成免费）
        if getattr(current_user, 'has_free_generation', False):
            is_free = True
            current_user.has_free_generation = False
            self.db.flush()

        # 如果不是免费，扣除积分
        if not is_free:
            credit_account = self.db.query(CreditAccount).filter(
                CreditAccount.user_id == current_user.id
            ).first()
            if not credit_account or credit_account.balance < credits_cost:
                current_balance = credit_account.balance if credit_account else 0
                raise InsufficientCreditsError(required=credits_cost, current=current_balance)

        # 获取原始图片和 OCR 结果
        from app.db.models.image import Image, OCRResult
        image = self.db.query(Image).filter(Image.id == request.image_id).first()
        if not image:
            raise NotFoundError("Image not found")

        ocr_result = self.db.query(OCRResult).filter(OCRResult.image_id == request.image_id).first()

        # 构建 OCR 数据快照（包含尺寸和语言信息供生成时使用）
        ocr_data = {
            "text_blocks": ocr_result.text_blocks if ocr_result else [],
            "image_width": image.width or 1024,
            "image_height": image.height or 1024,
            "detected_language": ocr_result.detected_language if ocr_result else "en",
        }

        # 创建生成任务记录
        task = GenerationTask(
            id=uuid.uuid4(),
            user_id=current_user.id,
            image_id=request.image_id,
            original_image_url=image.original_url,
            ocr_data=ocr_data,
            edit_data=[block.model_dump() for block in request.edit_blocks],
            status=GenerationStatus.PROCESSING,
            credits_cost=0 if is_free else credits_cost,
            is_free=1 if is_free else 0,
            has_watermark=0,
        )
        self.db.add(task)

        # 扣除积分（非免费情况下）
        if not is_free:
            self._deduct_credits(current_user.id, credits_cost, str(task.id))

        self.db.commit()

        try:
            # 同步调用图片生成
            result_url = await self._execute_generation(task)

            # 更新任务为完成
            task.status = GenerationStatus.DONE
            task.result_image_url = result_url
            task.completed_at = datetime.utcnow()
            self.db.commit()

            return GenerationTaskResponse(
                task_id=task.id,
                status=TaskStatus.DONE,
                result_image_url=result_url,
                original_image_url=task.original_image_url,
                credits_cost=task.credits_cost,
                has_watermark=False,
                error_message=None,
                estimated_seconds=None,
                created_at=task.created_at,
                completed_at=task.completed_at,
            )

        except Exception as e:
            # 生成失败，标记为失败
            task.status = GenerationStatus.FAILED
            task.error_message = str(e)
            self.db.commit()

            # 退还积分
            if not is_free and task.credits_cost > 0:
                self._refund_credits(current_user.id, task.credits_cost, str(task.id))

            raise

    async def _execute_generation(self, task: GenerationTask) -> str:
        """
        执行图片生成的核心逻辑

        使用阿里云百炼 wanxiang-image-edit 进行图片编辑：
        1. 下载原始图片
        2. 提取每个编辑区域的视觉风格
        3. 构建包含原文→新文和风格信息的提示词
        4. 调用 wanxiang-image-edit 直接生成

        [task] 数据库中的生成任务记录
        返回生成图片的 R2 URL
        """
        from app.external.aliyun_client import AliyunClient
        from app.external.s3_client import S3Client
        from app.external.google_vision import extract_text_region_style

        aliyun_client = AliyunClient()
        s3_client = S3Client()

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

        # 构建阿里云百炼提示词
        prompt = self._build_aliyun_prompt(
            ocr_blocks, edit_blocks, image_width, image_height, detected_language, visual_styles
        )

        # 调用阿里云百炼进行图片编辑
        result_b64 = await aliyun_client.edit_image(
            image_bytes=original_bytes,
            prompt=prompt,
            strength=0.4,
        )

        # 将 base64 结果解码为字节
        result_bytes = base64.b64decode(result_b64)

        # 上传结果图片到 R2
        result_url = await s3_client.upload_result(result_bytes, "image/png")

        return result_url

    def _build_aliyun_prompt(
        self,
        ocr_blocks: list[dict],
        edit_blocks: list[dict],
        image_width: int,
        image_height: int,
        detected_language: str,
        visual_styles: dict[str, dict] | None = None,
    ) -> str:
        """
        构建阿里云百炼图片编辑提示词

        [ocr_blocks] 原始 OCR 识别文字块列表
        [edit_blocks] 用户编辑后的文字块列表
        [image_width] 图片宽度
        [image_height] 图片高度
        [detected_language] 检测到的文字语言
        [visual_styles] 文字区域的视觉风格信息
        返回阿里云百炼格式的提示词
        """
        ocr_map = {b.get("id"): b for b in ocr_blocks}
        visual_styles = visual_styles or {}

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

    def _deduct_credits(self, user_id, amount: int, ref_id: str) -> None:
        """
        扣除用户积分，并记录积分流水

        [user_id] 用户 ID
        [amount] 扣除积分数量
        [ref_id] 关联的任务 ID
        """
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).with_for_update().first()

        credit_account.balance -= amount
        credit_account.total_spent += amount

        transaction = CreditTransaction(
            user_id=user_id,
            credit_account_id=credit_account.id,
            amount=-amount,
            type=CreditTransactionType.SPEND,
            source=CreditSourceType.GENERATION,
            ref_id=ref_id,
            description="AI image generation",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)

    def _refund_credits(self, user_id, amount: int, ref_id: str) -> None:
        """
        退款积分

        [user_id] 用户 ID
        [amount] 退款积分数量
        [ref_id] 关联的任务 ID
        """
        credit_account = self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).with_for_update().first()

        credit_account.balance += amount
        credit_account.total_spent -= amount

        transaction = CreditTransaction(
            user_id=user_id,
            credit_account_id=credit_account.id,
            amount=amount,
            type=CreditTransactionType.EARN,
            source=CreditSourceType.REFUND,
            ref_id=ref_id,
            description="Refund for failed generation",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)
