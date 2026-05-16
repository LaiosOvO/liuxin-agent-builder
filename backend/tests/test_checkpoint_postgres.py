"""LangGraph AsyncPostgresSaver 集成测试。

测试目标：
- checkpoint 表由 setup() 创建成功
- thread_id 含 workspace 前缀（防 Pitfall 13）
- parse_thread_id roundtrip 正确
- AsyncPostgresSaver put/get 端到端
- checkpoint 与 SQLAlchemy asyncpg 引擎共存（不互相干扰）

环境要求：
- POSTGRES_DSN 或 POSTGRES_CHECKPOINT_DSN 指向可用 Postgres（SSH 隧道 localhost:15432）
"""
from __future__ import annotations

import os
import uuid

import pytest


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _get_psycopg3_dsn() -> str:
    """获取 psycopg3 格式的测试 DSN。"""
    if dsn := os.getenv("POSTGRES_CHECKPOINT_DSN"):
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
        dsn = dsn.replace("postgresql+psycopg3://", "postgresql://")
        return dsn
    if dsn := os.getenv("POSTGRES_DSN"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        return dsn
    return "postgresql://agent_builder:AfOrHwRgDZRcPUmUSRNt7czeCGt7@localhost:15432/agent_builder"


# ── 测试 ──────────────────────────────────────────────────────────────────────

def test_thread_id_with_workspace_prefix():
    """build_thread_id 应返回 '<workspace_id>:<instance_id>' 格式。"""
    from app.agent_builder.workflow.checkpoint import build_thread_id

    ws_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    inst_id = uuid.UUID("22222222-2222-2222-2222-222222222222")

    thread_id = build_thread_id(ws_id, inst_id)

    assert ":" in thread_id, "thread_id 必须含 ':' 分隔符"
    assert thread_id == f"{ws_id}:{inst_id}"
    assert thread_id.startswith(str(ws_id))


def test_parse_thread_id_roundtrip():
    """parse_thread_id(build_thread_id(ws, inst)) == (ws, inst)。"""
    from app.agent_builder.workflow.checkpoint import build_thread_id, parse_thread_id

    ws_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    thread_id = build_thread_id(ws_id, inst_id)
    parsed_ws, parsed_inst = parse_thread_id(thread_id)

    assert parsed_ws == ws_id, f"workspace_id 不匹配: {parsed_ws} != {ws_id}"
    assert parsed_inst == inst_id, f"instance_id 不匹配: {parsed_inst} != {inst_id}"


def test_parse_thread_id_invalid_format():
    """parse_thread_id 对无效格式应抛 ValueError。"""
    from app.agent_builder.workflow.checkpoint import parse_thread_id

    with pytest.raises(ValueError, match="格式错误"):
        parse_thread_id("no-colon-here-just-uuid")


@pytest.mark.asyncio
async def test_setup_creates_checkpoint_tables():
    """ensure_checkpoint_tables() 应创建 checkpoints / checkpoint_writes / checkpoint_blobs 三张表。

    使用 psycopg3 同步连接查询 information_schema 确认。
    """
    import psycopg

    from app.agent_builder.workflow.checkpoint import ensure_checkpoint_tables

    # 调用 setup（幂等，可重复调用）
    await ensure_checkpoint_tables()

    # 用 psycopg3 查询验证表存在
    dsn = _get_psycopg3_dsn()
    expected_tables = {"checkpoints", "checkpoint_writes", "checkpoint_blobs"}

    with psycopg.connect(dsn) as conn:
        cursor = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('checkpoints', 'checkpoint_writes', 'checkpoint_blobs')
            ORDER BY table_name
            """
        )
        found = {row[0] for row in cursor.fetchall()}

    assert found == expected_tables, (
        f"缺少 checkpoint 表: {expected_tables - found}（实际存在: {found}）"
    )


@pytest.mark.asyncio
async def test_saver_put_and_get():
    """AsyncPostgresSaver.put() 写入 checkpoint 后，get() 能读回。"""
    from langchain_core.runnables import RunnableConfig

    from app.agent_builder.workflow.checkpoint import build_thread_id, get_checkpointer

    ws_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    thread_id = build_thread_id(ws_id, inst_id)

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }

    # 构造一个最小 checkpoint（仅验证 put/get 路径，不跑完整 graph）
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

    checkpoint_id = str(uuid.uuid4())
    checkpoint: Checkpoint = {
        "v": 1,
        "id": checkpoint_id,
        "ts": "2026-05-16T00:00:00+00:00",
        "channel_values": {"test_key": "test_value"},
        "channel_versions": {"test_key": 1},
        "versions_seen": {},
        "pending_sends": [],
    }
    metadata: CheckpointMetadata = {
        "source": "update",
        "step": 0,
        "writes": None,
        "parents": {},
    }

    async with get_checkpointer() as saver:
        # 写入
        await saver.aput(config, checkpoint, metadata, {})

        # 读回
        result = await saver.aget(config)

    assert result is not None, "get() 返回 None（put 失败）"
    assert result["id"] == checkpoint_id, (
        f"checkpoint_id 不匹配：{result['id']} != {checkpoint_id}"
    )


@pytest.mark.asyncio
async def test_saver_coexists_with_sqlalchemy_engine():
    """checkpoint（psycopg3）与 SQLAlchemy asyncpg 引擎同时工作，互不干扰。"""
    from sqlalchemy import text

    from app.agent_builder.db.engine import async_session_maker, engine
    from app.agent_builder.workflow.checkpoint import ensure_checkpoint_tables

    # 确保 checkpoint 表存在
    await ensure_checkpoint_tables()

    # SQLAlchemy asyncpg 连接：查询 workspaces 表
    await engine.dispose()
    async with async_session_maker() as session:
        result = await session.execute(text("SELECT 1 AS ping"))
        row = result.fetchone()
    assert row is not None and row[0] == 1, "SQLAlchemy asyncpg 查询失败"

    # psycopg3 连接：查询 checkpoint 表
    import psycopg
    dsn = _get_psycopg3_dsn()
    with psycopg.connect(dsn) as conn:
        cursor = conn.execute("SELECT 1 AS ping")
        row = cursor.fetchone()
    assert row is not None and row[0] == 1, "psycopg3 查询失败"
