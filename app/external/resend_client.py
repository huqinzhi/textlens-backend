"""
Resend 邮件发送客户端

封装 Resend API 实现邮件发送功能
"""

import resend
from app.config import settings
from app.core.exceptions import ExternalServiceError


class ResendClient:
    """
    Resend 邮件发送客户端

    [api_key] Resend API Key
    [from_email] 发件人邮箱地址
    """

    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.RESEND_FROM_EMAIL
        if self.api_key:
            resend.api_key = self.api_key

    def send_verification_email(self, email: str, code: str, scene: str) -> bool:
        """
        发送邮箱验证码邮件

        [email] 收件人邮箱
        [code] 6位验证码
        [scene] 场景 (register/login/reset_password)
        返回 bool 是否发送成功
        """
        subject_map = {
            "register": "TextLens 注册验证码",
            "login": "TextLens 登录验证码",
            "reset_password": "TextLens 密码重置验证码",
        }

        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #333;">TextLens</h2>
            <p style="color: #555; font-size: 16px;">您好，</p>
            <p style="color: #555; font-size: 16px;">您的验证码是：</p>
            <p style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #333; margin: 20px 0;">{code}</p>
            <p style="color: #555; font-size: 14px;">该验证码在 <strong>10 分钟</strong>内有效，请勿泄露给他人。</p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
            <p style="color: #999; font-size: 12px;">如果您没有发起此请求，请忽略此邮件。</p>
        </div>
        """

        try:
            if not self.api_key:
                # 开发环境：打印到日志
                print(f"[Dev Mode] Email to {email}, code: {code}, scene: {scene}")
                return True

            response = resend.Emails.send({
                "from": self.from_email,
                "to": email,
                "subject": subject_map.get(scene, "TextLens 验证码"),
                "html": html_content,
            })
            return response.get("id") is not None
        except Exception as e:
            raise ExternalServiceError(f"Failed to send email: {str(e)}")


resend_client = ResendClient()
