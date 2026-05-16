"""节点状态 ORM 模型。

表：node_states
用途：流程实例中每个节点的执行状态（SSE 推送用）。

设计决策（CONTEXT.md）：
- output_summary 存储节点输出摘要（不存 raw output，raw 走 Redis pointer 防 checkpoint 膨胀）
- node_id 对应 DSL 中的节点 ID（如 'llm_1' / 'start' / 'end'）
- node_type 对应 DSL 节点类型（start / end / llm / tool / if_else）
- v1 不支持节点级重试（retries 记录但 v1 始终为 0）
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base
from sqlalchemy import TIMESTAMP, func


class NodeState(Base):
    """节点执行状态。

    每个节点每次执行创建一条记录。
    SSE 推送时用 status 字段推 node.start / node.complete / node.error 事件。
    """

    __tablename__ = "node_states"

    # ── 主键 ─────────────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="节点状态 UUID",
    )

    # ── 多租户隔离（必须第一列）────────────────────────────────────────────────
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属工作区（ON DELETE CASCADE）",
    )

    # ── 关联 ──────────────────────────────────────────────────────────────────
    instance_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("flow_instances.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属流程实例（ON DELETE CASCADE）",
    )

    # ── 节点信息 ──────────────────────────────────────────────────────────────
    node_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="DSL 中的节点 ID（如 'llm_1' / 'start' / 'if_else_2'）",
    )
    node_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="节点类型：start / end / llm / tool / if_else",
    )

    # ── 状态机 ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="状态：pending / running / completed / failed",
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="节点开始执行时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="节点完成时间",
    )

    # ── 错误 + 重试 ────────────────────────────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息（status=failed 时记录）",
    )
    retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="重试次数（v1 始终为 0，v2+ 节点级重试时更新）",
    )

    # ── 输出摘要 ──────────────────────────────────────────────────────────────
    output_summary: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="节点输出摘要（非 raw output；raw output 走 Redis pointer 防 checkpoint 膨胀）",
    )

    # ── 索引 ──────────────────────────────────────────────────────────────────
    __table_args__ = (
        # 工作区 + 实例 + 开始时间（节点列表查询主路径）
        Index(
            "ix_node_states_ws_instance_created",
            "workspace_id",
            "instance_id",
            "started_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NodeState id={self.id} "
            f"node_id={self.node_id!r} "
            f"status={self.status!r}>"
        )
