"""
Stability AI API 客户端封装
负责图片编辑和生成调用
"""
import base64
import io
from typing import Optional
import httpx
from PIL import Image

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError


# SDXL 允许的尺寸映射表
SDXL_ALLOWED_DIMENSIONS = [
    (1024, 1024),
    (1152, 896),
    (1216, 832),
    (1344, 768),
    (1536, 640),
    (640, 1536),
    (768, 1344),
    (832, 1216),
    (896, 1152),
]


def create_mask_for_region(
    width: int,
    height: int,
    x: int,
    y: int,
    region_width: int,
    region_height: int,
) -> bytes:
    """
    根据文字区域创建白色蒙版（白色区域将被替换）

    [width] 蒙版图片宽度
    [height] 蒙版图片高度
    [x] 文字区域左上角 X 坐标
    [y] 文字区域左上角 Y 坐标
    [region_width] 文字区域宽度
    [region_height] 文字区域高度
    返回蒙版图片字节数据（灰度图，白色=替换区域，黑色=保留区域）
    """
    mask = Image.new("L", (width, height), 0)  # 黑色背景
    from PIL import ImageDraw
    draw = ImageDraw.Draw(mask)
    draw.rectangle(
        [x, y, x + region_width, y + region_height],
        fill=255  # 白色区域将被 AI 重新生成
    )
    output = io.BytesIO()
    mask.save(output, format="PNG")
    return output.getvalue()


def scale_mask_to_image(
    mask_bytes: bytes,
    orig_width: int,
    orig_height: int,
    target_width: int,
    target_height: int,
) -> bytes:
    """
    将原始尺寸的 mask 缩放到目标尺寸（与图片同步缩放）

    [mask_bytes] 原始 mask 字节数据
    [orig_width] 原始图片宽度
    [orig_height] 原始图片高度
    [target_width] 目标图片宽度
    [target_height] 目标图片高度
    返回缩放后的 mask 字节数据
    """
    mask = Image.open(io.BytesIO(mask_bytes))
    # 缩放 mask 到与图片相同的尺寸
    mask_resized = mask.resize((target_width, target_height), Image.LANCZOS)
    output = io.BytesIO()
    mask_resized.save(output, format="PNG")
    return output.getvalue()


def resize_image_for_sdxl(image_bytes: bytes) -> tuple[bytes, int, int, int, int]:
    """
    将图片缩放到 SDXL 允许的尺寸

    [image_bytes] 原始图片字节数据
    返回 (缩放后的图片字节数据, 原始宽度, 原始高度, 目标宽度, 目标高度)
    """
    img = Image.open(io.BytesIO(image_bytes))
    orig_width, orig_height = img.size

    # 计算目标尺寸（选择最接近的允许尺寸，保持宽高比）
    target_width, target_height = orig_width, orig_height
    min_diff = float('inf')

    for w, h in SDXL_ALLOWED_DIMENSIONS:
        # 检查宽高比是否接近
        orig_ratio = orig_width / orig_height
        new_ratio = w / h
        ratio_diff = abs(orig_ratio - new_ratio)
        area_diff = abs((w * h) - (orig_width * orig_height))

        # 综合考虑宽高比和面积
        score = ratio_diff * 10000 + area_diff / 1000000
        if score < min_diff:
            min_diff = score
            target_width, target_height = w, h

    # 如果原始尺寸已经是允许的，直接返回
    if (orig_width, orig_height) in SDXL_ALLOWED_DIMENSIONS:
        return image_bytes, orig_width, orig_height, orig_width, orig_height

    # 缩放图片
    img_resized = img.resize((target_width, target_height), Image.LANCZOS)
    output = io.BytesIO()
    img_resized.save(output, format=img.format or 'PNG')
    return output.getvalue(), orig_width, orig_height, target_width, target_height


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

        # 根据是否提供 mask 决定使用哪个端点
        if mask_bytes:
            url = f"{self.BASE_URL}/generation/{self.engine_id}/inpainting"
        else:
            url = f"{self.BASE_URL}/generation/{self.engine_id}/image-to-image"

        try:
            import json
            # 缩放图片到 SDXL 允许的尺寸
            image_bytes, orig_w, orig_h, target_w, target_h = resize_image_for_sdxl(image_bytes)

            # 如果提供了 mask，同步缩放 mask 到目标尺寸
            if mask_bytes:
                mask_bytes = scale_mask_to_image(mask_bytes, orig_w, orig_h, target_w, target_h)

            async with httpx.AsyncClient(timeout=120.0) as client:
                # 构造 multipart/form-data 请求
                # 使用 list of tuples 格式：(field_name, (filename, content, content_type)) 或 (field_name, content)
                files = [
                    ("init_image", ("image.png", image_bytes, "image/png")),
                    ("text_prompts[0][text]", prompt),
                    ("text_prompts[0][weight]", "1.0"),
                ]
                if mask_bytes:
                    files.insert(1, ("mask", ("mask.png", mask_bytes, "image/png")))

                response = await client.post(
                    url,
                    files=files,
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
