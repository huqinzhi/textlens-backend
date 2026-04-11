"""
全局依赖注入模块

定义 FastAPI 依赖注入函数，供路由层使用。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import verify_access_token
from app.core.exceptions import AuthenticationError

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """
    获取当前已登录用户的依赖函数

    从请求头的 Bearer Token 中解析并验证 JWT，返回对应的用户对象。
    未登录或 Token 失效时抛出 401 异常。

    [credentials] HTTP Bearer Token 凭证
    [db] 数据库会话对象
    返回 当前用户 ORM 对象
    """
    from app.db.models.user import User

    token = credentials.credentials
    payload = verify_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None),
        User.is_active == True,
    ).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user
