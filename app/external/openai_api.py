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
    ) -> str:
        """
        根据 OCR 文字块和编辑指令生成 GPT-4o 提示词

        将用户的文字编辑意图转化为精确的图片编辑提示，
        描述哪些文字需要被替换为什么内容。

        [ocr_blocks] 原始 OCR 识别文字块列表
        [edit_blocks] 用户编辑后的文字块列表（含新文字）
        返回格式化的提示词字符串
        """
        edit_instructions = []

        # 构建原文 → 新文的映射
        ocr_map = {b["id"]: b["text"] for b in ocr_blocks}

        for edit in edit_blocks:
            block_id = edit.get("id")
            new_text = edit.get("new_text", "").strip()
            original_text = ocr_map.get(block_id, "")

            if original_text and new_text and original_text != new_text:
                edit_instructions.append(
                    f'Replace the text "{original_text}" with "{new_text}"'
                )

        if not edit_instructions:
            return "Keep the image exactly as is, no changes needed."

        instructions_text = "; ".join(edit_instructions)
        prompt = (
            f"Edit the text in this image. {instructions_text}. "
            f"Keep the same font style, size, color, and positioning as the original text. "
            f"Make the changes look natural and seamlessly integrated into the image."
        )

        return prompt
