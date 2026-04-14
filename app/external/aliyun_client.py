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

    使用阿里云百炼的 wanx-v1 或 qwen-image-plus 模型进行图片编辑。
    支持海外节点 API。
    """

    # 阿里云百炼 API - 图生图（使用 ref_image 参考图）
    # 海外节点: https://dashscope-intl.aliyuncs.com
    # 北京节点: https://dashscope.aliyuncs.com
    BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"

    def __init__(self):
        self.api_key = settings.ALIYUN_API_KEY
        self.model = settings.ALIYUN_IMAGE_MODEL or "wanx-v1"

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        strength: float = 0.4,
    ) -> str:
        """
        使用阿里云百炼进行图片编辑

        调用 wanx-v1 模型配合 ref_image 参考图进行图片编辑，
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

        payload = {
            "model": self.model,
            "input": {
                "prompt": prompt,
                "ref_image": image_b64,
            },
            "parameters": {
                "size": "1024*1024",
                "ref_strength": strength,
                "ref_mode": "repaint",
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
                        "X-DashScope-Async": "enable",
                    },
                )

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[Aliyun] API error: {response.status_code} - {error_msg}")
                if "content_policy" in error_msg.lower() or "nsfw" in error_msg.lower():
                    raise ContentModerationError("Image content policy violation")
                raise ExternalServiceError("Aliyun", f"API error: {error_msg}")

            result = response.json()
            logger.info(f"[Aliyun] Response: {result}")

            # 检查是否有错误
            if "error" in result:
                error_msg = result.get("error", {}).get("message", "Unknown error")
                raise ExternalServiceError("Aliyun", f"API error: {error_msg}")

            # 解析响应 - 图片生成返回 task_id，需要等待任务完成
            output = result.get("output", {})
            task_id = output.get("task_id")
            task_status = output.get("task_status", "")

            if task_status == "SUCCEEDED":
                # 同步模式直接返回结果
                results = output.get("results", [])
                if results:
                    image_url = results[0].get("url")
                    if image_url:
                        # 下载图片并返回 base64
                        return await self._download_image_as_base64(image_url)
                raise ExternalServiceError("Aliyun", "No image URL in response")

            elif task_id:
                # 异步模式，等待任务完成
                image_url = await self._wait_for_task(task_id)
                return await self._download_image_as_base64(image_url)

            raise ExternalServiceError("Aliyun", f"Unexpected response: {result}")

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
            logger.error(f"[Aliyun] Unexpected error: {e}, response: {response.text if 'response' in dir() else 'N/A'}")
            raise ExternalServiceError("Aliyun", str(e))

    async def _wait_for_task(self, task_id: str, max_wait_seconds: int = 120) -> str:
        """
        轮询等待异步任务完成

        [task_id] 任务ID
        [max_wait_seconds] 最大等待时间（秒）
        返回生成图片的 URL
        """
        import asyncio
        import time

        task_url = f"https://dashscope-intl.aliyuncs.com/api/v1/tasks/{task_id}"
        start_time = time.time()

        while time.time() - start_time < max_wait_seconds:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    task_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )

            if response.status_code == 200:
                result = response.json()
                output = result.get("output", {})
                status = output.get("task_status", "")

                if status == "SUCCEEDED":
                    results = output.get("results", [])
                    if results:
                        return results[0].get("url")
                    raise ExternalServiceError("Aliyun", "Task succeeded but no image URL")

                elif status == "FAILED":
                    error_msg = output.get("message", "Task failed")
                    raise ExternalServiceError("Aliyun", f"Task failed: {error_msg}")

                # 继续等待
                logger.info(f"[Aliyun] Task {task_id} status: {status}, waiting...")
                await asyncio.sleep(3)
            else:
                raise ExternalServiceError("Aliyun", f"Failed to get task status: {response.text}")

        raise ExternalServiceError("Aliyun", f"Task timeout after {max_wait_seconds} seconds")

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
