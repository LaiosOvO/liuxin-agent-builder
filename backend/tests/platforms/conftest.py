"""Phase 5.A platforms 单元测试共享 fixture。

提供后续 Wave 2-6 所有 platforms 单测要复用的基础设施：
- workspace_id fixture（双 workspace 隔离测试）
- db_session fixture（复用 root conftest 的 async session + rollback 模式）
- clean_plugin_registry fixture（占位 — Plan 04 PluginRegistry 实现后改为真清空）

设计原则（与 root conftest 一致）：
- 每个测试独立 workspace_id（uuid.uuid4()）避免跨测试污染
- db_session 自动 rollback —— 测试结束后 DB 干净
- 不引入 testcontainers（root conftest 已处理 PG/Redis 容器；本 conftest 只声明 fixture，不重新起容器）

后续 plan 可在此 conftest 追加 fixture：
- Plan 03: manifest_loader fixture（加载 fixture YAML）
- Plan 04: clean_plugin_registry 真实清空 PluginRegistry 模块级 dict
- Plan 05: legacy_im_registry fixture（注册 Phase 4 mock providers）
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import AsyncIterator as AsyncIter

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def workspace_id_a() -> uuid.UUID:
    """测试 workspace A —— 用于双租户隔离场景。

    每次 test 独立 UUID，避免跨测试 DB 行残留干扰。
    """
    return uuid.uuid4()


@pytest.fixture
def workspace_id_b() -> uuid.UUID:
    """测试 workspace B —— 与 workspace_id_a 配对用于隔离测试。"""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def db_session() -> AsyncIter[AsyncSession]:
    """复用 Phase 1 async_session_maker，自动 rollback 保持 DB 干净。

    与 root conftest.py db_session 等价（重复定义为子目录显式声明，
    避免 fixture lookup 跨目录的隐式依赖）。

    用法：
        @pytest.mark.asyncio
        async def test_xxx(db_session, workspace_id_a):
            db_session.add(WorkspacePluginInstallation(workspace_id=workspace_id_a, ...))
            await db_session.flush()
    """
    from app.agent_builder.db.engine import async_session_maker, engine

    # 重置连接池（避免 "attached to a different loop" 错误）
    await engine.dispose()

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def clean_plugin_registry() -> AsyncIterator[None]:
    """占位 fixture —— Plan 04 PluginRegistry 实现后改为真清空。

    当前仅 yield，不做任何操作。Plan 04 后将变为：
        from app.agent_builder.platforms.registry import _PLUGIN_REGISTRY
        _PLUGIN_REGISTRY.clear()
        yield
        _PLUGIN_REGISTRY.clear()
    """
    yield
