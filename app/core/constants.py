"""
全局常量定义模块

定义应用中使用的所有枚举类型和常量值。
"""

from enum import Enum


class QualityLevel(str, Enum):
    """
    AI 生图质量等级枚举

    LOW   - 低质量（512×512，每日免费3次）
    MEDIUM - 中质量（1024×1024，消耗15积分）
    HIGH  - 高质量（1024×1024 HD，消耗25积分）
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(str, Enum):
    """
    Celery 异步任务状态枚举

    PENDING    - 等待处理
    PROCESSING - 处理中
    DONE       - 处理成功
    FAILED     - 处理失败
    CANCELLED  - 已取消
    """
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CreditTransactionType(str, Enum):
    """
    积分流水类型枚举

    EARN  - 获取积分（充值、签到、广告、邀请）
    SPEND - 消耗积分（AI生图）
    REFUND - 退款（生成失败退款）
    """
    EARN = "earn"
    SPEND = "spend"
    REFUND = "refund"


class CreditSourceType(str, Enum):
    """
    积分来源类型枚举

    PURCHASE  - 购买充值
    AD        - 观看广告
    DAILY     - 每日签到
    INVITE    - 邀请好友
    REGISTER  - 首次注册奖励
    REFUND    - 生成失败退款
    GENERATION - AI 生成消耗
    """
    PURCHASE = "purchase"
    AD = "ad"
    DAILY = "daily"
    INVITE = "invite"
    REGISTER = "register"
    REFUND = "refund"
    GENERATION = "generation"


class PaymentProvider(str, Enum):
    """
    支付渠道枚举

    STRIPE      - Stripe 信用卡支付
    APPLE_IAP   - Apple 应用内购买
    GOOGLE_IAP  - Google Play 应用内购买
    """
    STRIPE = "stripe"
    APPLE_IAP = "apple_iap"
    GOOGLE_IAP = "google_iap"


class PaymentStatus(str, Enum):
    """
    支付状态枚举

    PENDING   - 待支付
    SUCCESS   - 支付成功
    FAILED    - 支付失败
    REFUNDED  - 已退款
    """
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


# ── 积分消耗规则 ────────────────────────────────────────────────────────
QUALITY_CREDITS_MAP = {
    QualityLevel.LOW: 5,
    QualityLevel.MEDIUM: 15,
    QualityLevel.HIGH: 25,
}

# ── 积分充值套餐定义 ────────────────────────────────────────────────────
CREDIT_PACKAGES = {
    "starter": {"name": "Starter Pack", "price_usd": 0.99, "credits": 100, "bonus": 0},
    "basic":   {"name": "Basic Pack",   "price_usd": 2.99, "credits": 320, "bonus": 20},
    "pro":     {"name": "Pro Pack",     "price_usd": 6.99, "credits": 800, "bonus": 100},
    "premium": {"name": "Premium Pack", "price_usd": 14.99, "credits": 1800, "bonus": 300},
}

# ── OpenAI 生图参数映射 ─────────────────────────────────────────────────
QUALITY_OPENAI_PARAMS = {
    QualityLevel.LOW: {"size": "512x512", "quality": "standard"},
    QualityLevel.MEDIUM: {"size": "1024x1024", "quality": "standard"},
    QualityLevel.HIGH: {"size": "1024x1024", "quality": "hd"},
}

# ── AI 生图 Prompt 模板 ─────────────────────────────────────────────────
GENERATION_PROMPT_TEMPLATE = """Edit the text in this image. Replace the following text regions:
{regions}
Keep the exact same font style, size, color, background, and lighting.
The result must look photorealistic and natural.
Do not change any other parts of the image."""
