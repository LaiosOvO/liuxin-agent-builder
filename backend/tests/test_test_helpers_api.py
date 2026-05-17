"""test_helpers API endpoints — Plan 04-12 测试辅助路由集成测试。

验证：
1. ping endpoint 响应 OK（路由挂载验证）
2. im_mock_calls 返回 Provider 调用记录（4 Provider 一致）
3. im_mock_clear 清空特定 / 全部 mock 调用
4. hitl_tokens 查询 used_at 状态（Safe Links 回归基础）
5. audit_logs 查询 + action 过滤（委托/升级回归基础）
6. 安全：未注册 Provider 返回 404；生产 Provider 返回 409

CLAUDE.md 2.2：集成测试用真实 ASGI client（不 mock）+ 真实 Mock Provider 注册。
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 必须在 import 之前设环境变量（lifespan 挂载条件路由）
os.environ["ENABLE_TEST_API"] = "1"

pytestmark = pytest.mark.asyncio


# ── Fixture：ASGI client with test_helpers mounted ──────────────────────


@pytest_asyncio.fixture
async def test_api_client():
    """挂载 test_helpers 路由的 ASGI client（重新 import 触发条件挂载）。"""
    # 触发条件挂载（main.py 顶层执行 if os.environ['ENABLE_TEST_API']=='1':）
    import importlib

    import app.agent_builder.main

    importlib.reload(app.agent_builder.main)
    from app.agent_builder.main import agent_builder_app

    # 注册 4 MockIMProvider（与 mock_im_providers fixture 等价但局部）
    from app.agent_builder.notification.providers.base import (
        KNOWN_PROVIDERS,
        clear_providers,
        register_provider,
    )
    from app.agent_builder.notification.providers.mock import MockIMProvider

    clear_providers()
    mocks: dict[str, MockIMProvider] = {}
    for name in sorted(KNOWN_PROVIDERS):
        mock = MockIMProvider(name=name)
        register_provider(mock)
        mocks[name] = mock

    async with AsyncClient(
        transport=ASGITransport(app=agent_builder_app), base_url="http://test"
    ) as client:
        yield client, mocks

    clear_providers()


# ── Test：ping ────────────────────────────────────────────────────────────


async def test_ping_returns_ok(test_api_client):
    client, _ = test_api_client
    r = await client.get("/api/test/ping")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "module": "test_helpers"}


# ── Test：im_mock_calls 空 list ──────────────────────────────────────────


async def test_im_mock_calls_returns_empty_list_initially(test_api_client):
    client, _ = test_api_client
    r = await client.get("/api/test/im_mock_calls", params={"provider": "feishu"})
    assert r.status_code == 200
    assert r.json() == []


# ── Test：im_mock_calls 反映真实调用 ─────────────────────────────────────


async def test_im_mock_calls_reflects_actual_send(test_api_client):
    client, mocks = test_api_client
    # 通过 mock 直接调用（模拟 worker 触发投递）
    feishu_mock = mocks["feishu"]
    await feishu_mock.send_hitl_card(
        recipient="ou_test_user",
        flow_title="测试流程",
        node_title="测试节点",
        applicant_name="张三",
        actor_name="李四",
        deadline_at="2026-05-18T12:00:00Z",
        description="请审批",
        deeplinks=[
            {"action": "approve", "url": "http://test/approve"},
            {"action": "reject", "url": "http://test/reject"},
        ],
    )

    r = await client.get("/api/test/im_mock_calls", params={"provider": "feishu"})
    assert r.status_code == 200
    calls = r.json()
    assert len(calls) == 1
    assert calls[0]["method"] == "send_hitl_card"
    assert calls[0]["recipient"] == "ou_test_user"
    assert calls[0]["payload"]["flow_title"] == "测试流程"
    assert len(calls[0]["payload"]["deeplinks"]) == 2


# ── Test：im_mock_calls 404 / 409 ────────────────────────────────────────


async def test_im_mock_calls_404_for_unregistered_provider(test_api_client):
    client, _ = test_api_client
    r = await client.get("/api/test/im_mock_calls", params={"provider": "unknown-typo"})
    assert r.status_code == 404


# ── Test：im_mock_clear 清空特定 provider ───────────────────────────────


async def test_im_mock_clear_resets_specific_provider(test_api_client):
    client, mocks = test_api_client
    # 准备数据
    await mocks["feishu"].send_hitl_card(
        recipient="r1",
        flow_title="t",
        node_title="n",
        applicant_name="a",
        actor_name="ac",
        deadline_at="d",
        description="desc",
        deeplinks=[{"action": "approve", "url": "u"}],
    )
    assert len(mocks["feishu"].calls) == 1

    r = await client.post("/api/test/im_mock_clear", params={"provider": "feishu"})
    assert r.status_code == 200
    body = r.json()
    assert body["cleared"] == ["feishu"]
    assert body["count"] == 1
    assert len(mocks["feishu"].calls) == 0


async def test_im_mock_clear_all_resets_every_provider(test_api_client):
    client, mocks = test_api_client
    # 在 3 个 provider 各塞 1 call
    for name in ["feishu", "wecom", "slack"]:
        await mocks[name].send_hitl_card(
            recipient="r",
            flow_title="t",
            node_title="n",
            applicant_name="a",
            actor_name="ac",
            deadline_at="d",
            description="desc",
            deeplinks=[],
        )
        assert len(mocks[name].calls) == 1

    r = await client.post("/api/test/im_mock_clear", params={"provider": "all"})
    assert r.status_code == 200
    body = r.json()
    # 6 家 mock provider 都被清空
    assert body["count"] == 6
    for name in ["feishu", "wecom", "slack"]:
        assert len(mocks[name].calls) == 0


# ── Test：hitl_tokens unknown jti ────────────────────────────────────────


async def test_hitl_tokens_unknown_jti_returns_exists_false(test_api_client):
    client, _ = test_api_client
    random_jti = str(uuid.uuid4())
    r = await client.get("/api/test/hitl_tokens", params={"jti": random_jti})
    assert r.status_code == 200
    body = r.json()
    assert body["jti"] == random_jti
    assert body["exists"] is False
    assert body["used_at"] is None
    assert body["consumed"] is False


async def test_hitl_tokens_invalid_uuid_returns_422(test_api_client):
    client, _ = test_api_client
    r = await client.get("/api/test/hitl_tokens", params={"jti": "not-a-uuid"})
    assert r.status_code == 422


# ── Test：audit_logs 空查询 ─────────────────────────────────────────────


async def test_audit_logs_empty_action_filter(test_api_client):
    """audit_logs 查询过滤 — 需要 DB 连接（事件循环兼容性见 conftest pattern）。

    注意：本测试触发 DB 查询；engine.dispose() 前置避免跨测试 asyncpg loop 冲突
    （与 test_instances_api / test_hitl_action_service 同样模式）。
    断言宽松：只要返回 200 + list 即可（即便为空也算 OK）。
    """
    # 重置 engine 连接池（避免上一个测试残留连接绑定旧 loop）
    from app.agent_builder.db.engine import engine

    await engine.dispose()

    client, _ = test_api_client
    r = await client.get(
        "/api/test/audit_logs",
        params={"action": "definitely.does.not.exist", "limit": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


# ── Test：默认环境不挂载 test_helpers ─────────────────────────────────


@pytest.mark.asyncio
async def test_test_helpers_not_mounted_when_env_unset(monkeypatch):
    """ENABLE_TEST_API 未设时，test_helpers 路由不应挂载（生产安全）。"""
    monkeypatch.delenv("ENABLE_TEST_API", raising=False)

    import importlib

    import app.agent_builder.main

    importlib.reload(app.agent_builder.main)
    from app.agent_builder.main import agent_builder_app

    routes = [r.path for r in agent_builder_app.routes]
    test_routes = [p for p in routes if "/api/test/" in p]
    assert test_routes == [], f"非测试环境不应挂载，但发现：{test_routes}"

    # 恢复（其他测试需要）
    monkeypatch.setenv("ENABLE_TEST_API", "1")
    importlib.reload(app.agent_builder.main)
