"""邀请流程 API 路由。

端点：
- POST /api/invites           : admin 签发邀请（require_role admin/super_admin）
- GET  /api/invites/list      : admin 查看邀请列表
- GET  /api/invites/accept    : 预览邀请信息（公开，不消费 jti）
- POST /api/invites/accept    : 接受邀请、注册、自动登录（公开，消费 jti）

Workspace 隔离：POST /api/invites 和 GET /api/invites/list 通过 session cookie
中的 ws 字段识别当前工作区，只在当前工作区内操作（无需路径参数）。
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_current_user, require_role
from app.agent_builder.db.session import get_db
from app.agent_builder.models.invite import Invite
from app.agent_builder.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.invite import (
    AcceptInviteRequest,
    CreateInviteRequest,
    InvitePreviewResponse,
)
from app.services.invite_service import (
    accept_invite,
    create_invite,
    preview_invite,
)
from app.services.jwt_service import (
    TokenAlreadyUsedError,
    TokenExpired,
    TokenInvalid,
    sign_session,
)

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_invite_endpoint(
    request: Request,
    body: CreateInviteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rbac: None = Depends(require_role("admin", "super_admin")),
) -> MessageResponse:
    """admin 签发邀请（需要 admin 或 super_admin 角色）。

    从 session cookie 中的 ws 字段确定目标工作区，在当前工作区内操作。
    一次邀请一个邮箱，发送邀请邮件（24h 有效）。

    Args:
        body.email: 被邀请人邮箱
        body.role_code: 目标角色（admin/editor/viewer）
    """
    workspace_id: uuid.UUID = request.state.current_workspace_id

    try:
        invite = await create_invite(
            db=db,
            workspace_id=workspace_id,
            email=str(body.email),
            role_code=body.role_code,
            invited_by=current_user,
            request=request,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    log.info("邀请已发送：%s → %s", current_user.email, body.email)
    return MessageResponse(message=f"邀请邮件已发送至 {body.email}")


@router.get("/list")
async def list_invites(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rbac: None = Depends(require_role("admin", "super_admin")),
) -> dict:
    """查看当前工作区的邀请列表（admin only）。

    返回活跃和已使用的邀请记录。

    Returns:
        {invites: [...], total: N}
    """
    workspace_id: uuid.UUID = request.state.current_workspace_id

    result = await db.execute(
        select(Invite)
        .where(Invite.workspace_id == workspace_id)
        .order_by(Invite.created_at.desc())
        .limit(100)
    )
    invites = result.scalars().all()

    invite_list = [
        {
            "id": str(inv.id),
            "email": inv.email,
            "role_code": inv.target_role_code,
            "expires_at": inv.expires_at.isoformat(),
            "used_at": inv.used_at.isoformat() if inv.used_at else None,
            "created_at": inv.created_at.isoformat(),
        }
        for inv in invites
    ]

    return {"invites": invite_list, "total": len(invite_list)}


@router.get("/accept", response_model=InvitePreviewResponse)
async def preview_invite_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InvitePreviewResponse:
    """GET 预览邀请信息（公开端点，不消费 jti）。

    前端根据返回信息渲染注册表单（预填邮箱，不可修改）。

    Args:
        token: URL query 参数中的邀请 JWT token

    Returns:
        InvitePreviewResponse（工作区/角色/邀请人/过期时间/是否已用）
    """
    try:
        preview = await preview_invite(db=db, token=token)
    except TokenExpired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="邀请链接已过期，请联系管理员重新发送",
        )
    except TokenInvalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请链接无效",
        )

    return InvitePreviewResponse(
        workspace_name=preview.workspace_name,
        role_code=preview.role_code,
        inviter_display_name=preview.inviter_display_name,
        expires_at=preview.expires_at,
        already_used=preview.already_used,
        email=preview.email,
    )


@router.post("/accept", response_model=MessageResponse)
async def accept_invite_endpoint(
    request: Request,
    body: AcceptInviteRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """POST 落地：接受邀请，注册用户，自动登录。

    消费 jti（一次性），注册用户（直接 active 状态），签发 session cookie。

    Args:
        body.token: 邀请 JWT token
        body.password: 注册密码
        body.display_name: 显示名称
        body.department: 所属部门（可选）

    Returns:
        MessageResponse + Set-Cookie: session
    """
    try:
        user = await accept_invite(
            db=db,
            token=body.token,
            password=body.password,
            display_name=body.display_name,
            department=body.department,
            request=request,
        )
        await db.commit()
    except TokenAlreadyUsedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邀请链接已被使用，请联系管理员重新发送",
        )
    except TokenExpired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="邀请链接已过期，请联系管理员重新发送",
        )
    except TokenInvalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请链接无效",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    # 查询 workspace_id（从邀请 token 中已解析到 user 的 workspace 绑定）
    from sqlalchemy import select as sa_select

    from app.agent_builder.models.user_workspace_role import UserWorkspaceRole

    uwr_result = await db.execute(
        sa_select(UserWorkspaceRole)
        .where(UserWorkspaceRole.user_id == user.id)
        .limit(1)
    )
    uwr = uwr_result.scalar_one_or_none()
    workspace_id = uwr.workspace_id if uwr else uuid.uuid4()

    # 签发 session token（自动登录）
    session_token = sign_session(user.id, workspace_id)

    is_production = os.environ.get("APP_ENV", "development") == "production"
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=is_production,
        max_age=86400,
    )

    log.info("邀请注册成功：user=%s", user.id)
    return MessageResponse(message="注册成功，已自动登录")
