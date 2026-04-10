"""
全局错误处理中间件
统一捕获应用异常并转换为标准化 JSON 错误响应
"""
import traceback
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exceptions import (
    TextLensException,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
    InsufficientCreditsError,
    DailyLimitExceededError,
    RateLimitError,
    ExternalServiceError,
    ContentModerationError,
)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    全局异常捕获中间件

    将所有未处理异常统一转换为标准化 JSON 错误响应，
    避免框架默认的 500 Internal Server Error 泄露内部信息。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        捕获所有异常并转换为结构化 JSON 响应

        [request] 传入的 HTTP 请求
        [call_next] 下游处理函数
        返回正常响应或标准化错误 JSON
        """
        try:
            return await call_next(request)

        except AuthenticationError as e:
            return JSONResponse(
                status_code=401,
                content={"code": "UNAUTHORIZED", "message": str(e), "detail": None},
            )

        except AuthorizationError as e:
            return JSONResponse(
                status_code=403,
                content={"code": "FORBIDDEN", "message": str(e), "detail": None},
            )

        except NotFoundError as e:
            return JSONResponse(
                status_code=404,
                content={"code": "NOT_FOUND", "message": str(e), "detail": None},
            )

        except ValidationError as e:
            return JSONResponse(
                status_code=422,
                content={"code": "VALIDATION_ERROR", "message": str(e), "detail": None},
            )

        except InsufficientCreditsError as e:
            return JSONResponse(
                status_code=402,
                content={"code": "INSUFFICIENT_CREDITS", "message": str(e), "detail": None},
            )

        except DailyLimitExceededError as e:
            return JSONResponse(
                status_code=429,
                content={"code": "DAILY_LIMIT_EXCEEDED", "message": str(e), "detail": None},
            )

        except RateLimitError as e:
            return JSONResponse(
                status_code=429,
                content={"code": "RATE_LIMIT_EXCEEDED", "message": str(e), "detail": None},
            )

        except ContentModerationError as e:
            return JSONResponse(
                status_code=400,
                content={"code": "CONTENT_MODERATION", "message": str(e), "detail": None},
            )

        except ExternalServiceError as e:
            return JSONResponse(
                status_code=503,
                content={"code": "EXTERNAL_SERVICE_ERROR", "message": str(e), "detail": None},
            )

        except TextLensException as e:
            return JSONResponse(
                status_code=400,
                content={"code": "APP_ERROR", "message": str(e), "detail": None},
            )

        except Exception as e:
            # 记录未预期的系统异常（生产环境应发送到 Sentry 等告警系统）
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An internal server error occurred",
                    "detail": None,
                },
            )
