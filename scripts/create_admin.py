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
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 重要：先导入所有模型，避免 SQLAlchemy relationship 循环引用问题
from app.db.models.user import User
from app.db.models.credit import CreditAccount
from app.db.models.image import GenerationTask, Image, OCRResult  # noqa
from app.db.models.payment import PurchaseRecord  # noqa
from app.db.session import SessionLocal

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
    # 生成密码哈希
    password_hash = hash_password('123456')

    db = SessionLocal()
    try:
        # 检查是否已存在管理员
        existing = db.query(User).filter(
            User.email == 'admin',
            User.is_admin == True
        ).first()

        if existing:
            print('管理员已存在，跳过创建')
            return existing

        # 创建管理员用户
        admin = User(
            id=uuid.uuid4(),
            email='admin',
            password_hash=password_hash,
            username='admin',
            auth_provider=AuthProvider.EMAIL,
            is_email_verified=True,
            is_active=True,
            is_admin=True,
            age_verified=True,
            privacy_accepted_at=datetime.utcnow(),
            terms_accepted_at=datetime.utcnow()
        )
        db.add(admin)
        db.flush()

        # 创建积分账户
        credit = CreditAccount(
            user_id=admin.id,
            balance=99999,
            total_earned=99999,
            total_spent=0
        )
        db.add(credit)
        db.commit()

        print('=' * 50)
        print('管理员创建成功！')
        print('=' * 50)
        print(f'邮箱: admin')
        print(f'密码: 123456')
        print(f'积分: 99999')
        print('=' * 50)
        return admin

    except Exception as e:
        db.rollback()
        print(f'创建失败: {e}')
        raise
    finally:
        db.close()


if __name__ == '__main__':
    create_admin_user()
