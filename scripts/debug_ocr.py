"""
调试 OCR 解析问题

逐步检查解析流程，找出问题所在。
"""
import asyncio
import base64
import httpx


OCR_API_URL = "https://api.ocr.space/parse/image"
API_KEY = "K85802480388957"


async def debug_parse():
    """逐步调试 OCR 解析"""
    with open("/tmp/test.jpg", "rb") as f:
        image_bytes = f.read()

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "base64Image": f"data:image/jpeg;base64,{encoded}",
        "language": "auto",
        "isOverlayRequired": True,
        "detectOrientation": True,
        "scale": True,
        "OCREngine": 2,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(OCR_API_URL, data=payload, headers={"apikey": API_KEY})
        data = resp.json()

    parsed = data["ParsedResults"][0]
    text_overlay = parsed.get("TextOverlay", {})
    lines = text_overlay.get("Lines", [])
    img_width = text_overlay.get("ImageWidth", 1)
    img_height = text_overlay.get("ImageHeight", 1)

    print(f"Image dimensions: {img_width}x{img_height}")
    print(f"Lines count: {len(lines)}")

    # 检查第一行
    if lines:
        first_line = lines[0]
        print(f"\nFirst line: {first_line.get('LineText')}")
        print(f"LineWords: {first_line.get('LineWords')}")

        # 手动计算坐标
        words = first_line.get("LineWords", [])
        for word in words:
            print(f"  Word: {word.get('WordText')}")
            print(f"    Left={word.get('Left')}, Top={word.get('Top')}, Width={word.get('Width')}, Height={word.get('Height')}")
            print(f"    WordRectangles: {word.get('WordRectangles')}")


if __name__ == "__main__":
    asyncio.run(debug_parse())
