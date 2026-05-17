"""Phase 5.A HulyPlugin fault isolation test。

**用户硬性 DoD #2**（CONTEXT.md §HulyPlugin Acid Test 验收硬性）：
- daemon 子进程被 kill → 主进程下次 invoke 必须：
  1. 立即 raise ``PluginDaemonExitedError``（不是 ``PluginInvocationError``）
  2. 耗时 ``< 2s``（不能走 ``invoke_timeout=30s`` 路径，否则等于 fault isolation 失败）
  3. 主进程其他流程不受影响（webhook / DB 等 — 由 process isolation 天然保证，
     本测仅验证 invoke 路径 + 主进程能起新 daemon 继续工作）

测试链路（覆盖 2 个独立场景）：
1. test_kill_daemon_then_invoke_raises_immediately：
   起 daemon → warmup 1 invoke 验证活 → SIGKILL → 短 sleep → 下次 invoke
   验证 PluginDaemonExitedError + elapsed < 2s
2. test_main_process_can_spawn_new_daemon_after_kill：
   daemon crash 后主进程能 close + 起新 daemon + 继续工作（fault 局部化）

防 timeout 路径退化的关键防御：
- ``invoke_timeout=2.0`` (低 timeout) — 确保 fault isolation 走 daemon-exit 路径，
  而非 timeout 路径（否则 SLO 失败仍能 mask 为 timeout 通过）
- ``elapsed < 2.0`` timing assert — daemon EOF 检测必须在 2s 内触发
"""

from __future__ import annotations

import asyncio
import os
import signal
import time

import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.exceptions import PluginDaemonExitedError

HULY_MODULE = "plugins.huly.huly_plugin"


# ── Test 1: SIGKILL daemon → 下次 invoke 立即 raise < 2s ─────────────────────


@pytest.mark.asyncio
async def test_kill_daemon_then_invoke_raises_immediately(
    mock_huly_server: str,
    project_root: str,
) -> None:
    """SIGKILL daemon 子进程 → 主进程下次 invoke 在 < 2s 内 raise PluginDaemonExitedError。

    验证步骤：
    1. start daemon + 跑 1 个成功 invoke 验证 daemon 活
    2. ``os.kill(daemon._proc.pid, SIGKILL)`` 强杀子进程
    3. 等待 daemon process 被 reap（~50-200ms）
    4. 下次 invoke → 必须 raise ``PluginDaemonExitedError`` 且耗时 < 2s
       （不走 ``invoke_timeout=2.0`` 路径，因为 fault isolation 必须更快）
    """
    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=2.0,  # 低 timeout 确保 fault isolation 走 daemon-exit 路径
        cwd=project_root,
    )

    try:
        # Step 1: 验证 daemon 活（warmup invoke）
        result = await daemon.invoke(
            "im",
            "send_card",
            recipient={"kind": "channel", "id": "warmup"},
            card={"title": "warmup", "body_markdown": "x", "actions": []},
            idempotency_key="warmup-key",
        )
        assert result["plugin_name"] == "huly", (
            f"warmup invoke 应返回 huly plugin_name；实际 {result}"
        )
        assert daemon._proc is not None, "warmup 后 daemon 应已 spawn"
        daemon_pid = daemon._proc.pid

        # Step 2: SIGKILL daemon 子进程
        os.kill(daemon_pid, signal.SIGKILL)

        # Step 3: 等待 daemon process 被 reap（_read_loop 检测 stdout EOF）
        # 给 asyncio reactor 时间处理 SIGCHLD + _read_loop 关闭
        await asyncio.sleep(0.2)

        # Step 4: 下次 invoke 必须 raise PluginDaemonExitedError 且耗时 < 2s
        start = time.monotonic()
        with pytest.raises(PluginDaemonExitedError):
            await daemon.invoke(
                "im",
                "send_card",
                recipient={"kind": "channel", "id": "post-kill"},
                card={"title": "after kill", "body_markdown": "x", "actions": []},
                idempotency_key="post-kill-key",
            )
        elapsed = time.monotonic() - start

        # 关键断言：fault isolation 必须快（< 2s）
        # 若 elapsed ≥ 2.0s，说明走了 timeout 路径而非 fault isolation
        # 等于用户硬性 DoD #2 失败
        assert elapsed < 2.0, (
            f"daemon kill 后 invoke 耗时 {elapsed:.3f}s ≥ 2.0s — "
            "走 timeout 路径而非 fault isolation（用户硬性 DoD #2 失败）"
        )
    finally:
        # close 是 idempotent（Plan 05 已保证）
        await daemon.close()


# ── Test 2: daemon crash 后主进程能起新 daemon 继续工作 ──────────────────────


@pytest.mark.asyncio
async def test_main_process_can_spawn_new_daemon_after_kill(
    mock_huly_server: str,
    project_root: str,
) -> None:
    """daemon crash 后主进程能正常 close 并起新 daemon 实例（不死锁；fault 局部化）。

    验证两点：
    1. 旧 daemon close（即使已死）不会 hang —— ``close`` 幂等 + 5s terminate timeout 兜底
    2. 起新 PlatformDaemonClient 实例能正常 spawn + invoke —— fault 仅影响 crash 的 daemon，
       主进程其他流程完全不受影响（这是 process isolation 的核心承诺）

    验证步骤：
    1. 起 daemon1 + 跑 1 个成功 invoke
    2. SIGKILL daemon1
    3. 等待 reap
    4. close daemon1（不 hang 测试，< 6s 完成）
    5. 起 daemon2（独立实例）
    6. daemon2 invoke 成功 — 证明主进程能继续工作
    """
    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=2.0,
        cwd=project_root,
    )
    try:
        # 起 daemon1 + warmup
        await daemon.invoke(
            "im",
            "send_card",
            recipient={"kind": "channel", "id": "first"},
            card={"title": "first", "body_markdown": "x", "actions": []},
            idempotency_key="first-key",
        )
        assert daemon._proc is not None
        os.kill(daemon._proc.pid, signal.SIGKILL)
        await asyncio.sleep(0.2)
    finally:
        # close 不应 hang（即使 daemon 已死）
        start = time.monotonic()
        await daemon.close()
        elapsed = time.monotonic() - start
        assert elapsed < 6.0, (
            f"close 耗时 {elapsed:.3f}s — 应 < 6s（terminate 5s timeout + reap）"
        )

    # 起一个新 daemon — 主进程不受前次崩溃影响（关键验证点）
    daemon2 = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=5.0,
        cwd=project_root,
    )
    try:
        result = await daemon2.invoke(
            "im",
            "send_card",
            recipient={"kind": "channel", "id": "post-crash-new-daemon"},
            card={"title": "recovery", "body_markdown": "x", "actions": []},
            idempotency_key="recovery-key",
        )
        # 关键断言：新 daemon 真的工作了（拿到 huly mock 的 message_id）
        assert result["plugin_name"] == "huly"
        assert result["native_id"].startswith("huly-msg-"), (
            f"recovery daemon 应当真接通 mock huly server, "
            f"native_id={result['native_id']!r}"
        )
    finally:
        await daemon2.close()
