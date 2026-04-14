"""
测试 Flux 图片生成

测试 BFL Flux API 图片生成。
"""
import asyncio
import sys
import base64
sys.path.insert(0, '/app')

from PIL import Image
import io

from app.external.flux_api import FluxClient
from app.external.s3_client import S3Client


async def test_flux_generate():
    """
    测试 Flux 图片生成
    """
    # 测试提示词
    prompt = "A cute corgi dog wearing a space helmet, floating in outer space, colorful nebula background, high detail, 4K, cinematic"

    # 调用 Flux
    flux = FluxClient()
    print("Calling Flux API...")
    result_b64 = await flux.generate_image(
        prompt=prompt,
        width=1024,
        height=1024,
    )
    print(f"Generated image size: {len(result_b64)} bytes (base64)")

    # 保存本地测试
    result_bytes = base64.b64decode(result_b64)
    with open("/tmp/flux_gen.png", "wb") as f:
        f.write(result_bytes)
    print("Image saved to /tmp/flux_gen.png")

    # 上传到 R2
    s3 = S3Client()
    result_url = await s3.upload_result(result_bytes, "image/png")
    print(f"Result URL: {result_url}")


if __name__ == "__main__":
    asyncio.run(test_flux_generate())
