"""
测试完整 OCR 流程

模拟 OCR 接口的完整处理流程，定位问题所在。
"""
import asyncio
import base64
import httpx

OCR_API_URL = "https://api.ocr.space/parse/image"
API_KEY = "K85802480388957"


async def test_ocr_flow():
    """
    测试完整 OCR 流程

    1. 读取图片
    2. 调用 OCR.space API
    3. 解析响应
    """
    # 读取图片
    with open("/tmp/test.jpg", "rb") as f:
        image_bytes = f.read()
    print(f"Image size: {len(image_bytes)} bytes")

    # 调用 OCR.space
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
        print(f"OCR API Status: {resp.status_code}")
        data = resp.json()
        print(f"OCR API Response: {data}")

    # 检查是否有错误
    if data.get("ErrorMessage"):
        print(f"OCR Error: {data.get('ErrorMessage')}")
        return

    # 检查 ParsedResults
    parsed_results = data.get("ParsedResults", [])
    print(f"ParsedResults count: {len(parsed_results)}")

    if not parsed_results:
        print("No parsed results - image may have no text or OCR failed")
        return

    # 解析第一个结果
    first_result = parsed_results[0]
    parsed_text = first_result.get("ParsedText", "")
    print(f"ParsedText: '{parsed_text}'")

    # 检查 TextOverlay
    text_overlay = first_result.get("TextOverlay", {})
    print(f"TextOverlay keys: {text_overlay.keys() if text_overlay else 'None'}")

    lines = text_overlay.get("Lines", []) if text_overlay else []
    print(f"Lines count: {len(lines)}")

    for i, line in enumerate(lines):
        print(f"  Line {i}: {line.get('LineText', '')}")


if __name__ == "__main__":
    asyncio.run(test_ocr_flow())
