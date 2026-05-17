"""pytest 全局 fixtures。

约定（CLAUDE.md 2.2）：
- 集成测试用真实 Postgres / Redis（testcontainers），**禁止 mock 数据库**
- 单元测试可以不依赖容器，只跑纯 Python 逻辑
- ASGI client 通过 ASGITransport 直连 FastAPI app，不需要 uvicorn 真正起来

新增 fixtures（Plan 01-04）：
- smtp_capture: monkeypatch aiosmtplib.send，捕获发出的邮件
- setup_complete_workspace: 创建干净 admin + workspace，返回 (user, workspace, session_cookie)
- two_workspaces: 创建两个独立 workspace，各有 admin/editor/viewer 共 6 个用户
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

pytest_plugins = ["pytest_asyncio"]

# 使用 session 级事件循环，避免跨测试的 asyncpg 连接池冲突（engine 单例）
# 参考：pytest-asyncio 0.24+ 推荐配置
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )

# ── slowapi 测试环境：使用内存存储（不依赖 Redis）─────────────────────────────────
# 必须在导入任何使用 rate_limit 的模块之前设置
os.environ["SLOWAPI_STORAGE_URI"] = "memory://"

# ── 全局环境变量（测试用）────────────────────────────────────────────────────────
# 从 .env 读取（已在顶部通过 dotenv 加载），测试时 override 部分值

_TEST_POSTGRES_DSN = os.getenv(
    "TESTCONTAINER_PG_DSN",
    os.getenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://agent_builder:AfOrHwRgDZRcPUmUSRNt7czeCGt7@localhost:15432/agent_builder",
    ),
)

# 测试用固定密钥（startup_checks 需要 ≥ 32 字节）
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-bytes-minimum--!")
os.environ.setdefault("HMAC_SECRET", "test-hmac-secret-32-bytes-minimum-!")
os.environ.setdefault("POSTGRES_DSN", _TEST_POSTGRES_DSN)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:3000")
os.environ.setdefault("WEB_ORIGIN", "http://localhost:3000")


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """Postgres DSN。优先使用 TESTCONTAINER_PG_DSN env，否则起 testcontainers。

    返回 asyncpg 风格 DSN：postgresql+asyncpg://...
    """
    if env := os.getenv("TESTCONTAINER_PG_DSN"):
        return env
    # 使用 SSH 隧道 DB
    return _TEST_POSTGRES_DSN


@pytest.fixture(scope="session")
def redis_url() -> str:
    """Redis URL。优先使用 TESTCONTAINER_REDIS_URL env，否则起 testcontainers。"""
    if env := os.getenv("TESTCONTAINER_REDIS_URL"):
        return env
    pytest.importorskip("testcontainers.redis", reason="安装 testcontainers-redis 才能跑集成测试")
    from testcontainers.redis import RedisContainer

    container = RedisContainer("redis:7-alpine")
    container.start()
    host = container.get_container_host_ip()
    port = container.get_exposed_port(6379)
    yield f"redis://{host}:{port}/0"  # type: ignore[misc]
    container.stop()


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator:
    """FastAPI ASGI client，通过 ASGITransport 直连 agent_builder_app。

    集成测试用，需要真实 DB 可用。
    """
    from httpx import ASGITransport, AsyncClient

    from app.agent_builder.main import agent_builder_app

    async with AsyncClient(
        transport=ASGITransport(app=agent_builder_app), base_url="http://test"
    ) as client:
        yield client


# ── DB Session 工具 ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """每次测试前重置速率限制计数器。

    slowapi memory:// 存储在进程内持久，跨测试会累积计数导致误触发限流。
    此 fixture autouse=True，对所有测试透明生效。

    注意：test_rate_limit.py 中的 importlib.reload 会替换模块级 limiter 单例，
    导致 agent_builder_app.state.limiter 与重新加载的 limiter 不同。
    此 fixture 同时重置两者，确保跨测试的速率计数完全清零。
    """
    import app.agent_builder.security.rate_limit as rl_module
    # 重置模块级 limiter（reload 后可能是新对象）
    rl_module.limiter._storage.reset()

    # 同时重置 agent_builder_app 中存储的 limiter（避免 reload 后两者不一致）
    try:
        from app.agent_builder.main import agent_builder_app
        if hasattr(agent_builder_app.state, "limiter"):
            agent_builder_app.state.limiter._storage.reset()
    except Exception:
        pass

    yield


@pytest_asyncio.fixture
async def db_session():
    """直接返回 AsyncSession（集成测试写数据用）。

    每个函数作用域测试使用独立事件循环（asyncio_mode=function），
    需要在每次使用前 dispose 引擎，确保 asyncpg 连接绑定到当前事件循环。
    """
    from app.agent_builder.db.engine import async_session_maker, engine

    # 重置连接池（避免 "attached to a different loop" 错误）
    await engine.dispose()

    async with async_session_maker() as session:
        yield session
        await session.rollback()  # 测试后回滚，保持 DB 干净


@pytest_asyncio.fixture(autouse=False)
async def clean_db(db_session):
    """测试后清理 auth 相关表（保持 roles 种子数据）。"""
    yield
    from sqlalchemy import text

    # 按依赖顺序清理（FK 约束）
    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM email_verifications"))
    await db_session.execute(text("DELETE FROM invites"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()

    # 重置 setup 缓存
    from app.services.setup_service import reset_setup_cache
    reset_setup_cache()


# ── SMTP Capture Fixture ─────────────────────────────────────────────────────────


@pytest.fixture
def smtp_capture(monkeypatch):
    """Mock aiosmtplib.send，捕获发出的邮件到列表。

    用法：
        def test_foo(smtp_capture):
            # 调用触发邮件的代码
            assert len(smtp_capture) == 1
            assert smtp_capture[0]['To'] == 'test@example.com'
    """
    captured = []

    async def fake_send(**kwargs):
        msg = kwargs.get("message")
        if msg:
            captured.append({
                "To": msg.get("To"),
                "From": msg.get("From"),
                "Subject": msg.get("Subject"),
                "message": msg,
            })

    monkeypatch.setattr("aiosmtplib.send", fake_send)
    return captured


# ── Setup Complete Workspace Fixture ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def setup_complete_workspace(db_session, smtp_capture):
    """创建一个干净的 super_admin + workspace，返回 (user, workspace, session_cookie)。

    用于需要已初始化状态的测试。每次测试结束后重置。
    """
    from app.services.setup_service import initialize_first_admin, reset_setup_cache
    from app.services.jwt_service import sign_session

    reset_setup_cache()

    user, workspace = await initialize_first_admin(
        db=db_session,
        email=f"admin_{uuid.uuid4().hex[:8]}@test.example.com",
        password="AdminPassword1",
        display_name="测试管理员",
        workspace_name=f"测试工作区_{uuid.uuid4().hex[:6]}",
    )
    await db_session.commit()

    session_token = sign_session(user.id, workspace.id)

    yield user, workspace, session_token

    # 清理
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM email_verifications"))
    await db_session.execute(text("DELETE FROM invites"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()
    reset_setup_cache()


# ── Two Workspaces Fixture ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def two_workspaces(db_session, smtp_capture):
    """创建两个独立 workspace，各有 admin/editor/viewer 3 个用户共 6 个。

    返回 dict：{
        'ws_a': Workspace,
        'ws_b': Workspace,
        'ws_a_admin': (User, session_cookie),
        'ws_a_editor': (User, session_cookie),
        'ws_a_viewer': (User, session_cookie),
        'ws_b_admin': (User, session_cookie),
        'ws_b_editor': (User, session_cookie),
        'ws_b_viewer': (User, session_cookie),
        'super_admin': (User, session_cookie),
    }
    """
    from app.agent_builder.models.role import Role
    from app.agent_builder.models.user import User, UserStatus
    from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
    from app.agent_builder.models.workspace import Workspace
    from app.services.jwt_service import sign_session
    from app.services.password import hash_password
    from app.services.setup_service import reset_setup_cache
    from sqlalchemy import select

    reset_setup_cache()

    # 查询角色 ID
    roles = {}
    for code in ["super_admin", "admin", "editor", "viewer"]:
        result = await db_session.execute(select(Role).where(Role.code == code))
        role = result.scalar_one_or_none()
        if role:
            roles[code] = role.id

    def make_user(email_suffix: str) -> User:
        return User(
            id=uuid.uuid4(),
            email=f"{email_suffix}_{uuid.uuid4().hex[:6]}@test.example.com",
            password_hash=hash_password("TestPassword1"),
            display_name=email_suffix,
            status=UserStatus.active.value,
            is_super_admin=False,
        )

    def make_ws(name: str) -> Workspace:
        import re
        slug = re.sub(r"\s+", "-", name.lower()) + "-" + uuid.uuid4().hex[:6]
        return Workspace(id=uuid.uuid4(), name=name, slug=slug[:60])

    def make_uwr(ws_id, user_id, role_code) -> UserWorkspaceRole:
        return UserWorkspaceRole(
            workspace_id=ws_id,
            user_id=user_id,
            role_id=roles[role_code],
            granted_by=None,
        )

    # super_admin
    sa_user = User(
        id=uuid.uuid4(),
        email=f"superadmin_{uuid.uuid4().hex[:6]}@test.example.com",
        password_hash=hash_password("AdminPassword1"),
        display_name="超级管理员",
        status=UserStatus.active.value,
        is_super_admin=True,
    )
    db_session.add(sa_user)

    # ws_a
    ws_a = make_ws("工作区A")
    db_session.add(ws_a)
    await db_session.flush()

    ws_a_admin = make_user("ws_a_admin")
    ws_a_editor = make_user("ws_a_editor")
    ws_a_viewer = make_user("ws_a_viewer")
    for u in [ws_a_admin, ws_a_editor, ws_a_viewer]:
        db_session.add(u)
    await db_session.flush()

    for u, role in [(ws_a_admin, "admin"), (ws_a_editor, "editor"), (ws_a_viewer, "viewer")]:
        db_session.add(make_uwr(ws_a.id, u.id, role))

    # ws_b
    ws_b = make_ws("工作区B")
    db_session.add(ws_b)
    await db_session.flush()

    ws_b_admin = make_user("ws_b_admin")
    ws_b_editor = make_user("ws_b_editor")
    ws_b_viewer = make_user("ws_b_viewer")
    for u in [ws_b_admin, ws_b_editor, ws_b_viewer]:
        db_session.add(u)
    await db_session.flush()

    for u, role in [(ws_b_admin, "admin"), (ws_b_editor, "editor"), (ws_b_viewer, "viewer")]:
        db_session.add(make_uwr(ws_b.id, u.id, role))

    await db_session.commit()

    def cookie(user, ws_id):
        return sign_session(user.id, ws_id)

    result = {
        "ws_a": ws_a,
        "ws_b": ws_b,
        "ws_a_admin": (ws_a_admin, cookie(ws_a_admin, ws_a.id)),
        "ws_a_editor": (ws_a_editor, cookie(ws_a_editor, ws_a.id)),
        "ws_a_viewer": (ws_a_viewer, cookie(ws_a_viewer, ws_a.id)),
        "ws_b_admin": (ws_b_admin, cookie(ws_b_admin, ws_b.id)),
        "ws_b_editor": (ws_b_editor, cookie(ws_b_editor, ws_b.id)),
        "ws_b_viewer": (ws_b_viewer, cookie(ws_b_viewer, ws_b.id)),
        "super_admin": (sa_user, cookie(sa_user, ws_a.id)),
    }

    yield result

    # 清理
    from sqlalchemy import text
    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM email_verifications"))
    await db_session.execute(text("DELETE FROM invites"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()
    reset_setup_cache()


# ── Mock IM Providers Fixture（Plan 04-12 E2E 测试基础设施）─────────────────


@pytest.fixture(scope="session", autouse=False)
def mock_im_providers():
    """注册全 6 家 MockIMProvider 到全局 Registry（替代真实 IM Provider）。

    Plan 04-12 E2E spec 通过 GET /api/test/im_mock_calls?provider=X 拉取调用记录。
    单元 / 集成测试如不依赖 IM 投递，无需引用此 fixture（默认 autouse=False）。

    用法：
        def test_xxx(mock_im_providers):
            mocks = mock_im_providers  # {'feishu': MockIMProvider, 'wecom': ..., ...}
            # 触发业务代码
            assert len(mocks['feishu'].calls) == 1

    设计：
    - autouse=False（默认）— 避免污染既有 81 IM provider 单元测试（自己注册自己 mock）
    - scope='session' — registry 是模块级 dict，session 内复用同一组 mock
    - teardown 清空 registry — 防 spec 跨 session 状态泄漏

    生产 Provider 注册由 main.py lifespan 启动钩子完成（Plan 04-06+ 各 plan）；
    本 fixture 只在测试 session 主动引用时才覆盖。
    """
    from app.agent_builder.notification.providers.base import (
        KNOWN_PROVIDERS,
        clear_providers,
        register_provider,
    )
    from app.agent_builder.notification.providers.mock import MockIMProvider

    # 清空已注册 Provider（生产 lifespan 可能注册了真实 Provider）
    clear_providers()

    mocks: dict[str, MockIMProvider] = {}
    for name in sorted(KNOWN_PROVIDERS):
        mock = MockIMProvider(name=name)
        register_provider(mock)
        mocks[name] = mock

    yield mocks

    # teardown：清空 registry（防止跨 session 残留）
    clear_providers()
