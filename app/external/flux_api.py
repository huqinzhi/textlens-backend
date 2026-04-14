"""
Flux API 客户端封装
负责图片生成调用（BFL 官方 API）
"""
import base64
import logging
import time
from typing import Optional
import httpx

from app.config import settings
from app.core.exceptions import ExternalServiceError, ContentModerationError

logger = logging.getLogger(__name__)


class FluxClient:
    """
    Flux API 客户端

    使用 BFL API 进行图片生成。
    注意：Flux 是文本到图片模型，不支持图片编辑。
    图片编辑需要结合 PIL 渲染 + Flux 增强的方案。
    """

    BASE_URL = "https://api.bfl.ml/v1"

    def __init__(self):
        self.api_key = settings.FLUX_API_KEY
        self.model = settings.FLUX_MODEL or "flux-schnell"

    async def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        timeout: int = 120,
    ) -> str:
        """
        使用 Flux 生成图片

        提交生图任务，轮询等待结果，返回生成图片的 base64 数据。

        [prompt] 图片生成提示词
        [width] 输出图片宽度
        [height] 输出图片高度
        [timeout] 超时时间（秒）
        返回生成图片的 base64 编码字符串
        """
        if not self.api_key:
            raise ExternalServiceError("Flux", "API key not configured")

        # 1. 提交生图任务
        submit_url = f"{self.BASE_URL}/{self.model}"

        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_images": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    submit_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Key": self.api_key,
                    },
                )

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"[Flux] Submit error: {response.status_code} - {error_msg}")
                raise ExternalServiceError("Flux", f"Submit error: {error_msg}")

            result = response.json()
            task_id = result.get("id")
            if not task_id:
                raise ExternalServiceError("Flux", f"No task ID returned: {result}")

            logger.info(f"[Flux] Task submitted: {task_id}")

            # 2. 轮询获取结果
            result_url = f"{self.BASE_URL}/get_result?id={task_id}"
            start_time = time.time()

            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                while True:
                    if time.time() - start_time > timeout:
                        raise ExternalServiceError("Flux", "Timeout waiting for result")

                    response = await client.get(result_url, headers={"X-Key": self.api_key})

                    if response.status_code != 200:
                        raise ExternalServiceError("Flux", f"Polling error: {response.text}")

                    result = response.json()
                    status = result.get("status")

                    if status == "Ready":
                        sample = result.get("result", {}).get("sample")
                        if not sample:
                            raise ExternalServiceError("Flux", "No image URL in result")

                        # 3. 下载图片并转为 base64
                        img_response = await client.get(sample)
                        if img_response.status_code != 200:
                            raise ExternalServiceError("Flux", "Failed to download generated image")

                        return base64.b64encode(img_response.content).decode("utf-8")

                    elif status == "Error":
                        error_msg = result.get("error", "Unknown error")
                        raise ExternalServiceError("Flux", f"Generation error: {error_msg}")

                    # 等待后继续轮询
                    await client.sleep(1)

        except httpx.TimeoutException:
            raise ExternalServiceError("Flux", "Request timeout")
        except ExternalServiceError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "sensitive" in error_str or "content_policy" in error_str:
                raise ContentModerationError(f"Image content policy violation: {e}")
            raise ExternalServiceError("Flux", str(e))
