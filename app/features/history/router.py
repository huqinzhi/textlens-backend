"""
历史记录模块路由
处理用户 AI 生成历史记录的查询和删除接口
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.image import HistoryItem
from app.schemas.common import PageResponse
from app.features.history.service import HistoryService

router = APIRouter()


@router.get("", response_model=PageResponse[HistoryItem])
async def get_history(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页数量，最大50"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取用户历史记录列表接口

    分页返回用户所有 AI 生图记录，按创建时间倒序排列。
    每页最多 20 条，支持下拉刷新（page=1）和分页加载。

    [page] 页码，从 1 开始
    [page_size] 每页数量，默认 20，最大 50
    [current_user] 当前登录用户
    [db] 数据库会话
    返回 PageResponse[HistoryItem] 分页历史记录列表
    """
    history_service = HistoryService(db)
    return await history_service.get_history(current_user, page, page_size)


@router.delete("/{history_id}", status_code=204)
async def delete_history(
    history_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    删除单条历史记录接口

    同时删除数据库记录和 S3/R2 上的图片文件（本地 + 云端）。

    [history_id] 要删除的历史记录 ID（GenerationTask ID）
    [current_user] 当前登录用户（权限验证）
    [db] 数据库会话
    """
    history_service = HistoryService(db)
    await history_service.delete(history_id, current_user)
