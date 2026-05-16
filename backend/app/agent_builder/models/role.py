"""Role ORM 模型（静态种子表）。

角色由 migration 初始化种子数据，运行时不新增。
external 角色不存入 user_workspace_roles，由 HITL token 临时产生。

RoleCode 枚举供 Python 代码引用，避免硬编码字符串。
"""
from __future__ import annotations

import enum
from typing import Optional

from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class RoleCode(str, enum.Enum):
    """角色代码枚举。

    - super_admin: 平台级超级管理员（仅 setup 时创建）
    - admin: 工作区级管理员（可邀请成员、管理设置）
    - editor: 工作区编辑者（可创建/编辑工作流）
    - viewer: 只读（仅查看，不可启动实例）
    - external: 临时外部身份（HITL token 使用，不存入 user_workspace_roles）
    """

    super_admin = "super_admin"
    admin = "admin"
    editor = "editor"
    viewer = "viewer"
    external = "external"


class Role(Base):
    """角色表（静态种子，migration 插入 4 条）。

    external 不入此表，仅作为 HITL token 的临时身份。
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
        comment="角色 ID（SMALLINT，静态）",
    )
    code: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        comment="角色代码：super_admin / admin / editor / viewer",
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="角色描述",
    )
