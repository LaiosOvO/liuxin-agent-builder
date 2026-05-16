"""LangGraph AsyncPostgresSaver 工厂模块。

提供：
- get_checkpointer()：异步 context manager，提供 AsyncPostgresSaver 实例
- ensure_checkpoint_tables()：幂等创建 LangGraph checkpoint 表（启动时调用）
- build_thread_id()：构造含 workspace 前缀的 thread_id（防 Pitfall 13 跨租户碰撞）
- parse_thread_id()：解析 thread_id 为 (workspace_id, instance_id)

架构决策：
- checkpoint 使用 psycopg3 驱动（langgraph-checkpoint-postgres 3.1 要求）
- SQLAlchemy ORM 层使用 asyncpg（两个驱动共存，连接池独立）
- POSTGRES_CHECKPOINT_DSN（psycopg3 格式）与 POSTGRES_DSN（asyncpg 格式）分开配置
- thread_id 含 workspace_id 前缀，保证多租户 checkpoint 不碰撞（PITFALLS Pitfall 13）
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def _get_postgres_checkpoint_dsn() -> str:
    """获取 psycopg3 格式的 Postgres DSN（用于 LangGraph checkpoint）。

    优先读 POSTGRES_CHECKPOINT_DSN 环境变量（推荐），
    fallback 到从 POSTGRES_DSN 转换（去掉 +asyncpg 或 +psycopg 驱动前缀）。

    psycopg3 格式：postgresql://user:pass@host:port/db（不带驱动前缀）
    asyncpg 格式：postgresql+asyncpg://user:pass@host:port/db
    """
    if dsn := os.getenv("POSTGRES_CHECKPOINT_DSN"):
        # 如果错误地带了驱动前缀，去掉
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
        dsn = dsn.replace("postgresql+psycopg3://", "postgresql://")
        return dsn

    # fallback: 从 POSTGRES_DSN 转换
    if dsn := os.getenv("POSTGRES_DSN"):
        # asyncpg 格式 → psycopg3 格式
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
        return dsn

    # 硬编码 fallback（本地开发默认）
    return "postgresql://agent_builder:AfOrHwRgDZRcPUmUSRNt7czeCGt7@localhost:15432/agent_builder"


@asynccontextmanager
async def get_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """异步 context manager，提供 AsyncPostgresSaver 实例。

    使用方式：
        async with get_checkpointer() as checkpointer:
            app = graph.compile(checkpointer=checkpointer)
            result = await app.ainvoke(input, config)

    每次调用创建新连接，退出时自动释放。生产环境建议在 lifespan 中缓存单例。
    """
    dsn = _get_postgres_checkpoint_dsn()
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        yield saver


async def ensure_checkpoint_tables() -> None:
    """启动时调用一次，幂等创建 LangGraph checkpoint 所需的 3 张表。

    创建的表（由 langgraph-checkpoint-postgres 3.1 管理，不走 Alembic）：
    - checkpoints：完整状态快照（thread_id + checkpoint_id 为 PK）
    - checkpoint_blobs：大 blob 分离存储（3.1 新增）
    - checkpoint_writes：节点 pending writes（中间状态）
    - checkpoint_migrations：迁移版本追踪

    幂等性：使用 IF NOT EXISTS，重复调用安全。
    """
    dsn = _get_postgres_checkpoint_dsn()
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()


def build_thread_id(workspace_id: UUID, instance_id: UUID) -> str:
    """构造含 workspace 前缀的 thread_id。

    格式：'{workspace_id}:{instance_id}'

    防护：PITFALLS Pitfall 13 — thread_id 不带 workspace 前缀时，
    不同租户的实例在 checkpoint 表中无法区分，日志排查困难。

    Args:
        workspace_id: 工作区 UUID
        instance_id: 流程实例 UUID

    Returns:
        格式为 '<workspace_id>:<instance_id>' 的字符串
    """
    return f"{workspace_id}:{instance_id}"


def parse_thread_id(thread_id: str) -> tuple[UUID, UUID]:
    """解析 thread_id，返回 (workspace_id, instance_id)。

    Args:
        thread_id: build_thread_id 返回的字符串

    Returns:
        (workspace_id, instance_id) 元组

    Raises:
        ValueError: thread_id 格式不正确（不含 ':'，或 UUID 格式错误）
    """
    if ":" not in thread_id:
        raise ValueError(
            f"thread_id 格式错误（期望 '<workspace_id>:<instance_id>'）：{thread_id!r}"
        )
    ws_str, inst_str = thread_id.split(":", 1)
    return UUID(ws_str), UUID(inst_str)
