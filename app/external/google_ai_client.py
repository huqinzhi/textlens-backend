"""
Google AI Gemini API 客户端封装
负责图片编辑调用（使用 Gemini 3.1 Flash 的多模态能力）
"""
import base64
import logging
from typing import Optional
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError

logger = logging.getLogger(__name__)


class GoogleAIClient:
    """
    Google AI Gemini API 客户端

    使用 Gemini 3.1 Flash 的 generateContent API 进行图片编辑。
    支持传入原图 + 文本提示词，自动保持非编辑区域不变。
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self):
        self.api_key = settings.GOOGLE_AI_API_KEY
        self.model = settings.GOOGLE_AI_IMAGE_MODEL

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        """
        使用 Gemini 进行图片编辑

        传入原图和编辑指令，Gemini 会自动保持非编辑区域不变。

        [image_bytes] 原始图片字节数据
        [prompt] 图片编辑提示词（描述需要做的文字替换和风格）
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("Google AI", "API key not configured")

        url = f"{self.BASE_URL}/{self.model}:generateContent"

        # 将图片转换为 base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = self._get_mime_type(image_bytes)

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_b64,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["IMAGE", "TEXT"],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "x-goog-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[Google AI] API error: {response.status_code} - {error_msg}")
                if "content_policy" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("Google AI", f"API error: {error_msg}")

            result = response.json()

            # 解析响应，提取生成的图片
            candidates = result.get("candidates", [])
            if not candidates:
                raise ExternalServiceError("Google AI", "No image generated")

            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "inline_data" in part:
                    image_data = part["inline_data"].get("data", "")
                    if image_data:
                        return image_data

            raise ExternalServiceError("Google AI", "No image in response")

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("Google AI", "Request timeout")
        except ExternalServiceError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "sensitive" in error_str or "content_policy" in error_str:
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("Google AI", str(e))

    def _get_mime_type(self, image_bytes: bytes) -> str:
        """根据图片字节数据判断 MIME 类型"""
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        elif image_bytes[:2] == b"\xff\xd8":
            return "image/jpeg"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "image/png"
