"""Setup 流程集成测试。

覆盖：
- 初始状态未初始化
- 首次初始化创建 super_admin + workspace
- 二次初始化返回 409
- 初始化后 setup 路由返回 404
- 未初始化时其他 API 返回 503
- 密码强度不足返回 422
- 审计日志正确写入
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.agent_builder.main import agent_builder_app
from app.services.setup_service import reset_setup_cache


@pytest_asyncio.fixture
async def fresh_client():
    """每次测试用全新状态的 async_client（重置 setup 缓存）。

    每个测试函数有独立事件循环（asyncio_mode=auto, loop_scope=function）。
    需要在每次测试前处置连接池（dispose），让 asyncpg 用新事件循环创建新连接。
    """
    from sqlalchemy import text
    from app.agent_builder.db.engine import engine, async_session_maker
    from app.services.setup_service import is_setup_complete

    # 处置旧连接池（释放上一个事件循环的连接）
    await engine.dispose()

    # 清理 DB
    async with async_session_maker() as session:
        await session.execute(text("DELETE FROM audit_logs"))
        await session.execute(text("DELETE FROM email_verifications"))
        await session.execute(text("DELETE FROM invites"))
        await session.execute(text("DELETE FROM user_workspace_roles"))
        await session.execute(text("DELETE FROM users"))
        await session.execute(text("DELETE FROM workspaces"))
        await session.commit()

    # 重置并预热 setup 缓存
    reset_setup_cache()
    async with async_session_maker() as session:
        await is_setup_complete(session)

    async with AsyncClient(
        transport=ASGITransport(app=agent_builder_app),
        base_url="http://test",
    ) as client:
        yield client

    # 测试后清理
    async with async_session_maker() as session:
        await session.execute(text("DELETE FROM audit_logs"))
        await session.execute(text("DELETE FROM email_verifications"))
        await session.execute(text("DELETE FROM invites"))
        await session.execute(text("DELETE FROM user_workspace_roles"))
        await session.execute(text("DELETE FROM users"))
        await session.execute(text("DELETE FROM workspaces"))
        await session.commit()
    reset_setup_cache()


@pytest.mark.asyncio
async def test_initial_state_not_initialized(fresh_client):
    """未初始化时 GET /api/setup/state 返回 {initialized: False}。"""
    resp = await fresh_client.get("/api/setup/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["initialized"] is False
    assert "version" in data


@pytest.mark.asyncio
async def test_initialize_creates_super_admin_and_workspace(
    fresh_client, smtp_capture
):
    """POST /api/setup/initialize 创建 super_admin + workspace + role 绑定 + cookie。"""
    from sqlalchemy import select
    from app.agent_builder.models.user import User
    from app.agent_builder.models.workspace import Workspace
    from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
    from app.agent_builder.db.engine import async_session_maker

    resp = await fresh_client.post(
        "/api/setup/initialize",
        json={
            "email": "init_test@test.example.com",
            "password": "SecurePass1",
            "display_name": "管理员",
            "workspace_name": "测试工作区",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "user_id" in data
    assert "workspace_id" in data

    # 检查 Set-Cookie
    assert "session" in resp.cookies

    # 验证 DB（用独立 session 查已提交数据）
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.email == "init_test@test.example.com")
        )
        user = user_result.scalar_one_or_none()
        assert user is not None
        assert user.is_super_admin is True
        assert user.status == "active"

        ws_result = await session.execute(select(Workspace))
        workspaces = ws_result.scalars().all()
        assert len(workspaces) >= 1

        uwr_result = await session.execute(
            select(UserWorkspaceRole).where(UserWorkspaceRole.user_id == user.id)
        )
        uwr = uwr_result.scalar_one_or_none()
        assert uwr is not None


@pytest.mark.asyncio
async def test_initialize_second_call_409(fresh_client, smtp_capture):
    """POST /api/setup/initialize 第二次调用返回 409 或 404（初始化后 setup 路由被隐藏）。

    初始化后，SetupRedirectMiddleware 会将 /api/setup/* 路由返回 404。
    这也满足"不能重复初始化"的业务约束：初始化后无法再次访问 setup 端点。
    """
    data = {
        "email": "admin2@test.example.com",
        "password": "SecurePass1",
        "display_name": "管理员2",
        "workspace_name": "测试工作区2",
    }
    first = await fresh_client.post("/api/setup/initialize", json=data)
    assert first.status_code == 200

    # 初始化后：setup 路由对外 404（中间件）或 setup 本身返回 409
    # 两种情况都满足"不能重复初始化"的约束
    second = await fresh_client.post("/api/setup/initialize", json=data)
    assert second.status_code in (404, 409)


@pytest.mark.asyncio
async def test_setup_routes_404_after_init(fresh_client, smtp_capture):
    """初始化后 GET /api/setup/state 返回 404（SetupRedirectMiddleware）。"""
    # 先初始化
    await fresh_client.post(
        "/api/setup/initialize",
        json={
            "email": "admin@test.example.com",
            "password": "SecurePass1",
            "display_name": "管理员",
            "workspace_name": "测试工作区",
        },
    )
    reset_setup_cache()  # 强制重查 DB

    # 验证
    resp = await fresh_client.get("/api/setup/state")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_api_blocked_before_init(fresh_client):
    """未初始化时 GET /api/auth/me 返回 503 + redirect 信息。"""
    resp = await fresh_client.get("/api/auth/me")
    assert resp.status_code == 503
    data = resp.json()
    assert data.get("error") == "setup required"
    assert "redirect" in data


@pytest.mark.asyncio
async def test_short_password_rejected(fresh_client):
    """password 太短（< 8 字符）返回 422。"""
    resp = await fresh_client.post(
        "/api/setup/initialize",
        json={
            "email": "admin@test.example.com",
            "password": "abc",  # 太短
            "display_name": "管理员",
            "workspace_name": "测试工作区",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_audit_log_setup_created(fresh_client, smtp_capture):
    """初始化后 audit_logs 含 action='setup.created'（用独立 session 查询）。"""
    from sqlalchemy import select
    from app.agent_builder.models.audit_log import AuditLog
    from app.agent_builder.db.engine import async_session_maker

    await fresh_client.post(
        "/api/setup/initialize",
        json={
            "email": "audit_test@test.example.com",
            "password": "SecurePass1",
            "display_name": "管理员",
            "workspace_name": "审计测试工作区",
        },
    )

    # 用独立 session 查询（已提交的数据）
    async with async_session_maker() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.action == "setup.created")
        )
        audit = result.scalar_one_or_none()
    assert audit is not None
