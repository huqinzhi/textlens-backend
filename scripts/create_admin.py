#!/usr/bin/env python3
"""
创建管理员账户脚本

用法:
    python3 scripts/create_admin.py

注意事项:
    - 需要先运行: docker compose up -d
    - 脚本会在数据库中创建一个管理员账户
"""
import sys
import os
import uuid
from datetime import datetime, timezone

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt


def hash_password(password: str) -> str:
    """
    对用户密码进行哈希处理

    [password] 明文密码字符串
    返回 哈希后的密码字符串
    """
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def create_admin_user():
    """
    创建管理员账户

    创建一个邮箱为 admin，密码为 123456 的管理员用户，初始积分 99999
    """
    from sqlalchemy import text
    from app.db.session import engine

    password_hash = hash_password('huqinzhi')
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    with engine.connect() as conn:
        # 检查是否已存在管理员
        result = conn.execute(
            text("SELECT id FROM users WHERE email = 'admin' AND is_admin = true AND deleted_at IS NULL")
        )
        if result.fetchone():
            print('管理员已存在，跳过创建')
            return

        # 直接插入用户
        conn.execute(
            text(f"""
            INSERT INTO users (
                id, email, password_hash, username, auth_provider,
                is_email_verified, is_active, is_admin, age_verified,
                privacy_accepted_at, terms_accepted_at, created_at, updated_at
            ) VALUES (
                '{user_id}', 'admin@gmail.com', '{password_hash}', 'admin', 'EMAIL',
                true, true, true, true,
                '{now}', '{now}', '{now}', '{now}'
            )
            """)
        )

        # 插入积分账户
        conn.execute(
            text(f"""
            INSERT INTO credit_accounts (user_id, balance, total_earned, total_spent)
            VALUES ('{user_id}', 99999, 99999, 0)
            """)
        )
        conn.commit()

        print('=' * 50)
        print('管理员创建成功！')
        print('=' * 50)
        print(f'邮箱: admin')
        print(f'密码: 123456')
        print(f'积分: 99999')
        print('=' * 50)


if __name__ == '__main__':
    create_admin_user()
