"""邀请流程服务。

流程：
1. create_invite: admin 签发邀请 token + 发邮件 + 写 DB + 写 audit
2. preview_invite: GET 用，验证 token 有效性（不消费 jti）
3. accept_invite: POST 落地，消费 jti → 注册用户 → 发欢迎邮件

邀请 token 安全规则：
- jti 存 invites 表，UNIQUE + used_at IS NULL → 一次性消费
- 消费用 decode_consume_jti（UPDATE WHERE used_at IS NULL RETURNING *）
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.invite import Invite
from app.agent_builder.models.user import User
from app.agent_builder.models.workspace import Workspace
from app.services import audit as audit_service
from app.services.email_service import send_invitation_email, send_welcome_email
from app.services.jwt_service import (
    TokenAlreadyUsedError,
    TokenExpired,
    TokenInvalid,
    compute_token_hash,
    decode_consume_jti,
    decode_verify_only,
    sign_invite,
)

log = logging.getLogger(__name__)


@dataclass
class InvitePreview:
    """邀请预览信息（GET 用，不消费 jti）。"""

    workspace_name: str
    role_code: str
    inviter_display_name: str
    expires_at: datetime
    already_used: bool
    email: str  # 预填邮箱（前端锁定不可修改）


async def create_invite(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    email: str,
    role_code: str,
    invited_by: User,
    request: Any = None,
) -> Invite:
    """admin 签发邀请 token + 发邮件 + 写 DB。

    Args:
        db: AsyncSession
        workspace_id: 目标工作区 ID
        email: 被邀请人邮箱
        role_code: 目标角色代码（admin/editor/viewer）
        invited_by: 邀请人 User 对象
        request: Request 对象

    Returns:
        Invite 对象（已写入 DB）

    Raises:
        ValueError: 工作区不存在 / 邮箱已有用户
    """
    # 验证工作区存在
    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    if workspace is None:
        raise ValueError(f"工作区 {workspace_id} 不存在")

    # 检查邮箱是否已有用户（已注册的用户不能通过邀请重新注册）
    from app.agent_builder.models.user import User as UserModel

    existing_user = await db.execute(
        select(UserModel).where(UserModel.email == email.lower())
    )
    if existing_user.scalar_one_or_none() is not None:
        raise ValueError(f"邮箱 {email} 已被注册，无法邀请")

    # 签发邀请 token
    token, jti = sign_invite(
        workspace_id=workspace_id,
        email=email.lower(),
        role_code=role_code,
        invited_by=invited_by.id,
    )
    token_hash = compute_token_hash(token)

    now_utc = datetime.now(timezone.utc)
    invite = Invite(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        email=email.lower(),
        target_role_code=role_code,
        jti=jti,
        token_hash=token_hash,
        invited_by=invited_by.id,
        expires_at=now_utc + timedelta(hours=24),
    )
    db.add(invite)
    await db.flush()

    # 写 audit_log
    await audit_service.log(
        db,
        action="invite.created",
        workspace_id=workspace_id,
        actor_user_id=invited_by.id,
        target_type="invite",
        target_id=invite.id,
        meta={
            "email": email,
            "role": role_code,
        },
        request=request,
    )

    # 发送邀请邮件
    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000")
    invitation_url = f"{base_url}/invite/accept?token={token}"
    inviter_name = invited_by.display_name or invited_by.email

    try:
        await send_invitation_email(
            to=email,
            invitation_url=invitation_url,
            workspace_name=workspace.name,
            role=role_code,
            invited_by_name=inviter_name,
            db=db,
            request=request,
        )
    except Exception as exc:
        log.warning("发送邀请邮件失败（不影响邀请创建）：%s", exc)

    return invite


async def preview_invite(
    db: AsyncSession,
    token: str,
) -> InvitePreview:
    """GET 预览邀请信息（不消费 jti）。

    用于前端渲染注册表单（预填邮箱、显示工作区/角色信息）。

    Args:
        db: AsyncSession
        token: 邀请 JWT 字符串

    Returns:
        InvitePreview 数据类

    Raises:
        TokenExpired: token 已过期
        TokenInvalid: token 无效
    """
    # 只校验签名 + exp，不消费 jti
    try:
        payload = decode_verify_only(token, expected_purpose="invite")
    except TokenExpired:
        raise
    except TokenInvalid:
        raise

    jti_str = payload.get("jti")
    workspace_id = uuid.UUID(payload["workspace_id"])
    email = payload["email"]
    role_code = payload["target_role"]
    invited_by_id = uuid.UUID(payload["invited_by"])

    # 查询邀请记录（判断是否已用）
    invite_result = await db.execute(
        select(Invite).where(Invite.jti == uuid.UUID(jti_str))
    )
    invite = invite_result.scalar_one_or_none()
    already_used = invite is not None and invite.used_at is not None

    # 查询工作区名称
    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    workspace_name = workspace.name if workspace else "未知工作区"

    # 查询邀请人名称
    inviter_result = await db.execute(
        select(User).where(User.id == invited_by_id)
    )
    inviter = inviter_result.scalar_one_or_none()
    inviter_name = (
        inviter.display_name or inviter.email
        if inviter
        else "管理员"
    )

    from datetime import timezone

    exp_ts = payload.get("exp", 0)
    expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)

    return InvitePreview(
        workspace_name=workspace_name,
        role_code=role_code,
        inviter_display_name=inviter_name,
        expires_at=expires_at,
        already_used=already_used,
        email=email,
    )


async def accept_invite(
    db: AsyncSession,
    token: str,
    password: str,
    display_name: str,
    department: str | None = None,
    request: Any = None,
) -> User:
    """POST 落地：消费邀请 token，注册用户，发欢迎邮件。

    Args:
        db: AsyncSession
        token: 邀请 JWT 字符串
        password: 明文密码
        display_name: 显示名称
        department: 所属部门（可选）
        request: Request 对象

    Returns:
        创建的 User 对象

    Raises:
        TokenExpired: token 已过期
        TokenInvalid: token 无效
        TokenAlreadyUsedError: 邀请已被接受
        ValueError: 密码强度不足
    """
    # 消费 jti（原子更新）
    payload = await decode_consume_jti(
        token=token,
        table="invites",
        db=db,
    )

    workspace_id = uuid.UUID(payload["workspace_id"])
    email = payload["email"]
    role_code = payload["target_role"]
    jti = uuid.UUID(payload["jti"])

    # 注册用户（register_user 内部会处理密码校验、邮箱重复等）
    from app.services.registration_service import register_user

    user = await register_user(
        db=db,
        email=email,
        password=password,
        display_name=display_name,
        workspace_id=workspace_id,
        role_code=role_code,
        department=department,
        invited_via_jti=jti,
        request=request,
    )

    # 邀请注册直接激活（已通过邀请链接验证邮箱所有权）
    user.status = "active"

    # 写 audit_log
    await audit_service.log(
        db,
        action="invite.accepted",
        workspace_id=workspace_id,
        actor_user_id=user.id,
        target_type="invite",
        meta={
            "email": email,
            "role": role_code,
            "jti": str(jti),
        },
        request=request,
    )

    # 发送欢迎邮件
    try:
        await send_welcome_email(
            to=email,
            display_name=display_name,
            db=db,
            request=request,
        )
    except Exception as exc:
        log.warning("发送欢迎邮件失败（不影响注册）：%s", exc)

    return user
