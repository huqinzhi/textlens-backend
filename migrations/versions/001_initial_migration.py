"""initial migration

Revision ID: 001
Revises:
Create Date: 2026-04-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE authprovider AS ENUM ('email', 'google', 'apple')")
    op.execute("CREATE TYPE transactiontype AS ENUM ('earn', 'spend', 'refund')")
    op.execute("CREATE TYPE transactionsource AS ENUM ('purchase', 'ad', 'daily', 'invite', 'register', 'refund', 'generation')")
    op.execute("CREATE TYPE paymentstatus AS ENUM ('pending', 'success', 'failed', 'refunded')")
    op.execute("CREATE TYPE paymentprovider AS ENUM ('stripe', 'apple_iap', 'google_iap')")
    op.execute("CREATE TYPE imagestatus AS ENUM ('uploaded', 'ocr_processing', 'ocr_done', 'ocr_failed')")
    op.execute("CREATE TYPE generationstatus AS ENUM ('pending', 'processing', 'done', 'failed', 'cancelled')")
    op.execute("CREATE TYPE generationquality AS ENUM ('low', 'medium', 'high')")

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('username', sa.String(100), nullable=True),
        sa.Column('avatar_url', sa.Text(), nullable=True),
        sa.Column('auth_provider', postgresql.ENUM('email', 'google', 'apple', name='authprovider', create_type=False), default='email', nullable=False),
        sa.Column('provider_user_id', sa.String(255), nullable=True),
        sa.Column('is_email_verified', sa.Boolean(), default=False, nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('is_admin', sa.Boolean(), default=False, nullable=False),
        sa.Column('age_verified', sa.Boolean(), default=False, nullable=False),
        sa.Column('privacy_accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_email', 'users', ['email'])

    # Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token_hash', sa.String(255), unique=True, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_revoked', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('client_info', sa.String(500), nullable=True),
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])

    # Create credit_accounts table
    op.create_table(
        'credit_accounts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('balance', sa.Integer(), default=0, nullable=False),
        sa.Column('total_earned', sa.Integer(), default=0, nullable=False),
        sa.Column('total_spent', sa.Integer(), default=0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # Create credit_transactions table
    op.create_table(
        'credit_transactions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('credit_account_id', sa.Integer(), sa.ForeignKey('credit_accounts.id'), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('type', postgresql.ENUM('earn', 'spend', 'refund', name='transactiontype', create_type=False), nullable=False),
        sa.Column('source', postgresql.ENUM('purchase', 'ad', 'daily', 'invite', 'register', 'refund', 'generation', name='transactionsource', create_type=False), nullable=False),
        sa.Column('ref_id', sa.String(100), nullable=True),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_credit_transactions_user_id', 'credit_transactions', ['user_id'])

    # Create daily_free_usage table
    op.create_table(
        'daily_free_usage',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('used_count', sa.Integer(), default=0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # Create images table
    op.create_table(
        'images',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('original_url', sa.String(500), nullable=False),
        sa.Column('thumbnail_url', sa.String(500), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('file_format', sa.String(10), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('status', postgresql.ENUM('uploaded', 'ocr_processing', 'ocr_done', 'ocr_failed', name='imagestatus', create_type=False), default='uploaded', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    # Create ocr_results table
    op.create_table(
        'ocr_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('image_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('images.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('text_blocks', sa.JSON(), nullable=True),
        sa.Column('detected_language', sa.String(10), nullable=True),
        sa.Column('processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # Create generation_tasks table
    op.create_table(
        'generation_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('image_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('images.id', ondelete='SET NULL'), nullable=True),
        sa.Column('original_image_url', sa.String(500), nullable=False),
        sa.Column('result_image_url', sa.String(500), nullable=True),
        sa.Column('ocr_data', sa.JSON(), nullable=True),
        sa.Column('edit_data', sa.JSON(), nullable=True),
        sa.Column('quality', postgresql.ENUM('low', 'medium', 'high', name='generationquality', create_type=False), nullable=False, default='low'),
        sa.Column('status', postgresql.ENUM('pending', 'processing', 'done', 'failed', 'cancelled', name='generationstatus', create_type=False), default='pending', nullable=False),
        sa.Column('credits_cost', sa.Integer(), nullable=False, default=0),
        sa.Column('is_free', sa.Integer(), default=0),
        sa.Column('has_watermark', sa.Integer(), default=0),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('celery_task_id', sa.String(100), nullable=True),
        sa.Column('prompt_used', sa.Text(), nullable=True),
        sa.Column('generation_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_generation_tasks_user_id', 'generation_tasks', ['user_id'])
    op.create_index('ix_generation_tasks_status', 'generation_tasks', ['status'])

    # Create purchase_records table
    op.create_table(
        'purchase_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('package_id', sa.String(50), nullable=False),
        sa.Column('amount_usd', sa.Float(), nullable=False),
        sa.Column('credits_granted', sa.Integer(), nullable=False),
        sa.Column('payment_provider', postgresql.ENUM('stripe', 'apple_iap', 'google_iap', name='paymentprovider', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'success', 'failed', 'refunded', name='paymentstatus', create_type=False), default='pending', nullable=False),
        sa.Column('external_order_id', sa.String(255), nullable=True),
        sa.Column('receipt_data', sa.Text(), nullable=True),
        sa.Column('webhook_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('refunded_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('purchase_records')
    op.drop_table('generation_tasks')
    op.drop_table('ocr_results')
    op.drop_table('images')
    op.drop_table('daily_free_usage')
    op.drop_table('credit_transactions')
    op.drop_table('credit_accounts')
    op.drop_table('refresh_tokens')
    op.drop_table('users')

    op.execute('DROP TYPE IF EXISTS generationquality')
    op.execute('DROP TYPE IF EXISTS generationstatus')
    op.execute('DROP TYPE IF EXISTS imagestatus')
    op.execute('DROP TYPE IF EXISTS paymentprovider')
    op.execute('DROP TYPE IF EXISTS paymentstatus')
    op.execute('DROP TYPE IF EXISTS transactionsource')
    op.execute('DROP TYPE IF EXISTS transactiontype')
    op.execute('DROP TYPE IF EXISTS authprovider')
