"""WorkspaceScopedQuery 多租户隔离集成测试。

使用真实数据库（禁止 mock，CLAUDE.md 2.2）。
优先使用 testcontainers-postgres；若 Docker 不可用，回退到 POSTGRES_DSN 环境变量。

验证：
1. test_ws_a_cannot_see_ws_b：workspace A 的 invite 在 workspace B 上下文中查询返回空集
2. test_missing_ctx_raises：未设置 workspace context 时 select() 抛 RuntimeError
3. test_correct_ctx_returns_data：正确 context 下能查到自己的数据
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _get_sync_dsn_from_env() -> str | None:
    """从环境变量获取同步 DSN。"""
    raw = (
        os.getenv("TESTCONTAINER_PG_DSN")
        or os.getenv("POSTGRES_DSN")
    )
    if not raw:
        return None
    raw = raw.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if not raw.startswith("postgresql+psycopg://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


@pytest.fixture(scope="module")
def pg_dsn_sync_wsq() -> Generator[str, None, None]:
    """返回同步 DSN，优先 testcontainers，回退到环境变量。"""
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
            _run_migration(dsn_sync)
            yield dsn_sync
            return
    except Exception:
        pass

    dsn_sync = _get_sync_dsn_from_env()
    if not dsn_sync:
        pytest.skip("Docker 不可用且 POSTGRES_DSN 未设置，跳过集成测试")
        return

    _run_migration(dsn_sync)
    yield dsn_sync


def _run_migration(dsn_sync: str) -> None:
    """运行 Alembic upgrade head。"""
    from alembic import command
    from alembic.config import Config
    import os

    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini = backend_dir / "migrations" / "alembic.ini"

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))

    os.environ["POSTGRES_DSN"] = dsn_sync.replace("postgresql+psycopg://", "postgresql://", 1)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="module")
def async_dsn(pg_dsn_sync_wsq: str) -> str:
    """转换为 asyncpg DSN。"""
    return pg_dsn_sync_wsq.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)


def _seed_test_data(dsn_sync: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """在两个 workspace 各插入一条 invite，返回 (ws_a_id, ws_b_id, invite_a_id, invite_b_id)。"""
    engine = sa.create_engine(dsn_sync)
    ws_a_id = uuid.uuid4()
    ws_b_id = uuid.uuid4()
    user_id = uuid.uuid4()
    invite_a_id = uuid.uuid4()
    invite_b_id = uuid.uuid4()
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": str(ws_a_id), "name": "Workspace A", "slug": f"ws-a-{str(ws_a_id)[:8]}"},
        )
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": str(ws_b_id), "name": "Workspace B", "slug": f"ws-b-{str(ws_b_id)[:8]}"},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status) "
                "VALUES (:id, :email, :hash, 'active')"
            ),
            {"id": str(user_id), "email": f"seed-{str(user_id)[:8]}@example.com", "hash": "hash"},
        )
        # Invite in workspace A
        conn.execute(
            text(
                "INSERT INTO invites (id, workspace_id, email, target_role_code, jti, token_hash, expires_at) "
                "VALUES (:id, :ws, :email, 'editor', :jti, 'hash_a', :exp)"
            ),
            {
                "id": str(invite_a_id),
                "ws": str(ws_a_id),
                "email": "user-a@example.com",
                "jti": str(uuid.uuid4()),
                "exp": expires,
            },
        )
        # Invite in workspace B
        conn.execute(
            text(
                "INSERT INTO invites (id, workspace_id, email, target_role_code, jti, token_hash, expires_at) "
                "VALUES (:id, :ws, :email, 'viewer', :jti, 'hash_b', :exp)"
            ),
            {
                "id": str(invite_b_id),
                "ws": str(ws_b_id),
                "email": "user-b@example.com",
                "jti": str(uuid.uuid4()),
                "exp": expires,
            },
        )
        conn.commit()

    engine.dispose()
    return ws_a_id, ws_b_id, invite_a_id, invite_b_id


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_a_cannot_see_ws_b(pg_dsn_sync_wsq: str, async_dsn: str) -> None:
    """workspace A 的 invite 在 workspace B 上下文中查询应返回空集（隔离验证）。"""
    from app.agent_builder.db.scoped_query import WorkspaceScopedQuery, current_workspace_ctx
    from app.agent_builder.models.invite import Invite

    ws_a_id, ws_b_id, invite_a_id, _ = _seed_test_data(pg_dsn_sync_wsq)

    eng = create_async_engine(async_dsn, pool_pre_ping=True)
    session_factory = async_sessionmaker(eng, expire_on_commit=False)

    async with session_factory() as session:
        # 设置 workspace B 的上下文
        token = current_workspace_ctx.set(ws_b_id)
        try:
            stmt = WorkspaceScopedQuery.select(Invite)
            result = await session.execute(stmt)
            invites = result.scalars().all()
            # workspace B 看不到 workspace A 的 invite
            invite_ids = [str(inv.id) for inv in invites]
            assert str(invite_a_id) not in invite_ids, (
                f"安全漏洞：workspace B 看到了 workspace A 的 invite {invite_a_id}"
            )
        finally:
            current_workspace_ctx.reset(token)

    await eng.dispose()


@pytest.mark.asyncio
async def test_missing_ctx_raises(async_dsn: str) -> None:
    """未设置 workspace context 时调用 WorkspaceScopedQuery.select() 应抛 RuntimeError。"""
    from app.agent_builder.db.scoped_query import WorkspaceScopedQuery, current_workspace_ctx
    from app.agent_builder.models.invite import Invite

    # 确保 context 未设置（None）
    token = current_workspace_ctx.set(None)
    try:
        with pytest.raises(RuntimeError, match="current_workspace_ctx"):
            WorkspaceScopedQuery.select(Invite)
    finally:
        current_workspace_ctx.reset(token)


@pytest.mark.asyncio
async def test_correct_ctx_returns_data(pg_dsn_sync_wsq: str, async_dsn: str) -> None:
    """正确的 workspace context 下能查到自己的数据。"""
    from app.agent_builder.db.scoped_query import WorkspaceScopedQuery, current_workspace_ctx
    from app.agent_builder.models.invite import Invite

    ws_a_id, _, invite_a_id, _ = _seed_test_data(pg_dsn_sync_wsq)

    eng = create_async_engine(async_dsn, pool_pre_ping=True)
    session_factory = async_sessionmaker(eng, expire_on_commit=False)

    async with session_factory() as session:
        token = current_workspace_ctx.set(ws_a_id)
        try:
            stmt = WorkspaceScopedQuery.select(Invite)
            result = await session.execute(stmt)
            invites = result.scalars().all()
            invite_ids = [str(inv.id) for inv in invites]
            # workspace A 能看到自己的 invite
            assert str(invite_a_id) in invite_ids, (
                f"workspace A 未能查到自己的 invite {invite_a_id}，实际：{invite_ids}"
            )
        finally:
            current_workspace_ctx.reset(token)

    await eng.dispose()
