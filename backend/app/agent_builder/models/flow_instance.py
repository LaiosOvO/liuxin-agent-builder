"""流程实例 ORM 模型。

表：flow_instances
用途：工作流的运行实例，含状态、thread_id（LangGraph checkpoint key）、DSL 快照。

设计决策（CONTEXT.md）：
- thread_id = '{workspace_id}:{instance_id}'（防 Pitfall 13 跨租户碰撞）
- dsl_snapshot：实例创建时锁定 DSL，运行中修改工作流不影响已运行实例
- status: pending → running → completed / failed / aborted
- v1 不支持 pause（pause 在 Phase 3 HITL 自然引入）
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base
from sqlalchemy import TIMESTAMP, func


class FlowInstance(Base):
    """流程实例。

    每次用户触发工作流运行，创建一个 FlowInstance 记录。
    LangGraph 通过 thread_id 找到对应 checkpoint。
    """

    __tablename__ = "flow_instances"

    # ── 主键 ─────────────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="实例 UUID",
    )

    # ── 多租户隔离（必须第一列）────────────────────────────────────────────────
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属工作区（ON DELETE CASCADE）",
    )

    # ── 关联 ──────────────────────────────────────────────────────────────────
    workflow_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workflows.id"),
        nullable=False,
        comment="触发的工作流 UUID",
    )
    workflow_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workflow_versions.id"),
        nullable=False,
        comment="锁定的工作流版本 UUID",
    )

    # ── DSL 快照 ──────────────────────────────────────────────────────────────
    dsl_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="实例创建时锁定的 DSL 副本（运行中修改 DSL 不影响此实例）",
    )

    # ── LangGraph checkpoint key ──────────────────────────────────────────────
    thread_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        unique=True,
        comment="LangGraph thread_id（格式：workspace_id:instance_id，防 Pitfall 13）",
    )

    # ── 状态机 ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="状态：pending / running / completed / failed / aborted",
    )

    # ── 输入输出 ──────────────────────────────────────────────────────────────
    initial_input: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="初始输入（start 节点接收的参数）",
    )
    final_output: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="最终输出（end 节点返回的结果）",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息（status=failed / aborted 时记录）",
    )

    # ── 审计字段 ──────────────────────────────────────────────────────────────
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="触发用户 UUID（API 触发时有值；系统触发时为 NULL）",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间（UTC）",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="开始执行时间（status=running 时写入）",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="完成时间（status=completed/failed/aborted 时写入）",
    )

    # ── 索引 ──────────────────────────────────────────────────────────────────
    __table_args__ = (
        # 工作区 + 工作流 + 状态 + 时间（实例列表过滤主查询）
        Index(
            "ix_flow_instances_ws_wf_status_created",
            "workspace_id",
            "workflow_id",
            "status",
            text("created_at DESC"),
        ),
        # 工作区 + 状态 + 时间（跨工作流实例列表）
        Index(
            "ix_flow_instances_ws_status_created",
            "workspace_id",
            "status",
            text("created_at DESC"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<FlowInstance id={self.id} "
            f"thread_id={self.thread_id!r} "
            f"status={self.status!r}>"
        )
