# TextLens 后端技术方案文档

**项目名称**：TextLens Backend  
**文档版本**：v1.0  
**编写日期**：2026-04-10  
**技术栈**：Python 3.12 · FastAPI · PostgreSQL · Redis · Celery · OpenAI GPT-4o · Google Vision API

---

## 一、项目概述

TextLens 是一款 AI 图片文字编辑工具。用户上传含文字的图片 → OCR 识别文字内容 → 用户修改目标文字 → AI 重新生成替换后的图片。

本文档专注于后端服务的架构设计、模块划分、API 规范、数据模型和部署方案。

---

## 二、整体架构

```
┌──────────────────────────────────────────────────┐
│                   Mobile Client                   │
│             (Flutter iOS / Android)               │
└────────────────────┬─────────────────────────────┘
                     │ HTTPS / JSON
┌────────────────────▼─────────────────────────────┐
│                FastAPI (uvicorn)                  │
│  ┌───────────┐  ┌──────────┐  ┌───────────────┐ │
│  │  Router   │→ │ Service  │→ │ DB Models     │ │
│  │  (HTTP)   │  │(Business)│  │ (SQLAlchemy)  │ │
│  └───────────┘  └──────────┘  └───────────────┘ │
│                      │                           │
│                ┌─────▼──────┐                    │
│                │ External   │                    │
│                │ Clients    │                    │
│                └────────────┘                    │
└──────────────────────────────────────────────────┘
          │                │             │
  ┌───────▼──┐    ┌────────▼──┐   ┌─────▼──────┐
  │PostgreSQL│    │  Redis     │   │  Celery     │
  │          │    │(Cache/MQ)  │   │  Worker     │
  └──────────┘    └───────────┘   └────────────┘
                                       │
                           ┌───────────▼──────────┐
                           │  External Services    │
                           │  · Google Vision API  │
                           │  · OpenAI GPT-4o     │
                           │  · Stripe / IAP       │
                           │  · AWS S3 / R2        │
                           └───────────────────────┘
```

### 设计原则

| 原则 | 说明 |
|------|------|
| **Feature-based 架构** | 按功能模块划分（auth/users/credits/ocr/generation/payments/history），每模块独立 router + service |
| **异步任务解耦** | OCR 识别和 AI 生图均通过 Celery 异步执行，API 立即返回 task_id，客户端轮询进度 |
| **外部服务隔离** | 所有第三方 API（Google Vision / OpenAI / Stripe / S3）封装在 `app/external/` 层 |
| **积分原子性** | 所有积分变动操作使用 `SELECT FOR UPDATE` + 事务保证原子性 |
| **GDPR 合规** | 软删除（deleted_at），30 天后 Celery Beat 定时硬删除全部个人数据 |

---

## 三、目录结构

```
textlens-backend/
├── app/
│   ├── main.py                    # FastAPI 应用工厂，注册中间件和路由
│   ├── config.py                  # Pydantic Settings 配置（读取环境变量）
│   ├── dependencies.py            # get_current_user 等通用依赖注入
│   ├── core/
│   │   ├── security.py            # JWT 生成/验证，密码哈希
│   │   ├── exceptions.py          # 自定义异常层级
│   │   └── constants.py           # 枚举类型、积分规则常量
│   ├── db/
│   │   ├── base.py                # DeclarativeBase，聚合所有模型
│   │   ├── session.py             # 数据库引擎和会话工厂
│   │   └── models/
│   │       ├── user.py            # User, RefreshToken
│   │       ├── credit.py          # CreditAccount, CreditTransaction, DailyFreeUsage
│   │       ├── image.py           # Image, OCRResult, GenerationTask
│   │       └── payment.py         # PurchaseRecord
│   ├── schemas/                   # Pydantic 请求/响应数据模型
│   │   ├── common.py              # PageResponse 通用分页
│   │   ├── user.py, credit.py, image.py, payment.py
│   ├── features/
│   │   ├── auth/                  # 注册、登录、OAuth、Token 刷新
│   │   ├── users/                 # 用户资料查询和更新
│   │   ├── credits/               # 积分余额、流水、签到、广告奖励
│   │   ├── ocr/                   # 图片上传和 OCR 识别
│   │   ├── generation/            # AI 图片生成任务提交和查询
│   │   ├── payments/              # Stripe Checkout、IAP 验证、Webhook
│   │   └── history/               # 历史记录查询和删除
│   ├── middleware/
│   │   ├── rate_limit.py          # Redis 滑动窗口限流
│   │   ├── error_handler.py       # 全局异常捕获 → 标准化 JSON
│   │   └── request_logging.py     # 访问日志记录
│   ├── external/
│   │   ├── google_vision.py       # Google Cloud Vision OCR 客户端
│   │   ├── openai_api.py          # OpenAI GPT-4o 图片编辑客户端
│   │   ├── s3_client.py           # AWS S3 / Cloudflare R2 存储客户端
│   │   └── stripe_api.py          # Stripe 支付客户端
│   └── tasks/
│       ├── celery_app.py          # Celery 配置和 Beat 定时任务
│       ├── generation_tasks.py    # AI 生图 Celery 任务
│       ├── ocr_tasks.py           # OCR 识别 Celery 任务
│       └── cleanup_tasks.py       # 图片清理和 GDPR 删除任务
├── migrations/
│   ├── env.py                     # Alembic 迁移环境配置
│   └── versions/                  # 迁移版本文件
├── docker/
│   ├── Dockerfile                 # API 服务镜像
│   └── Dockerfile.celery          # Celery Worker 镜像
├── docker-compose.yml             # 完整栈编排
├── alembic.ini                    # Alembic 配置
├── requirements.txt               # 生产依赖
└── .env.example                   # 环境变量模板
```

---

## 四、数据库模型

### 4.1 users（用户表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 用户 ID |
| email | VARCHAR(255) UNIQUE | 邮箱（可 NULL，OAuth 用户） |
| password_hash | VARCHAR(255) | bcrypt 哈希密码 |
| username | VARCHAR(50) | 昵称 |
| avatar_url | VARCHAR(500) | 头像 URL |
| auth_provider | ENUM | email / google / apple |
| provider_user_id | VARCHAR(255) | OAuth 第三方 ID |
| is_active | BOOLEAN | 账户是否可用 |
| is_email_verified | BOOLEAN | 邮箱是否验证 |
| deleted_at | TIMESTAMP | 软删除时间（GDPR） |
| created_at | TIMESTAMP | 注册时间 |

### 4.2 credit_accounts（积分账户表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | 账户 ID |
| user_id | UUID FK | 关联用户 |
| balance | INT | 当前积分余额 |
| total_earned | INT | 累计获得积分 |
| total_spent | INT | 累计消耗积分 |

### 4.3 credit_transactions（积分流水表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | 流水 ID |
| user_id | UUID FK | 用户 ID |
| amount | INT | 变动数量（正=获得，负=消耗） |
| type | ENUM | earn / spend |
| source | ENUM | purchase/ad/daily/invite/register/refund |
| balance_after | INT | 变动后余额 |
| description | VARCHAR | 备注说明 |

### 4.4 generation_tasks（生成任务表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 任务 ID |
| user_id | UUID FK | 用户 ID |
| original_image_url | VARCHAR | 原图 S3 URL |
| result_image_url | VARCHAR | 生成结果 S3 URL |
| ocr_data | JSON | OCR 识别结果 |
| edit_data | JSON | 用户编辑指令 |
| quality | ENUM | low / medium / high |
| status | ENUM | pending/processing/done/failed/cancelled |
| credits_cost | INT | 消耗积分数 |
| celery_task_id | VARCHAR | Celery 任务 ID |
| has_watermark | BOOLEAN | 是否有水印（免费生成） |
| created_at | TIMESTAMP | 创建时间 |

### 4.5 purchase_records（购买记录表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 订单 ID |
| user_id | UUID FK | 用户 ID |
| package_id | VARCHAR | 套餐 ID |
| amount_usd | FLOAT | 支付金额（美元） |
| credits_granted | INT | 发放积分数 |
| payment_provider | ENUM | stripe/apple_iap/google_iap |
| status | ENUM | PENDING/SUCCESS/FAILED/REFUNDED |
| external_order_id | VARCHAR | Stripe Session ID / Apple Transaction ID |
| receipt_data | TEXT | IAP 收据原始数据 |

---

## 五、API 接口规范

**Base URL**: `https://api.textlens.app/api/v1`  
**认证方式**: `Authorization: Bearer <access_token>`  
**响应格式**: JSON

### 5.1 认证模块 `/auth`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 邮箱注册（含 COPPA 合规验证） |
| POST | `/auth/login` | 邮箱密码登录 |
| POST | `/auth/google` | Google OAuth 登录 |
| POST | `/auth/apple` | Apple Sign In 登录 |
| POST | `/auth/refresh` | 刷新 Access Token（滚动刷新） |
| POST | `/auth/logout` | 登出（吊销 Refresh Token） |
| DELETE | `/auth/account` | 注销账户（GDPR 软删除） |

**注册请求体**：
```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "username": "Alice",
  "age_verified": true,
  "terms_accepted": true,
  "privacy_accepted": true
}
```

**登录响应体**：
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

### 5.2 用户模块 `/users`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/users/profile` | 获取个人资料（含积分余额） |
| PUT | `/users/profile` | 更新用户名和头像 |
| GET | `/users/credits` | 快捷获取积分信息 |

### 5.3 OCR 模块 `/ocr`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ocr/upload` | 上传图片并触发 OCR 识别（返回 task_id） |
| GET | `/ocr/{task_id}` | 查询 OCR 识别结果 |

**OCR 结果响应**：
```json
{
  "task_id": "uuid",
  "status": "done",
  "image_id": "uuid",
  "image_url": "https://cdn.../uploads/xxx.jpg",
  "text_blocks": [
    {
      "id": "block_0",
      "text": "Hello World",
      "x": 0.12,
      "y": 0.08,
      "width": 0.35,
      "height": 0.06,
      "confidence": 0.98
    }
  ]
}
```

> **坐标系**：所有坐标均为归一化值（0.0 ~ 1.0），相对于图片宽高的比例，便于前端在不同分辨率设备上正确渲染覆盖层。

### 5.4 AI 生成模块 `/generate`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/generate` | 提交 AI 生成任务（202 立即返回） |
| GET | `/generate/{task_id}` | 查询生成任务状态和结果 |
| DELETE | `/generate/{task_id}` | 取消待处理任务（退还积分） |

**提交生成请求体**：
```json
{
  "image_id": "uuid",
  "quality": "medium",
  "edit_blocks": [
    {
      "id": "block_0",
      "new_text": "你好世界"
    }
  ]
}
```

**生成任务响应**（轮询）：
```json
{
  "task_id": "uuid",
  "status": "done",
  "result_image_url": "https://cdn.../results/xxx.png",
  "credits_cost": 15,
  "estimated_seconds": 0
}
```

**生成流程**：
```
客户端 POST /generate
  → 检查免费次数/积分余额
  → 内容安全审核（OpenAI Moderation API）
  → 扣除积分（FOR UPDATE 锁）
  → 创建 GenerationTask（status=pending）
  → 派发 Celery 任务
  → 返回 202 Accepted + task_id

Celery Worker（异步）
  → 下载原图
  → 构建 GPT-4o 提示词
  → 调用 GPT-4o 图片编辑 API
  → 上传结果到 S3
  → 更新 task.status = done

客户端 GET /generate/{task_id}（每2-3秒轮询）
  → 直到 status = done/failed/cancelled
```

### 5.5 积分模块 `/credits`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/credits/balance` | 查询积分余额和今日免费次数 |
| GET | `/credits/transactions` | 积分流水分页列表 |
| POST | `/credits/checkin` | 每日签到（+2积分，幂等） |
| POST | `/credits/ad-reward` | 广告奖励（+3积分/次，5次/天上限） |

### 5.6 支付模块 `/payments`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/payments/checkout` | 创建 Stripe Checkout Session |
| POST | `/payments/iap/verify` | 验证 Apple/Google IAP 收据 |
| POST | `/payments/webhook/stripe` | Stripe Webhook 回调（不需 JWT） |
| GET | `/payments/history` | 查询购买历史 |

### 5.7 历史记录模块 `/history`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/history` | 分页获取历史记录列表 |
| DELETE | `/history/{id}` | 删除单条历史（含 S3 文件） |

---

## 六、积分系统设计

### 6.1 积分消耗规则

| 质量等级 | 积分消耗 | 输出规格 | 说明 |
|----------|----------|----------|------|
| Low | 0（免费配额）/ 5积分 | 512×512 | 每日免费3次，超出扣积分，有水印 |
| Medium | 15 积分 | 1024×1024 | 标准质量 |
| High | 25 积分 | 1024×1024 HD | 最高质量 |

### 6.2 积分获取渠道

| 渠道 | 积分数 | 限制 |
|------|--------|------|
| 首次注册 | +10 | 一次性 |
| 每日签到 | +2 | 1次/天 |
| 看激励广告 | +3 | 5次/天（+15/天上限） |
| 邀请好友 | +20 | 邀请方，被邀请方各得 |
| 购买套餐 | 见下表 | - |

### 6.3 积分套餐

| 套餐 | 价格 | 积分 | 单价 |
|------|------|------|------|
| Starter | $0.99 | 100 | $0.0099/积分 |
| Basic | $2.99 | 320 | $0.0093/积分 |
| Pro | $6.99 | 800 | $0.0087/积分 |
| Premium | $14.99 | 1800 | $0.0083/积分 |

### 6.4 免费配额优先逻辑

```python
# Low 质量：优先消耗免费次数，不足则消耗积分
if quality == "low":
    if daily_free_remaining > 0:
        use_free_quota()  # 不扣积分，记录到 DailyFreeUsage
    else:
        deduct_credits(5)

# Medium/High：始终消耗积分
else:
    deduct_credits(credits_cost)
```

---

## 七、认证系统设计

### 7.1 JWT Token 策略

| Token | 有效期 | 存储位置 |
|-------|--------|----------|
| Access Token | 24小时 | 客户端内存 |
| Refresh Token | 30天（滚动刷新） | 数据库（SHA-256哈希存储） |

**滚动刷新**：每次使用 Refresh Token 获取新 Access Token 时，同时签发新的 Refresh Token，旧 Token 立即吊销（`is_revoked=True`），实现"活跃用户永不过期"效果。

### 7.2 Google OAuth 流程

```
客户端 → Google 获取 ID Token
      → POST /auth/google {"id_token": "..."}
      → 服务端调用 google-auth 库验证 ID Token
      → 提取 email/sub 字段
      → 查找或创建用户（upsert）
      → 返回 JWT 对
```

### 7.3 密码安全

- 使用 **bcrypt** 哈希存储密码（cost factor 12）
- Refresh Token 以 **SHA-256** 哈希存储数据库，明文仅返回给客户端一次

---

## 八、异步任务架构

### 8.1 Celery 配置

```
Broker:  Redis DB 1
Backend: Redis DB 2

队列划分：
- generation: AI 图片生成（高优先级，慢）
- ocr:        OCR 识别（中优先级，快）
- cleanup:    定时清理（低优先级）
```

### 8.2 生成任务生命周期

```
pending → processing → done
                    ↘ failed（最多重试2次，失败后退款）
       ↘ cancelled（仅 pending 状态可取消，退还积分）
```

### 8.3 定时任务（Celery Beat）

| 任务 | 执行频率 | 说明 |
|------|----------|------|
| cleanup_expired_images | 每日 | 删除 90 天以上的图片（S3 + DB） |
| gdpr_data_cleanup | 每日 | 注销 30 天后永久删除个人数据 |

---

## 九、速率限制

基于 **Redis Sorted Set 滑动窗口**算法实现：

| 端点 | 限制 | 时间窗口 |
|------|------|----------|
| /auth/register | 5次 | 1分钟 |
| /auth/login | 10次 | 1分钟 |
| /generate | 20次 | 1分钟 |
| /ocr | 30次 | 1分钟 |
| 其他 | 60次 | 1分钟 |

- 已认证用户按 `user_id` 限流
- 未认证请求按 `client_ip` 限流
- 超限返回 `429 Too Many Requests`

---

## 十、内容安全审核

在 AI 生成前调用 **OpenAI Moderation API** 对用户编辑内容审核：

```python
await openai_client.moderate_content(new_text)
# 如果违规 → 抛出 ContentModerationError → 返回 400
# 审核服务不可用 → 降级处理（不阻断，记录日志）
```

---

## 十一、错误响应规范

所有错误均返回统一 JSON 格式：

```json
{
  "code": "INSUFFICIENT_CREDITS",
  "message": "Insufficient credits balance",
  "detail": null
}
```

| HTTP 状态码 | code | 场景 |
|------------|------|------|
| 401 | UNAUTHORIZED | Token 无效或过期 |
| 403 | FORBIDDEN | 无权限操作他人数据 |
| 404 | NOT_FOUND | 资源不存在 |
| 402 | INSUFFICIENT_CREDITS | 积分不足 |
| 422 | VALIDATION_ERROR | 请求参数校验失败 |
| 429 | RATE_LIMIT_EXCEEDED | 超过频率限制 |
| 429 | DAILY_LIMIT_EXCEEDED | 超过每日免费次数 |
| 400 | CONTENT_MODERATION | 内容安全审核不通过 |
| 503 | EXTERNAL_SERVICE_ERROR | 第三方 API 不可用 |
| 500 | INTERNAL_SERVER_ERROR | 内部服务器错误 |

---

## 十二、图片存储策略

### 存储结构
```
S3/R2 Bucket: textlens-images/
├── uploads/        # 用户上传原图（OCR 输入）
│   └── {uuid}.jpg
└── results/        # AI 生成结果图
    └── {uuid}.png
```

### 生命周期策略
- **保留期**：90天（通过 Celery Beat 每日清理）
- **删除顺序**：先删 S3 文件 → 再删数据库记录
- **S3 删除失败**：不阻断数据库删除（记录警告日志）

---

## 十三、合规性设计

### GDPR 合规
- 注销账户时仅软删除（`deleted_at` 字段）
- 30 天后 Celery Beat 定时任务永久删除全部个人数据
- 支持数据导出（TODO：导出接口）

### COPPA 合规
- 注册时要求 `age_verified: true`（13岁以上）
- 后端强制校验字段，不满足则拒绝注册

---

## 十四、部署方案

### Docker Compose 服务

| 服务 | 镜像 | 说明 |
|------|------|------|
| api | 自建 Dockerfile | FastAPI + uvicorn，4 workers |
| celery_worker | 自建 Dockerfile.celery | 处理 generation/ocr/cleanup 队列 |
| celery_beat | 自建 Dockerfile.celery | 定时任务调度器 |
| postgres | postgres:15-alpine | 主数据库 |
| redis | redis:7-alpine | 消息队列 + 缓存 |
| flower | 自建 | Celery 任务监控界面（端口5555） |

### 生产推荐
- API 服务：AWS ECS / Fly.io / Railway
- 数据库：AWS RDS PostgreSQL / Supabase
- Redis：AWS ElastiCache / Upstash
- Celery Worker：独立 ECS Task（可按需弹性扩容）
- 图片存储：Cloudflare R2（出流量免费）

### 数据库迁移命令

```bash
# 生成迁移脚本
alembic revision --autogenerate -m "description"

# 应用迁移
alembic upgrade head

# 回滚
alembic downgrade -1
```

---

## 十五、环境变量清单

| 变量 | 必填 | 说明 |
|------|------|------|
| DATABASE_URL | ✅ | PostgreSQL 连接字符串 |
| REDIS_URL | ✅ | Redis 连接 URL |
| JWT_SECRET_KEY | ✅ | JWT 签名密钥（256位随机字符串） |
| GOOGLE_CLIENT_ID | ✅ | Google OAuth 客户端 ID |
| GOOGLE_VISION_API_KEY | ✅ | Google Vision API Key |
| OPENAI_API_KEY | ✅ | OpenAI API Key |
| STRIPE_SECRET_KEY | ✅ | Stripe 服务端密钥 |
| STRIPE_WEBHOOK_SECRET | ✅ | Stripe Webhook 签名密钥 |
| S3_ACCESS_KEY | ✅ | S3/R2 Access Key |
| S3_SECRET_KEY | ✅ | S3/R2 Secret Key |
| S3_BUCKET_NAME | ✅ | 存储桶名称 |
| APPLE_IAP_SECRET | ⚠️ | Apple IAP 共享密钥（iOS内购必填） |
| SENTRY_DSN | ❌ | 异常监控（可选） |

---

## 十六、开发快速启动

```bash
# 1. 克隆项目并进入目录
cd textlens-backend

# 2. 创建虚拟环境并安装依赖
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填写真实配置

# 4. 启动基础服务（PostgreSQL + Redis）
docker-compose up postgres redis -d

# 5. 执行数据库迁移
alembic upgrade head

# 6. 启动 API 服务
uvicorn app.main:app --reload --port 8000

# 7. 另开终端启动 Celery Worker
celery -A app.tasks.celery_app worker --loglevel=info -Q generation,ocr,cleanup

# 8. 访问 API 文档
open http://localhost:8000/docs
```

---

*文档由 Claude Code 基于 TextLens PRD 自动生成 · 2026-04-10*
