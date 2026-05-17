"""HITL API Pydantic schemas（Plan 03-06 + 04-03 委托）。

包含 POST /hitl/action 提交时的 form_data 入参 schema（如有 multi-step DSL 校验需求）。
+ Plan 04-03：DelegateRequest / DelegateResponse 用于 POST /hitl/action/<jwt>?op=delegate

v1 由于 form_data 通过 multipart Form 直接读取，且服务端用 jsonschema Draft-7 校验，
此处仅暴露错误响应 schema 给 OpenAPI 文档使用。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


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


# ── Plan 04-03 委托 schemas ───────────────────────────────────────────────────


class DelegateRequest(BaseModel):
    """POST /hitl/action/<jwt>?op=delegate 入参。

    Attributes:
        to_email: 被委托人邮箱（必须为合法 email + 同 workspace）
        reason: 委托原因（必填 + ≤ 500 字）
    """

    to_email: EmailStr = Field(
        ..., description="被委托人邮箱（必须在同 workspace 内）"
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="委托原因（必填，1~500 字）",
    )


class DelegateResponse(BaseModel):
    """POST /hitl/action/<jwt>?op=delegate 成功响应。

    Attributes:
        ok: 固定 True（错误走异常路径）
        new_token_count: 创建的新 token 数（默认 3 — approve/return/reject）
        depth: 本次委托后的委托链深度（1~3）
        recipient_email: 被委托人邮箱（确认用）
        instance_id: 流程实例 UUID（前端可跳详情页）
    """

    ok: bool = Field(default=True)
    new_token_count: int = Field(..., description="为被委托人创建的 token 行数")
    depth: int = Field(..., ge=1, le=3, description="委托链深度（1~3）")
    recipient_email: str = Field(..., description="被委托人邮箱")
    instance_id: str = Field(..., description="流程实例 UUID")


class DelegateErrorResponse(BaseModel):
    """委托失败响应（409 / 422）。"""

    error: str = Field(
        ...,
        description=(
            "错误码：depth_exceeded(409) / self_delegate(422) / "
            "circular(422) / recipient_not_found(422) / cross_workspace(422)"
        ),
    )
    message: str = Field(..., description="用户可见的中文错误文案")
