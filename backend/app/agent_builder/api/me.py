"""用户 profile 相关 API 路由。

端点：
- GET  /api/auth/me                         : 获取当前用户信息
- POST /api/me/workspaces/{workspace_id}/switch: 切换到指定工作区
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_current_user, _get_user_workspace_role
from app.agent_builder.db.session import get_db
from app.agent_builder.models.role import Role
from app.agent_builder.models.user import User
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.agent_builder.models.workspace import Workspace
from app.schemas.me import MeResponse, UpdateProfileRequest, UserInfo, WorkspaceInfo
from app.services.jwt_service import sign_session

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/auth/me", response_model=MeResponse)
async def get_me(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MeResponse:
    """获取当前用户的完整 profile 信息。

    包含：
    - 用户基本信息
    - 当前工作区信息 + 角色
    - 所有工作区列表（含角色）

    Args:
        request: FastAPI Request
        db: AsyncSession
        current_user: 当前登录用户（已验证）

    Returns:
        MeResponse
    """
    ws_id: uuid.UUID = request.state.current_workspace_id

    # 加载当前工作区
    ws_result = await db.execute(select(Workspace).where(Workspace.id == ws_id))
    current_ws = ws_result.scalar_one_or_none()

    current_role_code = await _get_user_workspace_role(current_user, ws_id, db)

    current_ws_info = None
    if current_ws:
        current_ws_info = WorkspaceInfo(
            id=current_ws.id,
            name=current_ws.name,
            slug=current_ws.slug,
            role=current_role_code or "unknown",
        )

    # 加载用户所属的全部工作区
    workspaces: list[WorkspaceInfo] = []
    if current_user.is_super_admin:
        # super_admin 可查看所有工作区
        all_ws_result = await db.execute(select(Workspace).limit(100))
        all_workspaces = all_ws_result.scalars().all()
        for ws in all_workspaces:
            workspaces.append(
                WorkspaceInfo(
                    id=ws.id,
                    name=ws.name,
                    slug=ws.slug,
                    role="super_admin",
                )
            )
    else:
        uwr_result = await db.execute(
            select(UserWorkspaceRole, Workspace, Role)
            .join(Workspace, Workspace.id == UserWorkspaceRole.workspace_id)
            .join(Role, Role.id == UserWorkspaceRole.role_id)
            .where(UserWorkspaceRole.user_id == current_user.id)
        )
        for uwr, ws, role in uwr_result.all():
            workspaces.append(
                WorkspaceInfo(
                    id=ws.id,
                    name=ws.name,
                    slug=ws.slug,
                    role=role.code,
                )
            )

    user_info = UserInfo(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        department=current_user.department,
        status=current_user.status,
        is_super_admin=current_user.is_super_admin,
        created_at=current_user.created_at,
        last_login_at=current_user.last_login_at,
    )

    return MeResponse(
        user=user_info,
        current_workspace=current_ws_info,
        workspaces=workspaces,
    )


@router.post("/me/workspaces/{workspace_id}/switch")
async def switch_workspace(
    workspace_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """切换到指定工作区（重签 session cookie，ws claim 更新）。

    要求：当前用户必须是目标工作区的成员（或 super_admin）。

    Args:
        workspace_id: 目标工作区 ID（路径参数）

    Returns:
        {message, workspace_id, role}（同时 Set-Cookie: session 更新 ws）
    """
    # 校验用户是否属于目标 workspace
    role_code = await _get_user_workspace_role(current_user, workspace_id, db)

    if role_code is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您不属于该工作区",
        )

    # 验证 workspace 存在
    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = ws_result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工作区不存在",
        )

    # 重签 session token（更新 ws claim）
    new_session_token = sign_session(current_user.id, workspace_id)

    is_production = os.environ.get("APP_ENV", "development") == "production"
    response.set_cookie(
        key="session",
        value=new_session_token,
        httponly=True,
        samesite="lax",
        secure=is_production,
        max_age=86400,
    )

    log.info(
        "切换工作区：user=%s → workspace=%s",
        current_user.id,
        workspace_id,
    )

    return {
        "message": f"已切换到工作区 {workspace.name}",
        "workspace_id": str(workspace_id),
        "role": role_code,
    }
