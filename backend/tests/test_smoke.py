"""Plan 01-01 测试基础设施冒烟测试。

仅验证 pytest + pytest-asyncio 跑通 + /health endpoint 可达（如果 flock app 起来）。
真正的业务测试在后续 plan 实现。
"""
from __future__ import annotations

import pytest


def test_pytest_works() -> None:
    """sanity: pytest 同步测试可跑。"""
    assert 1 + 1 == 2


@pytest.mark.asyncio
async def test_pytest_asyncio_works() -> None:
    """sanity: pytest-asyncio 异步测试可跑。"""
    import asyncio

    result = await asyncio.sleep(0, result="ok")
    assert result == "ok"


@pytest.mark.asyncio
async def test_health_endpoint(async_client) -> None:
    """agent-builder 提供的 /api/setup/state 端点返回 200（系统健康检查）。

    /api/setup/state 在未初始化时返回 {initialized: false}，
    在已初始化后由 SetupRedirectMiddleware 返回 404——
    两种情况下服务均正常（不是 500 / 503）。
    """
    response = await async_client.get("/api/setup/state")
    # 未初始化 → 200 {initialized: false}；已初始化 → 404（中间件隐藏 setup 路由）
    assert response.status_code in (200, 404)
