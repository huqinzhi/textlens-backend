"""
阿里云百炼 API 客户端封装
负责图片编辑调用（使用 wan2.6-image 模型）
"""
import base64
import logging
from typing import Optional
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError

logger = logging.getLogger(__name__)


class AliyunClient:
    """
    阿里云百炼 API 客户端

    使用阿里云百炼的 wan2.6-image 模型进行图片编辑。
    支持美国节点 API，使用 SDK 兼容的 HTTP 调用方式。
    """

    # 阿里云百炼 API - 图像生成（美国节点）
    # SDK 风格端点
    BASE_URL = "https://dashscope-us.aliyuncs.com/api/v1/services/aigc/image_generation/image_generation"

    def __init__(self):
        self.api_key = settings.ALIYUN_API_KEY
        self.model = settings.ALIYUN_IMAGE_MODEL or "wan2.6-image"

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        strength: float = 0.4,
    ) -> str:
        """
        使用阿里云百炼进行图片编辑

        调用 wan2.6-image 模型进行图片编辑，
        返回生成图片的 base64 数据。

        [image_bytes] 原始图片字节数据
        [prompt] 图片编辑提示词
        [strength] ref_strength 修改强度 (0-1)，越小越保真，0.3-0.5 最合适
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("Aliyun", "API key not configured")

        # 将图片转换为 base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # 图像编辑模式：enable_interleave=False
        # 参考 SDK 示例的请求格式
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"text": prompt},
                        {"image": f"data:image/jpeg;base64,{image_b64}"},
                    ]
                }
            ],
            "negative_prompt": "",
            "prompt_extend": True,
            "watermark": False,
            "n": 1,
            "enable_interleave": False,
            "size": "1K",
            "ref_strength": strength,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    self.BASE_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code != 200:
                error_msg = response.text or "empty response"
                logger.error(f"[Aliyun] API error: status={response.status_code}, body={error_msg}")
                if "content_policy" in error_msg.lower() or "nsfw" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("Aliyun", f"API error: status={response.status_code}, body={error_msg}")

            result = response.json()
            logger.info(f"[Aliyun] Response: {result}")

            # 检查是否有错误
            if result.get("code") and result.get("code") != "":
                error_msg = result.get("message", "Unknown error")
                raise ExternalServiceError("Aliyun", f"API error: code={result.get('code')}, message={error_msg}")

            # 解析响应
            # 格式: output.choices[0].message.content[].image
            output = result.get("output", {})
            choices = output.get("choices", [])

            if not choices:
                raise ExternalServiceError("Aliyun", f"No choices in response: {result}")

            message = choices[0].get("message", {})
            content = message.get("content", [])

            if not content:
                raise ExternalServiceError("Aliyun", f"No content in message: {result}")

            # 查找图片
            for item in content:
                if isinstance(item, dict):
                    image_url = item.get("image")
                    if image_url:
                        return await self._download_image_as_base64(image_url)

            raise ExternalServiceError("Aliyun", f"No image in response content: {content}")

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("Aliyun", "Request timeout")
        except httpx.ReadError as e:
            logger.error(f"[Aliyun] ReadError: {e}")
            raise ExternalServiceError("Aliyun", f"Connection error: {e}")
        except ExternalServiceError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "sensitive" in error_str or "nsfw" in error_str or "content_policy" in error_str:
                raise ContentModerationError(f"Image content policy violation: {e}")
            logger.error(f"[Aliyun] Unexpected error: {e}")
            raise ExternalServiceError("Aliyun", str(e))

    async def _download_image_as_base64(self, image_url: str) -> str:
        """
        下载图片并转换为 base64

        [image_url] 图片 URL
        返回图片的 base64 编码字符串
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(image_url)

        if response.status_code != 200:
            raise ExternalServiceError("Aliyun", f"Failed to download image: {response.status_code}")

        return base64.b64encode(response.content).decode("utf-8")
