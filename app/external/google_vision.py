"""
Google Cloud Vision API 客户端封装
负责图片 OCR 文字识别调用和结果解析
"""
import base64
from typing import Any
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError


class GoogleVisionClient:
    """
    Google Vision API 客户端

    封装 Google Cloud Vision API 的调用细节，
    提供图片 OCR 识别功能，返回结构化文字块数据。
    """

    VISION_API_URL = "https://vision.googleapis.com/v1/images:annotate"

    async def detect_text(self, image_url: str) -> dict[str, Any]:
        """
        对指定图片 URL 执行 OCR 文字识别

        调用 Google Vision API 的 TEXT_DETECTION 功能，
        返回原始文字和结构化文字块（含坐标）。

        [image_url] 图片的公开访问 URL（S3/R2 URL）
        返回包含 raw_text 和 text_blocks 的字典
        """
        payload = {
            "requests": [
                {
                    "image": {"source": {"imageUri": image_url}},
                    "features": [
                        {"type": "TEXT_DETECTION", "maxResults": 50},
                        {"type": "DOCUMENT_TEXT_DETECTION"},
                    ],
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self.VISION_API_URL,
                    json=payload,
                    params={"key": settings.GOOGLE_VISION_API_KEY},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"Google Vision API request failed: {e}")

        return self._parse_response(data)

    async def detect_text_from_bytes(self, image_bytes: bytes) -> dict[str, Any]:
        """
        对图片字节数据执行 OCR 文字识别

        将图片字节 base64 编码后提交 Google Vision API。

        [image_bytes] 图片原始字节数据
        返回包含 raw_text 和 text_blocks 的字典
        """
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "requests": [
                {
                    "image": {"content": encoded},
                    "features": [
                        {"type": "TEXT_DETECTION", "maxResults": 50},
                        {"type": "DOCUMENT_TEXT_DETECTION"},
                    ],
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self.VISION_API_URL,
                    json=payload,
                    params={"key": settings.GOOGLE_VISION_API_KEY},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"Google Vision API request failed: {e}")

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> dict[str, Any]:
        """
        解析 Google Vision API 响应，提取结构化文字块

        将 API 返回的 boundingPoly 坐标转换为归一化坐标（0-1 范围），
        便于前端在不同尺寸图片上正确渲染文字覆盖层。

        [data] Google Vision API 原始响应字典
        返回包含 raw_text、text_blocks、confidence 的字典
        """
        responses = data.get("responses", [])
        if not responses:
            return {"raw_text": "", "text_blocks": [], "confidence": 0.0}

        response = responses[0]

        # 检查 API 错误
        if "error" in response:
            error = response["error"]
            raise ExternalServiceError(
                f"Google Vision error {error.get('code')}: {error.get('message')}"
            )

        # 获取完整识别文本
        text_annotations = response.get("textAnnotations", [])
        raw_text = text_annotations[0]["description"] if text_annotations else ""

        # 从 fullTextAnnotation 获取更精确的段落和词块信息
        full_text = response.get("fullTextAnnotation", {})
        text_blocks = []

        # 获取图片尺寸（用于坐标归一化）
        # 注意：如果无法获取尺寸则不做归一化（保留像素坐标）
        img_width = None
        img_height = None

        pages = full_text.get("pages", [])
        if pages:
            page = pages[0]
            img_width = page.get("width")
            img_height = page.get("height")

            block_idx = 0
            for block in page.get("blocks", []):
                for paragraph in block.get("paragraphs", []):
                    para_text = ""
                    for word in paragraph.get("words", []):
                        word_text = "".join(
                            s.get("text", "") for s in word.get("symbols", [])
                        )
                        para_text += word_text + " "

                    para_text = para_text.strip()
                    if not para_text:
                        continue

                    # 提取段落边界框坐标
                    vertices = paragraph.get("boundingBox", {}).get("vertices", [])
                    if len(vertices) < 4:
                        continue

                    x_coords = [v.get("x", 0) for v in vertices]
                    y_coords = [v.get("y", 0) for v in vertices]
                    x = min(x_coords)
                    y = min(y_coords)
                    width = max(x_coords) - x
                    height = max(y_coords) - y

                    # 归一化坐标（0.0 ~ 1.0）
                    if img_width and img_height:
                        x_norm = x / img_width
                        y_norm = y / img_height
                        w_norm = width / img_width
                        h_norm = height / img_height
                    else:
                        x_norm, y_norm, w_norm, h_norm = x, y, width, height

                    # 计算置信度（取所有符号置信度的平均值）
                    confidences = []
                    for word in paragraph.get("words", []):
                        for symbol in word.get("symbols", []):
                            conf = symbol.get("confidence", 1.0)
                            confidences.append(conf)
                    confidence = sum(confidences) / len(confidences) if confidences else 1.0

                    text_blocks.append({
                        "id": f"block_{block_idx}",
                        "text": para_text,
                        "x": round(x_norm, 4),
                        "y": round(y_norm, 4),
                        "width": round(w_norm, 4),
                        "height": round(h_norm, 4),
                        "confidence": round(confidence, 4),
                    })
                    block_idx += 1

        # 计算整体置信度（所有文字块的平均值）
        overall_confidence = (
            sum(b["confidence"] for b in text_blocks) / len(text_blocks)
            if text_blocks else 0.0
        )

        return {
            "raw_text": raw_text,
            "text_blocks": text_blocks,
            "confidence": round(overall_confidence, 4),
        }
