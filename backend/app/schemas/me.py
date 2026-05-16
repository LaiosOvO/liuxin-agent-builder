"""用户 profile 相关 Pydantic v2 Schema。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceInfo(BaseModel):
    """工作区基本信息。"""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    slug: str
    role: str = Field(description="当前用户在该工作区的角色")


class UserInfo(BaseModel):
    """用户基本信息。"""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    email: str
    display_name: str | None
    department: str | None
    status: str
    is_super_admin: bool
    created_at: datetime
    last_login_at: datetime | None


class MeResponse(BaseModel):
    """GET /api/auth/me 响应。"""

    model_config = ConfigDict(extra="ignore")

    user: UserInfo = Field(description="当前用户信息")
    current_workspace: WorkspaceInfo | None = Field(
        description="当前工作区信息（若未绑定工作区则为 None）"
    )
    workspaces: list[WorkspaceInfo] = Field(
        default_factory=list,
        description="用户所属的全部工作区列表",
    )


class UpdateProfileRequest(BaseModel):
    """更新用户 profile 请求。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    display_name: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
