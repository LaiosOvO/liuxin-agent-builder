"""PosixResourceSandbox contract tests（cross-platform — macOS + Linux 都跑）。

本测试**不**断言资源 enforcement（macOS RLIMIT 弱 — Pitfall 1）：
- API 不抛错 ✓
- spawn 返回 asyncio.subprocess.Process ✓
- stdin/stdout/stderr PIPE 通信正常 ✓
- env / cwd 注入生效 ✓
- os.setsid() 让 daemon 成 session leader ✓
- close_fds=True 防 fd 泄漏（跨平台路径分流）✓
- RLIMIT_NPROC=16 在子进程内可观测（NPROC 是 cross-platform 严格的）✓

Linux-only enforcement test 在 `tests/platforms_integration/test_resource_limits.py`
（用 `@pytest.mark.linux_only` + `@pytest.mark.skipif(sys.platform == 'darwin')`）。

Reference: docs/reading-dify-05b-02-resource-runner-2026-05-17.md
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from app.agent_builder.platforms.sandbox.runner import (
    _DEFAULT_NPROC_LIMIT,
    PosixResourceSandbox,
    SandboxRunner,
)


# ── Protocol contract ──────────────────────────────────────────────────────────


def test_sandbox_runner_is_protocol() -> None:
    """PosixResourceSandbox 实例满足 SandboxRunner Protocol（runtime_checkable）。

    Wave 3 CgroupsV2Sandbox 必须通过同样断言（接口契约稳定性保证）。
    """
    sb = PosixResourceSandbox()
    assert isinstance(
        sb, SandboxRunner
    ), "PosixResourceSandbox 必须满足 SandboxRunner Protocol"


# ── 基础 spawn + 通信 ──────────────────────────────────────────────────────────


async def test_posix_sandbox_spawn_returns_process() -> None:
    """spawn_with_limits 返回 asyncio.subprocess.Process（与 5.A daemon_client API 一致）。"""
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-u", "-c", 'print("ok")'],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
    )
    assert isinstance(proc, asyncio.subprocess.Process), (
        f"返回类型应为 asyncio.subprocess.Process，实际: {type(proc)}"
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    assert stdout == b"ok\n", f"stdout 应为 'ok\\n'，实际: {stdout!r}"
    assert stderr == b"", f"stderr 应为空，实际: {stderr!r}"


async def test_posix_sandbox_stdin_pipe_works() -> None:
    """stdin PIPE 工作正常（5.A daemon_client JSONRPC 写入路径依赖此契约）。"""
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-u", "-c", "import sys; print(sys.stdin.read())"],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
    )
    assert proc.stdin is not None
    proc.stdin.write(b"hello\n")
    proc.stdin.close()
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    assert b"hello" in stdout, f"stdin echo 应含 'hello'，实际: {stdout!r}"


# ── env / cwd 注入 ─────────────────────────────────────────────────────────────


async def test_posix_sandbox_env_injection() -> None:
    """env 字段覆盖 os.environ（Wave 3 daemon_client 注入 HULY_ENDPOINT 等关键变量）。"""
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [
            sys.executable,
            "-u",
            "-c",
            'import os; print(os.environ.get("FOO", "missing"))',
        ],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
        env={"FOO": "bar", "PATH": os.environ.get("PATH", "")},
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    assert stdout.strip() == b"bar", f"env FOO 注入应为 'bar'，实际: {stdout!r}"


async def test_posix_sandbox_cwd_set() -> None:
    """cwd 字段切换工作目录（5.A acid test 用根目录注入让 daemon 找 plugins 包）。"""
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-u", "-c", "import os; print(os.getcwd())"],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
        cwd="/tmp",
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    # macOS /tmp 是 symlink → /private/tmp；Linux 直接 /tmp；两者都接受
    cwd_out = stdout.strip().decode()
    assert cwd_out in ("/tmp", "/private/tmp"), (
        f"cwd 应为 /tmp 或 /private/tmp，实际: {cwd_out!r}"
    )


# ── os.setsid() 验证（Pitfall 4 进程组隔离）────────────────────────────────────


async def test_posix_sandbox_setsid_new_session() -> None:
    """setsid 后 daemon 是 session leader（pid == sid）— Pitfall 4 防护核心。

    主进程后续 os.killpg(pgid, SIGTERM) 才能精准 kill 整棵子进程树。
    """
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [
            sys.executable,
            "-u",
            "-c",
            "import os; print(os.getpid() == os.getsid(0))",
        ],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    assert stdout.strip() == b"True", (
        f"setsid 后 pid 应等于 sid（session leader）；stdout={stdout!r}"
    )


# ── close_fds=True 防 fd 泄漏 ──────────────────────────────────────────────────


async def test_posix_sandbox_close_fds_no_leak() -> None:
    """close_fds=True 防父进程 fd 泄漏到子进程。

    Linux: 读 /proc/self/fd 计 fd 数，断言 ≤ 6（stdin/out/err + 少量 Python internal）
    macOS: /proc 不存在 — 走兜底（os.listdir 抛异常，子进程打印 'no_proc'）
    """
    sb = PosixResourceSandbox()
    code = (
        "import os\n"
        "if os.path.exists('/proc/self/fd'):\n"
        "    print(len(os.listdir('/proc/self/fd')))\n"
        "else:\n"
        "    print('no_proc')\n"
    )
    proc = await sb.spawn_with_limits(
        [sys.executable, "-u", "-c", code],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    out = stdout.strip().decode()
    if sys.platform == "darwin":
        # macOS 无 /proc — 走兜底分支（HIGH-3 fix: 显式 skip enforcement check）
        assert out == "no_proc", (
            f"macOS 应无 /proc/self/fd，但实际输出: {out!r}（HIGH-3 fix）"
        )
        pytest.skip(
            "macOS 无 /proc/self/fd — close_fds enforcement 验证跳过（Linux CI 跑）"
        )
    else:
        # Linux: fd 数应 ≤ 6（stdin/stdout/stderr + Python interpreter internal）
        fd_count = int(out)
        assert fd_count <= 6, (
            f"close_fds=True 下子进程 fd 数应 ≤ 6（防泄漏），实际: {fd_count}"
        )


# ── RLIMIT_NPROC 注入验证（cross-platform 严格）────────────────────────────────


async def test_posix_sandbox_rlimit_nproc_set() -> None:
    """RLIMIT_NPROC=16 在子进程内可观测 — cross-platform 严格生效（不在 macOS 弱 enforcement 列表）。

    其他 RLIMIT（CPU/AS）在 macOS 跳过设置（Darwin kernel 拒绝降低），
    但 NPROC + NOFILE 在 macOS + Linux 都严格 ✓
    """
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [
            sys.executable,
            "-u",
            "-c",
            "import resource; print(resource.getrlimit(resource.RLIMIT_NPROC))",
        ],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    out = stdout.decode().strip()
    expected = f"({_DEFAULT_NPROC_LIMIT}, {_DEFAULT_NPROC_LIMIT})"
    assert expected in out, f"RLIMIT_NPROC 应为 {expected}，实际: {out!r}"


async def test_posix_sandbox_rlimit_nofile_set() -> None:
    """RLIMIT_NOFILE=256 在子进程内可观测 — cross-platform 严格生效。

    防句柄泄漏 baseline；daemon stdin/stdout/stderr + httpx 连接池 + 业务 fd ≤ 256。
    """
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [
            sys.executable,
            "-u",
            "-c",
            "import resource; print(resource.getrlimit(resource.RLIMIT_NOFILE))",
        ],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    out = stdout.decode().strip()
    assert "(256, 256)" in out, f"RLIMIT_NOFILE 应为 (256, 256)，实际: {out!r}"


# ── Cross-platform 路径分流验证 ────────────────────────────────────────────────


async def test_posix_sandbox_does_not_raise_on_macos() -> None:
    """macOS 上 spawn_with_limits 不应 raise（Pitfall 1: AS setrlimit 在 macOS 必失败）。

    本测在 Linux 也跑（验证 cross-platform API 兼容）：spawn 成功 + 返回 Process 即视为通过。
    """
    sb = PosixResourceSandbox()
    # 即使在 macOS 上传 100MB memory_bytes（小于 process 当前 mapped），不应抛
    proc = await sb.spawn_with_limits(
        [sys.executable, "-u", "-c", 'print("alive")'],
        cpu_seconds=5,
        memory_bytes=100 * 1024 * 1024,  # macOS 上此值会让 setrlimit raise — 必须跳过
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    assert stdout.strip() == b"alive", (
        f"spawn 应在 macOS / Linux 都成功（不依赖 AS enforcement）；stdout={stdout!r}"
    )
