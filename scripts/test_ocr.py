"""
测试 OCR.space API 功能

用于验证 OCR 服务是否正常工作。
"""
import base64
import asyncio
import httpx


OCR_API_URL = "https://api.ocr.space/parse/image"
API_KEY = "K85802480388957"


async def test_ocr_space():
    """
    测试 OCR.space API

    读取 /tmp/test.jpg 图片并测试 OCR 识别。
    """
    try:
        with open("/tmp/test.jpg", "rb") as f:
            image_bytes = f.read()
    except FileNotFoundError:
        print("请先上传一张图片到 /tmp/test.jpg")
        return

    encoded = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "base64Image": f"data:image/jpeg;base64,{encoded}",
        "language": "auto",
        "isOverlayRequired": True,
        "detectOrientation": True,
        "scale": True,
        "OCREngine": 2,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                OCR_API_URL,
                data=payload,
                headers={"apikey": API_KEY},
            )
            print(f"Status: {resp.status_code}")
            data = resp.json()
            print(f"Response: {data}")

            if data.get("ParsedResults"):
                for result in data["ParsedResults"]:
                    print(f"Text: {result.get('ParsedText', '')}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_ocr_space())
