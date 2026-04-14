"""
Cloudflare AI API 客户端封装
负责图片编辑调用（使用 Stable Diffusion img2img）
"""
import base64
import logging
from typing import Optional
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError

logger = logging.getLogger(__name__)


class CloudflareAIClient:
    """
    Cloudflare AI API 客户端

    使用 Cloudflare Workers AI 的 Stable Diffusion img2img 模型进行图片编辑。
    """

    BASE_URL = "https://api.cloudflare.com/client/v4/accounts"

    def __init__(self):
        self.account_id = settings.CF_ACCOUNT_ID
        self.api_token = settings.CF_API_TOKEN
        self.model = settings.CF_IMAGE_MODEL or "@cf/runwayml/stable-diffusion-v1-5-img2img"

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        strength: float = 0.7,
        guidance: float = 7.5,
    ) -> str:
        """
        使用 Cloudflare AI 进行图片编辑

        调用 Stable Diffusion img2img 模型，传入原图和编辑指令，
        返回生成图片的 base64 数据。

        [image_bytes] 原始图片字节数据
        [prompt] 图片编辑提示词
        [strength] 变换强度 (0-1)，越大改变越多
        [guidance] 引导强度
        返回生成图片的 base64 编码字符串
        """
        if not self.account_id or not self.api_token:
            raise ExternalServiceError("Cloudflare AI", "Account ID or API token not configured")

        url = f"{self.BASE_URL}/{self.account_id}/ai/run/{self.model}"

        # 将图片转换为 base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "prompt": prompt,
            "image": image_b64,
            "strength": strength,
            "guidance": guidance,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_token}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[Cloudflare AI] API error: {response.status_code} - {error_msg}")
                if "content_policy" in error_msg.lower() or "nsfw" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("Cloudflare AI", f"API error: {error_msg}")

            result = response.json()
            image_data = result.get("result", {}).get("image")

            if not image_data:
                raise ExternalServiceError("Cloudflare AI", "No image in response")

            return image_data

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("Cloudflare AI", "Request timeout")
        except ExternalServiceError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "sensitive" in error_str or "nsfw" in error_str or "content_policy" in error_str:
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("Cloudflare AI", str(e))
