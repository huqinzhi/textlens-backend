"""
添加邀请码字段

Revision ID: 002
Revises: 001
Create Date: 2026-04-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加 invite_code 列
    op.add_column('users', sa.Column('invite_code', sa.String(20), unique=True, nullable=True))
    op.create_index('ix_users_invite_code', 'users', ['invite_code'])

    # 添加 invited_by 列（外键引用 users.id）
    op.add_column('users', sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index('ix_users_invited_by', 'users', ['invited_by'])


def downgrade() -> None:
    op.drop_index('ix_users_invited_by', table_name='users')
    op.drop_column('users', 'invited_by')
    op.drop_index('ix_users_invite_code', table_name='users')
    op.drop_column('users', 'invite_code')
