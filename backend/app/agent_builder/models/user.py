"""User ORM 模型。

邮箱使用 CITEXT 扩展实现大小写不敏感唯一约束。
密码使用 pwdlib[argon2] 哈希，不存储明文。
im_bindings 为 JSONB，Phase 5 用于存储 IM 账号绑定信息。
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class UserStatus(str, enum.Enum):
    """用户状态枚举。

    - pending_verification: 注册后等待邮箱验证
    - active: 正常活跃用户
    - disabled: 已禁用（admin 操作）
    """

    pending_verification = "pending_verification"
    active = "active"
    disabled = "disabled"


class User(Base):
    """用户表。

    email 使用 CITEXT 扩展，INSERT alice@example.com 和 Alice@example.com 会触发唯一约束冲突。
    is_super_admin 仅 setup 阶段创建的第一个用户为 True，其后不可通过普通注册获得。
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="用户主键",
    )
    email: Mapped[str] = mapped_column(
        CITEXT,
        unique=True,
        nullable=False,
        comment="邮箱地址（CITEXT 大小写不敏感唯一约束）",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="argon2 哈希后的密码（pwdlib 输出）",
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(120),
        nullable=True,
        comment="用户显示名称",
    )
    department: Mapped[Optional[str]] = mapped_column(
        String(120),
        nullable=True,
        comment="所属部门（Phase 5 IM 目录同步填充）",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="pending_verification",
        comment="用户状态：pending_verification / active / disabled",
    )
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="是否是平台级超级管理员（仅 setup 阶段第一个用户）",
    )
    im_bindings: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        server_default="{}",
        comment="IM 账号绑定信息（Phase 5 用）：{feishu: {...}, wecom: {...}}",
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
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近登录时间",
    )
