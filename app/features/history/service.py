"""
历史记录业务逻辑服务层
处理生图历史记录的查询、删除（含S3文件清理）
"""
from sqlalchemy.orm import Session
from app.core.exceptions import NotFoundError, AuthorizationError
from app.db.models.image import GenerationTask
from app.external.s3_client import S3Client
from app.schemas.image import HistoryItem
from app.schemas.common import PageResponse
from app.core.constants import TaskStatus


class HistoryService:
    """
    历史记录服务类

    处理用户生成历史的查询和删除逻辑。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db
        self.s3_client = S3Client()

    async def get_history(self, current_user, page: int, page_size: int) -> PageResponse:
        """
        分页查询用户生图历史记录

        [current_user] 当前登录用户
        [page] 页码
        [page_size] 每页数量
        返回 PageResponse[HistoryItem] 分页历史记录
        """
        query = self.db.query(GenerationTask).filter(
            GenerationTask.user_id == current_user.id,
            GenerationTask.status.in_(["done", "failed"]),
        ).order_by(GenerationTask.created_at.desc())

        total = query.count()
        tasks = query.offset((page - 1) * page_size).limit(page_size).all()

        items = [
            HistoryItem(
                task_id=task.id,
                original_image_url=task.original_image_url,
                result_image_url=task.result_image_url,
                status=TaskStatus(task.status.value),
                credits_cost=task.credits_cost,
                created_at=task.created_at,
            )
            for task in tasks
        ]

        return PageResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size,
        )

    async def delete(self, history_id: str, current_user) -> None:
        """
        删除历史记录（数据库 + S3 文件）

        先验证权限，然后删除数据库记录，
        最后异步删除 S3/R2 上的原图和结果图。

        [history_id] 要删除的 GenerationTask ID
        [current_user] 当前登录用户
        """
        task = self.db.query(GenerationTask).filter(
            GenerationTask.id == history_id
        ).first()

        if not task:
            raise NotFoundError("History record")

        # 权限验证
        if str(task.user_id) != str(current_user.id):
            raise AuthorizationError()

        # 删除 S3 文件
        try:
            if task.result_image_url:
                await self.s3_client.delete(task.result_image_url)
        except Exception:
            pass  # S3 删除失败不阻断数据库删除

        # 删除数据库记录
        self.db.delete(task)
        self.db.commit()
