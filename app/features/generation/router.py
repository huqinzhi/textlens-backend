"""
AI 生图模块路由
处理 AI 生图请求提交、状态轮询等接口
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.image import GenerateRequest, GenerationTaskResponse
from app.features.generation.service import GenerationService

router = APIRouter()


@router.post("", response_model=GenerationTaskResponse, status_code=202)
async def submit_generation(
    request: GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    提交 AI 生图任务接口（异步）

    验证用户积分/免费次数后，扣除相应积分，
    创建 Celery 异步任务进行 AI 生图，
    立即返回 task_id，客户端通过轮询接口获取进度。

    生成流程：
    1. 验证免费次数/积分是否充足
    2. 内容审核（OpenAI Moderation API）
    3. 扣除积分
    4. 异步提交 Celery 任务（调用 OpenAI GPT-4o）
    5. 返回 task_id 和预计等待时间

    [request] 生图请求，包含图片ID、编辑内容和质量等级
    [current_user] 当前登录用户
    [db] 数据库会话
    返回 GenerationTaskResponse 包含 task_id 和初始状态
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
    查询 AI 生图任务状态接口（轮询）

    客户端每隔2-3秒调用此接口轮询生图进度，
    任务完成（done/failed）后停止轮询。

    状态流转：pending → processing → done / failed

    [task_id] 提交生图请求时返回的任务 ID
    [current_user] 当前登录用户（确保只能查询自己的任务）
    [db] 数据库会话
    返回 GenerationTaskResponse 当前任务状态，完成时包含结果图片 URL
    """
    generation_service = GenerationService(db)
    return await generation_service.get_status(task_id, current_user)


@router.post("/{task_id}/cancel", status_code=204)
async def cancel_generation(
    task_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    取消 AI 生图任务接口

    取消尚未开始的 pending 状态任务，并退还已扣积分。
    已在处理中的任务（processing）不可取消。

    [task_id] 需要取消的任务 ID
    [current_user] 当前登录用户
    [db] 数据库会话
    """
    generation_service = GenerationService(db)
    await generation_service.cancel(task_id, current_user)
