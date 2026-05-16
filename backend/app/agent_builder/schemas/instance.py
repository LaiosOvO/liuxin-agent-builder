"""实例相关 Pydantic v2 请求/响应模型。

请求模型：
- CreateInstanceRequest — POST /workflows/<id>/instances

响应模型：
- NodeStateInfo  — 单节点状态
- InstanceSummary — 实例列表项
- InstanceDetail  — 实例详情（含 node_states[]）
- InstanceListResponse — 分页列表响应
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── 请求模型 ──────────────────────────────────────────────────────────────────

class CreateInstanceRequest(BaseModel):
    """创建实例请求。"""

    initial_input: dict[str, Any] = Field(
        default_factory=dict,
        description="初始输入参数（对应 state_schema 字段）",
    )


# ── 响应模型 ──────────────────────────────────────────────────────────────────

class NodeStateInfo(BaseModel):
    """单节点执行状态信息。"""

    id: UUID
    node_id: str = Field(..., description="DSL 中的节点 ID（如 'llm_1'）")
    node_type: str = Field(..., description="节点类型：start / end / llm / tool / if_else")
    status: str = Field(..., description="状态：pending / running / completed / failed")
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    retries: int = 0
    output_summary: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class InstanceSummary(BaseModel):
    """实例列表摘要（不含节点状态）。"""

    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    status: str = Field(..., description="状态：pending / running / completed / failed / aborted")
    initial_input: dict[str, Any] | None = None
    error_message: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class InstanceDetail(InstanceSummary):
    """实例详情（含 node_states[] timeline）。"""

    final_output: dict[str, Any] | None = None
    dsl_snapshot: dict[str, Any] | None = None
    node_states: list[NodeStateInfo] = Field(default_factory=list)


class InstanceListResponse(BaseModel):
    """实例分页列表响应。"""

    items: list[InstanceSummary]
    total: int
    page: int
    page_size: int
