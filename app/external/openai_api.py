"""
OpenAI API 客户端封装
负责 GPT-4o 图片编辑调用和内容审核
"""
import base64
from typing import Any
from openai import AsyncOpenAI

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError


class OpenAIClient:
    """
    OpenAI API 客户端

    封装 GPT-4o 图片编辑和 Moderation API 调用，
    提供图片文字替换生成和内容安全审核功能。
    """

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def moderate_content(self, text: str) -> None:
        """
        对用户输入文本执行内容安全审核

        调用 OpenAI Moderation API，如果内容违规则抛出 ContentModerationError。

        [text] 需要审核的用户输入文本
        """
        try:
            response = await self.client.moderations.create(input=text)
            result = response.results[0]
            if result.flagged:
                # 找出触发的具体类别
                categories = result.categories.model_dump()
                flagged_cats = [cat for cat, flagged in categories.items() if flagged]
                raise ContentModerationError(
                    f"Content flagged for: {', '.join(flagged_cats)}"
                )
        except ContentModerationError:
            raise
        except Exception as e:
            # Moderation 接口失败时降级处理（不阻断生成流程）
            pass

    async def edit_image_with_text(
        self,
        original_image_url: str,
        original_image_bytes: bytes,
        prompt: str,
        quality: str = "low",
        size: str = "1024x1024",
    ) -> str:
        """
        使用 GPT-4o 对图片进行文字编辑并生成新图片

        将原图和编辑指令发送给 GPT-4o，返回生成图片的 URL 或 base64 数据。
        根据 quality 参数调整生成质量和成本。

        [original_image_bytes] 原始图片字节数据
        [original_image_url] 原始图片 URL（用于日志）
        [prompt] 图片编辑提示词（描述需要做的文字替换）
        [quality] 生成质量：low/medium/high，对应不同推理努力度
        [size] 输出图片尺寸
        返回生成图片的 base64 编码字符串
        """
        # 将原图编码为 base64
        image_b64 = base64.b64encode(original_image_bytes).decode("utf-8")

        # 根据质量级别设置参数
        quality_params = {
            "low": {"quality": "low"},
            "medium": {"quality": "medium"},
            "high": {"quality": "high"},
        }
        params = quality_params.get(quality, quality_params["low"])

        try:
            response = await self.client.images.edit(
                model="gpt-image-1",
                image=[
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{image_b64}",
                    }
                ],
                prompt=prompt,
                size=size,
                quality=params["quality"],
                n=1,
                response_format="b64_json",
            )

            if not response.data:
                raise ExternalServiceError("OpenAI returned empty response")

            return response.data[0].b64_json

        except ContentModerationError:
            raise
        except Exception as e:
            if "content_policy_violation" in str(e).lower():
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError(f"OpenAI image edit failed: {e}")

    async def generate_edit_prompt(
        self,
        ocr_blocks: list[dict],
        edit_blocks: list[dict],
        image_width: int = 1024,
        image_height: int = 1024,
        detected_language: str = "en",
    ) -> str:
        """
        根据 OCR 文字块和编辑指令生成 GPT-4o 提示词

        将用户的文字编辑意图转化为精确的图片编辑提示，
        包含文字位置、大小、风格等详细信息，确保修改后的图片与原图保持一致。

        [ocr_blocks] 原始 OCR 识别文字块列表
        [edit_blocks] 用户编辑后的文字块列表（含新文字）
        [image_width] 图片宽度（像素）
        [image_height] 图片高度（像素）
        [detected_language] 检测到的文字语言
        返回格式化的提示词字符串
        """
        from app.core.constants import GENERATION_PROMPT_TEMPLATE

        # 构建原文 → 文字块数据的映射
        ocr_map = {b.get("id"): b for b in ocr_blocks}

        # 构建替换指令列表
        regions_list = []

        for edit in edit_blocks:
            block_id = edit.get("id") or edit.get("block_id")
            new_text = edit.get("new_text", "").strip()
            original_text = edit.get("original_text", "")

            # 尝试从 OCR 结果中获取原文
            if not original_text and block_id and block_id in ocr_map:
                original_text = ocr_map[block_id].get("text", "")

            if not new_text:
                continue

            # 获取该文字块的位置和大小信息
            block_info = ocr_map.get(block_id, {})
            x = block_info.get("x", 0.0)
            y = block_info.get("y", 0.0)
            width = block_info.get("width", 0.0)
            height = block_info.get("height", 0.0)
            confidence = block_info.get("confidence", 1.0)
            font_size_estimate = block_info.get("font_size_estimate")

            # 计算绝对坐标（像素）
            abs_x = int(x * image_width)
            abs_y = int(y * image_height)
            abs_width = int(width * image_width)
            abs_height = int(height * image_height)

            # 构建位置描述
            position_desc = f"位置: 左上角({abs_x},{abs_y})px, 区域尺寸: {abs_width}x{abs_height}px"

            # 构建字体大小描述
            size_desc = ""
            if font_size_estimate:
                size_desc = f", 估算字体大小: {font_size_estimate}px"
            elif height > 0:
                # 从高度估算字体大小（假设文字高度约占区块高度的80%）
                estimated_font_size = int(abs_height * 0.8)
                size_desc = f", 估算字体大小: {estimated_font_size}px"

            # 构建详细替换指令
            region_desc = f"""[{len(regions_list) + 1}] 原文字: "{original_text}" → 新文字: "{new_text}"
    {position_desc}{size_desc}
    识别置信度: {confidence:.0%}"""

            regions_list.append(region_desc)

        if not regions_list:
            return "Keep the image exactly as is, no changes needed."

        # 使用模板生成完整提示词
        regions_text = "\n".join(regions_list)

        prompt = GENERATION_PROMPT_TEMPLATE.format(
            image_width=image_width,
            image_height=image_height,
            language=detected_language,
            region_count=len(regions_list),
            regions=regions_text,
        )

        return prompt
