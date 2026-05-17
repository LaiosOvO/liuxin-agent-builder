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


# ══════════════════════════════════════════════════════════════════════════════
# Plan 05b-04 新增测试：sandbox_config 集成 + _build_filtered_env Pitfall 8
# ══════════════════════════════════════════════════════════════════════════════


from app.agent_builder.platforms.manifest import SandboxConfig  # noqa: E402


# ── _build_filtered_env strip-all-allowlist（Pitfall 8）─────────────────────


def test_sandbox_config_none_uses_5a_compat_path() -> None:
    """sandbox_config=None → 走 5.A 老路径（_build_filtered_env 不被调）.

    构造时不传 sandbox_config，验证 _sandbox_config/_sandbox_runner/_watchdog 全 None
    + last_invoke_at 默认 0.0.
    """
    client = PlatformDaemonClient(ECHO_MODULE)
    assert client._sandbox_config is None
    assert client._sandbox_runner is None
    assert client._watchdog is None
    assert client.last_invoke_at == 0.0


def test_build_filtered_env_strips_secrets_by_default(monkeypatch) -> None:
    """默认 env_allowlist=[] → HMAC_SECRET / DATABASE_URL 即使在 os.environ 也被 strip."""
    monkeypatch.setenv("HMAC_SECRET", "supersecret123")
    monkeypatch.setenv("DATABASE_URL", "postgres://x:y@localhost/db")
    cfg = SandboxConfig()  # 默认 env_allowlist=[]
    client = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg)

    filtered = client._build_filtered_env()

    assert "HMAC_SECRET" not in filtered
    assert "DATABASE_URL" not in filtered


def test_build_filtered_env_allows_safe_base(monkeypatch) -> None:
    """PATH / HOME / LANG 默认在 filtered env（_SAFE_BASE_ENV）."""
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/Users/test")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    cfg = SandboxConfig()
    client = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg)

    filtered = client._build_filtered_env()

    assert filtered["PATH"] == "/usr/bin"
    assert filtered["HOME"] == "/Users/test"
    assert filtered["LANG"] == "en_US.UTF-8"


def test_build_filtered_env_respects_env_allowlist(monkeypatch) -> None:
    """sandbox_config(env_allowlist=['HULY_ENDPOINT']) + env HULY_ENDPOINT=... → filtered 含."""
    monkeypatch.setenv("HULY_ENDPOINT", "http://localhost:18765")
    cfg = SandboxConfig(env_allowlist=["HULY_ENDPOINT"])
    client = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg)

    filtered = client._build_filtered_env()

    assert filtered.get("HULY_ENDPOINT") == "http://localhost:18765"


def test_build_filtered_env_forbidden_prefix_always_rejected(monkeypatch, caplog) -> None:
    """即使 env_allowlist=['AGENT_BUILDER_X'] 也被 FORBIDDEN_PREFIXES 拒绝 + warning log."""
    import logging

    monkeypatch.setenv("AGENT_BUILDER_X", "should_be_blocked")
    cfg = SandboxConfig(env_allowlist=["AGENT_BUILDER_X"])
    client = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg)

    with caplog.at_level(logging.WARNING):
        filtered = client._build_filtered_env()

    assert "AGENT_BUILDER_X" not in filtered
    # 验证 warning log 含拒绝信息
    assert any(
        "AGENT_BUILDER_X" in r.message and "FORBIDDEN_PREFIXES" in r.message
        for r in caplog.records
    )


def test_build_filtered_env_forbidden_exact_always_rejected(monkeypatch, caplog) -> None:
    """即使 env_allowlist=['HMAC_SECRET'] 也被 FORBIDDEN_EXACT 拒绝 + warning log."""
    import logging

    monkeypatch.setenv("HMAC_SECRET", "hmac-secret-32-bytes-or-more-here")
    cfg = SandboxConfig(env_allowlist=["HMAC_SECRET"])
    client = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg)

    with caplog.at_level(logging.WARNING):
        filtered = client._build_filtered_env()

    assert "HMAC_SECRET" not in filtered
    assert any(
        "HMAC_SECRET" in r.message and "FORBIDDEN_EXACT" in r.message
        for r in caplog.records
    )


def test_build_filtered_env_user_env_overrides(monkeypatch) -> None:
    """用户传入 env={"X": "v"} → filtered 包含 X 即使不在 SAFE_BASE 或 allowlist."""
    cfg = SandboxConfig()
    client = PlatformDaemonClient(
        ECHO_MODULE, env={"HULY_ENDPOINT": "http://test:9999"}, sandbox_config=cfg
    )

    filtered = client._build_filtered_env()

    assert filtered["HULY_ENDPOINT"] == "http://test:9999"


# ── _choose_runner ───────────────────────────────────────────────────────────


def test_choose_runner_returns_injected_runner() -> None:
    """sandbox_runner 显式传入 → _choose_runner 直接返回（测试注入用）."""

    class _MockRunner:
        async def spawn_with_limits(self, cmd, *, cpu_seconds, memory_bytes, env=None, cwd=None):
            raise NotImplementedError

    mock = _MockRunner()
    cfg = SandboxConfig()
    client = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg, sandbox_runner=mock)

    assert client._choose_runner() is mock


def test_choose_runner_defaults_to_posix_resource_sandbox() -> None:
    """不传 sandbox_runner → _choose_runner 返回 PosixResourceSandbox（baseline）."""
    from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox

    cfg = SandboxConfig()
    client = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg)

    runner = client._choose_runner()
    assert isinstance(runner, PosixResourceSandbox)


# ── sandbox path 集成（用 injected MockSandboxRunner，不 spawn 真子进程）──────


@pytest.mark.asyncio
async def test_sandbox_config_set_uses_sandbox_runner() -> None:
    """sandbox_config 非 None → start() 走 _sandbox_runner.spawn_with_limits 路径.

    用 MockRunner 拦截真 spawn — 验证调用路径（不真起子进程）。
    """
    spawn_calls: list[dict] = []

    class _MockRunner:
        async def spawn_with_limits(self, cmd, *, cpu_seconds, memory_bytes, env=None, cwd=None):
            spawn_calls.append(
                {
                    "cmd": cmd,
                    "cpu_seconds": cpu_seconds,
                    "memory_bytes": memory_bytes,
                    "env": env,
                    "cwd": cwd,
                }
            )
            # 返回 None — 后续 start 会因 _proc.pid 报错；我们只验证 spawn 被调到
            raise RuntimeError("MockRunner intentional — verify spawn_with_limits was called")

    cfg = SandboxConfig(memory="256Mi", cpu_limit="1.0", env_allowlist=[])
    client = PlatformDaemonClient(
        ECHO_MODULE, sandbox_config=cfg, sandbox_runner=_MockRunner()
    )

    with pytest.raises(RuntimeError, match="MockRunner intentional"):
        await client.start()

    assert len(spawn_calls) == 1
    call = spawn_calls[0]
    assert call["cmd"][-1] == ECHO_MODULE
    assert call["cpu_seconds"] == cfg.cpu_limit_seconds
    assert call["memory_bytes"] == cfg.memory_bytes
    # env 走 _build_filtered_env，不含 secret
    import os

    os.environ["HMAC_SECRET"] = "test"
    # 重新构造测 env 过滤
    client2 = PlatformDaemonClient(ECHO_MODULE, sandbox_config=cfg, sandbox_runner=_MockRunner())
    filtered = client2._build_filtered_env()
    assert "HMAC_SECRET" not in filtered
    os.environ.pop("HMAC_SECRET", None)


# ── last_invoke_at（Pitfall 6 finally 块更新）────────────────────────────────


@pytest.mark.asyncio
async def test_last_invoke_at_updates_on_invoke_finally() -> None:
    """调 invoke() 后 last_invoke_at > 0（finally 块更新生效）."""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        assert client.last_invoke_at == 0.0

        await client.invoke(
            "im",
            "send_card",
            recipient={"kind": "channel", "id": "c1"},
            card={"title": "t", "body_markdown": "b", "actions": []},
            idempotency_key="k1",
        )

        assert client.last_invoke_at > 0.0, "invoke finally 应更新 last_invoke_at"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_last_invoke_at_updates_even_on_invoke_exception() -> None:
    """invoke raise 异常时 last_invoke_at 仍然更新（finally 不是 try — Pitfall 6）."""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)
    try:
        # 触发业务错误
        with pytest.raises(PluginInvocationError):
            await client.invoke("im", "nonexistent_method")

        # 即使 raise 也要更新 last_invoke_at（reaper 不能误判 idle）
        assert client.last_invoke_at > 0.0, (
            "exception 路径 last_invoke_at 也应更新"
        )
    finally:
        await client.close()


# ── close stops watchdog ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_stops_watchdog_if_present() -> None:
    """sandbox_config 启动后 close → watchdog._stopped == True + _watchdog 设回 None.

    用 MockRunner 注入 — 不需真 spawn 子进程；用 mock proc 模拟 pid.
    """
    import asyncio as _asyncio
    from unittest.mock import MagicMock

    # MockRunner 返回 mock proc + 不 raise
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stderr = MagicMock()
    # readline 返回空 bytes → daemon EOF（让 _read_loop 立即退出）
    async def _empty_readline():
        return b""

    mock_proc.stdout.readline = _empty_readline
    mock_proc.stderr.readline = _empty_readline

    async def _wait():
        return 0

    mock_proc.wait = _wait
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.returncode = 0

    class _MockRunner:
        async def spawn_with_limits(self, cmd, *, cpu_seconds, memory_bytes, env=None, cwd=None):
            return mock_proc

    cfg = SandboxConfig(memory="256Mi")
    client = PlatformDaemonClient(
        ECHO_MODULE, sandbox_config=cfg, sandbox_runner=_MockRunner()
    )

    await client.start()
    assert client._watchdog is not None
    watchdog_ref = client._watchdog
    assert watchdog_ref._stopped is False

    await client.close()

    assert watchdog_ref._stopped is True
    assert client._watchdog is None
