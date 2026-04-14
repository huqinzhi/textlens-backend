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
    支持美国节点 API，使用流式输出。
    """

    # 阿里云百炼 API - 多模态生成（美国节点）
    BASE_URL = "https://dashscope-us.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

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
        [strength] 修改强度 (0-1)，越小越保真，0.3-0.5 最合适
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("Aliyun", "API key not configured")

        # 将图片转换为 base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # 构建多模态消息格式
        # 美国节点必须启用流式输出
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:image/jpeg;base64,{image_b64}",
                                "text": prompt,
                            }
                        ]
                    }
                ]
            },
            "parameters": {
                "size": "1024*1024",
                "ref_strength": strength,
                "ref_mode": "repaint",
                "stream": True,
                "enable_interleave": True,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    self.BASE_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "X-DashScope-Sse": "enable",
                    },
                ) as response:
                    if response.status_code != 200:
                        error_msg = ""
                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                data = line[5:].strip()
                                if data and data != "[DONE]":
                                    try:
                                        import json
                                        msg = json.loads(data)
                                        error_msg = msg.get("error", {}).get("message", "")
                                        if error_msg:
                                            break
                                    except:
                                        pass
                        logger.error(f"[Aliyun] API error: status={response.status_code}, error={error_msg}")
                        raise ExternalServiceError("Aliyun", f"API error: status={response.status_code}, error={error_msg}")

                    # 解析 SSE 流式响应
                    image_url = None
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data and data != "[DONE]":
                                try:
                                    import json
                                    msg = json.loads(data)
                                    # 查找图片
                                    output = msg.get("output", {})
                                    choices = output.get("choices", [])
                                    if choices:
                                        message = choices[0].get("message", {})
                                        content = message.get("content", [])
                                        for item in content:
                                            if isinstance(item, dict) and item.get("image"):
                                                image_url = item["image"]
                                                break
                                            elif isinstance(item, dict) and item.get("image_url"):
                                                image_url = item["image_url"]
                                                break
                                    if image_url:
                                        break
                                except Exception as e:
                                    logger.warning(f"[Aliyun] Failed to parse SSE message: {e}")
                                    continue

                    if not image_url:
                        raise ExternalServiceError("Aliyun", "No image URL in streaming response")

                    return await self._download_image_as_base64(image_url)

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
