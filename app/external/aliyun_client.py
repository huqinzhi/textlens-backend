"""
阿里云百炼 API 客户端封装
负责图片编辑调用（使用 wanxiang-image-edit 模型）
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

    使用阿里云百炼的 wanxiang-image-edit 模型进行图片编辑。
    支持海外节点 API。
    """

    # 海外节点 API
    BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/image-edit/editing"

    def __init__(self):
        self.api_key = settings.ALIYUN_API_KEY
        self.model = settings.ALIYUN_IMAGE_MODEL or "wanxiang-image-edit"

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        strength: float = 0.4,
    ) -> str:
        """
        使用阿里云百炼进行图片编辑

        调用 wanxiang-image-edit 模型，传入原图和编辑指令，
        返回生成图片的 base64 数据。

        [image_bytes] 原始图片字节数据
        [prompt] 图片编辑提示词
        [strength] 修改强度 (0-1)，越小越保真，0.3-0.5 最合适
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("Aliyun", "API key not configured")

        # 将图片转换为 base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": self.model,
            "input": {
                "image": image_b64,
                "prompt": prompt,
                "strength": strength,
            },
            "parameters": {
                "size": "1024*1024",
            },
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
                error_msg = response.text
                logger.error(f"[Aliyun] API error: {response.status_code} - {error_msg}")
                if "content_policy" in error_msg.lower() or "nsfw" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("Aliyun", f"API error: {error_msg}")

            result = response.json()

            # 检查是否有错误
            if "error" in result:
                error_msg = result.get("error", {}).get("message", "Unknown error")
                raise ExternalServiceError("Aliyun", f"API error: {error_msg}")

            # 解析响应
            output = result.get("output", {})
            image_data = output.get("image")

            if not image_data:
                raise ExternalServiceError("Aliyun", "No image in response")

            return image_data

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("Aliyun", "Request timeout")
        except ExternalServiceError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "sensitive" in error_str or "nsfw" in error_str or "content_policy" in error_str:
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("Aliyun", str(e))
