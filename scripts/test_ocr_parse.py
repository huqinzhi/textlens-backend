"""
测试 OCR 解析逻辑

模拟 OCRService._parse_ocr_result 的完整流程，验证解析是否正确。
"""
import asyncio
import base64
import httpx
from app.features.ocr.service import OCRService


OCR_API_URL = "https://api.ocr.space/parse/image"
API_KEY = "K85802480388957"


async def test_ocr_parse():
    """
    测试 OCR 解析流程

    1. 调用 OCR.space API
    2. 通过 OCRService 解析结果
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

    # 模拟 OCRService._parse_ocr_result
    ocr_result = parse_ocr_response(data)

    print(f"\nParsed text_blocks count: {len(ocr_result.get('text_blocks', []))}")
    print(f"First 5 text_blocks:")
    for i, block in enumerate(ocr_result.get("text_blocks", [])[:5]):
        print(f"  {i}: {block}")


def parse_ocr_response(data: dict) -> dict:
    """
    解析 OCR.space API 响应，提取结构化文字块

    [data] OCR.space API 原始响应字典
    返回包含 raw_text、text_blocks、confidence 的字典
    """
    # 检查 API 错误
    if data.get("ErrorMessage"):
        return {"raw_text": "", "text_blocks": [], "confidence": 0.0}

    # 检查是否成功
    if not data.get("ParsedResults"):
        return {"raw_text": "", "text_blocks": [], "confidence": 0.0}

    raw_text_parts = []
    text_blocks = []
    overall_confidence = 0.0

    for parsed in data.get("ParsedResults", []):
        # 获取完整识别文本
        text = parsed.get("ParsedText", "")
        raw_text_parts.append(text)

        # 获取文本区域的坐标信息
        text_overlay = parsed.get("TextOverlay", {})
        if not text_overlay:
            continue

        # 遍历每个文字区域
        for i, line in enumerate(text_overlay.get("Lines", [])):
            line_text = line.get("LineText", "").strip()
            if not line_text:
                continue

            # 获取边界框坐标
            vertices = line.get("LineWords", [])
            if not vertices:
                continue

            # 计算所有词的边界
            min_x = min_y = float("inf")
            max_x = max_y = 0
            for word in vertices:
                for v in word.get("WordRectangles", []):
                    x = v.get("Left", 0)
                    y = v.get("Top", 0)
                    w = v.get("Width", 0)
                    h = v.get("Height", 0)
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x + w)
                    max_y = max(max_y, y + h)

            # 如果没有找到 WordRectangles，尝试直接从 word 获取坐标
            if min_x == float("inf"):
                for word in vertices:
                    x = word.get("Left", 0)
                    y = word.get("Top", 0)
                    w = word.get("Width", 0)
                    h = word.get("Height", 0)
                    min_x = min(min_x if min_x != float("inf") else x, x)
                    min_y = min(min_y if min_y != float("inf") else y, y)
                    max_x = max(max_x, x + w)
                    max_y = max(max_y, y + h)

            # 获取图片尺寸用于归一化
            img_width = text_overlay.get("ImageWidth", 1)
            img_height = text_overlay.get("ImageHeight", 1)

            # 归一化坐标（0.0 ~ 1.0）
            x_norm = min_x / img_width if img_width else 0
            y_norm = min_y / img_height if img_height else 0
            w_norm = (max_x - min_x) / img_width if img_width else 0
            h_norm = (max_y - min_y) / img_height if img_height else 0

            # 获取置信度
            confidence = parsed.get("Confidence", 1.0)

            text_blocks.append({
                "id": f"block_{i}",
                "text": line_text,
                "x": round(x_norm, 4),
                "y": round(y_norm, 4),
                "width": round(w_norm, 4),
                "height": round(h_norm, 4),
                "confidence": round(confidence / 100, 4) if confidence > 1 else round(confidence, 4),
            })

        # 更新整体置信度
        conf = parsed.get("Confidence", 100)
        overall_confidence += conf if conf <= 1 else conf / 100

    # 计算平均置信度
    num_results = len(data.get("ParsedResults", []))
    if num_results > 0:
        overall_confidence = overall_confidence / num_results

    return {
        "raw_text": "\n".join(raw_text_parts),
        "text_blocks": text_blocks,
        "confidence": round(overall_confidence, 4),
    }


if __name__ == "__main__":
    asyncio.run(test_ocr_parse())
