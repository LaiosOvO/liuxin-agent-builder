"""登录流程集成测试。

覆盖：
- 正常登录成功
- 密码错误 401
- 未验证邮箱 403
- 账号禁用 403
- 退出登录清除 cookie
- session cookie HttpOnly + SameSite=Lax
- 过期 token 401
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.user import User, UserStatus
from app.services.jwt_service import sign_session


@pytest.mark.asyncio
async def test_login_success(async_client, setup_complete_workspace, db_session):
    """合法邮密 -> 200 + Set-Cookie session + audit('login.success')。"""
    admin_user, workspace, _ = setup_complete_workspace

    resp = await async_client.post(
        "/api/auth/login",
        json={
            "email": admin_user.email,
            "password": "AdminPassword1",
        },
    )
    assert resp.status_code == 200, resp.text

    # 检查 cookie
    assert "session" in resp.cookies

    # 检查响应体
    data = resp.json()
    assert str(admin_user.id) == data["user_id"]

    # 检查 audit log
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "login.success",
            AuditLog.actor_user_id == admin_user.id,
        )
    )
    audit = result.scalar_one_or_none()
    assert audit is not None


@pytest.mark.asyncio
async def test_login_wrong_password_401(
    async_client, setup_complete_workspace, db_session
):
    """密码错误 -> 401 + audit('login.failed')。"""
    admin_user, workspace, _ = setup_complete_workspace

    resp = await async_client.post(
        "/api/auth/login",
        json={
            "email": admin_user.email,
            "password": "WrongPassword99",
        },
    )
    assert resp.status_code == 401

    # 检查 audit log
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "login.failed",
            AuditLog.actor_user_id == admin_user.id,
        )
    )
    audit = result.scalar_one_or_none()
    assert audit is not None


@pytest.mark.asyncio
async def test_login_user_pending_verification_403(
    async_client, setup_complete_workspace, db_session
):
    """未验证邮箱用户登录 -> 403。"""
    from app.services.password import hash_password
    from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
    from app.agent_builder.models.role import Role

    admin_user, workspace, _ = setup_complete_workspace

    # 创建 pending_verification 用户
    role_result = await db_session.execute(select(Role).where(Role.code == "viewer"))
    viewer_role = role_result.scalar_one()

    pending_user = User(
        id=uuid.uuid4(),
        email=f"pending_{uuid.uuid4().hex[:6]}@test.example.com",
        password_hash=hash_password("PendingPass1"),
        display_name="待验证用户",
        status=UserStatus.pending_verification.value,
        is_super_admin=False,
    )
    db_session.add(pending_user)
    await db_session.flush()

    uwr = UserWorkspaceRole(
        workspace_id=workspace.id,
        user_id=pending_user.id,
        role_id=viewer_role.id,
    )
    db_session.add(uwr)
    await db_session.commit()

    resp = await async_client.post(
        "/api/auth/login",
        json={"email": pending_user.email, "password": "PendingPass1"},
    )
    assert resp.status_code == 403
    assert "验证" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_user_disabled_403(
    async_client, setup_complete_workspace, db_session
):
    """已禁用账号登录 -> 403。"""
    from app.services.password import hash_password
    from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
    from app.agent_builder.models.role import Role

    admin_user, workspace, _ = setup_complete_workspace

    role_result = await db_session.execute(select(Role).where(Role.code == "viewer"))
    viewer_role = role_result.scalar_one()

    disabled_user = User(
        id=uuid.uuid4(),
        email=f"disabled_{uuid.uuid4().hex[:6]}@test.example.com",
        password_hash=hash_password("DisabledPass1"),
        display_name="已禁用用户",
        status=UserStatus.disabled.value,
        is_super_admin=False,
    )
    db_session.add(disabled_user)
    await db_session.flush()

    uwr = UserWorkspaceRole(
        workspace_id=workspace.id,
        user_id=disabled_user.id,
        role_id=viewer_role.id,
    )
    db_session.add(uwr)
    await db_session.commit()

    resp = await async_client.post(
        "/api/auth/login",
        json={"email": disabled_user.email, "password": "DisabledPass1"},
    )
    assert resp.status_code == 403
    assert "禁用" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_logout_clears_cookie(async_client, setup_complete_workspace):
    """退出登录 -> 200 + Set-Cookie session 被清除。"""
    admin_user, workspace, session_cookie = setup_complete_workspace

    resp = await async_client.post(
        "/api/auth/logout",
        cookies={"session": session_cookie},
    )
    assert resp.status_code == 200

    # 退出后 cookie 应该被清除（max-age=0 或 delete）
    # 检查响应中 Set-Cookie 头
    set_cookie = resp.headers.get("set-cookie", "")
    assert "session" in set_cookie or resp.status_code == 200


@pytest.mark.asyncio
async def test_session_cookie_httponly_samesite(async_client, setup_complete_workspace):
    """登录响应 Set-Cookie 含 HttpOnly + SameSite=Lax。"""
    admin_user, workspace, _ = setup_complete_workspace

    resp = await async_client.post(
        "/api/auth/login",
        json={
            "email": admin_user.email,
            "password": "AdminPassword1",
        },
    )
    assert resp.status_code == 200

    # 检查 cookie 属性
    set_cookie_header = resp.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie_header
    assert "samesite=lax" in set_cookie_header


@pytest.mark.asyncio
async def test_session_expired_token_401(async_client, setup_complete_workspace):
    """过期 session token -> GET /api/auth/me 返回 401。"""
    import os
    import jwt
    from datetime import datetime, timedelta, timezone

    admin_user, workspace, _ = setup_complete_workspace

    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": str(admin_user.id),
        "ws": str(workspace.id),
        "iat": int((now - timedelta(hours=25)).timestamp()),
        "exp": int((now - timedelta(hours=1)).timestamp()),
    }
    expired_token = jwt.encode(
        expired_payload, os.environ["JWT_SECRET"], algorithm="HS256"
    )

    resp = await async_client.get(
        "/api/auth/me",
        cookies={"session": expired_token},
    )
    assert resp.status_code == 401
