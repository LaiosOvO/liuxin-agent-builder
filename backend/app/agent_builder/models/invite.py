"""Invite ORM 模型（邀请 token 表）。

workspace_id 为第一列，满足多租户复合索引规则（CLAUDE.md 2.4）。
jti 与 JWT jti 字段对齐，UNIQUE 约束防止双重使用。
token_hash 存储 JWT 完整哈希用于审计，不存明文。
used_at 为 NULL 表示未使用，消费时通过 UPDATE WHERE used_at IS NULL RETURNING * 保证幂等。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class Invite(Base):
    """邀请表。

    流程：admin 填邮箱+角色 → 生成 JWT → 发邮件 → 被邀请人点链接注册 → 加入 workspace。
    """

    __tablename__ = "invites"
    __table_args__ = (
        Index("ix_invites_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_invites_email_workspace_id", "email", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="邀请记录主键",
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
        comment="目标工作区 ID（业务表首列，满足多租户索引规则）",
    )
    email: Mapped[str] = mapped_column(
        CITEXT,
        nullable=False,
        comment="被邀请人邮箱（CITEXT 大小写不敏感）",
    )
    target_role_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="目标角色代码：admin / editor / viewer",
    )
    jti: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid.uuid4,
        comment="JWT jti（一次性消费 ID，UNIQUE 约束）",
    )
    token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="JWT 完整 token 的 SHA256 哈希（审计用，不存明文）",
    )
    invited_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="邀请人 user_id",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Token 过期时间（通常为创建后 24h）",
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Token 消费时间（NULL 表示未使用）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="邀请创建时间",
    )
