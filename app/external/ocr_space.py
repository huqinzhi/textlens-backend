"""
OCR.space API 客户端封装

负责调用 OCR.space 免费 OCR API 进行文字识别，
支持上传图片或传入图片 URL 进行识别。
"""

import base64
from typing import Any
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError


class OCRSpaceClient:
    """
    OCR.space API 客户端

    提供免费的 OCR 文字识别功能，支持 Base64 图片和 URL 两种模式。
    API 文档: https://ocr.space/ocrapi
    """

    OCR_API_URL = "https://api.ocr.space/parse/image"

    async def detect_text(self, image_url: str) -> dict[str, Any]:
        """
        对指定图片 URL 执行 OCR 文字识别

        [image_url] 图片的公开访问 URL
        返回包含 raw_text 和 text_blocks 的字典
        """
        payload = {
            "url": image_url,
            "language": "auto",
            "isOverlayRequired": True,
            "detectOrientation": True,
            "scale": True,
            "OCREngine": 2,  # 更精准的引擎
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self.OCR_API_URL,
                    data=payload,
                    headers={"apikey": settings.OCR_SPACE_API_KEY},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"OCR.space API request failed: {e}")

        return self._parse_response(data)

    async def detect_text_from_bytes(self, image_bytes: bytes) -> dict[str, Any]:
        """
        对图片字节数据执行 OCR 文字识别

        将图片字节进行 base64 编码后提交 OCR.space API。

        [image_bytes] 图片原始字节数据
        返回包含 raw_text 和 text_blocks 的字典
        """
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
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self.OCR_API_URL,
                    data=payload,
                    headers={"apikey": settings.OCR_SPACE_API_KEY},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"OCR.space API request failed: {e}")

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> dict[str, Any]:
        """
        解析 OCR.space API 响应，提取结构化文字块

        提取每个文字区域的文字内容、坐标、置信度等信息，
        坐标统一归一化为相对图片尺寸的比例值（0-1范围）。

        [data] OCR.space API 原始响应字典
        返回包含 raw_text、text_blocks、confidence 的字典
        """
        # 检查 API 错误
        if data.get("ErrorMessage"):
            error = data.get("ErrorMessage", [])
            raise ExternalServiceError(f"OCR.space error: {error}")

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
                    # 优先从 WordRectangles 获取坐标（部分 OCR API 格式）
                    word_rects = word.get("WordRectangles", [])
                    if word_rects:
                        for v in word_rects:
                            x = v.get("Left", 0)
                            y = v.get("Top", 0)
                            w = v.get("Width", 0)
                            h = v.get("Height", 0)
                            min_x = min(min_x, x)
                            min_y = min(min_y, y)
                            max_x = max(max_x, x + w)
                            max_y = max(max_y, y + h)
                    else:
                        # OCR.space API 坐标直接在 word 对象上
                        x = word.get("Left", 0)
                        y = word.get("Top", 0)
                        w = word.get("Width", 0)
                        h = word.get("Height", 0)
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
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
