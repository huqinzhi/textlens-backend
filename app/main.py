"""
TextLens FastAPI 应用主入口

负责创建 FastAPI 应用实例，注册所有路由、中间件和异常处理器。
"""

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.db.session import create_tables
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.features.auth.router import router as auth_router
from app.features.users.router import router as users_router
from app.features.credits.router import router as credits_router
from app.features.ocr.router import router as ocr_router
from app.features.generation.router import router as generation_router
from app.features.history.router import router as history_router
from app.features.payments.router import router as payments_router
from app.features.admin.router import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器

    在应用启动时执行初始化操作（创建数据库表、初始化 Redis 等），
    在应用关闭时执行资源清理操作。
    """
    # 启动时：初始化数据库连接、创建表
    await create_tables()

    # 初始化 Redis 连接并挂载到 app.state（供速率限制等中间件使用）
    app.state.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

    yield

    # 关闭时：释放 Redis 连接
    await app.state.redis.close()


def create_application() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例

    注册所有中间件、路由和异常处理器。
    返回 [FastAPI] 配置完成的应用实例
    """
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="TextLens AI 图片文字编辑服务端 API",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # ── 注册中间件（顺序很重要，后注册的先执行）─────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(ErrorHandlerMiddleware)

    # ── 注册业务路由 ──────────────────────────────────────────────────
    API_PREFIX = "/api/v1"

    application.include_router(auth_router, prefix=f"{API_PREFIX}/auth", tags=["认证"])
    application.include_router(users_router, prefix=f"{API_PREFIX}/user", tags=["用户"])
    application.include_router(credits_router, prefix=f"{API_PREFIX}/credits", tags=["积分"])
    application.include_router(ocr_router, prefix=f"{API_PREFIX}/ocr", tags=["OCR识别"])
    application.include_router(generation_router, prefix=f"{API_PREFIX}/generate", tags=["AI生图"])
    application.include_router(history_router, prefix=f"{API_PREFIX}/history", tags=["历史记录"])
    application.include_router(payments_router, prefix=f"{API_PREFIX}/payments", tags=["支付"])
    application.include_router(admin_router, prefix=f"{API_PREFIX}/admin", tags=["管理员"])

    return application


# 创建全局应用实例
app = create_application()


@app.get("/health", tags=["健康检查"])
async def health_check():
    """
    健康检查接口

    返回服务运行状态，用于负载均衡器和监控系统检查。
    返回包含状态信息的字典
    """
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
    }
