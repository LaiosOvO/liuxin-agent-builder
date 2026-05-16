"""工作流相关 Pydantic v2 请求/响应模型。

请求模型：
- CreateWorkflowRequest  — POST /workflows
- SaveDraftRequest       — PUT /workflows/<id>/draft
- ValidateRequest        — POST /workflows/validate

响应模型：
- WorkflowSummary   — 列表项（不含 DSL）
- WorkflowDetail    — 详情（含 draft DSL + published DSL）
- WorkflowVersionInfo — 版本信息
- ValidationResponse  — DSL 校验结果
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── 请求模型 ──────────────────────────────────────────────────────────────────

class CreateWorkflowRequest(BaseModel):
    """创建工作流请求。"""

    name: str = Field(..., min_length=1, max_length=120, description="工作流名称")
    description: str | None = Field(None, max_length=1000, description="工作流描述（可选）")


class SaveDraftRequest(BaseModel):
    """保存草稿请求。

    dsl: 完整 DSL JSON（后端进行校验；fatal error 返回 422）
    """

    dsl: dict[str, Any] = Field(..., description="工作流 DSL（JSON 对象）")


class ValidateRequest(BaseModel):
    """DSL 独立校验请求（不保存）。"""

    dsl: dict[str, Any] = Field(..., description="待校验的 DSL JSON")


# ── 响应模型 ──────────────────────────────────────────────────────────────────

class ValidationErrorResponse(BaseModel):
    """单个 DSL 校验错误响应条目。"""

    severity: str = Field(..., description="严重程度：error（阻断）/ warning（可放行）")
    code: str = Field(..., description="错误代码，如 E_CYCLE")
    message: str = Field(..., description="错误描述（中文）")
    node_id: str | None = Field(None, description="涉及的节点 ID")
    edge_id: str | None = Field(None, description="涉及的边 ID")
    field_path: str | None = Field(None, description="涉及的字段路径（如 config.temperature）")


class ValidationResponse(BaseModel):
    """DSL 校验响应。"""

    errors: list[ValidationErrorResponse] = Field(default_factory=list)


class WorkflowSummary(BaseModel):
    """工作流摘要（列表页使用，不含 DSL）。"""

    id: UUID
    name: str
    description: str | None
    status: str = Field(..., description="状态：draft / published / archived")
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowVersionInfo(BaseModel):
    """工作流版本信息。"""

    id: UUID
    version_no: int
    kind: str = Field(..., description="版本类型：draft / published")
    dsl: dict[str, Any]
    created_by: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowDetail(WorkflowSummary):
    """工作流详情（含 DSL）。

    draft_dsl: 当前草稿 DSL（若存在草稿版本）
    published_dsl: 当前发布 DSL（若已发布）
    draft_version_id: 草稿版本 ID
    published_version_id: 发布版本 ID
    """

    draft_version_id: UUID | None = None
    published_version_id: UUID | None = None
    draft_dsl: dict[str, Any] | None = None
    published_dsl: dict[str, Any] | None = None

    model_config = {"from_attributes": True}
