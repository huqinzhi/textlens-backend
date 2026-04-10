"""
速率限制中间件
基于 Redis 滑动窗口算法实现 API 访问频率限制
"""
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.exceptions import RateLimitError


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis 滑动窗口速率限制中间件

    对每个 IP（未登录）或用户 ID（已登录）进行访问频率控制。
    使用 Redis Sorted Set 实现滑动窗口算法，精度高且无边界效应。
    """

    # 各端点的速率限制配置（每分钟最大请求次数）
    RATE_LIMITS = {
        "/api/v1/auth/register": (5, 60),      # 注册：5次/分钟
        "/api/v1/auth/login": (10, 60),         # 登录：10次/分钟
        "/api/v1/generate": (20, 60),           # 生图：20次/分钟
        "/api/v1/ocr": (30, 60),               # OCR：30次/分钟
        "default": (60, 60),                    # 默认：60次/分钟
    }

    async def dispatch(self, request: Request, call_next):
        """
        拦截请求并检查速率限制

        [request] FastAPI 请求对象
        [call_next] 下一个中间件或路由处理函数
        返回响应或抛出速率限制错误
        """
        # 健康检查和文档接口不限流
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        # 确定速率限制标识符（优先用户ID，降级到IP）
        client_key = self._get_client_key(request)

        # 获取该路径的速率限制配置
        max_requests, window_seconds = self._get_limit_config(request.url.path)

        # 检查速率限制（仅在 Redis 可用时执行）
        redis = getattr(request.app.state, "redis", None)
        if redis:
            await self._check_rate_limit(redis, client_key, request.url.path, max_requests, window_seconds)

        response = await call_next(request)
        return response

    def _get_client_key(self, request: Request) -> str:
        """
        提取请求的限流标识符

        优先使用请求头中的用户 ID（由 JWT 解析后注入），
        降级使用客户端 IP 地址。

        [request] FastAPI 请求对象
        返回限流 key 字符串
        """
        # 从请求状态中获取用户 ID（已认证请求）
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"

        # 未认证请求使用 IP 限流
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        return f"ip:{client_ip}"

    def _get_limit_config(self, path: str) -> tuple[int, int]:
        """
        根据请求路径获取速率限制配置

        [path] 请求 URL 路径
        返回 (最大请求数, 时间窗口秒数) 元组
        """
        for prefix, limit in self.RATE_LIMITS.items():
            if prefix != "default" and path.startswith(prefix):
                return limit
        return self.RATE_LIMITS["default"]

    async def _check_rate_limit(
        self,
        redis,
        client_key: str,
        path: str,
        max_requests: int,
        window_seconds: int,
    ) -> None:
        """
        执行 Redis 滑动窗口速率限制检查

        使用 Sorted Set 存储请求时间戳，移除过期记录后
        判断当前窗口内的请求数是否超过限制。

        [redis] Redis 客户端实例
        [client_key] 限流标识符（user:xxx 或 ip:xxx）
        [path] 请求路径（用于构造 Redis Key）
        [max_requests] 时间窗口内最大请求次数
        [window_seconds] 时间窗口长度（秒）
        """
        now = time.time()
        window_start = now - window_seconds

        # Redis Key：rate_limit:{client_key}:{path_prefix}
        path_prefix = path.split("/")[3] if len(path.split("/")) > 3 else "other"
        redis_key = f"rate_limit:{client_key}:{path_prefix}"

        # 使用 Pipeline 保证原子性
        pipe = redis.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)  # 移除过期记录
        pipe.zadd(redis_key, {str(now): now})              # 添加当前请求
        pipe.zcard(redis_key)                               # 统计当前窗口请求数
        pipe.expire(redis_key, window_seconds + 1)          # 设置 Key 过期时间
        results = await pipe.execute()

        current_count = results[2]

        if current_count > max_requests:
            raise RateLimitError(
                f"Rate limit exceeded: {max_requests} requests per {window_seconds}s"
            )
