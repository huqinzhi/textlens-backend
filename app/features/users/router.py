"""
用户模块路由
处理用户信息查询和更新接口
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.user import UserProfileResponse, UserUpdateRequest
from app.features.users.service import UserService

router = APIRouter()


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取用户个人资料接口

    返回用户基本信息，包含积分余额和今日免费次数。

    [current_user] 当前登录用户
    [db] 数据库会话
    返回 UserProfileResponse 用户完整个人资料
    """
    user_service = UserService(db)
    return await user_service.get_profile(current_user)


@router.put("/profile", response_model=UserProfileResponse)
async def update_profile(
    request: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    更新用户个人资料接口

    支持更新用户名和头像 URL。

    [request] 更新请求体（username/avatar_url）
    [current_user] 当前登录用户
    [db] 数据库会话
    返回 UserProfileResponse 更新后的个人资料
    """
    user_service = UserService(db)
    return await user_service.update_profile(current_user, request)


@router.get("/credits", response_model=UserProfileResponse)
async def get_user_credits(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取用户积分信息接口

    返回积分余额和今日免费次数（快捷接口）。

    [current_user] 当前登录用户
    [db] 数据库会话
    返回 UserProfileResponse 包含积分信息的用户资料
    """
    user_service = UserService(db)
    return await user_service.get_profile(current_user)


@router.get("/export-data")
async def export_user_data(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    导出用户所有数据接口（GDPR 合规）

    返回用户的所有个人信息、积分数据、OCR 记录和生成历史。
    用于用户下载自己的数据副本。

    [current_user] 当前登录用户
    [db] 数据库会话
    返回 包含用户所有数据的字典
    """
    user_service = UserService(db)
    return await user_service.export_user_data(current_user)
