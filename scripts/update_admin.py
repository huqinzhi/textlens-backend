#!/usr/bin/env python3
"""
更新管理员账户脚本

用法:
    python3 scripts/update_admin.py
"""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt


def hash_password(password: str) -> str:
    """
    对用户密码进行哈希处理

    [password] 明文密码字符串
    返回 哈希后的密码字符串
    """
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def update_admin():
    """
    更新管理员账户为指定邮箱和密码
    """
    from sqlalchemy import text
    from app.db.session import engine

    password_hash = hash_password('huqinzhi')
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    with engine.connect() as conn:
        # 查找现有管理员（按邮箱查找）
        result = conn.execute(
            text("SELECT id FROM users WHERE email = 'admin@gmail.com' AND deleted_at IS NULL LIMIT 1")
        )
        row = result.fetchone()

        if row:
            # 更新现有管理员
            conn.execute(
                text(f"""
                UPDATE users SET
                    password_hash = '{password_hash}',
                    is_admin = true,
                    updated_at = '{now}'
                WHERE id = '{row[0]}'
                """)
            )

            # 更新或创建积分账户
            credit_result = conn.execute(
                text(f"SELECT id FROM credit_accounts WHERE user_id = '{row[0]}'")
            )
            credit_row = credit_result.fetchone()
            if credit_row:
                conn.execute(
                    text(f"""
                    UPDATE credit_accounts SET
                        balance = 99999,
                        total_earned = 99999
                    WHERE user_id = '{row[0]}'
                    """)
                )
            else:
                conn.execute(
                    text(f"""
                    INSERT INTO credit_accounts (user_id, balance, total_earned, total_spent)
                    VALUES ('{row[0]}', 99999, 99999, 0)
                    """)
                )

            conn.commit()
            print('管理员更新成功！')
            print('=' * 50)
            print(f'邮箱: admin@gmail.com')
            print(f'密码: huqinzhi')
            print(f'积分: 99999')
            print('=' * 50)
        else:
            print('未找到管理员账户')


if __name__ == '__main__':
    update_admin()
