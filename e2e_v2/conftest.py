"""Phase 4 E2E v2 pytest fixtures。

约定（与 Phase 1-3 e2e/ 对齐）：
- Smoke 默认 skip — RUN_E2E=1 才跑
- 三档：Smoke / Standard / Full (E2E_FULL_STACK=1 加 timeout 真实快进)
- 全 fixture session-scoped — 6 spec 共享一组 admin / workspace

后端依赖：
- backend 已启动（端口 8000）且 ENABLE_TEST_API=1（test_helpers 路由可用）
- MailHog 已起（端口 1025 / 8025）
- Postgres / Redis 已起（与 conftest 后端一致）
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from e2e_v2.helpers.api_client import (
    API_BASE_URL,
    DEFAULT_PASSWORD,
    ensure_initialized,
    random_email,
)
from e2e_v2.helpers.im_mock_client import IMMockClient
from e2e_v2.helpers.mailhog_client import purge_all


# ── 三档运行模式标志 ────────────────────────────────────────────────────

RUN_E2E = os.environ.get("RUN_E2E", "").strip() == "1"
RUN_E2E_FULL = os.environ.get("E2E_FULL_STACK", "").strip() == "1"

# pytest 跳过装饰器
e2e_required = pytest.mark.skipif(
    not (RUN_E2E or RUN_E2E_FULL),
    reason="设置 RUN_E2E=1 才跑 Phase 4 E2E spec（Smoke 默认 skip）",
)
e2e_full_required = pytest.mark.skipif(
    not RUN_E2E_FULL,
    reason="设置 E2E_FULL_STACK=1 才跑含 timeout 真实快进的 spec",
)


# ── HTTP 客户端 fixture ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def httpx_client() -> AsyncIterator[httpx.AsyncClient]:
    """spec 默认 HTTP 客户端（base_url = API_BASE_URL，cookies 自动透传）。

    function-scoped — 每个 test 独立 cookie state 避免污染。
    """
    async with httpx.AsyncClient(
        base_url=API_BASE_URL, timeout=30.0, follow_redirects=True
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def admin_session() -> AsyncIterator[tuple[str, str]]:
    """session 级 admin 登录 — 测试启动时一次性 initialize/login。

    Yields:
        (email, password) — 已 initialize 的 admin 凭据
    """
    if not (RUN_E2E or RUN_E2E_FULL):
        # Smoke 模式 — skip 所有 E2E test，此 fixture 也不应被引用
        yield "", ""
        return

    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
        email, password = await ensure_initialized(
            client,
            admin_email=os.environ.get("E2E_ADMIN_EMAIL", "admin@e2e.test"),
        )
        yield email, password


@pytest_asyncio.fixture
async def admin_client(admin_session) -> AsyncIterator[httpx.AsyncClient]:
    """已登录的 admin client（cookies 已设）。"""
    email, password = admin_session
    async with httpx.AsyncClient(
        base_url=API_BASE_URL, timeout=30.0, follow_redirects=True
    ) as client:
        r = await client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        r.raise_for_status()
        yield client


# ── Mock IM Client fixture ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def im_mock(httpx_client) -> AsyncIterator[IMMockClient]:
    """Mock IM Provider 客户端（GET /api/test/im_mock_calls 等）。

    每个 test 开始时 clear all（spec 隔离）。
    """
    mock = IMMockClient(httpx_client)
    try:
        await mock.clear("all")
    except httpx.HTTPStatusError as e:
        # 404 — backend 未挂 test_helpers（缺 ENABLE_TEST_API）
        pytest.fail(
            "test_helpers 路由不可达 — 请确认 backend 启动时设了 ENABLE_TEST_API=1"
            f"\n原始错误: {e}"
        )
    yield mock


# ── MailHog purge fixture ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def mailhog_purged() -> AsyncIterator[None]:
    """每个 spec 开始时清空 MailHog（防跨 spec 邮件污染）。

    要求 MailHog 已启动（http://localhost:8025）。
    """
    try:
        await purge_all()
    except (httpx.ConnectError, httpx.HTTPError) as e:
        pytest.skip(f"MailHog 不可达 — {e}")
    yield


# ── 测试用户工厂 ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def make_approver(
    admin_client: httpx.AsyncClient,
) -> AsyncIterator[callable]:
    """工厂 fixture：创建 N 个 approver 用户（带 email + 已登录 session）。

    用法：
        async def test_xxx(make_approver):
            users = await make_approver(3)  # 返回 [(email, cookie_value), ...]
    """
    created: list[tuple[str, str]] = []

    async def _factory(n: int) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for i in range(n):
            email = random_email(f"approver{i}")
            invite = await admin_client.post(
                "/api/invites", json={"email": email, "role_code": "editor"}
            )
            invite.raise_for_status()
            invite_body = invite.json()
            token = invite_body.get("token")
            if not token:
                pytest.skip(
                    f"邀请 token 不可见（dev 模式可能没返回）— spec 需要 token"
                )

            # 用新 client 走 accept
            async with httpx.AsyncClient(base_url=API_BASE_URL) as nc:
                r = await nc.post(
                    "/api/invites/accept",
                    json={
                        "token": token,
                        "password": DEFAULT_PASSWORD,
                        "display_name": f"E2E 审批人 {i}",
                    },
                )
                r.raise_for_status()
                cookie = r.cookies.get("session", "")
                result.append((email, cookie))
        created.extend(result)
        return result

    yield _factory

    # 不做用户清理 — 测试 admin 是临时 workspace，重启即重置；保留 audit 完整性


# ── pytest 配置 ────────────────────────────────────────────────────────


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "e2e: end-to-end 测试（默认 skip，RUN_E2E=1 启用）"
    )
    config.addinivalue_line(
        "markers", "e2e_full: 含 timeout 真实快进的 spec（E2E_FULL_STACK=1 启用）"
    )
    config.addinivalue_line(
        "markers", "browser: 需启动 browser-harness 的 spec"
    )
