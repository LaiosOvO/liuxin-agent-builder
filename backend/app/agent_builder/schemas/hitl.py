"""HITL API Pydantic schemas（Plan 03-06）。

包含 POST /hitl/action 提交时的 form_data 入参 schema（如有 multi-step DSL 校验需求）。

v1 由于 form_data 通过 multipart Form 直接读取，且服务端用 jsonschema Draft-7 校验，
此处仅暴露错误响应 schema 给 OpenAPI 文档使用。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HitlActionErrorResponse(BaseModel):
    """决策提交失败响应（422 / 409 / 410 / 401 等）。"""

    error: str = Field(..., description="错误码：jti_consumed / token_expired / form_invalid / unauth")
    message: str = Field(..., description="用户可见的错误文案（中文）")
    details: dict[str, Any] | None = Field(
        None, description="可选附加信息（如 form_data 校验时的字段错误）"
    )


class HitlActionSuccessResponse(BaseModel):
    """决策提交成功响应。"""

    status: str = Field(default="ok", description="固定 'ok'")
    new_node_status: str = Field(..., description="节点新状态（in_review / done / rejected / returned）")
    instance_id: str = Field(..., description="流程实例 UUID")
