"""
MiniMax API 客户端封装
负责图片生成和编辑调用（海外版）
"""
import base64
import io
import logging
from typing import Optional
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError

logger = logging.getLogger(__name__)


class MiniMaxClient:
    """
    MiniMax API 客户端（海外版）

    封装 MiniMax image-01 模型调用，
    提供图片生成和 image-to-image 功能。
    """

    BASE_URL = "https://api.minimax.io/v1"

    def __init__(self):
        self.api_key = settings.MINIMAX_API_KEY
        self.model = settings.MINIMAX_IMAGE_MODEL

    async def image_to_image(
        self,
        image_bytes: bytes,
        prompt: str,
        response_format: str = "base64",
    ) -> str:
        """
        使用 MiniMax 进行图片到图片的编辑生成

        调用 MiniMax Image-to-Image API，传入原图和编辑指令，
        返回生成图片的 base64 数据。

        [image_bytes] 原始图片字节数据
        [prompt] 图片编辑提示词（描述需要做的文字替换和风格）
        [response_format] 返回格式: base64 或 url
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("MiniMax", "API key not configured")

        url = f"{self.BASE_URL}/image_generation"

        # 将图片转换为 base64 data URL
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = self._get_mime_type(image_bytes)
        image_data_url = f"data:{mime_type};base64,{image_b64}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "subject_reference": [
                {
                    "type": "image_url",
                    "data": image_data_url,
                }
            ],
            "response_format": response_format,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code != 200:
                error_msg = response.text
                status_code = response.json().get("base_resp", {}).get("status_code", 0)
                if status_code == 1026 or "sensitive" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                if status_code == 1008:
                    raise ExternalServiceError("MiniMax", "Insufficient account balance")
                if status_code == 1004 or status_code == 2049:
                    raise ExternalServiceError("MiniMax", "Invalid API key")
                raise ExternalServiceError("MiniMax", f"API error: {error_msg}")

            result = response.json()

            # 调试：打印完整响应
            logger.info(f"[MiniMax] Response status: {response.status_code}")
            logger.info(f"[MiniMax] Response body: {result}")

            # 解析响应
            data = result.get("data")
            if data is None:
                raise ExternalServiceError("MiniMax", f"Invalid response: {result}")
            items = data.get("items", [])
            if not items:
                raise ExternalServiceError("MiniMax", "No image generated")

            # 优先返回 base64
            if response_format == "base64":
                return items[0].get("base64", "")
            else:
                # 如果是 url 格式，需要再下载回来转为 base64
                image_url = items[0].get("url", "")
                if not image_url:
                    raise ExternalServiceError("MiniMax", "No image URL returned")
                # 下载图片
                image_bytes = await self._download_image(image_url)
                return base64.b64encode(image_bytes).decode("utf-8")

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("MiniMax", "Request timeout")
        except ExternalServiceError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "sensitive" in error_str or "content_policy" in error_str:
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("MiniMax", str(e))

    async def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        response_format: str = "base64",
        n: int = 1,
    ) -> list[str]:
        """
        使用 MiniMax 文本生成图片

        调用 MiniMax Text-to-Image API，根据提示词生成图片。

        [prompt] 图片生成提示词
        [width] 输出图片宽度（默认 1024）
        [height] 输出图片高度（默认 1024）
        [response_format] 返回格式: base64 或 url
        [n] 生成图片数量
        返回生成图片的 base64 编码字符串列表
        """
        if not self.api_key:
            raise ExternalServiceError("MiniMax", "API key not configured")

        url = f"{self.BASE_URL}/image_generation"

        # 计算 aspect_ratio
        aspect_ratio = self._calculate_aspect_ratio(width, height)

        payload = {
            "model": self.model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "response_format": response_format,
            "n": n,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code != 200:
                error_msg = response.text
                status_code = response.json().get("base_resp", {}).get("status_code", 0)
                if status_code == 1026 or "sensitive" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("MiniMax", f"API error: {error_msg}")

            result = response.json()
            items = result.get("data", {}).get("items", [])

            results = []
            for item in items:
                if response_format == "base64":
                    results.append(item.get("base64", ""))
                else:
                    image_url = item.get("url", "")
                    if image_url:
                        image_bytes = await self._download_image(image_url)
                        results.append(base64.b64encode(image_bytes).decode("utf-8"))

            return results

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("MiniMax", "Request timeout")
        except Exception as e:
            if "sensitive" in str(e).lower():
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("MiniMax", str(e))

    def _get_mime_type(self, image_bytes: bytes) -> str:
        """根据图片字节数据判断 MIME 类型"""
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        elif image_bytes[:2] == b"\xff\xd8":
            return "image/jpeg"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "image/png"

    def _calculate_aspect_ratio(self, width: int, height: int) -> str:
        """根据宽高计算最接近的 aspect_ratio"""
        ratio = width / height

        ratios = {
            "1:1": 1.0,
            "16:9": 16 / 9,
            "4:3": 4 / 3,
            "3:2": 3 / 2,
            "2:3": 2 / 3,
            "3:4": 3 / 4,
            "9:16": 9 / 16,
            "21:9": 21 / 9,
        }

        closest = min(ratios.items(), key=lambda x: abs(x[1] - ratio))
        return closest[0]

    async def _download_image(self, url: str) -> bytes:
        """下载图片并返回字节数据"""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise ExternalServiceError("MiniMax", f"Failed to download image: {url}")
            return response.content
