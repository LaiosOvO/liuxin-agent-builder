"""WorkspaceScopedQuery：多租户查询抽象层（防 Pitfall 6）。

所有业务表查询必须经过此抽象，自动注入 WHERE workspace_id = :current_workspace。

使用约定：
    必须走 WorkspaceScopedQuery：
        invites, email_verifications, audit_logs（有 workspace_id 的业务数据）
        Phase 2+ 新增的 workflows, instances 等

    可以绕过（直接 sa_select）：
        workspaces, users, roles（跨 workspace 可见的全局表）
        super_admin 跨 ws 查询

用法：
    from app.agent_builder.db.scoped_query import WorkspaceScopedQuery, current_workspace_ctx

    # 在 FastAPI 依赖或 middleware 中设置 workspace context
    token = current_workspace_ctx.set(workspace_id)
    try:
        stmt = WorkspaceScopedQuery.select(Invite)
        result = await session.execute(stmt)
    finally:
        current_workspace_ctx.reset(token)
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any, Type, TypeVar

from sqlalchemy import select as sa_select
from sqlalchemy.sql import Select

# ── Context Variable ───────────────────────────────────────────────────────────
# 当前请求的 workspace_id，由 FastAPI middleware 在请求开始时设置
current_workspace_ctx: ContextVar[uuid.UUID | None] = ContextVar(
    "current_workspace",
    default=None,
)

T = TypeVar("T")


class WorkspaceScopedQuery:
    """业务表 select() 统一入口，自动注入 workspace_id 过滤。

    例外（不走此类）：
        - workspaces / users / roles：跨 workspace 可见的全局表
        - super_admin 跨 ws 管理查询：直接用 sa_select()

    示例：
        stmt = WorkspaceScopedQuery.select(Invite)
        # 等价于：sa_select(Invite).where(Invite.workspace_id == current_ws_id)
    """

    @staticmethod
    def select(model: Type[T]) -> Select[tuple[T]]:
        """创建带 workspace_id 过滤的 select 语句。

        Args:
            model: SQLAlchemy ORM 模型类（必须有 workspace_id 列）

        Returns:
            Select 语句，已注入 WHERE workspace_id = :current_workspace

        Raises:
            RuntimeError: 如果 current_workspace_ctx 未设置（即 workspace_id 为 None）
        """
        ws_id = current_workspace_ctx.get()
        if ws_id is None:
            raise RuntimeError(
                "WorkspaceScopedQuery.select() 要求 current_workspace_ctx 已设置。"
                "请在调用前通过 current_workspace_ctx.set(workspace_id) 注入租户上下文。"
            )
        return sa_select(model).where(model.workspace_id == ws_id)  # type: ignore[attr-defined]

    @staticmethod
    def get_current_workspace_id() -> uuid.UUID:
        """获取当前请求的 workspace_id。

        Returns:
            当前 workspace_id

        Raises:
            RuntimeError: 如果 workspace_id 未设置
        """
        ws_id = current_workspace_ctx.get()
        if ws_id is None:
            raise RuntimeError(
                "当前请求未设置 workspace context。"
                "请检查认证中间件是否正确设置 current_workspace_ctx。"
            )
        return ws_id
