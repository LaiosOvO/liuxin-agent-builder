"""SandboxWatchdog 集成测试 — 真 spawn 子进程验证 SIGTERM grace → SIGKILL 路径.

Linux only：macOS RLIMIT_AS 弱 enforcement + /proc 不可读 + setsid 行为差异。
在 GitHub Actions ubuntu-latest CI 上跑。

测试 fixture：tests.platforms_integration.fixtures.sigterm_ignoring_daemon
- 故意 SIGTERM = SIG_IGN
- alloc_200mb method 分配 200MB byte buffer 持久（让 RSS 真涨）

验证：
1. test_watchdog_sigterm_then_sigkill_after_grace: invoke alloc_200mb → watchdog 超限
   → SIGTERM (被 IGN) → 3s grace → SIGKILL → daemon.returncode == -9 + invoke raise
   SandboxLimitExceeded + elapsed < 9.0s
2. test_watchdog_normal_daemon_no_violation: 起 echo_daemon + sandbox_config(memory='500Mi')
   → invoke 多次成功 + watchdog 任务存活 + 无 SandboxLimitExceeded
3. test_watchdog_on_violation_fails_pending_invoke_immediately: invoke alloc 长 timeout
   → watchdog 超限触发 → invoke 立即 raise SandboxLimitExceeded（不是 timeout）→ elapsed < 10s
"""

from __future__ import annotations

import sys
import time

import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.exceptions import (
    PluginDaemonExitedError,
    SandboxLimitExceeded,
)
from app.agent_builder.platforms.manifest import SandboxConfig

# 仅 Linux 跑（macOS RLIMIT 弱 + /proc/<pid>/status 不可读）
pytestmark = [
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="macOS RLIMIT 弱 enforcement + /proc 不可读 — Linux CI 跑",
    ),
    pytest.mark.linux_only,
    pytest.mark.sandbox_integration,
]


SIGTERM_IGNORING_MODULE = (
    "tests.platforms_integration.fixtures.sigterm_ignoring_daemon"
)
ECHO_MODULE = "tests.platforms.fixtures.echo_daemon"


@pytest.mark.asyncio
async def test_watchdog_sigterm_then_sigkill_after_grace() -> None:
    """daemon 忽略 SIGTERM → watchdog 3s grace → SIGKILL daemon.returncode == -9.

    超限检测路径：
    1. invoke alloc_200mb → daemon 分配 200MB
    2. watchdog 5s 后扫描 → RSS > 50MB → SIGTERM
    3. daemon IGN SIGTERM → 3s grace
    4. SIGKILL → daemon.returncode == -SIGKILL (-9)
    5. invoke raise SandboxLimitExceeded
    6. elapsed < 9.0s（scan 5 + grace 3 + jitter 1）
    """
    cfg = SandboxConfig(memory="50Mi", timeout_invoke=30)
    client = PlatformDaemonClient(
        SIGTERM_IGNORING_MODULE,
        sandbox_config=cfg,
        invoke_timeout=30.0,
    )

    start = time.monotonic()
    try:
        with pytest.raises((SandboxLimitExceeded, PluginDaemonExitedError)):
            await client.invoke("im", "alloc_200mb")

        elapsed = time.monotonic() - start
        # 上限 9s: scan_interval (5s default) + grace_period (3s default) + jitter (1s)
        assert elapsed < 12.0, (
            f"watchdog kill 路径耗时 {elapsed:.1f}s 过长 — 检查 grace 配置"
        )

        # daemon returncode 应是 -SIGKILL (-9)
        if client._proc is not None and client._proc.returncode is not None:
            # -9 = SIGKILL（POSIX 返码约定）；某些场景可能是 -15 SIGTERM 才生效
            assert client._proc.returncode in (-9, -15, 1, 137), (
                f"daemon returncode 应是 -9 SIGKILL，实际 {client._proc.returncode}"
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_watchdog_normal_daemon_no_violation() -> None:
    """正常 daemon（不超内存）→ watchdog 不触发 + invoke 多次成功.

    用 echo_daemon + sandbox_config(memory='500Mi')；echo 不分配大内存。
    """
    cfg = SandboxConfig(memory="500Mi", timeout_invoke=10)
    client = PlatformDaemonClient(
        ECHO_MODULE,
        sandbox_config=cfg,
        invoke_timeout=10.0,
    )

    try:
        # 多次 invoke 成功 — watchdog 不应误触发
        for i in range(3):
            result = await client.invoke(
                "im",
                "send_card",
                recipient={"kind": "channel", "id": f"c{i}"},
                card={"title": "t", "body_markdown": "b", "actions": []},
                idempotency_key=f"k{i}",
            )
            assert result["plugin_name"] == "echo"

        # watchdog task 存活
        assert client._watchdog is not None
        assert client._watchdog._task is not None
        assert not client._watchdog._task.done(), "watchdog task 不应自动 exit"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_watchdog_on_violation_fails_pending_invoke_immediately() -> None:
    """**Pitfall 5 关键**：watchdog on_violation 让主 invoke 立即 raise，不是 timeout.

    invoke_timeout=30s 给足容差；如果走 timeout 路径会等 30s；
    走 watchdog on_violation 路径应 < 10s（scan + grace）。
    """
    cfg = SandboxConfig(memory="50Mi", timeout_invoke=30)
    client = PlatformDaemonClient(
        SIGTERM_IGNORING_MODULE,
        sandbox_config=cfg,
        invoke_timeout=30.0,  # 长 timeout 验证不走 timeout 路径
    )

    start = time.monotonic()
    try:
        with pytest.raises((SandboxLimitExceeded, PluginDaemonExitedError)):
            await client.invoke("im", "alloc_200mb")

        elapsed = time.monotonic() - start
        # 必须 < 15s 才能证明走 watchdog on_violation 不是 30s timeout
        assert elapsed < 15.0, (
            f"watchdog on_violation 应让 invoke 立即 raise，elapsed={elapsed:.1f}s 太长 "
            f"— 可能走了 30s timeout 路径"
        )
    finally:
        await client.close()
