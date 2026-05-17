"""IdleDaemonReaper 集成测试 — 真 spawn echo daemon + 短 timeout_idle 验证 auto-close.

跨平台测试（不需 Linux only — reaper 逻辑与 OS 无关，仅依赖 last_invoke_at 跟踪）。

测试覆盖：
1. test_idle_reaper_closes_idle_daemon: 真 spawn daemon + invoke → 等过 timeout
   → 手动触发 scan_once → daemon close 被调
2. test_idle_reaper_skips_active_invoke: daemon 在长 invoke 中（_pending 非空）→
   即使 last_invoke_at 很久前也不 close
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.sandbox.idle_reaper import IdleDaemonReaper

pytestmark = [pytest.mark.sandbox_integration]


ECHO_MODULE = "tests.platforms.fixtures.echo_daemon"


@pytest.mark.asyncio
async def test_idle_reaper_closes_idle_daemon() -> None:
    """daemon idle 超 timeout → reaper.scan_once close daemon + _proc 设回 None."""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)

    # 启动 daemon + 调一次 invoke 设 last_invoke_at
    await client.invoke(
        "im",
        "send_card",
        recipient={"kind": "channel", "id": "c1"},
        card={"title": "t", "body_markdown": "b", "actions": []},
        idempotency_key="k1",
    )

    assert client._proc is not None
    assert client.last_invoke_at > 0

    # 模拟 idle：强行设 last_invoke_at 为 100s 前
    client.last_invoke_at = time.monotonic() - 100.0

    # 用短 timeout_idle=1.0 + reaper 触发 scan
    reaper = IdleDaemonReaper(
        get_daemons=lambda: [client], timeout_idle=1.0, scan_interval=10.0
    )

    reaped = await reaper.scan_once()

    assert reaped == 1, "idle daemon 应被 close"
    # close 后 _proc 设回 None（5.A close() 行为）
    assert client._proc is None


@pytest.mark.asyncio
async def test_idle_reaper_skips_active_invoke() -> None:
    """daemon._pending 非空（活跃 invoke）→ reaper 跳过即使 last_invoke_at 很久前."""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)

    # 启动 daemon
    await client.start()
    assert client._proc is not None

    # 模拟活跃 invoke：手动添加 pending future + 设 last_invoke_at 100s 前
    fake_future = asyncio.get_event_loop().create_future()
    client._pending["fake-req-id"] = fake_future
    client.last_invoke_at = time.monotonic() - 100.0

    reaper = IdleDaemonReaper(
        get_daemons=lambda: [client], timeout_idle=1.0, scan_interval=10.0
    )

    reaped = await reaper.scan_once()

    assert reaped == 0, "活跃 invoke 不应被 reaper close（Pitfall 6 防竞争）"
    assert client._proc is not None, "daemon 应仍存活"

    # cleanup
    client._pending.pop("fake-req-id", None)
    fake_future.cancel()
    await client.close()


@pytest.mark.asyncio
async def test_idle_reaper_lazy_respawn_after_close() -> None:
    """reaper close idle daemon 后，下次 invoke 自动 lazy re-spawn 新进程."""
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=10.0)

    # 第一次 invoke
    r1 = await client.invoke(
        "im",
        "send_card",
        recipient={"kind": "channel", "id": "c1"},
        card={"title": "t", "body_markdown": "b", "actions": []},
        idempotency_key="k1",
    )
    assert r1["plugin_name"] == "echo"

    # reaper close
    client.last_invoke_at = time.monotonic() - 100.0
    reaper = IdleDaemonReaper(get_daemons=lambda: [client], timeout_idle=1.0)
    await reaper.scan_once()
    assert client._proc is None

    # 下次 invoke 应自动 lazy spawn 新 daemon
    r2 = await client.invoke(
        "im",
        "send_card",
        recipient={"kind": "channel", "id": "c2"},
        card={"title": "t", "body_markdown": "b", "actions": []},
        idempotency_key="k2",
    )
    assert r2["plugin_name"] == "echo"
    assert r2["native_id"] == "echo-k2"

    await client.close()
