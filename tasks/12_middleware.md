# Task 12: 中间件系统实现

## 任务描述

实现错误处理中间件、请求日志中间件和基于 Redis 的滑动窗口限流中间件。

## 涉及文件

- `app/middleware/error_handler.py` - 全局异常捕获
- `app/middleware/request_logging.py` - 访问日志
- `app/middleware/rate_limit.py` - 限流

## 详细任务

### 12.1 创建错误处理中间件

```python
# app/middleware/error_handler.py
import traceback
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    TextLensException,
    AuthenticationError,
    ValidationError,
    ResourceNotFoundError,
    InsufficientCreditsError,
)

ERROR_CODE_MAP = {
    AuthenticationError: ("UNAUTHORIZED", 401),
    ResourceNotFoundError: ("NOT_FOUND", 404),
    ValidationError: ("VALIDATION_ERROR", 400),
    InsufficientCreditsError: ("INSUFFICIENT_CREDITS", 402),
}

class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """全局异常捕获中间件"""
    
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
            
        except StarletteHTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": exc.status_code,
                    "message": exc.detail,
                    "detail": None,
                }
            )
            
        except TextLensException as exc:
            code, status_code = ERROR_CODE_MAP.get(
                type(exc), ("INTERNAL_ERROR", 500)
            )
            return JSONResponse(
                status_code=status_code,
                content={
                    "code": code,
                    "message": str(exc),
                    "detail": None,
                }
            )
            
        except Exception as exc:
            # 记录未知错误
            traceback.print_exc()
            
            return JSONResponse(
                status_code=500,
                content={
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Internal server error",
                    "detail": None,
                }
            )
```

### 12.2 创建请求日志中间件

```python
# app/middleware/request_logging.py
import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger("textlens.request")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """访问日志记录中间件"""
    
    async def dispatch(self, request: Request, call_next):
        # 生成请求 ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # 记录开始时间
        start_time = time.time()
        
        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"
        
        # 记录请求
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"IP: {client_ip} - Started"
        )
        
        # 处理请求
        try:
            response = await call_next(request)
            
            # 计算耗时
            duration = time.time() - start_time
            
            # 记录响应
            logger.info(
                f"[{request_id}] {request.method} {request.url.path} - "
                f"Status: {response.status_code} - "
                f"Duration: {duration:.3f}s"
            )
            
            # 添加响应头
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            
            logger.error(
                f"[{request_id}] {request.method} {request.url.path} - "
                f"Error: {str(e)} - Duration: {duration:.3f}s"
            )
            raise
```

### 12.3 创建限流中间件

```python
# app/middleware/rate_limit.py
import time
from typing import Callable

import redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

settings = Settings()

# Redis 连接
redis_client = redis.from_url(settings.REDIS_URL, db=0)

# 限流配置
RATE_LIMITS = {
    "/api/v1/auth/register": (5, 60),      # 5次/分钟
    "/api/v1/auth/login": (10, 60),         # 10次/分钟
    "/api/v1/generate": (20, 60),           # 20次/分钟
    "/api/v1/ocr": (30, 60),               # 30次/分钟
}

DEFAULT_LIMIT = (60, 60)  # 其他端点 60次/分钟

class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于 Redis 滑动窗口的限流中间件"""
    
    def _get_rate_limit_key(self, request: Request) -> str:
        """获取限流 key"""
        # 已认证用户按 user_id 限流
        if hasattr(request.state, "user_id"):
            return f"rate_limit:user:{request.state.user_id}"
        
        # 未认证按 IP 限流
        client_ip = request.client.host if request.client else "unknown"
        return f"rate_limit:ip:{client_ip}"
    
    def _check_rate_limit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """
        滑动窗口算法检查限流
        
        返回 (allowed, remaining)
        """
        now = time.time()
        window_start = now - window
        
        pipe = redis_client.pipeline()
        
        # 删除窗口外的旧记录
        pipe.zremrangebyscore(key, 0, window_start)
        
        # 统计当前窗口内的请求数
        pipe.zcard(key)
        
        # 如果未超限，添加当前请求
        results = pipe.execute()
        current_count = results[1]
        
        if current_count >= limit:
            # 超限
            return False, 0
        
        # 添加请求时间戳
        redis_client.zadd(key, {str(now): now})
        
        # 设置过期时间
        redis_client.expire(key, window)
        
        return True, limit - current_count - 1
    
    async def dispatch(self, request: Request, call_next):
        # 获取限流配置
        path = request.url.path
        limit, window = RATE_LIMITS.get(path, DEFAULT_LIMIT)
        
        # 获取限流 key
        key = self._get_rate_limit_key(request)
        
        # 检查限流
        allowed, remaining = self._check_rate_limit(key, limit, window)
        
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded. Max {limit} requests per {window} seconds.",
                    "detail": None,
                },
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                }
            )
        
        # 处理请求
        response = await call_next(request)
        
        # 添加限流响应头
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        return response
```

## 验收标准

- [ ] 异常被正确捕获并返回统一格式
- [ ] 所有请求都有 request_id
- [ ] 请求日志包含方法、路径、状态码、耗时
- [ ] 限流正确返回 429 状态码
- [ ] 已认证用户按 user_id 限流
- [ ] 未认证用户按 IP 限流

## 前置依赖

- Task 01: 项目基础架构搭建

## 后续任务

- Task 13: 外部服务集成
