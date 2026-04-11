"""
邮箱验证码服务

处理验证码的生成、存储、校验逻辑
"""

import json
import random
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import redis

from app.core.exceptions import ValidationError, RateLimitError
from app.core.security import create_access_token
from app.config import settings


class VerificationService:
    """
    邮箱验证码服务

    负责验证码生命周期管理：生成、发送、校验、限流
    """

    # 验证码长度
    CODE_LENGTH = 6

    # 各场景过期时间（秒）
    EXPIRY_SECONDS = {
        "register": 600,       # 10分钟
        "login": 300,          # 5分钟
        "reset_password": 900, # 15分钟
    }

    # 发送频率限制（秒）
    RATE_LIMIT_SECONDS = 60

    # 每日最大发送次数
    DAILY_MAX_SENDS = 10

    # 最大校验失败次数
    MAX_ATTEMPTS = 5

    def __init__(self, redis_client: redis.Redis):
        """
        初始化验证码服务

        [redis_client] Redis 客户端实例
        """
        self.redis = redis_client

    def _get_key(self, email: str, scene: str) -> str:
        """
        获取 Redis Key

        [email] 邮箱地址
        [scene] 验证场景
        返回 str Redis Key 格式
        """
        return f"email_verify:{scene}:{email}"

    def _get_count_key(self, email: str) -> str:
        """
        获取计数器 Key

        [email] 邮箱地址
        返回 str 计数器 Redis Key
        """
        return f"email_code_count:{email}"

    def _generate_code(self) -> str:
        """
        生成6位数字验证码

        返回 str 6位数字字符串
        """
        return str(random.randint(100000, 999999))

    def _hash_code(self, code: str) -> str:
        """
        对验证码进行哈希（存储时脱敏）

        [code] 原始验证码
        返回 str SHA-256 哈希值
        """
        return hashlib.sha256(code.encode()).hexdigest()

    def _is_rate_limited(self, email: str, scene: str) -> bool:
        """
        检查是否在频率限制期内

        [email] 邮箱地址
        [scene] 验证场景
        返回 bool 是否被限制
        """
        key = f"email_rate:{scene}:{email}"
        return self.redis.exists(key) == 1

    def _set_rate_limit(self, email: str, scene: str) -> None:
        """
        设置频率限制

        [email] 邮箱地址
        [scene] 验证场景
        """
        key = f"email_rate:{scene}:{email}"
        self.redis.setex(key, self.RATE_LIMIT_SECONDS, "1")

    def _check_daily_limit(self, email: str) -> bool:
        """
        检查是否超过每日发送次数

        [email] 邮箱地址
        返回 bool 是否超限
        """
        key = self._get_count_key(email)
        count = self.redis.get(key)
        if count is None:
            return False
        return int(count) >= self.DAILY_MAX_SENDS

    def _increment_daily_count(self, email: str) -> int:
        """
        增加每日发送计数

        [email] 邮箱地址
        返回 int 当前计数
        """
        key = self._get_count_key(email)
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)  # 24小时过期
        results = pipe.execute()
        return results[0]

    def send_code(self, email: str, scene: str) -> Tuple[bool, int]:
        """
        发送验证码

        [email] 目标邮箱
        [scene] 场景 register/login/reset_password
        返回 (是否成功, 剩余有效期秒数)
        """
        # 频率限制检查
        if self._is_rate_limited(email, scene):
            raise RateLimitError(f"发送过于频繁，请 {self.RATE_LIMIT_SECONDS} 秒后重试")

        # 每日次数检查
        if self._check_daily_limit(email):
            raise RateLimitError("今日发送次数已用完，请明天再试")

        # 生成验证码
        code = self._generate_code()
        expiry = self.EXPIRY_SECONDS.get(scene, 600)

        # 存储验证码（Redis）
        key = self._get_key(email, scene)
        data = json.dumps({
            "code": self._hash_code(code),
            "created_at": int(datetime.now(timezone.utc).timestamp()),
            "attempts": 0,
        })
        self.redis.setex(key, expiry, data)

        # 发送邮件
        from app.external.resend_client import resend_client
        resend_client.send_verification_email(email, code, scene)

        # 设置频率限制
        self._set_rate_limit(email, scene)

        # 增加每日计数
        self._increment_daily_count(email)

        return True, expiry

    def verify_code(self, email: str, scene: str, code: str) -> bool:
        """
        校验验证码

        [email] 目标邮箱
        [scene] 场景
        [code] 用户输入的验证码
        返回 bool 是否验证通过
        """
        key = self._get_key(email, scene)
        data = self.redis.get(key)

        if not data:
            raise ValidationError("验证码已过期，请重新发送")

        info = json.loads(data)

        # 校验失败次数超限
        if info["attempts"] >= self.MAX_ATTEMPTS:
            self.redis.delete(key)
            raise ValidationError("验证失败次数过多，请重新发送验证码")

        # 验证码匹配
        if info["code"] == self._hash_code(code):
            # 验证成功，删除验证码（一次性）
            self.redis.delete(key)
            return True

        # 匹配失败，增加失败次数
        info["attempts"] += 1
        self.redis.setex(key, self.EXPIRY_SECONDS.get(scene, 600), json.dumps(info))

        remaining = self.MAX_ATTEMPTS - info["attempts"]
        raise ValidationError(f"验证码错误，剩余 {remaining} 次尝试机会")

    def create_verify_token(self, email: str, scene: str) -> str:
        """
        创建验证通过后的临时 Token

        [email] 已验证的邮箱
        [scene] 验证场景
        返回 str JWT Token
        """
        payload = {
            "sub": email,
            "scene": scene,
            "verified": True,
            "type": "verify",  # 区分于普通 access token
        }
        return create_access_token(payload, expires_delta=timedelta(minutes=15))

    def verify_token(self, token: str, expected_scene: str) -> str:
        """
        验证临时 Token，获取邮箱

        [token] 临时 Token
        [expected_scene] 期望的场景
        返回 str 邮箱地址
        """
        from jose import jwt, JWTError
        from app.core.exceptions import AuthenticationError

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError:
            raise AuthenticationError("无效的验证令牌")

        if not payload.get("verified"):
            raise AuthenticationError("未完成邮箱验证")

        if payload.get("scene") != expected_scene:
            raise AuthenticationError("验证场景不匹配")

        return payload.get("sub")
