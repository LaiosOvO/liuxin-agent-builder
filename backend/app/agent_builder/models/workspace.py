"""Workspace ORM 模型。

工作区是多租户隔离的边界单位，所有业务表通过 workspace_id 与之关联。
首个 workspace 在 setup 阶段由 super_admin 创建。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class Workspace(Base):
    """工作区表。

    slug 用于 URL 友好的标识符（如 /ws/my-company）。
    created_by 首次 setup 时为 NULL（super_admin 创建第一个 workspace 时自引用为空）。
    """

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="工作区主键",
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="工作区显示名称",
    )
    slug: Mapped[str] = mapped_column(
        String(60),
        unique=True,
        nullable=False,
        comment="URL 友好标识符，全局唯一",
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="创建者 user_id（首次 setup 时为 NULL）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="最后更新时间",
    )
