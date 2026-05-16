"""UserWorkspaceRole ORM 模型（多对多 + 角色）。

联结表：用户 ↔ 工作区 ↔ 角色三元关系。
PK 为 (workspace_id, user_id) 复合主键，防止同一用户在同一 workspace 有多个角色。
反查索引 (user_id, workspace_id) 用于"查询用户所属的所有 workspace"。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class UserWorkspaceRole(Base):
    """用户工作区角色关联表。

    workspace_id 为复合 PK 第一列，满足多租户索引规则（CLAUDE.md 2.4）。
    """

    __tablename__ = "user_workspace_roles"
    __table_args__ = (
        Index("ix_user_workspace_roles_user_id_workspace_id", "user_id", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
        comment="工作区 ID（复合 PK 第一列）",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        comment="用户 ID（复合 PK 第二列）",
    )
    role_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("roles.id"),
        nullable=False,
        comment="角色 ID",
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="角色授予时间",
    )
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="授予者 user_id（setup 阶段可能为 NULL）",
    )
