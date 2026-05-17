"""AllowlistTransport 端到端集成测（PLUG-FW-11）。

测试策略:

- ``asyncio.subprocess.create_subprocess_exec`` 真起 ``network_test_daemon`` 子进程
  （模拟 plugin daemon 启动场景）
- 通过 env ``PLUGIN_NETWORK_ALLOW`` + ``TARGET_URL`` 注入测试参数
- 断言 daemon 进程的 returncode + stdout/stderr 区分行为类型:
  - 10: ``blocked:`` （AllowlistTransport 拒绝 — v1 预期）
  - 20: ``network_error:`` （白名单放行 + 真网络不通 — DNS / connect 失败）
  - 0:  ``unexpected_ok:`` （真发请求并成功 — 测试中通常不应到达）
  - 30: ``import_error:`` （PYTHONPATH 错或 module 缺失）

4 测试覆盖（计划要求 ≥ 4）：
- empty allow → blocked everything
- target 在 allow → 放行真发请求（DNS 不可控故只断言 returncode != 10）
- target 不在 allow → blocked
- structured log ``network.blocked`` event 出现在 stderr

均加 ``@pytest.mark.sandbox_integration`` marker（Plan 05b-02 已注册到 pyproject.toml）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.sandbox_integration


# backend/ 目录 — fixture daemon 子进程的 cwd
_BACKEND_DIR = Path(__file__).resolve().parents[2]


async def _run_daemon(
    *, allow: str, target_url: str, timeout: float = 15.0
) -> tuple[int, str, str]:
    """spawn fixture daemon 子进程, 等其退出, 返回 ``(returncode, stdout, stderr)``。

    cwd 必须是 backend/ — 让 daemon 内 ``from app.agent_builder...`` 能解析。
    """
    env = {
        **os.environ,
        "PLUGIN_NETWORK_ALLOW": allow,
        "TARGET_URL": target_url,
        # 显式不继承 PROXY env — 防 CI 上有 HTTP_PROXY 干扰真发请求行为
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "NO_PROXY": "*",
    }
    # 启用 sandbox.network logger WARNING 级 → stderr，用来断言 structured log
    env["PYTHONUNBUFFERED"] = "1"
    env["LOG_LEVEL"] = "WARNING"

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-m",
        "tests.platforms_integration.fixtures.network_test_daemon",
        cwd=str(_BACKEND_DIR),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


@pytest.mark.asyncio
async def test_daemon_with_empty_allow_blocks_everything():
    """空 allow + 任意 TARGET → AllowlistTransport 拒（returncode=10, stdout 含 blocked）。"""
    rc, stdout, stderr = await _run_daemon(
        allow="", target_url="https://blocked.example.com/"
    )
    assert rc == 10, (
        f"expected returncode 10 (blocked) but got {rc}; "
        f"stdout={stdout!r} stderr={stderr!r}"
    )
    assert "blocked:" in stdout, f"stdout missing 'blocked:': {stdout!r}"


@pytest.mark.asyncio
async def test_daemon_target_in_allow_attempts_real_request():
    """target host 在 allow → AllowlistTransport 放行 → 真发请求。

    DNS 不可控（``blocked.example.com`` 不存在）—— 期望 returncode != 10（**不**被 AllowlistTransport
    block，而是后续真发请求失败 / 成功）。

    可能结果:
    - returncode 20 + ``network_error:`` （DNS / connect failure — 最常见）
    - returncode 0 + ``unexpected_ok:`` （如果 CI 有 DNS 重定向 — 也算"放行"语义正确）
    """
    rc, stdout, stderr = await _run_daemon(
        allow="blocked.example.com:443",
        target_url="https://blocked.example.com/",
    )
    assert rc != 10, (
        f"expected NOT 10 (放行后真发请求) but got {rc}; "
        f"stdout={stdout!r} stderr={stderr!r}"
    )
    # stdout 应含 network_error 或 unexpected_ok（不应是 blocked / import_error）
    assert "blocked:" not in stdout
    assert any(prefix in stdout for prefix in ("network_error:", "unexpected_ok:")), (
        f"expected network_error: or unexpected_ok: in stdout, got: {stdout!r}"
    )


@pytest.mark.asyncio
async def test_daemon_target_not_in_allow_is_blocked():
    """target host 不在 allow（allow 含别的 host）→ 拒。"""
    rc, stdout, stderr = await _run_daemon(
        allow="other-host.com:443",
        target_url="https://blocked.example.com/",
    )
    assert rc == 10, f"expected blocked (rc=10) got {rc}; stdout={stdout!r}"
    assert "blocked:" in stdout
    assert "blocked.example.com" in stdout


@pytest.mark.asyncio
async def test_daemon_logs_network_blocked_event_in_stderr(caplog):
    """拒绝时 structured log ``network.blocked`` 出现在 stderr（监控可串告警）。

    Python logging 默认输出到 stderr; fixture daemon 也不重定向 logging,
    所以 ``_log.warning("network.blocked ...")`` 应出现在子进程 stderr。
    """
    rc, stdout, stderr = await _run_daemon(
        allow="other-host.com:443",
        target_url="https://blocked.example.com/",
    )
    assert rc == 10
    # logging.basicConfig 在 daemon 内未显式 setLevel — 默认是 WARNING 上报
    # warning 默认输出到 stderr
    assert "network.blocked" in stderr, (
        f"expected 'network.blocked' in stderr, got: {stderr!r}"
    )
