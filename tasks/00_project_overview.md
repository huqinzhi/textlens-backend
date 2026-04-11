# TextLens Backend 开发任务总览

本文档列出 TextLens Backend 项目的所有开发任务及其依赖关系。

## 任务列表

| 序号 | 任务名称 | 描述 | 前置依赖 |
|------|----------|------|----------|
| 01 | [项目基础架构搭建](./01_project_scaffold.md) | FastAPI 应用工厂、中间件、配置 | 无 |
| 02 | [数据库模型设计](./02_database_models.md) | User、Credit、Image、Payment 模型 | 01 |
| 03 | [数据库迁移脚本](./03_database_migrations.md) | Alembic 迁移配置 | 02 |
| 04 | [认证系统实现](./04_auth_system.md) | JWT + OAuth 登录注册 | 01, 02 |
| 05 | [用户模块实现](./05_user_module.md) | 个人信息查询更新 | 04 |
| 06 | [OCR 模块实现](./06_ocr_module.md) | 图片上传和 Google Vision OCR | 01, 02, 04 |
| 07 | [AI 生成模块实现](./07_ai_generation_module.md) | OpenAI GPT-4o 图片编辑 | 06 |
| 08 | [积分系统实现](./08_credits_system.md) | 余额、流水、签到、广告奖励 | 04 |
| 09 | [支付系统实现](./09_payments_system.md) | Stripe、IAP、Webhook | 04 |
| 10 | [历史记录模块实现](./10_history_module.md) | 历史查询和删除 | 06, 07 |
| 11 | [Celery 异步任务系统](./11_celery_tasks.md) | 队列配置、定时任务 | 02, 06, 07 |
| 12 | [中间件系统实现](./12_middleware.md) | 错误处理、日志、限流 | 01 |
| 13 | [外部服务集成](./13_external_services.md) | Google Vision、OpenAI、S3、Stripe | 01 |
| 14 | [Docker 部署配置](./14_docker_deployment.md) | Dockerfile、docker-compose | 所有任务 |

## 开发顺序建议

### 阶段一：基础架构（可并行开发）
- Task 01: 项目基础架构搭建
- Task 02: 数据库模型设计
- Task 03: 数据库迁移脚本

### 阶段二：认证与用户
- Task 04: 认证系统实现
- Task 05: 用户模块实现

### 阶段三：核心功能
- Task 06: OCR 模块实现
- Task 07: AI 生成模块实现
- Task 08: 积分系统实现
- Task 09: 支付系统实现
- Task 10: 历史记录模块实现

### 阶段四：基础设施
- Task 11: Celery 异步任务系统
- Task 12: 中间件系统实现
- Task 13: 外部服务集成

### 阶段五：部署
- Task 14: Docker 部署配置

## 技术栈

- **框架**: FastAPI (Python 3.12)
- **数据库**: PostgreSQL + SQLAlchemy + Alembic
- **缓存/队列**: Redis + Celery
- **存储**: AWS S3 / Cloudflare R2
- **外部 API**: Google Cloud Vision, OpenAI, Stripe

## 项目结构

```
textlens-backend/
├── app/
│   ├── main.py              # FastAPI 应用工厂
│   ├── config.py            # Pydantic Settings
│   ├── dependencies.py      # 依赖注入
│   ├── core/                # 核心模块
│   │   ├── security.py      # JWT、密码
│   │   ├── exceptions.py    # 自定义异常
│   │   └── constants.py     # 常量
│   ├── db/                  # 数据库
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   ├── features/            # 功能模块
│   │   ├── auth/
│   │   ├── users/
│   │   ├── credits/
│   │   ├── ocr/
│   │   ├── generation/
│   │   ├── payments/
│   │   └── history/
│   ├── middleware/          # 中间件
│   ├── external/            # 外部服务客户端
│   └── tasks/               # Celery 任务
├── migrations/              # Alembic 迁移
├── docker/                  # Docker 配置
└── tasks/                   # 开发任务文档
```
