"""HITL-07 申请人追踪页 Pydantic v2 响应模型。

CONTEXT §申请人追踪页隐私：
- 申请人能看到审批人姓名 + 决策 + 时间（不能看 IP / UA）
- admin 能看全（含 NET-05 审计字段 IP/UA）

设计参考：Dify api/controllers/console/app/workflow_run.py + WorkflowPauseDetailsResponse
（详见 docs/reading-dify-03-08-tracking-page-2026-05-17.md §7）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── 单条决策记录（脱敏前后字段一致；脱敏时 ip/ua 置 None）────────────────────


class TrackingRecord(BaseModel):
    """一条审批决策记录。

    申请人视角：actor_email + actor_name + action + reason + ts（ip/ua=None）
    admin 视角：完整字段（含 ip/ua）
    """

    actor_email: str = Field("", description="审批人邮箱")
    actor_name: str | None = Field(None, description="审批人显示名")
    action: str = Field(..., description="决策动作：submit/approve/return/reject/escalate")
    reason: str = Field("", description="决策理由（可选）")
    ts: str = Field(..., description="决策时间（ISO8601 字符串）")
    ip: str | None = Field(
        None,
        description="决策来源 IP（仅 admin 可见；申请人视角为 None）",
    )
    ua: str | None = Field(
        None,
        description="决策来源 User-Agent（仅 admin 可见；申请人视角为 None）",
    )


# ── 申请人信息（简化）─────────────────────────────────────────────────────────


class TrackingApplicant(BaseModel):
    """实例申请人摘要。"""

    id: UUID
    name: str | None = Field(None, description="申请人显示名（缺失时回退 email 前缀）")


# ── 当前节点（节点可视化要求 — user feedback_node_visualization）────────────


class TrackingCurrentActor(BaseModel):
    """当前节点等待的 actor。"""

    email: str | None = Field(None, description="当前 actor 邮箱")
    name: str | None = Field(None, description="当前 actor 显示名")


class TrackingCurrentNode(BaseModel):
    """当前正在等待的节点（active 节点高亮 + 倒计时）。

    None → 实例已终态（completed/failed/aborted），无 current_node。
    """

    id: str = Field(..., description="DSL 中的节点 ID（如 hitl_review_1）")
    title: str | None = Field(None, description="节点 DSL 配置中的 title")
    status: str = Field(..., description="状态：pending/waiting_human/in_review")
    node_type: str = Field(..., description="节点类型：hitl/llm/tool/...")
    actor: TrackingCurrentActor | None = Field(None, description="当前等待的 actor")
    deadline_at: str | None = Field(None, description="截止时间（ISO8601 字符串）")
    started_at: str | None = Field(None, description="节点开始时间")


# ── 顶层响应 ──────────────────────────────────────────────────────────────────


class TrackingResponse(BaseModel):
    """申请人追踪页响应。

    CONTEXT §申请人追踪页隐私：
    - records 已在 service 层按用户角色脱敏（admin 见全；申请人 ip/ua=None）
    - current_node None 表示实例已终态
    """

    instance_id: UUID
    status: str = Field(..., description="实例状态：pending/running/completed/failed/aborted")
    workflow_id: UUID
    applicant: TrackingApplicant
    current_node: TrackingCurrentNode | None = Field(
        None,
        description="当前正在等待的节点；终态实例为 None",
    )
    records: list[TrackingRecord] = Field(
        default_factory=list,
        description="所有节点聚合后的决策时间线，按 ts ASC 排序",
    )
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
