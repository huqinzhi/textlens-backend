"""
S3/Cloudflare R2 对象存储客户端封装
负责图片文件的上传、下载、删除操作
"""
import uuid
from typing import Optional
import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.core.exceptions import ExternalServiceError


class S3Client:
    """
    S3/R2 对象存储客户端

    兼容 AWS S3 和 Cloudflare R2（S3 兼容协议），
    提供图片上传、URL 生成和文件删除功能。
    """

    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )
        self.bucket = settings.S3_BUCKET_NAME

    async def upload(
        self,
        file_bytes: bytes,
        content_type: str,
        folder: str = "uploads",
        file_extension: str = "jpg",
    ) -> str:
        """
        上传文件到 S3/R2 存储桶

        生成唯一文件名后上传，返回可公开访问的 URL。

        [file_bytes] 文件字节数据
        [content_type] MIME 类型（如 image/jpeg）
        [folder] 存储目录前缀（uploads/results/etc）
        [file_extension] 文件扩展名
        返回文件的公开访问 URL
        """
        # 生成唯一文件名
        file_key = f"{folder}/{uuid.uuid4().hex}.{file_extension}"

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=file_key,
                Body=file_bytes,
                ContentType=content_type,
                # 公开读取权限
                ACL="public-read" if not settings.S3_ENDPOINT_URL else None,
            )
        except ClientError as e:
            raise ExternalServiceError(f"S3 upload failed: {e}")

        # 构造公开访问 URL
        if settings.S3_CUSTOM_DOMAIN:
            url = f"https://{settings.S3_CUSTOM_DOMAIN}/{file_key}"
        elif settings.S3_ENDPOINT_URL:
            # Cloudflare R2 公开访问 URL
            url = f"{settings.S3_ENDPOINT_URL}/{self.bucket}/{file_key}"
        else:
            # AWS S3 标准 URL
            url = f"https://{self.bucket}.s3.{settings.S3_REGION}.amazonaws.com/{file_key}"

        return url

    async def upload_image(self, image_bytes: bytes, content_type: str = "image/png") -> str:
        """
        上传图片文件到 uploads 目录

        [image_bytes] 图片字节数据
        [content_type] 图片 MIME 类型，默认 image/png
        返回图片公开访问 URL
        """
        ext = content_type.split("/")[-1] if "/" in content_type else "jpg"
        return await self.upload(
            file_bytes=image_bytes,
            content_type=content_type,
            folder="uploads",
            file_extension=ext,
        )

    async def upload_result(self, image_bytes: bytes, content_type: str = "image/png") -> str:
        """
        上传 AI 生成结果图片到 results 目录

        [image_bytes] 生成图片字节数据
        [content_type] 图片 MIME 类型，默认 image/png
        返回生成图片公开访问 URL
        """
        ext = content_type.split("/")[-1] if "/" in content_type else "png"
        return await self.upload(
            file_bytes=image_bytes,
            content_type=content_type,
            folder="results",
            file_extension=ext,
        )

    async def download(self, url: str) -> bytes:
        """
        从 S3/R2 下载文件字节数据

        根据 URL 提取文件 Key 后下载。

        [url] 文件的公开访问 URL
        返回文件字节数据
        """
        file_key = self._extract_key_from_url(url)

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=file_key)
            return response["Body"].read()
        except ClientError as e:
            raise ExternalServiceError(f"S3 download failed: {e}")

    async def delete(self, url: str) -> None:
        """
        从 S3/R2 删除文件

        [url] 要删除的文件公开访问 URL
        """
        file_key = self._extract_key_from_url(url)

        try:
            self.client.delete_object(Bucket=self.bucket, Key=file_key)
        except ClientError as e:
            raise ExternalServiceError(f"S3 delete failed: {e}")

    def _extract_key_from_url(self, url: str) -> str:
        """
        从 URL 中提取 S3 文件 Key

        支持多种 URL 格式（自定义域名、R2、AWS S3 标准格式）。

        [url] 文件访问 URL
        返回 S3 文件 Key（路径部分）
        """
        # 自定义域名格式: https://cdn.example.com/uploads/xxx.jpg
        if settings.S3_CUSTOM_DOMAIN and settings.S3_CUSTOM_DOMAIN in url:
            return url.split(settings.S3_CUSTOM_DOMAIN + "/")[-1]

        # 通用提取：取 URL 路径的最后两段（folder/filename）
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.lstrip("/")

        # 如果路径包含 bucket 名称则去除
        if path.startswith(self.bucket + "/"):
            path = path[len(self.bucket) + 1:]

        return path

    def generate_presigned_url(self, url: str, expires_in: int = 3600) -> str:
        """
        生成预签名 URL（用于私有文件临时访问）

        [url] 文件的存储 URL
        [expires_in] 有效期（秒），默认 1 小时
        返回预签名访问 URL
        """
        file_key = self._extract_key_from_url(url)

        try:
            presigned_url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": file_key},
                ExpiresIn=expires_in,
            )
            return presigned_url
        except ClientError as e:
            raise ExternalServiceError(f"Failed to generate presigned URL: {e}")
