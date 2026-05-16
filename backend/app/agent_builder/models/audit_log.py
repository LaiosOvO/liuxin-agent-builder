"""AuditLog ORM 模型（审计日志表）。

workspace_id 可为 NULL（系统级事件如 setup 没有 workspace）。
使用 BIGSERIAL PK 保证时序有序，不用 UUID。
actor_meta 存储 external actor 信息（HITL token 的外部邮箱/jti）。

Phase 3 NET-05 增强（0003 migration）：
- actor_ip：HITL 决策的客户端 IP（与已有 ip INET 列含义重叠但语义不同 —
  ip 是请求级 IP 兜底，actor_ip 是显式决策审计字段，避免在 HITL 决策日志中
  混淆"是哪个 IP 做的决定"）
- actor_ua：决策时的 User-Agent（同上，HITL 专用语义）
- decision：决策动作字符串（submit/approve/return/reject 或其他业务事件）
- node_state_id：关联到具体 node_states 行（HITL 决策审计可向上关联到节点）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class AuditLog(Base):
    """审计日志表。

    append-only 设计，不支持 UPDATE/DELETE（审计完整性要求）。
    高频写入场景（登录、决策、RBAC 检查），使用 BIGSERIAL 而非 UUID PK。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_audit_logs_actor_user_id_created_at", "actor_user_id", "created_at"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
        # Phase 3 NET-05 新增：节点状态关联索引（HITL 决策审计按 node_state_id 查）
        Index("ix_audit_logs_node_state", "node_state_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="自增审计日志 ID（BIGSERIAL，时序有序）",
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="工作区 ID（系统级事件如 setup 为 NULL）",
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="操作者 user_id（external token 操作为 NULL，见 actor_meta）",
    )
    actor_meta: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        server_default="{}",
        comment="操作者元数据（external email / token jti 等）",
    )
    action: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="操作类型：setup.created / user.registered / login.success / rbac.denied 等",
    )
    target_type: Mapped[Optional[str]] = mapped_column(
        String(40),
        nullable=True,
        comment="操作目标类型：workspace / user / invite / workflow 等",
    )
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="操作目标 ID",
    )
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        server_default="{}",
        comment="附加元数据（操作上下文信息）",
    )
    ip: Mapped[Optional[str]] = mapped_column(
        INET,
        nullable=True,
        comment="客户端 IP 地址（请求级，Phase 1 即有）",
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="客户端 User-Agent（请求级，Phase 1 即有）",
    )

    # ── Phase 3 NET-05 新增字段（0003 migration） ─────────────────────────────
    actor_ip: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="HITL 决策的客户端 IP（NET-05 决策审计专用，与 ip 列语义并列）",
    )
    actor_ua: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True,
        comment="HITL 决策的 User-Agent（NET-05 决策审计专用）",
    )
    decision: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        comment="决策动作：submit / approve / return / reject（NET-05）",
    )
    node_state_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联节点状态 UUID（NET-05，HITL 决策审计可向上关联到节点）",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="日志记录时间",
    )
