"""
自定义异常类模块

定义应用中所有的业务异常，方便统一错误处理和响应格式化。
"""

from fastapi import HTTPException, status


class TextLensException(Exception):
    """
    TextLens 应用基础异常类

    所有业务异常的父类，包含错误码和错误消息。
    [status_code] HTTP 状态码
    [detail] 错误详情描述
    [error_code] 业务错误码（用于客户端区分错误类型）
    """

    def __init__(self, status_code: int, detail: str, error_code: str = "UNKNOWN"):
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        super().__init__(detail)


class AuthenticationError(TextLensException):
    """
    认证失败异常

    Token 无效、过期或用户不存在时抛出。
    [detail] 错误详情，默认为 "Authentication failed"
    """

    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="AUTH_FAILED",
        )


class AuthorizationError(TextLensException):
    """
    权限不足异常

    用户没有执行该操作的权限时抛出。
    [detail] 错误详情，默认为 "Permission denied"
    """

    def __init__(self, detail: str = "Permission denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="PERMISSION_DENIED",
        )


class NotFoundError(TextLensException):
    """
    资源未找到异常

    请求的资源不存在时抛出。
    [resource] 资源名称（如 "User", "Image"）
    """

    def __init__(self, resource: str = "Resource"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} not found",
            error_code="NOT_FOUND",
        )


class ValidationError(TextLensException):
    """
    数据验证失败异常

    请求参数不合法时抛出。
    [detail] 具体的验证失败信息
    """

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="VALIDATION_ERROR",
        )


class InsufficientCreditsError(TextLensException):
    """
    积分不足异常

    用户积分余额不足以执行操作时抛出。
    [required] 需要的积分数量
    [current] 当前积分余额
    """

    def __init__(self, required: int, current: int):
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient credits. Required: {required}, Current: {current}",
            error_code="INSUFFICIENT_CREDITS",
        )


class DailyLimitExceededError(TextLensException):
    """
    每日免费次数已用尽异常

    用户当天免费生成次数已达上限时抛出。
    """

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily free generation limit exceeded",
            error_code="DAILY_LIMIT_EXCEEDED",
        )


class RateLimitError(TextLensException):
    """
    请求频率超限异常

    用户请求频率超过限制时抛出。
    [detail] 错误详情描述
    [retry_after] 建议的重试等待秒数
    """

    def __init__(self, detail: str = None, retry_after: int = 60):
        if detail is None:
            detail = f"Rate limit exceeded. Retry after {retry_after} seconds"
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            error_code="RATE_LIMIT_EXCEEDED",
        )


class ExternalServiceError(TextLensException):
    """
    外部服务调用失败异常

    调用第三方 API（Google Vision、OpenAI、Stripe）失败时抛出。
    [service] 服务名称
    [detail] 错误详情
    """

    def __init__(self, service: str, detail: str = ""):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"External service error [{service}]: {detail}",
            error_code="EXTERNAL_SERVICE_ERROR",
        )


class ContentModerationError(TextLensException):
    """
    内容审核未通过异常

    AI 生成内容审核不通过（涉及违规内容）时抛出，并退款积分。
    """

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content violates our usage policy. Credits have been refunded.",
            error_code="CONTENT_MODERATION_FAILED",
        )
