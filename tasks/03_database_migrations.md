# Task 03: 数据库迁移脚本

## 任务描述

使用 Alembic 创建数据库迁移脚本，生成所有表结构。配置迁移环境以支持 PostgreSQL。

## 涉及文件

- `migrations/env.py` - Alembic 迁移环境配置
- `migrations/script.py.mako` - 迁移模板
- `alembic.ini` - Alembic 配置文件
- `migrations/versions/` - 迁移版本文件目录

## 详细任务

### 3.1 配置 alembic.ini

```ini
# alembic.ini
[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = ${DATABASE_URL}

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### 3.2 配置 migrations/env.py

```python
# migrations/env.py
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Add app to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.db.base import Base
from app.db.models.user import User, RefreshToken
from app.db.models.credit import CreditAccount, CreditTransaction, DailyFreeUsage
from app.db.models.image import Image, OCRResult, GenerationTask
from app.db.models.payment import PurchaseRecord

config = context.config
settings = Settings()

# Set sqlalchemy.url from settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### 3.3 创建 migrations/script.py.mako

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

### 3.4 生成初始迁移

```bash
# 在项目根目录执行
alembic revision --autogenerate -m "initial migration"
```

### 3.5 验证迁移

```bash
# 查看所有迁移版本
alembic history --verbose

# 应用迁移
alembic upgrade head

# 回滚测试
alembic downgrade -1
alembic upgrade head
```

## 验收标准

- [ ] `alembic.ini` 配置正确
- [ ] `migrations/env.py` 可正确导入所有模型
- [ ] 运行 `alembic revision --autogenerate` 生成迁移文件
- [ ] `alembic upgrade head` 成功执行
- [ ] 所有表在数据库中正确创建

## 前置依赖

- Task 02: 数据库模型设计

## 后续任务

- Task 04: 认证系统实现 (JWT + OAuth)
