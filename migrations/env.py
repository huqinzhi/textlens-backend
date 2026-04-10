"""
Alembic 数据库迁移环境配置
配置数据库连接、迁移目标元数据和迁移运行模式
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# 导入所有模型确保迁移时能检测到表结构变更
from app.db.base import Base
import app.db.models.user  # noqa
import app.db.models.credit  # noqa
import app.db.models.image  # noqa
import app.db.models.payment  # noqa
from app.config import settings

# Alembic Config 对象
config = context.config

# 从环境变量读取数据库 URL（覆盖 alembic.ini 中的静态配置）
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据（用于自动生成迁移脚本）
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    以离线模式运行迁移（不需要实际数据库连接）

    在离线模式下生成 SQL 脚本，适用于审查迁移内容。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    以在线模式运行迁移（直接连接数据库执行）

    在线模式直接应用迁移到目标数据库。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
