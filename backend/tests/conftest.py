"""pytest 全局 fixtures。

约定（CLAUDE.md 2.2）：
- 集成测试用真实 Postgres / Redis（testcontainers），**禁止 mock**
- 单元测试可以不依赖容器，只跑纯 Python 逻辑
- ASGI client 通过 ASGITransport 直连 FastAPI app，不需要 uvicorn 真正起来
"""
from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """Postgres DSN。优先使用 TESTCONTAINER_PG_DSN env，否则起 testcontainers。

    返回 asyncpg 风格 DSN：postgresql+asyncpg://...
    """
    if env := os.getenv("TESTCONTAINER_PG_DSN"):
        return env
    pytest.importorskip("testcontainers.postgres", reason="安装 testcontainers-postgres 才能跑集成测试")
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:18-alpine")
    container.start()
    dsn = container.get_connection_url().replace("postgresql://", "postgresql+asyncpg://")

    # session 结束时清理（pytest fixture lifecycle 自动处理）
    yield dsn  # type: ignore[misc]
    container.stop()


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
    """FastAPI ASGI client，通过 ASGITransport 直连 app。

    需要 flock app 可导入（Phase 2 完成 DSL/auth 后会稳定）。
    Phase 1 阶段如导入失败，则 skip。
    """
    from httpx import ASGITransport, AsyncClient

    try:
        # flock 原入口（CONTEXT.md：保留 flock import path）
        from app.main import app  # type: ignore
    except ImportError as e:
        pytest.skip(f"flock app 暂未可导入（Phase 1 早期，正常）：{e}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
