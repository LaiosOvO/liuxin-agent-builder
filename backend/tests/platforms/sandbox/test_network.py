"""AllowlistTransport + make_sandboxed_http_client 单元测试（PLUG-FW-11）。

测试策略:

- 所有测试用 ``httpx.MockTransport`` 作为 delegate — 不真发 TCP 请求（CI 友好）
- ``httpx.MockTransport`` 接收 ``Callable[[httpx.Request], httpx.Response]``
- ``AllowlistTransport(allow_list, delegate=MockTransport(handler))`` 注入测试桩
- 断言两类行为：
  1. 命中白名单 → ``await client.get(...)`` 返回 mock 响应
  2. 未命中白名单 → raise ``NetworkBlockedError``（含 ``host`` / ``port``）

12 测试覆盖（计划要求 ≥ 10）：
- block/allow/case-insensitive/port-default 4 类核心场景
- empty allow / malformed entry skip / aclose 传播 / NetworkBlockedError 字段 4 类边界
- make_sandboxed_http_client factory 2 测
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.agent_builder.platforms.exceptions import NetworkBlockedError
from app.agent_builder.platforms.sandbox.network import (
    AllowlistTransport,
    make_sandboxed_http_client,
)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    """MockTransport handler — 总是返回 200 OK + 简单 JSON。"""
    return httpx.Response(200, json={"ok": True, "url": str(request.url)})


# ── 拒绝模式 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowlist_blocks_unlisted_host():
    """非白名单 host → raise NetworkBlockedError（不真发请求 — handler 不应被调）。"""
    handler_calls: list[httpx.Request] = []

    def tracking_handler(req: httpx.Request) -> httpx.Response:
        handler_calls.append(req)
        return httpx.Response(200, json={"unexpected": True})

    transport = AllowlistTransport(
        ["example.com:443"],
        delegate=httpx.MockTransport(tracking_handler),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NetworkBlockedError) as exc_info:
            await client.get("https://other-untrusted.com/foo")

    # NetworkBlockedError 字段断言（Plan 05b-02 已定义）
    assert exc_info.value.host == "other-untrusted.com"
    assert exc_info.value.port == 443
    # delegate 不应被调（请求被前置拒绝）
    assert handler_calls == [], "blocked request should not reach delegate"


@pytest.mark.asyncio
async def test_allowlist_empty_blocks_everything():
    """空 allow_list = 拒所有出站（restrictive baseline, Pitfall 8）。"""
    transport = AllowlistTransport([], delegate=httpx.MockTransport(_ok_handler))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NetworkBlockedError):
            await client.get("https://anything.com/")


@pytest.mark.asyncio
async def test_allowlist_port_mismatch_blocked():
    """白名单 port 不同 → 拒（host 匹配但 port 不同也算 block）。"""
    transport = AllowlistTransport(
        ["example.com:443"], delegate=httpx.MockTransport(_ok_handler)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NetworkBlockedError) as exc_info:
            await client.get("http://example.com:80/")
    assert exc_info.value.port == 80


# ── 放行模式 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowlist_allows_whitelisted_host():
    """命中白名单 → delegate.handle_async_request 被调 → 返回 mock 响应。"""
    transport = AllowlistTransport(
        ["example.com:443"], delegate=httpx.MockTransport(_ok_handler)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://example.com/path")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_allowlist_host_case_insensitive():
    """allow_list 含大写 host → 实际 URL 用任意大小写都应命中（DNS 不区分大小写）。"""
    transport = AllowlistTransport(
        ["Example.COM:443"], delegate=httpx.MockTransport(_ok_handler)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://EXAMPLE.com/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_allowlist_https_default_port_443():
    """URL 无显式 port + scheme=https → port 推断为 443 → 命中。"""
    transport = AllowlistTransport(
        ["example.com:443"], delegate=httpx.MockTransport(_ok_handler)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        # URL 不写 :443，让 AllowlistTransport 按 scheme 推断
        resp = await client.get("https://example.com/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_allowlist_http_default_port_80():
    """URL 无显式 port + scheme=http → port 推断为 80 → 命中。"""
    transport = AllowlistTransport(
        ["example.com:80"], delegate=httpx.MockTransport(_ok_handler)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("http://example.com/")
    assert resp.status_code == 200


# ── 边界 / 鲁棒性 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowlist_malformed_entry_skipped_with_warning(caplog):
    """非法 entry（缺 port / port 非 int）跳过 + 记 warning；合法 entry 仍工作。"""
    import logging

    with caplog.at_level(logging.WARNING):
        transport = AllowlistTransport(
            ["bad-no-port", "host:not-int", "example.com:443"],
            delegate=httpx.MockTransport(_ok_handler),
        )
    # 跳过两条非法 entry，应仅剩 1 条合法
    assert transport._allow_set == {("example.com", 443)}
    # 两条 warning 都应记录
    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("bad-no-port" in m for m in warnings)
    assert any("host:not-int" in m for m in warnings)


@pytest.mark.asyncio
async def test_aclose_propagates_to_delegate():
    """AllowlistTransport.aclose() 应 await delegate.aclose()。"""
    mock_delegate = AsyncMock(spec=httpx.AsyncBaseTransport)
    transport = AllowlistTransport(["example.com:443"], delegate=mock_delegate)
    await transport.aclose()
    mock_delegate.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_network_blocked_error_message_contains_host_port():
    """NetworkBlockedError str 含 host + port + allowlist size — 调试友好。"""
    transport = AllowlistTransport(
        ["example.com:443"], delegate=httpx.MockTransport(_ok_handler)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NetworkBlockedError) as exc_info:
            await client.get("https://blocked-host.com/x")
    msg = str(exc_info.value)
    assert "blocked-host.com" in msg
    assert "443" in msg
    # Plan 05b-02 NetworkBlockedError(__init__) 含 "Network egress blocked"
    assert "blocked" in msg.lower()


@pytest.mark.asyncio
async def test_structured_log_network_blocked_event(caplog):
    """拒绝时记 ``network.blocked`` event — 监控系统可基于此 event 串告警。"""
    import logging

    transport = AllowlistTransport(
        ["example.com:443"], delegate=httpx.MockTransport(_ok_handler)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with (
            caplog.at_level(
                logging.WARNING,
                logger="app.agent_builder.platforms.sandbox.network",
            ),
            pytest.raises(NetworkBlockedError),
        ):
            await client.get("https://untrusted.com/")

    # 至少一条 warning 含 "network.blocked"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("network.blocked" in m for m in msgs), (
        f"Expected 'network.blocked' in log records, got: {msgs}"
    )


# ── make_sandboxed_http_client factory ──────────────────────────────────────


def test_make_sandboxed_http_client_returns_async_client():
    """factory 返回值是 httpx.AsyncClient 实例。"""
    client = make_sandboxed_http_client(["example.com:443"])
    try:
        assert isinstance(client, httpx.AsyncClient)
    finally:
        # AsyncClient 必须在 event loop 内 aclose；测试同步只检查类型不开关
        pass


@pytest.mark.asyncio
async def test_make_sandboxed_http_client_uses_allowlist():
    """factory 返回的 client 实际生效 — 非白名单 host raise NetworkBlockedError。"""
    async with make_sandboxed_http_client(["example.com:443"]) as client:
        with pytest.raises(NetworkBlockedError):
            await client.get("https://untrusted.com/")
