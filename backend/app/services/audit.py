"""审计日志写入工具。

提供统一的 audit log 写入接口，自动从 Request 提取 IP 和 User-Agent。
append-only 设计（AuditLog 模型不支持 UPDATE/DELETE）。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.agent_builder.models.audit_log import AuditLog


async def log(
    db: AsyncSession,
    *,
    action: str,
    workspace_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_meta: dict[str, Any] | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """写入一条审计日志。

    Args:
        db: AsyncSession（调用者负责 commit）
        action: 操作类型，如 'setup.created' / 'login.success' / 'rbac.denied'
        workspace_id: 工作区 ID（系统级事件如 setup 为 None）
        actor_user_id: 操作者 user_id（external token 操作为 None）
        actor_meta: 操作者元数据（external email/jti 等）
        target_type: 操作目标类型（workspace/user/invite/workflow 等）
        target_id: 操作目标 ID
        meta: 附加元数据（操作上下文信息）
        request: FastAPI Request 对象，用于自动提取 IP 和 User-Agent
    """
    ip: str | None = None
    user_agent: str | None = None

    if request is not None:
        # 从 X-Forwarded-For 获取真实 IP（经过 nginx 代理后）
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # 取第一个 IP（最原始的客户端 IP）
            ip = forwarded_for.split(",")[0].strip()
        elif request.client:
            ip = request.client.host

        user_agent = request.headers.get("User-Agent")
        # 截断 user_agent 避免超过 255 字节
        if user_agent and len(user_agent) > 255:
            user_agent = user_agent[:252] + "..."

    audit_entry = AuditLog(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        actor_meta=actor_meta or {},
        action=action,
        target_type=target_type,
        target_id=target_id,
        meta=meta or {},
        ip=ip,
        user_agent=user_agent,
    )
    db.add(audit_entry)
    # 注意：不在此处 commit，由调用方的 session 统一 commit
