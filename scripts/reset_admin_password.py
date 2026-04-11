#!/usr/bin/env python3
"""
重置管理员密码脚本

用法:
    python3 scripts/reset_admin_password.py
"""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt


def reset_admin_password():
    """
    重置管理员密码
    """
    from sqlalchemy import text
    from app.db.session import engine

    # 生成新的密码哈希
    new_hash = bcrypt.hashpw(b'huqinzhi', bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    with engine.connect() as conn:
        # 更新管理员密码
        result = conn.execute(
            text(f"UPDATE users SET password_hash = '{new_hash}', updated_at = '{now}' WHERE email = 'admin@gmail.com'")
        )
        conn.commit()

        if result.rowcount > 0:
            print('=' * 50)
            print('管理员密码已重置！')
            print('=' * 50)
            print(f'邮箱: admin@gmail.com')
            print(f'密码: huqinzhi')
            print('=' * 50)
        else:
            print('未找到管理员账户')


if __name__ == '__main__':
    reset_admin_password()
