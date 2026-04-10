"""
通用 Pydantic 模型
定义分页、响应基类等通用数据结构
"""
from typing import Generic, TypeVar, List, Optional, Any
from pydantic import BaseModel

T = TypeVar("T")


class PageParams(BaseModel):
    """
    分页参数模型

    [page] 当前页码，从 1 开始
    [page_size] 每页数量，默认 20
    """
    page: int = 1
    page_size: int = 20


class PageResponse(BaseModel, Generic[T]):
    """
    分页响应模型

    [items] 当前页数据列表
    [total] 总数据量
    [page] 当前页码
    [page_size] 每页数量
    [total_pages] 总页数
    """
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class APIResponse(BaseModel, Generic[T]):
    """
    统一 API 响应格式

    [success] 是否成功
    [data] 业务数据
    [message] 提示信息
    [error_code] 错误码（失败时）
    """
    success: bool = True
    data: Optional[T] = None
    message: str = "OK"
    error_code: Optional[str] = None
