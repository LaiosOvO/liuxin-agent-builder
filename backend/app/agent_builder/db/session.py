"""FastAPI 数据库 session 依赖 + workspace context 管理工具。

get_db: FastAPI 依赖，yield AsyncSession
with_workspace_ctx: 上下文管理器，设置当前请求的 workspace_id
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.db.engine import async_session_maker
from app.agent_builder.db.scoped_query import current_workspace_ctx


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 数据库 session 依赖。

    用法（在 FastAPI router 中）：
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    session 会在请求结束时自动关闭（无论成功/失败）。
    expire_on_commit=False 防止 commit 后访问属性触发额外查询。
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@contextmanager
def with_workspace_ctx(workspace_id: uuid.UUID):  # type: ignore[return]
    """同步上下文管理器：设置 current_workspace_ctx。

    用于非 FastAPI 场景（后台任务、脚本、测试）。

    用法：
        with with_workspace_ctx(ws_id):
            stmt = WorkspaceScopedQuery.select(Invite)
    """
    token = current_workspace_ctx.set(workspace_id)
    try:
        yield workspace_id
    finally:
        current_workspace_ctx.reset(token)


@asynccontextmanager
async def async_with_workspace_ctx(workspace_id: uuid.UUID):  # type: ignore[return]
    """异步上下文管理器：设置 current_workspace_ctx。

    用法：
        async with async_with_workspace_ctx(ws_id):
            stmt = WorkspaceScopedQuery.select(Invite)
    """
    token = current_workspace_ctx.set(workspace_id)
    try:
        yield workspace_id
    finally:
        current_workspace_ctx.reset(token)
