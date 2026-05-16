"""AsyncEngine 单例 + async_session_maker + DISCARD ALL hook 注册。

对外导出：
- engine: AsyncEngine（全局单例）
- async_session_maker: async_sessionmaker，用于创建 AsyncSession

启动时自动注册 DISCARD ALL checkout hook（防 Pitfall 6 PgBouncer 上下文污染）。
"""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.agent_builder.db.checkout_hook import register_discard_all_hook


def _get_postgres_dsn() -> str:
    """构建 PostgreSQL asyncpg DSN。

    优先级：POSTGRES_DSN env > 分段变量拼接。
    """
    if dsn := os.getenv("POSTGRES_DSN"):
        if not dsn.startswith("postgresql+asyncpg://"):
            dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        return dsn

    user = os.getenv("POSTGRES_USER", "agent_builder")
    password = os.getenv("POSTGRES_PASSWORD", "")
    server = os.getenv("POSTGRES_SERVER", "localhost")
    port = os.getenv("POSTGRES_PORT", "15432")
    db = os.getenv("POSTGRES_DB", "agent_builder")
    return f"postgresql+asyncpg://{user}:{password}@{server}:{port}/{db}"


@lru_cache(maxsize=1)
def _create_engine() -> AsyncEngine:
    """创建并缓存 AsyncEngine 单例。

    pool_pre_ping: 连接前 ping，检测断连后自动重新连接。
    pool_recycle: 1800s 回收连接，防止 PostgreSQL idle timeout 断开。
    """
    dsn = _get_postgres_dsn()
    eng = create_async_engine(
        dsn,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=os.getenv("SQLALCHEMY_ECHO", "").lower() in ("1", "true", "yes"),
    )
    # 注册 DISCARD ALL checkout hook（防 Pitfall 6）
    register_discard_all_hook(eng)
    return eng


# ── 模块级单例（可直接 import）─────────────────────────────────────────────────
engine: AsyncEngine = _create_engine()

async_session_maker: async_sessionmaker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)
