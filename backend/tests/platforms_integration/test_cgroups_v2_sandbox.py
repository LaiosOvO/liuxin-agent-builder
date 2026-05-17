"""CgroupsV2Sandbox 集成测试 — Linux + systemd-userdbd 真行为验证。

测试覆盖（cgroups v2 内核真 enforcement）:
- smoke: cgroups v2 包裹下 daemon 正常 stdout 通信
- MemoryMax 触发 OOM kill（200MB alloc 超 50MB MemoryMax → SIGKILL/137）
- TasksMax=32 阻 fork bomb（80 次 fork 应在 32 附近失败）

环境约束（**任一不满足全 skip**）:
- 必须 Linux（macOS skip — cgroups v2 是 Linux 专属）
- 必须 ``is_cgroups_v2_available()`` 真试 systemd-run --user 成功
  - 容器（docker / GitHub Actions ubuntu-latest）通常无 cgroup delegation → skip
  - 物理 Linux + 桌面用户 + systemd-userdbd 运行 → 真跑

CI 兼容性:
- macOS 本地 dev: 全部 skipped（cgroups v2 不可用）
- GitHub Actions ubuntu-latest: 全部 skipped（容器无 systemd-userdbd）
- Linux 物理机 dev: 真跑 3 测全绿

Reference: docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.agent_builder.platforms.sandbox.cgroups_v2 import (
    CgroupsV2Sandbox,
    is_cgroups_v2_available,
)

# ── pytest markers + skipif（macOS / 容器 / 无 systemd 全 skip） ──────────────


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.linux_only,
    pytest.mark.cgroups_v2,
    pytest.mark.sandbox_integration,
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="cgroups v2 是 Linux 专属（Pitfall 2 — macOS 无 cgroups 实现）",
    ),
    pytest.mark.skipif(
        not is_cgroups_v2_available(),
        reason=(
            "cgroups v2 / systemd-run --user 不可用 — "
            "容器无 cgroup delegation / 无 systemd-userdbd / 无 systemd-run "
            "(CI ubuntu-latest 通常 skip — Pitfall 2)"
        ),
    ),
]


# ── smoke: cgroups v2 包裹不破坏 stdout 通信 ────────────────────────────────


async def test_cgroups_v2_smoke_normal_daemon() -> None:
    """smoke: CgroupsV2Sandbox 包裹下 daemon 仍能正常 stdout 通信。

    验证 ``--quiet`` 抑制了 systemd-run 自身的 unit name 输出（否则会污染 stdout pipe）。
    """
    sandbox = CgroupsV2Sandbox()
    proc = await sandbox.spawn_with_limits(
        [sys.executable, "-u", "-c", "print('hello cgroups', flush=True)"],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    assert b"hello cgroups" in stdout, (
        f"stdout pipe 应能传递 daemon 输出，实际: {stdout!r}"
    )


# ── MemoryMax 触发 cgroups v2 OOM kill ──────────────────────────────────────


async def test_cgroups_v2_memory_max_triggers_oom() -> None:
    """cgroups MemoryMax=50MB → daemon alloc 200MB 应被 OOM kill。

    Pitfall 7 验证: ``--collect`` 让 cgroup 在 OOM 后自动释放（否则下次 spawn EBUSY）。
    OOM kill 信号在 Python 中表现为 returncode = -SIGKILL = -9 或 137（shell convention）。
    """
    sandbox = CgroupsV2Sandbox()
    proc = await sandbox.spawn_with_limits(
        [
            sys.executable,
            "-u",
            "-c",
            "x = b'a' * (200 * 1024 * 1024); print('alloc_unexpected_ok', flush=True)",
        ],
        cpu_seconds=10,
        memory_bytes=50 * 1024 * 1024,  # 50MB 限制
    )
    await asyncio.wait_for(proc.wait(), timeout=15.0)
    # cgroups OOM kill → SIGKILL；returncode = -9 (Python negative) 或 137 (shell)
    assert proc.returncode != 0, (
        f"200MB alloc 超 50MB MemoryMax 应被 OOM kill；实际 returncode={proc.returncode}"
    )


# ── TasksMax 阻 fork bomb ──────────────────────────────────────────────────


async def test_cgroups_v2_tasks_max_blocks_fork_bomb() -> None:
    """cgroups TasksMax=32 → 子进程 fork 远超 32 时应失败（防 fork bomb）。

    daemon 尝试 fork 80 次 subprocess.Popen — cgroups TasksMax 应在远小于 80 时阻断。
    """
    code = (
        "import subprocess, sys\n"
        "children = []\n"
        "for i in range(80):\n"
        "    try:\n"
        "        children.append(subprocess.Popen(\n"
        "            [sys.executable, '-c', 'import time; time.sleep(5)']\n"
        "        ))\n"
        "    except (OSError, BlockingIOError) as e:\n"
        "        print(f'fork_failed_at_{i}', flush=True)\n"
        "        break\n"
        "print(f'spawned_{len(children)}', flush=True)\n"
    )
    sandbox = CgroupsV2Sandbox()
    proc = await sandbox.spawn_with_limits(
        [sys.executable, "-u", "-c", code],
        cpu_seconds=10,
        memory_bytes=300 * 1024 * 1024,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
    out = stdout.decode()
    # 容差: cgroups TasksMax=32 应在 30 多次 fork 后阻断（含 daemon 自己 + 内核 task）
    # 接受 "fork_failed_at_<N>" 或 "spawned_N" 形式，但 N 应 < 60（远小于 80）
    assert "fork_failed_at_" in out or "spawned_" in out, f"输出格式异常：{out}"

    for line in out.splitlines():
        if line.startswith("spawned_"):
            n = int(line.split("_")[1])
            assert n < 60, f"TasksMax=32 应阻 fork 超 60 次；实际 spawned={n}"
