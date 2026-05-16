"""工作流主表 ORM 模型。

表：workflows
用途：工作流定义（草稿 / 已发布 / 已归档），含版本指针。

多租户规则（CLAUDE.md 2.4）：
- workspace_id 列为所有查询的第一过滤条件
- PK 复合索引第一列为 workspace_id
- 通过 WorkspaceScopedQuery 隔离租户数据
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base
from sqlalchemy import TIMESTAMP, func


class Workflow(Base):
    """工作流主表。

    状态流转：draft → published → archived（或直接 archived）
    version 指针：current_draft_version_id / current_published_version_id
    """

    __tablename__ = "workflows"

    # ── 主键 ─────────────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="工作流 UUID（gen_random_uuid()）",
    )

    # ── 多租户隔离（必须第一列）────────────────────────────────────────────────
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属工作区（ON DELETE CASCADE）",
    )

    # ── 基本字段 ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="工作流名称",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="工作流描述（可空）",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="draft",
        comment="状态：draft / published / archived",
    )

    # ── 版本指针（自引用，在 workflow_versions 表创建后才有意义）─────────────────
    current_draft_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=True,
        comment="当前草稿版本 UUID（workflow_versions.id）",
    )
    current_published_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=True,
        comment="当前发布版本 UUID（workflow_versions.id）",
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
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="最后更新时间（UTC）",
    )

    # ── 索引 ──────────────────────────────────────────────────────────────────
    __table_args__ = (
        # 工作区下按状态 + 时间降序查询（列表页主查询路径）
        Index(
            "ix_workflows_ws_status_created",
            "workspace_id",
            "status",
            text("created_at DESC"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} name={self.name!r} status={self.status}>"
