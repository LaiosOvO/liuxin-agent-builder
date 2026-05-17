"""Phase 5.C Plan 01 — SandboxRunner docker_networks 集成测试（真 docker，禁止 mock）。

CLAUDE.md §2.2 / §feedback_e2e_browser_harness:
- 集成测试必须真起 docker network（不 mock docker SDK）
- 真 spawn host process（asyncio.create_subprocess_exec 真起 Python）
- mock huly server 18087 端口可监听（Wave 2-3 mock huly server 复用基线）
- 仅 Linux + docker 可用时跑真 docker test，macOS / 无 docker 环境 skip 真 docker
  （happy path 不依赖 docker，跨平台跑）

测试场景:
- happy path: daemon 是 host process（macOS / Linux 非 container 部署）→ docker_networks=[] no-op
- Linux + docker 真 attach 失败模式 3 (host pid not in container) 真实表现
- mock huly server @ 127.0.0.1:18087 端口连通性（Wave 2-3 复用基线）

E2E gate 留 plan 08（DAG → doc_write → 真 Outline/Lark/Huly 文档）。

License: 100% 独立创作 — Dify AGPL-3.0 仅借鉴设计模式。
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import sys

import pytest

from app.agent_builder.platforms.sandbox.cgroups_v2 import CgroupsV2Sandbox
from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox


def _docker_available() -> bool:
    """检测 docker daemon 是否真可用（CI / 本地）。

    Returns:
        True 当且仅当 `docker version --format ...` 在 2s 内返回 returncode 0。
        False 在 macOS docker desktop 未启 / CI 未装 docker / docker engine 不响应。
    """
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=2,
            check=False,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


_DOCKER_OK = _docker_available()
_IS_LINUX = sys.platform == "linux"


# ── happy path: host process no-op（跨平台跑，不依赖 docker） ─────────────────


@pytest.mark.asyncio
async def test_posix_resource_docker_networks_empty_default() -> None:
    """空 docker_networks → daemon 正常 spawn + no-op + 不依赖 docker SDK。"""
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-c", "print('hello'); import sys; sys.exit(0)"],
        cpu_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        docker_networks=[],
    )
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_posix_resource_docker_networks_none_no_op() -> None:
    """docker_networks=None（5.A/5.B 老路径）→ daemon 正常 spawn + 0 影响。"""
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-c", "print('alive'); import sys; sys.exit(0)"],
        cpu_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        # 不传 docker_networks（兜底 None 默认）
    )
    await proc.wait()
    assert proc.returncode == 0


# ── CgroupsV2 真 docker network attach 失败模式 3（仅 Linux + docker） ───────


@pytest.mark.skipif(
    not (_DOCKER_OK and _IS_LINUX),
    reason="requires Linux + docker daemon (macOS / CI without docker skips)",
)
@pytest.mark.asyncio
async def test_cgroups_v2_attach_real_docker_network_host_pid_fails() -> None:
    """CgroupsV2 host process pid（非 container）→ _attach raise RuntimeError 失败模式 3。

    此测试在 Linux + docker 可用环境验证 Pitfall 5 失败模式 3 真实表现。
    集成测真起 docker network create + 真 spawn host process（asyncio.create_subprocess_exec）
    + 调 _attach 触发"pid 不在 container"错误路径 + 真 cleanup docker network。

    禁止 mock docker（CLAUDE.md §2.2）— 这是集成测试的核心契约。
    """
    net_name = "test-net-phase5c-01"

    # 真创建 test-net（已存在 ignore）
    subprocess.run(
        ["docker", "network", "create", net_name],
        capture_output=True,
        check=False,
    )

    try:
        sb = CgroupsV2Sandbox()
        # 真 spawn 一个 host process（非 container）
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(2)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        with pytest.raises(RuntimeError, match="not in any docker container"):
            await sb._attach_docker_networks(proc, [net_name])

        # daemon 必须被 terminate
        await proc.wait()
    finally:
        # cleanup test-net 不管前面成功 / 失败
        subprocess.run(
            ["docker", "network", "rm", net_name],
            capture_output=True,
            check=False,
        )


# ── mock huly server 端口连通性（Wave 2-3 基线） ──────────────────────────────


def test_mock_huly_server_can_listen_on_18087() -> None:
    """Phase 5.C 测试基线: mock huly server 监听 127.0.0.1:18087 应可用（防端口冲突）。

    若此 test fail（端口被占），后续 Wave 2-3 huly mock 测试会全部失败。
    本测试不真起 mock server，仅校验 18087 端口本机当前可 bind + listen。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", 18087))
        s.listen(1)
    except OSError as e:
        pytest.fail(
            f"port 18087 unavailable (Wave 2-3 mock huly server 基线): {e}"
        )
    finally:
        s.close()
