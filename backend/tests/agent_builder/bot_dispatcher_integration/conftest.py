"""Phase 4.5 bot_dispatcher 集成测试共享 fixture。

集成测试连真 Postgres（root conftest 提供 testcontainers / SSH 隧道 DSN）：
- workspace_id_a / workspace_id_b: 双租户隔离测试
- db_session: 真 AsyncSession，自动 rollback

与 tests/platforms/conftest.py 等价（复制粘贴模式而非交叉依赖，避免 fixture lookup 跨目录的隐式耦合）。
"""
from __future__ import annotations

import uuid
from typing import AsyncIterator as AsyncIter

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def workspace_id_a() -> uuid.UUID:
    """测试 workspace A — 用于双租户隔离场景。"""
    return uuid.uuid4()


@pytest.fixture
def workspace_id_b() -> uuid.UUID:
    """测试 workspace B — 与 workspace_id_a 配对。"""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def db_session() -> AsyncIter[AsyncSession]:
    """复用 Phase 1 async_session_maker，自动 rollback 保持 DB 干净。"""
    from app.agent_builder.db.engine import async_session_maker, engine

    await engine.dispose()

    async with async_session_maker() as session:
        yield session
        await session.rollback()
