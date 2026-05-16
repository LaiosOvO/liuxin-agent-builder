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
    """flock 提供的 /api/v1/utils/health endpoint 返回 200。

    若 flock app 导入失败（Phase 1 早期）conftest 会 skip 整个测试。
    """
    response = await async_client.get("/api/v1/utils/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ok"
