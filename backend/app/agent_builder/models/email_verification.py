"""EmailVerification ORM 模型（邮箱验证 token 表）。

用于注册后的邮箱验证流程。
workspace_id 可为 NULL（setup 阶段首个 super_admin 注册时无 workspace）。
jti 一次性消费，消费规则同 Invite：POST 才消费，GET 不消费（Pitfall 3 防护）。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class EmailVerification(Base):
    """邮箱验证表。

    注册后系统发送含 token 链接的邮件，用户点击后此记录的 used_at 被填充。
    """

    __tablename__ = "email_verifications"
    __table_args__ = (
        Index("ix_email_verifications_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="验证记录主键",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="目标用户 ID",
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联工作区（setup 阶段 super_admin 注册时为 NULL）",
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
        comment="JWT 完整 token 的 SHA256 哈希（审计用）",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Token 过期时间",
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
        comment="验证记录创建时间",
    )
