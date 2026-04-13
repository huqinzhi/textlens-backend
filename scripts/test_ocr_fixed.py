"""
测试修复后的 OCR 解析逻辑

直接从 OCRService 调用解析方法，验证修复是否有效。
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.external.ocr_space import OCRSpaceClient


async def test():
    """测试 OCR.space 解析"""
    client = OCRSpaceClient()

    # 读取图片
    with open("/tmp/test.jpg", "rb") as f:
        image_bytes = f.read()

    # 调用 OCR API
    result = await client.detect_text_from_bytes(image_bytes)

    print(f"raw_text length: {len(result.get('raw_text', ''))}")
    print(f"text_blocks count: {len(result.get('text_blocks', []))}")
    print(f"First 5 blocks:")
    for i, block in enumerate(result.get("text_blocks", [])[:5]):
        print(f"  {i}: {block}")


if __name__ == "__main__":
    asyncio.run(test())
