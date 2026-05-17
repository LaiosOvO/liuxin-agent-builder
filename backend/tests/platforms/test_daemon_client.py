"""PlatformDaemonClient 测试 — 真起子进程 + JSONRPC roundtrip（PLUG-FW-05）。

测试覆盖：
- test_basic_invoke_roundtrip: 主流程 spawn + invoke + 收响应
- test_method_not_found_returns_error: JSONRPC -32601 错误协议
- test_explicit_error_response: JSONRPC -32000 业务错误协议
- test_daemon_crash_fails_pending_future: **Pitfall 2 fault isolation 关键测试**
  - invoke_timeout=2.0（不许走默认 30s 路径）
  - 必须 raise PluginDaemonExitedError（不接受 PluginInvocationError）
  - timing assertion: elapsed < 2.0s（确保走 fault isolation，不走 timeout）
- test_multiple_concurrent_invokes: 并发 5 个 invoke 正确按 id 路由响应
- test_close_idempotent: close 可重复调
- test_invoke_after_close_starts_new: close 后再 invoke 重新 spawn 新 daemon
- test_invoke_timeout_raises: timeout 路径（与 fault isolation 区别）
- test_repr_does_not_crash: __repr__ 各种状态下不报错
- test_text_method_roundtrip: send_text method 路径

环境要求：
- pytest-asyncio + Python 3.11+ asyncio.subprocess
- 测试运行时主进程必须是 -u 或同等 unbuffered 模式（pytest 默认 OK）
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.exceptions import (
    PluginDaemonExitedError,
    PluginInvocationError,
)

# echo_daemon module entry — 注意路径要相对 backend/ 工作目录
# pytest 从 backend/ 运行时，tests.platforms.fixtures.echo_daemon 可被 -m 找到
ECHO_MODULE = "tests.platforms.fixtures.echo_daemon"


# ── 基础 invoke 路径 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_basic_invoke_roundtrip() -> None:
    """主流程：spawn daemon → invoke → 收 result → close。"""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        result = await client.invoke(
            "im",
            "send_card",
            recipient={"kind": "channel", "id": "c1"},
            card={"title": "t", "body_markdown": "b", "actions": []},
            idempotency_key="k1",
        )
        assert result["plugin_name"] == "echo"
        assert result["native_id"] == "echo-k1"
        assert result["extras"] == {}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_text_method_roundtrip() -> None:
    """send_text method 路径 — 验证多 method 都能路由。"""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        result = await client.invoke(
            "im",
            "send_text",
            recipient={"kind": "dm_user", "id": "u42"},
            text="hello",
        )
        assert result["plugin_name"] == "echo"
        assert result["native_id"] == "text-u42"
    finally:
        await client.close()


# ── 错误协议 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_method_not_found_returns_error() -> None:
    """daemon 返回 JSONRPC -32601 → 主进程 raise PluginInvocationError + error_payload."""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        with pytest.raises(PluginInvocationError) as exc_info:
            await client.invoke("im", "nonexistent_method")
        assert exc_info.value.error_payload["code"] == -32601
        assert "nonexistent_method" in exc_info.value.error_payload["message"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_explicit_error_response() -> None:
    """daemon 返回 JSONRPC -32000 业务错误 → 主进程 raise PluginInvocationError."""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        with pytest.raises(PluginInvocationError) as exc_info:
            await client.invoke("im", "echo_error")
        assert exc_info.value.error_payload["code"] == -32000
        assert "intentional error" in exc_info.value.error_payload["message"]
    finally:
        await client.close()


# ── Fault isolation（Pitfall 2 关键）─────────────────────────────────────────


@pytest.mark.asyncio
async def test_daemon_crash_fails_pending_future() -> None:
    """**Pitfall 2 关键 + High 4 修复**：daemon sys.exit(1) → pending future 在 < 2s 内 raise.

    High 4 修复点：
    - 客户端 invoke_timeout=2.0（不是默认 30s）— fault isolation 必须快
    - 只能 raise PluginDaemonExitedError（不接受 PluginInvocationError —— daemon 已死不可能再发 JSONRPC error response）
    - 加 timing assertion：从 invoke 开始到 raise 必须 < 2.0s（防止退化为超时路径）

    硬性要求来自 CONTEXT.md §HulyPlugin Acid Test DoD #2。
    """
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=2.0)
    try:
        start = time.monotonic()
        with pytest.raises(PluginDaemonExitedError):
            # echo_daemon 收到 im.crash 后 sys.exit(1)
            await client.invoke("im", "crash")
        elapsed = time.monotonic() - start
        assert (
            elapsed < 2.0
        ), f"daemon crash 检测耗时 {elapsed:.3f}s ≥ 2.0s — 走超时路径而非 fault isolation"
    finally:
        await client.close()


# ── 并发路由 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_concurrent_invokes() -> None:
    """并发 5 个 invoke，正确按 id 路由响应（不串）— 验证 _pending dict 路由。"""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        results = await asyncio.gather(
            *[
                client.invoke(
                    "im",
                    "send_card",
                    recipient={"kind": "channel", "id": f"c{i}"},
                    card={"title": "t", "body_markdown": "b", "actions": []},
                    idempotency_key=f"k{i}",
                )
                for i in range(5)
            ]
        )
        assert len(results) == 5
        for i, r in enumerate(results):
            assert (
                r["native_id"] == f"echo-k{i}"
            ), f"index {i} 收到 {r['native_id']}，预期 echo-k{i} — 响应路由串了"
    finally:
        await client.close()


# ── 生命周期 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_idempotent() -> None:
    """close 可重复调（首次正常关闭；二次直接返回）— 测试 cleanup 路径稳定。"""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    await client.invoke(
        "im",
        "send_card",
        recipient={"kind": "channel", "id": "c1"},
        card={"title": "t", "body_markdown": "b", "actions": []},
        idempotency_key="k",
    )
    await client.close()
    await client.close()  # 再 close 不报错


@pytest.mark.asyncio
async def test_invoke_after_close_starts_new() -> None:
    """close 之后 invoke 重新 start 新 daemon 进程（_closed 标志被 start 重置）。"""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    r1 = await client.invoke(
        "im",
        "send_card",
        recipient={"kind": "channel", "id": "c1"},
        card={"title": "t", "body_markdown": "b", "actions": []},
        idempotency_key="k1",
    )
    assert r1["native_id"] == "echo-k1"

    await client.close()

    # 现在重新 invoke — 应该 start 新进程
    r2 = await client.invoke(
        "im",
        "send_card",
        recipient={"kind": "channel", "id": "c2"},
        card={"title": "t", "body_markdown": "b", "actions": []},
        idempotency_key="k2",
    )
    assert r2["native_id"] == "echo-k2"

    await client.close()


# ── Timeout 路径（业务正常，非 fault isolation）─────────────────────────────────


@pytest.mark.asyncio
async def test_invoke_timeout_raises() -> None:
    """invoke_timeout 触发 asyncio.TimeoutError（与 fault isolation 区别）— daemon 还活着但慢."""
    # invoke_timeout=0.5s, im.slow 会 sleep 5s
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=0.5)
    try:
        with pytest.raises(asyncio.TimeoutError):
            await client.invoke("im", "slow")
    finally:
        await client.close()


# ── 调试辅助 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repr_does_not_crash() -> None:
    """__repr__ 在各种状态下不报错 — 测试 not_started / running / exited."""
    client = PlatformDaemonClient(ECHO_MODULE)
    repr_before = repr(client)
    assert "not_started" in repr_before
    assert ECHO_MODULE in repr_before

    await client.invoke(
        "im",
        "send_card",
        recipient={"kind": "channel", "id": "c1"},
        card={"title": "t", "body_markdown": "b", "actions": []},
        idempotency_key="k",
    )
    repr_running = repr(client)
    assert "pid=" in repr_running

    await client.close()
    repr_after = repr(client)
    assert "not_started" in repr_after  # _proc 被重置为 None


# ── start 显式调用 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_start_then_invoke() -> None:
    """显式 start 后 invoke 不重复 spawn — start 幂等。"""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        await client.start()
        await client.start()  # 幂等：第二次返回 不重复 spawn
        result = await client.invoke(
            "im",
            "send_card",
            recipient={"kind": "channel", "id": "c1"},
            card={"title": "t", "body_markdown": "b", "actions": []},
            idempotency_key="k",
        )
        assert result["plugin_name"] == "echo"
    finally:
        await client.close()
