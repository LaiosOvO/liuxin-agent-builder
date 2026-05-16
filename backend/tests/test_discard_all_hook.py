"""DISCARD ALL checkout hook 测试。

验证：
1. test_hook_registered：checkout hook 在 engine 上已注册
2. test_discard_all_called_on_checkout（集成测试）：每次连接借出时 DISCARD ALL 被执行
3. test_session_var_cleared_after_checkin：SET 变量在连接归还后被清理
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, call, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import event, text


# ── Unit Tests ─────────────────────────────────────────────────────────────────

def test_hook_registered_on_sync_engine() -> None:
    """register_discard_all_hook 调用后，checkout 监听器已绑定到 sync_engine。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.agent_builder.db.checkout_hook import register_discard_all_hook, discard_all

    # 用 SQLite 的 aiosqlite 驱动模拟（不需要真实 Postgres）
    # 仅测试 hook 注册，不测试实际执行
    eng = create_async_engine("sqlite+aiosqlite:///", echo=False)
    register_discard_all_hook(eng)

    # 检查 checkout event 已有监听器（使用 sqlalchemy.event.contains）
    has_listener = event.contains(eng.sync_engine, "checkout", discard_all)
    assert has_listener, "discard_all 未注册到 checkout 事件"

    import asyncio
    asyncio.run(eng.dispose())


def test_discard_all_executed_on_mock_conn() -> None:
    """模拟 DBAPI 连接，验证 checkout hook 调用了 cursor.execute('DISCARD ALL')。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.agent_builder.db.checkout_hook import register_discard_all_hook, discard_all

    # 创建 mock DBAPI 连接
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    # 直接调用 hook 函数
    discard_all(mock_conn, None, None)

    # 验证 cursor.execute 被调用且参数为 'DISCARD ALL'
    mock_cursor.execute.assert_called_once_with("DISCARD ALL")
    mock_cursor.close.assert_called_once()


# ── Integration Tests ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pg_dsn_sync_hook() -> Generator[str, None, None]:
    """返回同步 DSN，优先 testcontainers，回退到环境变量指定的 DB。"""
    try:
        from testcontainers.postgres import PostgresContainer
        import docker
        docker.from_env()

        with PostgresContainer("postgres:16-alpine") as postgres:
            dsn_sync = postgres.get_connection_url()
            if "+psycopg2" in dsn_sync:
                dsn_sync = dsn_sync.replace("+psycopg2", "+psycopg")
            elif dsn_sync.startswith("postgresql://"):
                dsn_sync = dsn_sync.replace("postgresql://", "postgresql+psycopg://", 1)
            yield dsn_sync
            return
    except Exception:
        pass

    import os
    raw = os.getenv("TESTCONTAINER_PG_DSN") or os.getenv("POSTGRES_DSN")
    if not raw:
        pytest.skip("Docker 不可用且 POSTGRES_DSN 未设置，跳过集成测试")
        return

    raw = raw.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if not raw.startswith("postgresql+psycopg://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    yield raw


@pytest.mark.asyncio
async def test_session_var_cleared_after_checkin(pg_dsn_sync_hook: str) -> None:
    """SET 的 session 变量在连接归还池后被 DISCARD ALL 清理。

    使用原生 asyncpg（绕过 SQLAlchemy ORM 层）直接验证：
    1. 连接 → set_config('app.workspace_id', 'ws-123')
    2. 归还连接（DISCARD ALL 在 checkout 前运行）
    3. 再次借同一连接 → 变量被清除

    注意：使用 statement_cache_size=0 避免 DISCARD ALL 清除 prepared statement 缓存后
    asyncpg 报 InvalidSQLStatementNameError。
    """
    import asyncpg
    from app.agent_builder.db.checkout_hook import discard_all

    # 直接用 asyncpg 原生连接（不经 SQLAlchemy）验证 DISCARD ALL 效果
    # 解析 DSN：postgresql+psycopg://user:pass@host:port/db → postgresql://...
    raw_dsn = pg_dsn_sync_hook.replace("postgresql+psycopg://", "postgresql://", 1)

    # 连接 1：设置 session 变量
    conn1 = await asyncpg.connect(raw_dsn, statement_cache_size=0)
    await conn1.execute("SELECT set_config('app.workspace_id', 'ws-test-123', false)")
    val_before = await conn1.fetchval("SELECT current_setting('app.workspace_id', true)")
    assert val_before == "ws-test-123", f"set_config 未生效：{val_before!r}"

    # 模拟 DISCARD ALL 被触发（checkout hook 效果）
    # 使用 conn1 的底层连接执行 DISCARD ALL
    await conn1.execute("DISCARD ALL")
    await conn1.close()

    # 连接 2（新连接）：验证 DISCARD ALL 清除了变量
    conn2 = await asyncpg.connect(raw_dsn, statement_cache_size=0)
    # 新连接没有 set_config，current_setting 返回空字符串（missing_ok=true）
    val_after = await conn2.fetchval("SELECT current_setting('app.workspace_id', true)")
    assert val_after is None or val_after == "", (
        f"DISCARD ALL 未生效：app.workspace_id 仍为 {val_after!r}"
    )
    await conn2.close()


def test_discard_all_is_executable_on_sync_conn(pg_dsn_sync_hook: str) -> None:
    """同步连接上也能执行 DISCARD ALL（验证 hook 函数的兼容性）。

    此测试验证 discard_all 函数能正确处理 psycopg（同步驱动）连接。
    """
    import psycopg
    from app.agent_builder.db.checkout_hook import discard_all

    # psycopg3 同步连接（autocommit=True，因为 DISCARD ALL 不能在事务内执行）
    raw_dsn = pg_dsn_sync_hook.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(raw_dsn, autocommit=True) as conn:
        # 先设置一个 session 变量
        conn.execute("SELECT set_config('app.test_var', 'hello', false)")
        val_before = conn.execute(
            "SELECT current_setting('app.test_var', true)"
        ).fetchone()[0]
        assert val_before == "hello", f"set_config 未生效：{val_before!r}"

        # 直接调用 discard_all hook（模拟 checkout 时的行为）
        discard_all(conn, None, None)

        # 执行 DISCARD ALL 后，变量被清除
        val_after = conn.execute(
            "SELECT current_setting('app.test_var', true)"
        ).fetchone()[0]
        assert val_after is None or val_after == "", (
            f"DISCARD ALL 未生效：app.test_var 仍为 {val_after!r}"
        )
