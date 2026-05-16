"""工作流 CRUD + 草稿/发布/校验 API（v1）。

端点列表（7 个）：
  POST   /workflows               — 创建工作流（editor+）
  GET    /workflows               — 列出工作流（viewer+）
  GET    /workflows/{id}          — 获取工作流详情（viewer+）
  PUT    /workflows/{id}/draft    — 保存草稿（editor+）
  POST   /workflows/{id}/publish  — 发布（editor+）
  DELETE /workflows/{id}          — 删除（admin）
  POST   /workflows/validate      — 独立校验 DSL（viewer+）

所有查询走 WorkspaceScopedQuery（CLAUDE.md 2.4）。
鉴权通过 require_role() Depends 工厂。

Dify 参考：api/controllers/console/app/workflow.py — save_draft/publish 双态
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_current_user, require_role
from app.agent_builder.db.session import get_db
from app.agent_builder.models.user import User
from app.agent_builder.schemas.workflow import (
    CreateWorkflowRequest,
    SaveDraftRequest,
    ValidateRequest,
    ValidationResponse,
    ValidationErrorResponse,
    WorkflowDetail,
    WorkflowSummary,
)
from app.agent_builder.services.workflow_service import WorkflowService
from app.agent_builder.workflow.validator import DSLCompilationError

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _build_workflow_summary(wf) -> WorkflowSummary:
    """从 ORM 对象构建 WorkflowSummary。"""
    return WorkflowSummary(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        status=wf.status,
        created_by=wf.created_by,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


async def _build_workflow_detail(wf, service: WorkflowService) -> WorkflowDetail:
    """从 ORM 对象构建 WorkflowDetail（含 DSL）。"""
    draft_dsl = None
    published_dsl = None

    if wf.current_draft_version_id:
        draft_ver = await service.load_version(wf.current_draft_version_id)
        if draft_ver:
            draft_dsl = draft_ver.dsl

    if wf.current_published_version_id:
        pub_ver = await service.load_version(wf.current_published_version_id)
        if pub_ver:
            published_dsl = pub_ver.dsl

    return WorkflowDetail(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        status=wf.status,
        created_by=wf.created_by,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        draft_version_id=wf.current_draft_version_id,
        published_version_id=wf.current_published_version_id,
        draft_dsl=draft_dsl,
        published_dsl=published_dsl,
    )


# ── POST /workflows/validate（必须在 /{id} 路由之前注册，防止路由冲突）────────────

@router.post(
    "/validate",
    response_model=ValidationResponse,
    summary="校验 DSL（不保存）",
    description="独立校验 DSL，返回所有 error + warning，不创建/修改任何工作流。",
)
async def validate_only(
    req: ValidateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ValidationResponse:
    """校验 DSL，返回 errors[]（可能为空列表）。"""
    service = WorkflowService(db)
    errors = service._validator.validate(req.dsl)
    return ValidationResponse(
        errors=[
            ValidationErrorResponse(**e.to_dict())
            for e in errors
        ]
    )


# ── POST /workflows ────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=201,
    response_model=WorkflowSummary,
    summary="创建工作流",
    description="创建新工作流（初始 draft 状态，空 DSL：仅含 start + end 节点）。",
)
async def create_workflow(
    req: CreateWorkflowRequest,
    request: Request,
    _rbac: None = Depends(require_role("admin", "editor", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowSummary:
    """创建工作流，要求 editor 以上权限。"""
    ws_id: UUID = request.state.current_workspace_id
    service = WorkflowService(db)
    wf = await service.create_workflow(
        workspace_id=ws_id,
        name=req.name,
        description=req.description,
        user_id=current_user.id,
    )
    return _build_workflow_summary(wf)


# ── GET /workflows ─────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[WorkflowSummary],
    summary="列出工作流",
    description="列出当前 workspace 下所有工作流（支持 status / search 过滤）。",
)
async def list_workflows(
    status: str | None = None,
    search: str | None = None,
    request: Request = None,
    _rbac: None = Depends(require_role("admin", "editor", "viewer", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowSummary]:
    """列出工作流，viewer+ 可访问。"""
    ws_id: UUID = request.state.current_workspace_id
    service = WorkflowService(db)
    workflows = await service.list_workflows(
        workspace_id=ws_id,
        status=status,
        search=search,
    )
    return [_build_workflow_summary(wf) for wf in workflows]


# ── GET /workflows/{workflow_id} ───────────────────────────────────────────────

@router.get(
    "/{workflow_id}",
    response_model=WorkflowDetail,
    summary="获取工作流详情",
    description="获取工作流详情（含当前草稿 DSL + 当前发布 DSL）。",
)
async def get_workflow(
    workflow_id: UUID,
    request: Request,
    _rbac: None = Depends(require_role("admin", "editor", "viewer", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDetail:
    """获取工作流详情，viewer+ 可访问。"""
    ws_id: UUID = request.state.current_workspace_id
    service = WorkflowService(db)
    wf = await service.get_workflow(workflow_id=workflow_id, workspace_id=ws_id)
    return await _build_workflow_detail(wf, service)


# ── PUT /workflows/{workflow_id}/draft ────────────────────────────────────────

@router.put(
    "/{workflow_id}/draft",
    response_model=WorkflowDetail,
    summary="保存草稿",
    description=(
        "保存草稿 DSL。"
        "fatal error → 422 + errors[]；warning 可放行（返回 200 + warnings[]）。"
    ),
)
async def save_draft(
    workflow_id: UUID,
    req: SaveDraftRequest,
    request: Request,
    _rbac: None = Depends(require_role("admin", "editor", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDetail:
    """保存草稿，editor+ 可访问。"""
    ws_id: UUID = request.state.current_workspace_id
    service = WorkflowService(db)
    wf, errors = await service.save_draft(
        workflow_id=workflow_id,
        workspace_id=ws_id,
        dsl=req.dsl,
        user_id=current_user.id,
    )
    if wf is None:
        # fatal errors 存在，返回 422
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [e.to_dict() for e in errors],
            },
        )

    detail = await _build_workflow_detail(wf, service)
    return detail


# ── POST /workflows/{workflow_id}/publish ─────────────────────────────────────

@router.post(
    "/{workflow_id}/publish",
    response_model=WorkflowDetail,
    summary="发布工作流",
    description="发布工作流（DSL 必须无 fatal error）。成功后 status = published。",
)
async def publish_workflow(
    workflow_id: UUID,
    request: Request,
    _rbac: None = Depends(require_role("admin", "editor", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDetail:
    """发布工作流，editor+ 可访问。"""
    ws_id: UUID = request.state.current_workspace_id
    service = WorkflowService(db)
    try:
        wf = await service.publish(
            workflow_id=workflow_id,
            workspace_id=ws_id,
            user_id=current_user.id,
        )
    except DSLCompilationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [err.to_dict() for err in e.errors],
            },
        )
    return await _build_workflow_detail(wf, service)


# ── DELETE /workflows/{workflow_id} ────────────────────────────────────────────

@router.delete(
    "/{workflow_id}",
    status_code=204,
    summary="删除工作流",
    description="删除工作流（物理删除，级联删除所有版本和实例）。需要 admin 权限。",
)
async def delete_workflow(
    workflow_id: UUID,
    request: Request,
    _rbac: None = Depends(require_role("admin", "super_admin")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除工作流，admin 才能删除。"""
    ws_id: UUID = request.state.current_workspace_id
    service = WorkflowService(db)
    await service.delete_workflow(workflow_id=workflow_id, workspace_id=ws_id)
