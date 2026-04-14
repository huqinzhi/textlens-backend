"""
测试 Cloudflare AI 图片生成

测试 Cloudflare Workers AI 的 Stable Diffusion img2img 模型。
"""
import asyncio
import sys
import base64
sys.path.insert(0, '/app')

from PIL import Image
import io

from app.external.cloudflare_ai_client import CloudflareAIClient
from app.external.s3_client import S3Client


async def test_cloudflare_edit():
    """
    测试 Cloudflare AI SD img2img 图片编辑
    """
    image_url = "https://r2.hqzservice.top/uploads/bf1f401f-0748-4dca-966c-c600134b8fc5/7c8a703a2abb40f498316880034d6e13.jpeg"

    # 下载图片
    s3 = S3Client()
    print("Downloading image...")
    image_bytes = await s3.download(image_url)
    print(f"Image size: {len(image_bytes)} bytes")

    # 获取图片尺寸
    img = Image.open(io.BytesIO(image_bytes))
    img_width, img_height = img.size
    print(f"Image dimensions: {img_width}x{img_height}")

    # OCR 结果
    ocr_blocks = [{
        "id": "block_1",
        "text": "18681264718",
        "x": 405 / img_width,
        "y": 539 / img_height,
        "width": 440 / img_width,
        "height": 93 / img_height,
    }]

    # 编辑指令
    edit_blocks = [{
        "id": "block_1",
        "original_text": "18681264718",
        "new_text": "测试测试",
    }]

    # 提取视觉风格
    from app.external.google_vision import extract_text_region_style
    ocr_map = {b.get("id"): b for b in ocr_blocks}
    visual_styles = {}
    for edit in edit_blocks:
        block_id = edit.get("id")
        block_info = ocr_map.get(block_id, {})
        x_norm = block_info.get("x", 0.0)
        y_norm = block_info.get("y", 0.0)
        w_norm = block_info.get("width", 0.0)
        h_norm = block_info.get("height", 0.0)
        abs_x = int(x_norm * img_width)
        abs_y = int(y_norm * img_height)
        abs_w = int(w_norm * img_width)
        abs_h = int(h_norm * img_height)
        style = await extract_text_region_style(image_bytes, abs_x, abs_y, abs_w, abs_h)
        visual_styles[block_id] = style
        print(f"Visual style for {block_id}: {style}")

    # 构建提示词
    from app.tasks.generation_tasks import _build_sd_prompt
    prompt = _build_sd_prompt(ocr_blocks, edit_blocks, img_width, img_height, "zh", visual_styles)
    print(f"Prompt:\n{prompt}\n")

    # 创建 mask
    from app.external.cloudflare_ai_client import CloudflareAIClient
    mask_bytes = CloudflareAIClient.create_mask(
        img_width, img_height, edit_blocks, ocr_blocks
    )
    print(f"Mask size: {len(mask_bytes)} bytes")

    # 调用 Cloudflare AI
    cf = CloudflareAIClient()
    print("Calling Cloudflare AI SD inpainting...")
    result_b64 = await cf.edit_image(
        image_bytes=image_bytes,
        prompt=prompt,
        mask_bytes=mask_bytes,
        guidance=7.5,
    )
    print(f"Generated image size: {len(result_b64)} bytes (base64)")

    # 保存本地
    result_bytes = base64.b64decode(result_b64)
    with open("/tmp/cloudflare_gen.png", "wb") as f:
        f.write(result_bytes)
    print("Image saved to /tmp/cloudflare_gen.png")

    # 上传到 R2
    result_url = await s3.upload_result(result_bytes, "image/png")
    print(f"Result URL: {result_url}")


if __name__ == "__main__":
    asyncio.run(test_cloudflare_edit())
