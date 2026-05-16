"""工作流版本快照 ORM 模型。

表：workflow_versions
用途：工作流的草稿/发布版本快照，存储完整 DSL JSON。

设计决策（CONTEXT.md）：
- version_no = 0 为草稿版本（只有一个活跃草稿）
- version_no = 1/2/3... 为发布版本（单调递增）
- kind 区分草稿和发布：'draft' | 'published'
- UNIQUE (workflow_id, version_no, kind) 防止重复版本
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base
from sqlalchemy import TIMESTAMP, func


class WorkflowVersion(Base):
    """工作流版本快照。

    DSL 存为 JSONB，包含完整工作流定义（nodes / edges / state_schema 等）。
    实例创建时锁定 dsl 字段（dsl_snapshot 写入 flow_instances），后续修改不影响运行中实例。
    """

    __tablename__ = "workflow_versions"

    # ── 主键 ─────────────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="版本 UUID",
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
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属工作流 UUID",
    )

    # ── 版本信息 ──────────────────────────────────────────────────────────────
    version_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="版本号（草稿=0，发布=1/2/3...）",
    )
    kind: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="版本类型：draft | published",
    )
    dsl: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="完整 DSL JSON（nodes / edges / state_schema / version 等）",
    )

    # ── 审计字段 ──────────────────────────────────────────────────────────────
    created_by: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="创建人 UUID",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间（UTC）",
    )

    # ── 约束 + 索引 ────────────────────────────────────────────────────────────
    __table_args__ = (
        # 同一工作流的 version_no + kind 唯一（防重复发布）
        UniqueConstraint(
            "workflow_id",
            "version_no",
            "kind",
            name="uq_workflow_versions_wf_version_kind",
        ),
        # 工作区 + 工作流查询（列表 / 版本历史）
        Index(
            "ix_workflow_versions_ws_wf",
            "workspace_id",
            "workflow_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowVersion id={self.id} "
            f"workflow_id={self.workflow_id} "
            f"version_no={self.version_no} kind={self.kind!r}>"
        )
