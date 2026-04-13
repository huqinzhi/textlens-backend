"""
Stability AI API 客户端封装
负责图片编辑和生成调用
"""
import base64
from typing import Optional
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError


class StabilityAIClient:
    """
    Stability AI API 客户端

    封装 Stability AI 生图 API 调用，
    提供图片编辑和生成功能。
    """

    BASE_URL = "https://api.stability.ai/v1"

    def __init__(self):
        self.api_key = settings.STABILITY_API_KEY
        self.engine_id = settings.STABILITY_ENGINE_ID

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        mask_bytes: Optional[bytes] = None,
        negative_prompt: str = "",
    ) -> str:
        """
        使用 Stability AI 对图片进行文字编辑并生成新图片

        调用 Stability AI Image Editing API，传入原图和编辑指令，
        返回生成图片的 base64 数据。

        [image_bytes] 原始图片字节数据
        [prompt] 图片编辑提示词（描述需要做的文字替换）
        [mask_bytes] 可选的蒙版图片字节数据（用于局部编辑）
        [negative_prompt] 负面提示词（不希望出现的内容）
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("Stability AI", "API key not configured")

        url = f"{self.BASE_URL}/generation/{self.engine_id}/image-to-image"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Stability AI image-to-image: 发送图片和 prompt 作为 JSON
                files = {
                    "init_image": ("image.png", image_bytes, "image/png"),
                }
                if mask_bytes:
                    files["mask"] = ("mask.png", mask_bytes, "image/png")

                json_data = {
                    "text_prompts": [
                        {"text": prompt, "weight": 1.0},
                    ],
                    "output_format": "png",
                }

                response = await client.post(
                    url,
                    files=files,
                    json=json_data,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )

            if response.status_code != 200:
                error_msg = response.text
                if "content_policy" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("Stability AI", f"API error: {error_msg}")

            result = response.json()

            # 解析返回的 base64 图片数据
            artifacts = result.get("artifacts", [])
            if not artifacts:
                raise ExternalServiceError("Stability AI", "No image generated")

            return artifacts[0]["base64"]

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("Stability AI", "Request timeout")
        except Exception as e:
            if "content_policy" in str(e).lower():
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("Stability AI", str(e))

    async def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        negative_prompt: str = "",
        steps: int = 30,
        seed: int = 0,
    ) -> str:
        """
        使用 Stability AI 文本生成图片

        调用 Stability AI Text-to-Image API，根据提示词生成图片。

        [prompt] 图片生成提示词
        [width] 输出图片宽度（默认 1024）
        [height] 输出图片高度（默认 1024）
        [negative_prompt] 负面提示词
        [steps] 推理步数（影响生成质量，默认 30）
        [seed] 随机种子（固定值可复现结果，0 表示随机）
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("Stability AI", "API key not configured")

        url = f"{self.BASE_URL}/generation/{self.engine_id}/text-to-image"

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "seed": seed if seed > 0 else None,
            "output_format": "png",
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
                if "content_policy" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("Stability AI", f"API error: {error_msg}")

            data = response.json()

            artifacts = data.get("artifacts", [])
            if not artifacts:
                raise ExternalServiceError("Stability AI", "No image generated")

            return artifacts[0]["base64"]

        except ContentModerationError:
            raise
        except httpx.TimeoutException:
            raise ExternalServiceError("Stability AI", "Request timeout")
        except Exception as e:
            if "content_policy" in str(e).lower():
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("Stability AI", str(e))
