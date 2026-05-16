"""Setup 流程 Pydantic v2 Schema。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SetupStateResponse(BaseModel):
    """Setup 状态查询响应。"""

    model_config = ConfigDict(extra="ignore")

    initialized: bool = Field(description="系统是否已初始化")
    version: str = Field(default="1.0.0", description="API 版本")


class InitializeRequest(BaseModel):
    """Setup 初始化请求。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr = Field(description="超级管理员邮箱")
    password: str = Field(min_length=8, description="超级管理员密码（≥ 8 位，含字母和数字）")
    display_name: str = Field(min_length=1, max_length=120, description="超级管理员显示名")
    workspace_name: str = Field(min_length=1, max_length=120, description="第一个工作区名称")
