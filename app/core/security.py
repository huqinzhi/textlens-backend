"""
安全工具模块

提供 JWT Token 生成与验证、密码哈希等安全相关功能。
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# 密码哈希上下文，使用 bcrypt 算法
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    对用户密码进行哈希处理

    使用 bcrypt 算法生成安全哈希，不可逆加密。
    [password] 明文密码字符串
    返回 哈希后的密码字符串
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码与哈希密码是否匹配

    [plain_password] 用户输入的明文密码
    [hashed_password] 数据库中存储的哈希密码
    返回 匹配返回 True，否则返回 False
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    生成 JWT Access Token

    [data] 需要编码到 Token 中的数据字典（通常包含 sub: user_id）
    [expires_delta] 自定义过期时间，默认使用配置文件中的时长
    返回 JWT Token 字符串
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """
    生成 JWT Refresh Token

    Refresh Token 有效期更长，用于获取新的 Access Token。
    [user_id] 用户 ID
    返回 Refresh Token 字符串
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS)
    data = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(data, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    验证并解析 JWT Access Token

    [token] JWT Token 字符串
    返回 解析成功返回 payload 字典，失败返回 None
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def verify_refresh_token(token: str) -> Optional[str]:
    """
    验证并解析 JWT Refresh Token

    [token] Refresh Token 字符串
    返回 验证成功返回用户 ID 字符串，失败返回 None
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "refresh":
            return None
        return payload.get("sub")
    except JWTError:
        return None
