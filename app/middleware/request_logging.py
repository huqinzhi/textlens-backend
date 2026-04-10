"""
请求日志中间件
记录每个 HTTP 请求的方法、路径、状态码和响应时间
"""
import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("textlens.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    请求访问日志中间件

    记录所有 API 请求的关键信息，用于监控、调试和性能分析。
    对健康检查等高频低价值接口可选择性跳过记录。
    """

    # 不记录日志的路径（高频健康检查减少噪音）
    SKIP_PATHS = {"/health", "/metrics"}

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        拦截请求，记录请求和响应日志

        [request] HTTP 请求对象
        [call_next] 下游处理函数
        返回原始响应（不修改）
        """
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        start_time = time.time()

        # 提取请求基本信息
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")

        response = await call_next(request)

        # 计算响应耗时（毫秒）
        duration_ms = (time.time() - start_time) * 1000

        # 获取响应状态码
        status_code = response.status_code

        # 结构化日志
        log_msg = (
            f"{method} {path}"
            + (f"?{query}" if query else "")
            + f" {status_code} {duration_ms:.1f}ms"
            + f" [{client_ip}]"
        )

        # 根据状态码选择日志级别
        if status_code >= 500:
            logger.error(log_msg + f" UA={user_agent}")
        elif status_code >= 400:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """
        提取客户端真实 IP 地址

        优先从 X-Forwarded-For 头获取（代理/负载均衡后的真实 IP），
        降级使用直连 IP。

        [request] HTTP 请求对象
        返回客户端 IP 字符串
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"
