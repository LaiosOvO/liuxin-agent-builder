"""认证相关 Pydantic v2 Schema。

全部使用 ConfigDict(str_strip_whitespace=True, extra='forbid')。
"""
from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """用户注册请求。

    注意：公开注册关闭，invite_token 必填。
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr = Field(description="用户邮箱（大小写不敏感）")
    password: str = Field(min_length=8, description="明文密码（≥ 8 位，含字母和数字）")
    display_name: str = Field(min_length=1, max_length=120, description="显示名称")
    department: str | None = Field(default=None, max_length=120, description="所属部门")
    invite_token: str = Field(description="邀请 token（必填，公开注册关闭）")


class LoginRequest(BaseModel):
    """用户登录请求。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr = Field(description="用户邮箱")
    password: str = Field(description="明文密码")


class LoginResponse(BaseModel):
    """登录成功响应。"""

    model_config = ConfigDict(extra="ignore")

    user_id: uuid.UUID = Field(description="用户 ID")
    workspace_id: uuid.UUID = Field(description="当前工作区 ID")
    role: str = Field(description="当前工作区内角色")
    redirect_to: str = Field(description="登录后跳转路径")


class MessageResponse(BaseModel):
    """通用消息响应。"""

    model_config = ConfigDict(extra="ignore")

    message: str = Field(description="提示消息")
