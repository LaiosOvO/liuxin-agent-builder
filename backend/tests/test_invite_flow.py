"""邀请流程集成测试。

覆盖：
- admin 创建邀请（成功）
- editor 创建邀请（403）
- GET 预览不消费 jti
- POST accept 创建用户 + 绑定角色 + 消费 jti
- 重放攻击（409）
- 过期 token（410）
- 邮件捕获验证
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.invite import Invite
from app.agent_builder.models.user import User
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.services.jwt_service import sign_invite


@pytest.mark.asyncio
async def test_admin_can_create_invite(
    async_client, setup_complete_workspace, smtp_capture, db_session
):
    """admin POST /api/invites -> 201 + DB 有 invite 行 + 捕获邮件。"""
    admin_user, workspace, session_cookie = setup_complete_workspace

    resp = await async_client.post(
        "/api/invites",
        json={
            "email": "invited@test.example.com",
            "role_code": "editor",
        },
        cookies={"session": session_cookie},
    )
    assert resp.status_code == 201, resp.text

    # 检查 DB
    result = await db_session.execute(
        select(Invite).where(Invite.workspace_id == workspace.id)
    )
    invites = result.scalars().all()
    assert len(invites) == 1
    assert invites[0].email == "invited@test.example.com"

    # 检查邮件捕获
    assert len(smtp_capture) >= 1


@pytest.mark.asyncio
async def test_editor_cannot_create_invite(
    async_client, two_workspaces, db_session
):
    """editor POST /api/invites -> 403 + audit('rbac.denied')。"""
    ws_a = two_workspaces["ws_a"]
    editor, editor_cookie = two_workspaces["ws_a_editor"]

    resp = await async_client.post(
        "/api/invites",
        json={
            "email": "newinvite@test.example.com",
            "role_code": "viewer",
        },
        cookies={"session": editor_cookie},
    )
    assert resp.status_code == 403, resp.text

    # 检查 audit log
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "rbac.denied",
            AuditLog.workspace_id == ws_a.id,
        )
    )
    audit = result.scalar_one_or_none()
    assert audit is not None


@pytest.mark.asyncio
async def test_invite_preview_get_does_not_consume(
    async_client, setup_complete_workspace, smtp_capture, db_session
):
    """GET /api/invites/accept?token= -> 200 + DB invites.used_at IS NULL。"""
    admin_user, workspace, session_cookie = setup_complete_workspace

    # 创建邀请
    await async_client.post(
        "/api/invites",
        json={"email": "preview@test.example.com", "role_code": "viewer"},
        cookies={"session": session_cookie},
    )

    # 获取 token 从 DB
    result = await db_session.execute(
        select(Invite).where(Invite.workspace_id == workspace.id)
    )
    invite = result.scalar_one_or_none()
    assert invite is not None

    # 用 jwt_service 重签一个 token（因为 DB 存了 token_hash，没存 token 明文）
    # 这里直接从新签一个 token 来测试 preview 端点的 GET 不消费逻辑
    from app.services.jwt_service import sign_invite, compute_token_hash

    token, jti = sign_invite(
        workspace_id=workspace.id,
        email="preview@test.example.com",
        role_code="viewer",
        invited_by=admin_user.id,
    )

    # 更新 DB 中的 invite 用新 jti
    invite.jti = jti
    invite.token_hash = compute_token_hash(token)
    db_session.add(invite)
    await db_session.commit()

    # GET 预览（多次调用不消费）
    for _ in range(3):
        resp = await async_client.get(f"/api/invites/accept?token={token}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["already_used"] is False

    # 验证 DB used_at 仍为 NULL
    await db_session.refresh(invite)
    assert invite.used_at is None


@pytest.mark.asyncio
async def test_accept_invite_creates_user_and_role(
    async_client, setup_complete_workspace, smtp_capture, db_session
):
    """POST /api/invites/accept -> 200 + 用户创建 + role 绑定 + jti consumed + auto-login。"""
    admin_user, workspace, session_cookie = setup_complete_workspace

    from app.services.jwt_service import sign_invite, compute_token_hash
    from datetime import datetime, timedelta, timezone

    # 创建 invite 记录
    token, jti = sign_invite(
        workspace_id=workspace.id,
        email="newmember@test.example.com",
        role_code="editor",
        invited_by=admin_user.id,
    )
    from app.agent_builder.models.invite import Invite as InviteModel

    invite = InviteModel(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        email="newmember@test.example.com",
        target_role_code="editor",
        jti=jti,
        token_hash=compute_token_hash(token),
        invited_by=admin_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(invite)
    await db_session.commit()

    # POST accept
    resp = await async_client.post(
        "/api/invites/accept",
        json={
            "token": token,
            "password": "NewMember1",
            "display_name": "新成员",
        },
    )
    assert resp.status_code == 200, resp.text

    # 自动登录 cookie
    assert "session" in resp.cookies

    # 验证用户创建
    user_result = await db_session.execute(
        select(User).where(User.email == "newmember@test.example.com")
    )
    new_user = user_result.scalar_one_or_none()
    assert new_user is not None
    assert new_user.status == "active"

    # 验证 role 绑定
    uwr_result = await db_session.execute(
        select(UserWorkspaceRole).where(
            UserWorkspaceRole.user_id == new_user.id,
            UserWorkspaceRole.workspace_id == workspace.id,
        )
    )
    uwr = uwr_result.scalar_one_or_none()
    assert uwr is not None

    # 验证 jti 已消费
    await db_session.refresh(invite)
    assert invite.used_at is not None


@pytest.mark.asyncio
async def test_invite_token_replay_409(
    async_client, setup_complete_workspace, smtp_capture, db_session
):
    """同一 token POST /api/invites/accept 两次 -> 409。"""
    admin_user, workspace, session_cookie = setup_complete_workspace

    from app.services.jwt_service import sign_invite, compute_token_hash
    from app.agent_builder.models.invite import Invite as InviteModel

    token, jti = sign_invite(
        workspace_id=workspace.id,
        email="replay@test.example.com",
        role_code="viewer",
        invited_by=admin_user.id,
    )
    invite = InviteModel(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        email="replay@test.example.com",
        target_role_code="viewer",
        jti=jti,
        token_hash=compute_token_hash(token),
        invited_by=admin_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(invite)
    await db_session.commit()

    body = {"token": token, "password": "ReplayPass1", "display_name": "重放用户"}

    first = await async_client.post("/api/invites/accept", json=body)
    assert first.status_code == 200

    second = await async_client.post("/api/invites/accept", json=body)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_invite_token_expired(
    async_client, setup_complete_workspace, smtp_capture, db_session
):
    """过期邀请 token -> 410。"""
    admin_user, workspace, session_cookie = setup_complete_workspace

    import jwt as pyjwt
    import os
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    expired_payload = {
        "jti": str(uuid.uuid4()),
        "workspace_id": str(workspace.id),
        "email": "expired@test.example.com",
        "target_role": "viewer",
        "invited_by": str(admin_user.id),
        "purpose": "invite",
        "iat": int((now - timedelta(hours=25)).timestamp()),
        "exp": int((now - timedelta(hours=1)).timestamp()),
    }
    expired_token = pyjwt.encode(
        expired_payload, os.environ["JWT_SECRET"], algorithm="HS256"
    )

    resp = await async_client.post(
        "/api/invites/accept",
        json={
            "token": expired_token,
            "password": "ExpiredPass1",
            "display_name": "过期用户",
        },
    )
    assert resp.status_code == 410
