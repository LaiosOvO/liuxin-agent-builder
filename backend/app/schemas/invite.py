"""邀请流程 Pydantic v2 Schema。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CreateInviteRequest(BaseModel):
    """创建邀请请求（admin only）。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr = Field(description="被邀请人邮箱")
    role_code: Literal["admin", "editor", "viewer"] = Field(
        description="目标角色代码"
    )


class InvitePreviewResponse(BaseModel):
    """邀请预览响应（GET 不消费 jti）。"""

    model_config = ConfigDict(extra="ignore")

    workspace_name: str = Field(description="工作区名称")
    role_code: str = Field(description="目标角色代码")
    inviter_display_name: str = Field(description="邀请人显示名")
    expires_at: datetime = Field(description="邀请链接过期时间")
    already_used: bool = Field(description="邀请是否已被使用")
    email: str = Field(description="被邀请人邮箱（预填，前端不可修改）")


class AcceptInviteRequest(BaseModel):
    """接受邀请请求（POST 消费 jti + 注册）。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    token: str = Field(description="邀请 JWT token")
    password: str = Field(min_length=8, description="注册密码")
    display_name: str = Field(min_length=1, max_length=120, description="显示名称")
    department: str | None = Field(default=None, max_length=120, description="所属部门")
