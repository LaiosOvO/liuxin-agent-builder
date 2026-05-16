"""实例 CRUD API（v1）。

端点列表（5 个）：
  POST /workflows/{workflow_id}/instances     — 创建实例（editor+）
  GET  /instances                             — 列表（viewer+，filter/search/pagination）
  GET  /instances/{instance_id}               — 详情含 node_states[]（viewer+）
  GET  /instances/{instance_id}/tracking      — 申请人追踪页（applicant or admin）— HITL-07
  POST /instances/{instance_id}/abort         — 中止（editor+）

所有查询走 WorkspaceScopedQuery（CLAUDE.md 2.4）。

Dify 参考：api/controllers/console/app/workflow_run.py + WorkflowPauseDetailsResponse
（详见 docs/reading-dify-03-08-tracking-page-2026-05-17.md）
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_current_user, require_role
from app.agent_builder.db.session import get_db
from app.agent_builder.models.user import User
from app.agent_builder.schemas.instance import (
    CreateInstanceRequest,
    InstanceDetail,
    InstanceListResponse,
    InstanceSummary,
    NodeStateInfo,
)
from app.agent_builder.schemas.tracking import TrackingResponse
from app.agent_builder.services.instance_service import InstanceService

_log = logging.getLogger(__name__)

router = APIRouter(tags=["instances"])


def _to_instance_summary(inst) -> InstanceSummary:
    """ORM → InstanceSummary。"""
    return InstanceSummary(
        id=inst.id,
        workflow_id=inst.workflow_id,
        workflow_version_id=inst.workflow_version_id,
        status=inst.status,
        initial_input=inst.initial_input,
        error_message=inst.error_message,
        created_by=inst.created_by,
        created_at=inst.created_at,
        started_at=inst.started_at,
        completed_at=inst.completed_at,
    )


def _to_node_state_info(ns) -> NodeStateInfo:
    """ORM → NodeStateInfo。"""
    return NodeStateInfo(
        id=ns.id,
        node_id=ns.node_id,
        node_type=ns.node_type,
        status=ns.status,
        started_at=ns.started_at,
        completed_at=ns.completed_at,
        error_message=ns.error_message,
        retries=ns.retries,
        output_summary=ns.output_summary,
    )


# ── POST /workflows/{workflow_id}/instances ────────────────────────────────────

@router.post(
    "/workflows/{workflow_id}/instances",
    status_code=201,
    response_model=InstanceSummary,
    summary="创建实例",
    description=(
        "基于工作流已发布版本创建运行实例。"
        "工作流未发布时返回 409。"
    ),
)
async def start_instance(
    workflow_id: UUID,
    req: CreateInstanceRequest,
    request: Request,
    _rbac: None = Depends(require_role("admin", "editor", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InstanceSummary:
    """创建实例，editor+ 权限。"""
    ws_id: UUID = request.state.current_workspace_id
    service = InstanceService(db)
    inst = await service.start(
        workflow_id=workflow_id,
        workspace_id=ws_id,
        initial_input=req.initial_input,
        user_id=current_user.id,
    )
    return _to_instance_summary(inst)


# ── GET /instances ─────────────────────────────────────────────────────────────

@router.get(
    "/instances",
    response_model=InstanceListResponse,
    summary="列出实例",
    description=(
        "列出当前 workspace 下的实例，支持 workflow_id / status / search 过滤和分页。"
        "search 按实例 ID 前缀搜索。"
    ),
)
async def list_instances(
    workflow_id: UUID | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    request: Request = None,
    _rbac: None = Depends(require_role("admin", "editor", "viewer", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InstanceListResponse:
    """列出实例，viewer+ 权限。"""
    ws_id: UUID = request.state.current_workspace_id
    service = InstanceService(db)
    items, total = await service.list(
        workspace_id=ws_id,
        workflow_id=workflow_id,
        status=status,
        search=search,
        page=max(1, page),
        page_size=min(max(1, page_size), 100),
    )
    return InstanceListResponse(
        items=[_to_instance_summary(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── GET /instances/{instance_id} ──────────────────────────────────────────────

@router.get(
    "/instances/{instance_id}",
    response_model=InstanceDetail,
    summary="获取实例详情",
    description="获取实例详情，含 node_states[] timeline（Dify NodeExecution 对应物）。",
)
async def get_instance(
    instance_id: UUID,
    request: Request,
    _rbac: None = Depends(require_role("admin", "editor", "viewer", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InstanceDetail:
    """获取实例详情，viewer+ 权限。"""
    ws_id: UUID = request.state.current_workspace_id
    service = InstanceService(db)
    inst, node_states = await service.get(instance_id=instance_id, workspace_id=ws_id)
    return InstanceDetail(
        id=inst.id,
        workflow_id=inst.workflow_id,
        workflow_version_id=inst.workflow_version_id,
        status=inst.status,
        initial_input=inst.initial_input,
        final_output=inst.final_output,
        dsl_snapshot=inst.dsl_snapshot,
        error_message=inst.error_message,
        created_by=inst.created_by,
        created_at=inst.created_at,
        started_at=inst.started_at,
        completed_at=inst.completed_at,
        node_states=[_to_node_state_info(ns) for ns in node_states],
    )


# ── GET /instances/{instance_id}/tracking ─────────────────────────────────────


@router.get(
    "/instances/{instance_id}/tracking",
    response_model=TrackingResponse,
    summary="获取实例追踪信息（HITL-07 申请人追踪页）",
    description=(
        "申请人本人或当前工作区 admin 可访问。"
        "返回 instance 状态 + 当前节点 + 决策时间线。"
        "非 admin 申请人视角 records 中 ip/ua 字段会被脱敏为 null。"
    ),
    responses={
        403: {"description": "非该实例的申请人，且非 admin"},
        404: {"description": "实例不存在（跨 workspace 也返回 404）"},
    },
)
async def get_instance_tracking(
    instance_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingResponse:
    """获取实例追踪信息，applicant or admin 权限。

    权限规则（CONTEXT §申请人追踪页隐私）：
    - 跨 workspace（实例查不到）→ 404
    - 同 workspace 但 applicant_id != current_user.id 且非 admin → 403
    - 申请人本人 → 200，records 中 ip/ua 脱敏为 None
    - admin / super_admin → 200，records 完整含 ip/ua
    """
    ws_id: UUID = request.state.current_workspace_id
    service = InstanceService(db)
    data = await service.get_tracking_for_applicant(
        instance_id=instance_id,
        workspace_id=ws_id,
        current_user=current_user,
    )
    return TrackingResponse.model_validate(data)


# ── POST /instances/{instance_id}/abort ───────────────────────────────────────

@router.post(
    "/instances/{instance_id}/abort",
    response_model=InstanceSummary,
    summary="中止实例",
    description="中止运行中或等待中的实例（status → aborted）。editor+ 权限。",
)
async def abort_instance(
    instance_id: UUID,
    request: Request,
    _rbac: None = Depends(require_role("admin", "editor", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InstanceSummary:
    """中止实例，editor+ 权限。"""
    ws_id: UUID = request.state.current_workspace_id
    service = InstanceService(db)
    inst = await service.abort(
        instance_id=instance_id,
        workspace_id=ws_id,
        user_id=current_user.id,
    )
    return _to_instance_summary(inst)
