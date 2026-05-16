"""Alembic 迁移环境配置（agent-builder 独立迁移，与 flock 原有 alembic 无关）。

运行方式（在 backend/ 目录下）：
    alembic -c migrations/alembic.ini upgrade head
    alembic -c migrations/alembic.ini downgrade base

支持 asyncpg 异步模式（ORM 层）和同步模式（CI 校验）。
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── 路径设置 ──────────────────────────────────────────────────────────────────
# backend/ 目录加入 sys.path，使 app.agent_builder.* 可导入
_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))

# 加载 .env 文件（开发环境；生产环境通过 Docker env 注入）
_env_file = _backend_dir.parent / ".env"
load_dotenv(dotenv_path=_env_file, override=False)

# ── 导入模型 metadata ─────────────────────────────────────────────────────────
# 必须 import 所有模型才能让 autogenerate 发现表定义
from app.agent_builder.db.base import Base  # noqa: E402
from app.agent_builder.models import (  # noqa: E402,F401
    AuditLog,
    EmailVerification,
    Invite,
    Role,
    User,
    UserWorkspaceRole,
    Workspace,
)

# Alembic Config 对象
config = context.config

# 配置 Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标 metadata（用于 autogenerate 比对）
target_metadata = Base.metadata


def get_url() -> str:
    """构建 PostgreSQL 连接 URL（asyncpg 驱动）。

    优先级：POSTGRES_DSN env > 分段变量拼接。
    """
    if dsn := os.getenv("POSTGRES_DSN"):
        # 支持 postgresql://... 和 postgresql+asyncpg://... 两种格式
        if not dsn.startswith("postgresql+asyncpg://"):
            dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        return dsn

    user = os.getenv("POSTGRES_USER", "agent_builder")
    password = os.getenv("POSTGRES_PASSWORD", "")
    server = os.getenv("POSTGRES_SERVER", "localhost")
    port = os.getenv("POSTGRES_PORT", "15432")
    db = os.getenv("POSTGRES_DB", "agent_builder")
    return f"postgresql+asyncpg://{user}:{password}@{server}:{port}/{db}"


def get_sync_url() -> str:
    """同步版 URL（migration online 模式需要同步连接）。"""
    return get_url().replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连接数据库。"""
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在同步连接上执行迁移。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """异步模式：使用 asyncpg 连接，在 run_sync 中执行迁移。"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_sync_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # 使用同步 psycopg 驱动（alembic 在 run_sync 内部执行，不需要 asyncpg）
        url=get_sync_url(),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式（默认）：同步连接执行迁移。"""
    from sqlalchemy import create_engine

    url = get_sync_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
