"""
Cloudflare AI API 客户端封装
负责图片编辑调用（使用 Stable Diffusion inpainting）
"""
import base64
import io
import logging
from typing import Optional
from PIL import Image
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError

logger = logging.getLogger(__name__)


class CloudflareAIClient:
    """
    Cloudflare AI API 客户端

    使用 Cloudflare Workers AI 的 Stable Diffusion inpainting 模型进行图片编辑。
    """

    BASE_URL = "https://api.cloudflare.com/client/v4/accounts"

    def __init__(self):
        self.account_id = settings.CF_ACCOUNT_ID
        self.api_token = settings.CF_API_TOKEN
        self.model = settings.CF_IMAGE_MODEL or "@cf/runwayml/stable-diffusion-v1-5-inpainting"

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        mask_bytes: Optional[bytes] = None,
        guidance: float = 7.5,
    ) -> str:
        """
        使用 Cloudflare AI 进行图片编辑（inpainting）

        调用 Stable Diffusion inpainting 模型，传入原图、mask 和编辑指令，
        只重新生成 mask 标记的区域，其他部分保持不变。

        [image_bytes] 原始图片字节数据
        [prompt] 图片编辑提示词
        [mask_bytes] mask 图片字节数据（白色区域表示要替换的部分）
        [guidance] 引导强度
        返回生成图片的 base64 编码字符串
        """
        if not self.account_id or not self.api_token:
            raise ExternalServiceError("Cloudflare AI", "Account ID or API token not configured")

        url = f"{self.BASE_URL}/{self.account_id}/ai/run/{self.model}"

        # 将图片和 mask 转换为 base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "prompt": prompt,
            "image_b64": image_b64,
            "guidance": guidance,
        }

        # 如果提供了 mask，添加到请求中
        if mask_bytes:
            mask_b64 = base64.b64encode(mask_bytes).decode("utf-8")
            payload["mask_b64"] = mask_b64

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

            # Cloudflare 返回的是二进制 PNG 数据
            image_data = base64.b64encode(response.content).decode("utf-8")

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

    @staticmethod
    def create_mask(
        image_width: int,
        image_height: int,
        edit_blocks: list[dict],
        ocr_blocks: list[dict],
    ) -> bytes:
        """
        根据编辑区域创建 inpainting mask

        白色区域表示需要 AI 重新生成的部分。

        [image_width] 图片宽度
        [image_height] 图片高度
        [edit_blocks] 编辑区域列表
        [ocr_blocks] OCR 文字块列表
        返回 mask 图片的字节数据
        """
        # 构建原文 → 文字块数据的映射
        ocr_map = {b.get("id"): b for b in ocr_blocks}

        # 创建黑色背景的 mask
        mask = Image.new("L", (image_width, image_height), 0)

        # 收集所有需要编辑的区域
        regions = []
        for edit in edit_blocks:
            block_id = edit.get("id") or edit.get("block_id")
            block_info = ocr_map.get(block_id, {})

            x = block_info.get("x", 0.0)
            y = block_info.get("y", 0.0)
            width = block_info.get("width", 0.0)
            height = block_info.get("height", 0.0)

            abs_x = int(x * image_width)
            abs_y = int(y * image_height)
            abs_width = int(width * image_width)
            abs_height = int(height * image_height)

            if abs_width > 0 and abs_height > 0:
                regions.append((abs_x, abs_y, abs_width, abs_height))

        if not regions:
            return None

        # 在 mask 上绘制所有编辑区域（白色 = 要替换的区域）
        from PIL import ImageDraw
        draw = ImageDraw.Draw(mask)
        for x, y, w, h in regions:
            draw.rectangle([x, y, x + w, y + h], fill=255)

        # 保存为 PNG
        output = io.BytesIO()
        mask.save(output, format="PNG")
        return output.getvalue()
