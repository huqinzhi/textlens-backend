"""
测试 Stability AI 图片生成

使用 OCR 图片进行文字编辑测试。
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.external.stability_api import StabilityAIClient
from app.external.s3_client import S3Client


async def test_stability_edit():
    """
    测试 Stability AI 图片编辑

    下载 OCR 图片，修改文字并生成新图片。
    """
    image_url = "https://r2.hqzservice.top/uploads/bf1f401f-0748-4dca-966c-c600134b8fc5/7c8a703a2abb40f498316880034d6e13.jpeg"

    # 下载图片
    s3 = S3Client()
    print("Downloading image...")
    image_bytes = await s3.download(image_url)
    print(f"Image size: {len(image_bytes)} bytes")

    # 构建编辑提示词
    # 根据 OCR 结果，"18681264718" 在位置 (405, 539)，尺寸 440x93
    prompt = """Preserve the entire original image exactly as-is, with ALL elements, colors, textures, and details completely unchanged.
ONLY perform this single specific edit: replace the phone number "18681264718" with "测试".
Do NOT modify, alter, blur, enhance, or change anything else in the image.
Keep all text crisp and sharp. Maintain exact same style, position, size, font, and color.
The only change is swapping that one phone number to "测试"."""

    # 调用 Stability AI
    stability = StabilityAIClient()
    print("Calling Stability AI...")
    result_b64 = await stability.edit_image(
        image_bytes=image_bytes,
        prompt=prompt,
    )
    print(f"Generated image size: {len(result_b64)} bytes (base64)")

    # 上传结果到 R2
    result_bytes = __import__('base64').b64decode(result_b64)
    result_url = await s3.upload_result(result_bytes, "image/png")
    print(f"Result URL: {result_url}")


if __name__ == "__main__":
    asyncio.run(test_stability_edit())
