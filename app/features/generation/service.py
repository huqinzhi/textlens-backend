"""
AI 生图业务逻辑服务层
处理积分验证、内容审核、任务创建、Celery调度等核心逻辑
"""
import uuid
from sqlalchemy.orm import Session

from app.core.constants import TaskStatus, GENERATION_PROMPT_TEMPLATE
from app.core.exceptions import InsufficientCreditsError, NotFoundError, AuthorizationError
from app.db.models.image import GenerationTask, GenerationStatus
from app.db.models.credit import CreditAccount, CreditTransaction
from app.core.constants import CreditTransactionType, CreditSourceType
from app.schemas.image import GenerateRequest, GenerationTaskResponse
from app.config import settings


class GenerationService:
    """
    AI 生图服务类

    编排积分验证、内容审核、Celery 任务创建的完整流程。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db

    async def submit(self, request: GenerateRequest, current_user) -> GenerationTaskResponse:
        """
        提交 AI 生图任务

        执行完整的前置检查：
        1. 检查是否有免费生成次数（新用户1次）
        2. 检查积分是否充足
        3. 创建 GenerationTask 记录
        4. 扣除积分或标记为免费
        5. 提交 Celery 异步任务

        [request] 生图请求数据
        [current_user] 当前登录用户
        返回 GenerationTaskResponse 包含任务 ID 和预计等待时间
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
            status=GenerationStatus.PENDING,
            credits_cost=0 if is_free else credits_cost,
            is_free=1 if is_free else 0,
            has_watermark=0,
        )
        self.db.add(task)

        # 扣除积分（非免费情况下）
        if not is_free:
            self._deduct_credits(current_user.id, credits_cost, str(task.id))

        self.db.commit()

        # 提交 Celery 异步任务
        from app.tasks.generation_tasks import process_generation
        celery_task = process_generation.delay(str(task.id))
        task.celery_task_id = celery_task.id
        self.db.commit()

        return self._to_response(task)

    async def get_status(self, task_id: str, current_user) -> GenerationTaskResponse:
        """
        查询生图任务状态

        [task_id] 任务 UUID 字符串
        [current_user] 当前登录用户（权限验证）
        返回 GenerationTaskResponse 任务当前状态
        """
        task = self.db.query(GenerationTask).filter(
            GenerationTask.id == task_id
        ).first()

        if not task:
            raise NotFoundError("Generation task")

        # 权限验证：只能查询自己的任务
        if str(task.user_id) != str(current_user.id):
            raise AuthorizationError()

        return self._to_response(task)

    async def cancel(self, task_id: str, current_user) -> None:
        """
        取消生图任务并退款积分

        只能取消 pending 状态的任务。
        取消后退还已扣除的积分。

        [task_id] 任务 UUID 字符串
        [current_user] 当前登录用户
        """
        task = self.db.query(GenerationTask).filter(
            GenerationTask.id == task_id,
            GenerationTask.user_id == current_user.id,
        ).first()

        if not task:
            raise NotFoundError("Generation task")

        if task.status != GenerationStatus.PENDING:
            from app.core.exceptions import ValidationError
            raise ValidationError("Only pending tasks can be cancelled")

        task.status = GenerationStatus.CANCELLED

        # 退款积分
        if task.credits_cost > 0:
            self._refund_credits(current_user.id, task.credits_cost, str(task.id))

        self.db.commit()

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
            description=f"AI image generation",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)

    def _refund_credits(self, user_id, amount: int, ref_id: str) -> None:
        """
        退款积分（任务取消或失败时调用）

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
            description="Refund for cancelled/failed generation",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)

    def _to_response(self, task: GenerationTask) -> GenerationTaskResponse:
        """
        将 GenerationTask ORM 对象转换为响应体

        [task] GenerationTask ORM 对象
        返回 GenerationTaskResponse Pydantic 响应体
        """
        # 预计等待时间
        estimated = 20

        return GenerationTaskResponse(
            task_id=task.id,
            status=TaskStatus(task.status.value),
            result_image_url=task.result_image_url,
            original_image_url=task.original_image_url,
            credits_cost=task.credits_cost,
            has_watermark=bool(task.has_watermark),
            error_message=task.error_message,
            estimated_seconds=estimated if task.status == GenerationStatus.PENDING else None,
            created_at=task.created_at,
            completed_at=task.completed_at,
        )
