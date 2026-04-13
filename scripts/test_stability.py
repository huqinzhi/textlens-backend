"""
测试 Stability AI 图片生成

使用 OCR 图片进行文字编辑测试。
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.external.stability_api import StabilityAIClient, create_mask_for_region
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

    # OCR 结果：文字 "18681264718" 在位置 (405, 539)，尺寸 440x93
    # 获取图片实际尺寸
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes))
    img_width, img_height = img.size
    print(f"Image dimensions: {img_width}x{img_height}")

    # 创建 mask：白色区域表示需要 AI 重新生成的部分
    print("Creating mask...")
    mask_bytes = create_mask_for_region(
        width=img_width,
        height=img_height,
        x=405,        # 文字区域左上角 X
        y=539,        # 文字区域左上角 Y
        region_width=440,   # 文字区域宽度
        region_height=93,   # 文字区域高度
    )
    print(f"Mask size: {len(mask_bytes)} bytes")

    # 构建编辑提示词
    prompt = """Precise text replacement inpainting. The original text "18681264718" has a underline beneath it.
CRITICAL requirements:
1. Replace ONLY the text "18681264718" with "测试" - keep the exact same underline style and position
2. Keep the background COMPLETELY TRANSPARENT in the text area - do NOT add any background color
3. Use the exact same font, size, weight, and style as the original text
4. Keep the underline exactly as it was - same thickness, same position below text
5. DO NOT modify, add, or change anything else in the image - preserve all UI elements, colors, logos exactly
The new text "测试" must look identical in style to the original "18681264718" including the underline."""

    # 调用 Stability AI
    stability = StabilityAIClient()
    print("Calling Stability AI...")
    result_b64 = await stability.edit_image(
        image_bytes=image_bytes,
        prompt=prompt,
        mask_bytes=mask_bytes,
    )
    print(f"Generated image size: {len(result_b64)} bytes (base64)")

    # 上传结果到 R2
    result_bytes = __import__('base64').b64decode(result_b64)
    result_url = await s3.upload_result(result_bytes, "image/png")
    print(f"Result URL: {result_url}")


if __name__ == "__main__":
    asyncio.run(test_stability_edit())
