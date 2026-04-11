# Task 14: Docker 部署配置

## 任务描述

完善 Docker 配置文件，包括 API 服务镜像、Celery Worker 镜像、docker-compose 编排。

## 涉及文件

- `docker/Dockerfile` - API 服务镜像
- `docker/Dockerfile.celery` - Celery Worker 镜像
- `docker-compose.yml` - 完整栈编排

## 详细任务

### 14.1 创建 API Dockerfile

```dockerfile
# docker/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建非 root 用户
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 14.2 创建 Celery Dockerfile

```dockerfile
# docker/Dockerfile.celery
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建非 root 用户
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# 启动命令（根据参数决定启动 worker 还是 beat）
CMD ["sh", "-c", "if [ \"$1\" = 'beat' ]; then \
    celery -A app.tasks.celery_app beat --loglevel=info; \
    else \
    celery -A app.tasks.celery_app worker --loglevel=info -Q generation,ocr,cleanup; \
    fi"]
```

### 14.3 完善 docker-compose.yml

```yaml
# docker-compose.yml
version: "3.9"

services:
  # API 服务
  api:
    build:
      context: .
      dockerfile: docker/Dockerfile
    container_name: textlens-api
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://textlens:${POSTGRES_PASSWORD}@postgres:5432/textlens
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
      - GOOGLE_VISION_API_KEY=${GOOGLE_VISION_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
      - STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET}
      - S3_ACCESS_KEY=${S3_ACCESS_KEY}
      - S3_SECRET_KEY=${S3_SECRET_KEY}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME}
      - S3_ENDPOINT_URL=${S3_ENDPOINT_URL:-}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped
    networks:
      - textlens-network

  # Celery Worker
  celery_worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.celery
    container_name: textlens-celery-worker
    command: ["celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info", "-Q", "generation,ocr,cleanup"]
    environment:
      - DATABASE_URL=postgresql://textlens:${POSTGRES_PASSWORD}@postgres:5432/textlens
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - GOOGLE_VISION_API_KEY=${GOOGLE_VISION_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - S3_ACCESS_KEY=${S3_ACCESS_KEY}
      - S3_SECRET_KEY=${S3_SECRET_KEY}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME}
      - S3_ENDPOINT_URL=${S3_ENDPOINT_URL:-}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped
    networks:
      - textlens-network

  # Celery Beat (定时任务调度器)
  celery_beat:
    build:
      context: .
      dockerfile: docker/Dockerfile.celery
    container_name: textlens-celery-beat
    command: ["celery", "-A", "app.tasks.celery_app", "beat", "--loglevel=info"]
    environment:
      - DATABASE_URL=postgresql://textlens:${POSTGRES_PASSWORD}@postgres:5432/textlens
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis
    restart: unless-stopped
    networks:
      - textlens-network

  # Flower (Celery 监控)
  flower:
    build:
      context: .
      dockerfile: docker/Dockerfile.celery
    container_name: textlens-flower
    command: ["celery", "-A", "app.tasks.celery_app", "flower", "--port", "5555"]
    ports:
      - "5555:5555"
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped
    networks:
      - textlens-network

  # PostgreSQL 数据库
  postgres:
    image: postgres:15-alpine
    container_name: textlens-postgres
    environment:
      - POSTGRES_USER=textlens
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=textlens
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped
    networks:
      - textlens-network

  # Redis
  redis:
    image: redis:7-alpine
    container_name: textlens-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    networks:
      - textlens-network

volumes:
  postgres_data:
  redis_data:

networks:
  textlens-network:
    driver: bridge
```

### 14.4 创建 .env 文件模板

```bash
# .env.example (已存在，补充缺失项)

# Database
DATABASE_URL=postgresql://textlens:your_password_here@localhost:5432/textlens
POSTGRES_PASSWORD=your_secure_password_here

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=your_256bit_random_secret_key_here

# OAuth
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com

# External APIs
GOOGLE_VISION_API_KEY=your_google_vision_api_key
OPENAI_API_KEY=sk-your_openai_api_key

# Stripe
STRIPE_SECRET_KEY=sk_test_your_stripe_secret_key
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret

# S3/R2
S3_ACCESS_KEY=your_access_key
S3_SECRET_KEY=your_secret_key
S3_BUCKET_NAME=textlens-images
S3_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com  # 可选，用于 R2

# Optional
SENTRY_DSN=  # 可选
```

## 验收标准

- [ ] `docker-compose up` 可启动所有服务
- [ ] API 服务正常响应
- [ ] Celery Worker 可处理任务
- [ ] Celery Beat 定时任务正确调度
- [ ] Flower 监控界面可访问 (localhost:5555)

## 前置依赖

- 所有功能模块实现完成

## 后续任务

无（所有任务已完成）
