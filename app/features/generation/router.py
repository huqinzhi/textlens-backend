"""
AI 生图模块路由
处理 AI 生图请求提交、状态查询等接口
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.image import GenerateRequest, GenerationTaskResponse
from app.features.generation.service import GenerationService

router = APIRouter()


@router.post("", response_model=GenerationTaskResponse)
async def submit_generation(
    request: GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    提交并同步执行 AI 生图任务

    验证用户积分/免费次数后：
    1. 扣除相应积分
    2. 同步调用阿里云百炼 API 生成图片
    3. 直接返回结果图片 URL

    注意：此接口为同步接口，生成图片可能需要 10-20 秒，请前端显示 loading。

    [request] 生图请求，包含图片ID和编辑内容
    [current_user] 当前登录用户
    [db] 数据库会话
    返回 GenerationTaskResponse 包含 task_id 和结果图片 URL
    """
    generation_service = GenerationService(db)
    return await generation_service.submit(request, current_user)


@router.get("/{task_id}", response_model=GenerationTaskResponse)
async def get_generation_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    查询 AI 生图任务状态

    查询已完成任务的结果。

    [task_id] 提交生图请求时返回的任务 ID
    [current_user] 当前登录用户（确保只能查询自己的任务）
    [db] 数据库会话
    返回 GenerationTaskResponse 当前任务状态，包含结果图片 URL
    """
    generation_service = GenerationService(db)
    task = db.query(GenerationTask).filter(
        GenerationTask.id == task_id
    ).first()

    if not task:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Generation task")

    if str(task.user_id) != str(current_user.id):
        from app.core.exceptions import AuthorizationError
        raise AuthorizationError()

    from app.core.constants import TaskStatus
    return GenerationTaskResponse(
        task_id=task.id,
        status=TaskStatus(task.status.value),
        result_image_url=task.result_image_url,
        original_image_url=task.original_image_url,
        credits_cost=task.credits_cost,
        has_watermark=bool(task.has_watermark),
        error_message=task.error_message,
        estimated_seconds=None,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


# 导入 GenerationTask 模型
from app.db.models.image import GenerationTask
