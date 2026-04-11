#!/bin/bash
# ============================================================================
# TextLens 后端一键部署脚本
# 适用于: Debian 12 Bookworm
# 域名: https://hqzservice.top/
# ============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 日志函数
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

PROJECT_DIR="/home/huqinzhi/projects/textlens-backend"

# ==============================================================================
# 函数定义
# ==============================================================================

# 配置环境变量函数
configure_env() {
    log_info "请提供以下配置信息（或直接回车跳过）..."

    echo ""
    echo "请输入 PostgreSQL 密码 (数据库用户: textlens_user):"
    read -r -s DB_PASSWORD
    echo ""

    echo "请输入 JWT 密钥 (直接回车自动生成):"
    read -r JWT_SECRET
    if [ -z "$JWT_SECRET" ]; then
        JWT_SECRET=$(openssl rand -base64 32)
    fi

    echo "OpenAI API Key (sk-...): 直接回车跳过"
    read -r OPENAI_API_KEY

    echo "Stability AI API Key (sk-...): 直接回车跳过"
    read -r STABILITY_API_KEY

    echo "Stripe Secret Key (sk_test_...): 直接回车跳过"
    read -r STRIPE_SECRET_KEY

    # 创建 .env 文件
    cat > "$ENV_FILE" << EOF
# 应用配置
APP_ENV=production
APP_DEBUG=false
APP_NAME=TextLens API
APP_VERSION=1.0.0
APP_BASE_URL=https://hqzservice.top

# 数据库
DATABASE_URL=postgresql://textlens_user:${DB_PASSWORD}@db:5432/textlens

# Redis
REDIS_URL=redis://redis:6379/0
REDIS_CACHE_URL=redis://redis:6379/1
REDIS_BROKER_URL=redis://redis:6379/2
REDIS_RESULT_BACKEND=redis://redis:6379/3

# JWT
JWT_SECRET_KEY=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
JWT_REFRESH_EXPIRATION_DAYS=30

# OCR 配置 (使用 OCR.space 免费 API)
OCR_SPACE_API_KEY=K85802480388957
OCR_PROVIDER=ocr_space

# OpenAI (用于内容审核) - 可留空
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENAI_MODEL=gpt-4o

# Stability AI (用于图片生成) - 可留空
STABILITY_API_KEY=${STABILITY_API_KEY}
STABILITY_ENGINE_ID=stable-diffusion-xl-1024-v1-0
IMAGE_GENERATION_PROVIDER=stability

# Stripe - 可留空
STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
STRIPE_WEBHOOK_SECRET=

# S3/R2 存储
USE_R2=false
S3_BUCKET_NAME=textlens-images
S3_REGION=us-east-1

# 积分配置
FREE_DAILY_LIMIT=3
CREDITS_INITIAL_BONUS=10
CREDITS_DAILY_CHECKIN=2
CREDITS_AD_REWARD=3
CREDITS_INVITE_REWARD=20

# CORS
CORS_ORIGINS=["https://hqzservice.top","https://www.hqzservice.top"]
EOF

    log_info ".env 文件已创建"
    log_warn "注意: OpenAI/Stability AI API Key 如留空，请在 .env 文件中后续补充"
}

# ==============================================================================
# 主流程
# ==============================================================================

echo "=========================================="
echo "  TextLens 后端一键部署脚本"
echo "=========================================="

# -----------------------------------------------------------------------------
# 步骤 1: 检查并安装 Docker
# -----------------------------------------------------------------------------
log_info "步骤 1: 检查并安装 Docker..."

if command -v docker &> /dev/null; then
    log_info "Docker 已安装: $(docker --version)"
else
    log_warn "Docker 未安装，开始安装..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg lsb-release

    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    sudo usermod -aG docker $USER
    log_warn "Docker 已安装，请重新登录或运行: newgrp docker"
fi

sudo systemctl start docker 2>/dev/null || true
sudo systemctl enable docker 2>/dev/null || true

# -----------------------------------------------------------------------------
# 步骤 2: 准备项目目录
# -----------------------------------------------------------------------------
log_info "步骤 2: 准备项目目录..."

if [ -d "$PROJECT_DIR" ]; then
    log_warn "项目目录已存在，是否更新代码? (y/n)"
    read -r response
    if [ "$response" = "y" ]; then
        cd "$PROJECT_DIR"
        git pull origin main
        log_info "代码已更新"
    fi
else
    log_info "创建项目目录并克隆代码..."
    sudo mkdir -p "$(dirname "$PROJECT_DIR")"
    sudo chown -R $(whoami):$(id -gn) "$(dirname "$PROJECT_DIR")"
    git clone https://github.com/huqinzhi/textlens-backend.git "$PROJECT_DIR"
    cd "$PROJECT_DIR"
    log_info "代码已克隆到 $PROJECT_DIR"
fi

# -----------------------------------------------------------------------------
# 步骤 3: 配置环境变量
# -----------------------------------------------------------------------------
log_info "步骤 3: 配置环境变量..."

ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    log_warn ".env 文件已存在，是否重新配置? (y/n)"
    read -r response
    if [ "$response" != "y" ]; then
        log_info "跳过环境变量配置"
    else
        configure_env
    fi
else
    configure_env
fi

# -----------------------------------------------------------------------------
# 步骤 4: 配置 Nginx
# -----------------------------------------------------------------------------
log_info "步骤 4: 配置 Nginx 反向代理..."

NGINX_CONF="/etc/nginx/sites-available/hqzservice.top"

sudo tee "$NGINX_CONF" > /dev/null << 'EOF'
server {
    server_name hqzservice.top www.hqzservice.top;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /api/docs {
        proxy_pass http://127.0.0.1:8000/api/docs;
        proxy_set_header Host $host;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/hqzservice.top/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hqzservice.top/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    if ($host = www.hqzservice.top) {
        return 301 https://$host$request_uri;
    }
    if ($host = hqzservice.top) {
        return 301 https://$host$request_uri;
    }
    listen 80;
    server_name hqzservice.top www.hqzservice.top;
    return 404;
}
EOF

sudo nginx -t && sudo systemctl reload nginx
log_info "Nginx 配置已更新"

# -----------------------------------------------------------------------------
# 步骤 5: 启动 Docker 服务
# -----------------------------------------------------------------------------
log_info "步骤 5: 启动 Docker 服务..."

cd "$PROJECT_DIR"
mkdir -p data/postgres data/redis
sudo docker-compose up -d --build
log_info "Docker 服务已启动"

# -----------------------------------------------------------------------------
# 步骤 6: 等待服务就绪
# -----------------------------------------------------------------------------
log_info "步骤 6: 等待服务就绪..."

log_info "等待 PostgreSQL..."
for i in {1..30}; do
    if sudo docker-compose exec -T db pg_isready -U textlens_user -d textlens &>/dev/null; then
        log_info "PostgreSQL 已就绪"
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

log_info "等待 Redis..."
for i in {1..15}; do
    if sudo docker-compose exec -T redis redis-cli ping &>/dev/null; then
        log_info "Redis 已就绪"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

# -----------------------------------------------------------------------------
# 步骤 7: 执行数据库迁移
# -----------------------------------------------------------------------------
log_info "步骤 7: 执行数据库迁移..."

sudo docker-compose exec -T api alembic upgrade head
log_info "数据库迁移完成"

# -----------------------------------------------------------------------------
# 步骤 8: 检查服务状态
# -----------------------------------------------------------------------------
log_info "步骤 8: 检查服务状态..."

sudo docker-compose ps
log_info "最近 API 日志:"
sudo docker-compose logs --tail=10 api

# -----------------------------------------------------------------------------
# 完成
# -----------------------------------------------------------------------------
echo ""
echo "=========================================="
log_info "部署完成!"
echo "=========================================="
echo ""
echo "API 地址: https://hqzservice.top"
echo "API 文档: https://hqzservice.top/api/docs"
echo ""
echo "后续配置（如需补充 API Key）:"
echo "  nano $PROJECT_DIR/.env"
echo "  sudo docker-compose restart"
echo ""
