"""
测试 Cloudflare R2 上传功能

用于验证 S3Client 能否正确连接到 R2 并上传文件。
"""
import asyncio
from app.external.s3_client import S3Client


async def test_r2_upload():
    """
    测试 R2 上传功能

    上传一小段测试数据到 R2，验证凭证配置是否正确。
    """
    client = S3Client()
    try:
        url = await client.upload(
            file_bytes=b"test data",
            content_type="text/plain",
            folder="test",
            file_extension="txt"
        )
        print(f"Upload success: {url}")
        return True
    except Exception as e:
        print(f"Upload failed: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_r2_upload())
    exit(0 if result else 1)
