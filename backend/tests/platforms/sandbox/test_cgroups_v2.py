"""CgroupsV2Sandbox 单元测试 — 全 mock systemd-run / subprocess（cross-platform）。

测试覆盖：
- ``is_cgroups_v2_available`` 4 检测路径 + silent fail（任何环境不抛）
- ``CgroupsV2Sandbox.spawn_with_limits`` systemd-run cmd 正确构造
- Protocol 契约（``isinstance(CgroupsV2Sandbox(), SandboxRunner) is True``）
- ``PlatformDaemonClient._choose_runner`` 3 分支:
  - use_cgroups=True + available → CgroupsV2Sandbox
  - use_cgroups=True + unavailable → PosixResourceSandbox + warning log
  - use_cgroups=False → PosixResourceSandbox 不调 is_cgroups_v2_available

设计：全 mock 路径让 macOS + Linux + CI ubuntu-latest 都跑通。
真行为测试见 ``tests/platforms_integration/test_cgroups_v2_sandbox.py``（cgroups_v2 marker）。

Reference: docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md §可借鉴的设计模式
"""

from __future__ import annotations

import logging
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.manifest import SandboxConfig
from app.agent_builder.platforms.sandbox.cgroups_v2 import (
    _CPU_QUOTA,
    _SYSTEMD_SLICE,
    _TASKS_MAX,
    CgroupsV2Sandbox,
    is_cgroups_v2_available,
)
from app.agent_builder.platforms.sandbox.runner import (
    PosixResourceSandbox,
    SandboxRunner,
)


# ── is_cgroups_v2_available 4 条检测（任一失败 silent return False） ──────────


def test_is_cgroups_v2_available_returns_false_when_no_controllers_file() -> None:
    """检查 1: ``/sys/fs/cgroup/cgroup.controllers`` 不存在 → False。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path:
        mock_path.exists.return_value = False
        assert is_cgroups_v2_available() is False


def test_is_cgroups_v2_available_returns_false_when_missing_memory_controller() -> None:
    """检查 2: 文件存在但缺 memory controller → False。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path:
        mock_path.exists.return_value = True
        # 仅 cpu + pids 启用，缺 memory
        mock_path.read_text.return_value = "cpu pids"
        assert is_cgroups_v2_available() is False


def test_is_cgroups_v2_available_returns_false_when_missing_cpu_controller() -> None:
    """检查 2 反向: 文件存在但缺 cpu controller → False。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "memory pids"
        assert is_cgroups_v2_available() is False


def test_is_cgroups_v2_available_returns_false_when_no_systemd_run_in_path() -> None:
    """检查 3: ``shutil.which('systemd-run')`` 返回 None → False。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path, patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.shutil.which",
        return_value=None,
    ):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "cpu memory pids io"
        assert is_cgroups_v2_available() is False


def test_is_cgroups_v2_available_returns_false_when_systemd_run_probe_fails() -> None:
    """检查 4: 真试 systemd-run returncode != 0（容器 EPERM）→ False。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path, patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.shutil.which",
        return_value="/usr/bin/systemd-run",
    ), patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.subprocess.run"
    ) as mock_run:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "cpu memory pids io"
        # 模拟容器内 systemd-run EPERM
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"Permission denied"
        )
        assert is_cgroups_v2_available() is False


def test_is_cgroups_v2_available_returns_false_when_systemd_run_times_out() -> None:
    """检查 4 边界: systemd-run 真试 hang → TimeoutExpired → False（Pitfall 2）。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path, patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.shutil.which",
        return_value="/usr/bin/systemd-run",
    ), patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=[], timeout=2.0),
    ):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "cpu memory pids io"
        # 必须 silent return False，不抛 TimeoutExpired
        assert is_cgroups_v2_available() is False


def test_is_cgroups_v2_available_silent_on_permission_error() -> None:
    """边界: read_text 抛 PermissionError → silent return False（容器内文件不可读）。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path:
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = PermissionError("read denied")
        # 必须 silent return False，不抛 PermissionError
        assert is_cgroups_v2_available() is False


def test_is_cgroups_v2_available_returns_true_when_all_checks_pass() -> None:
    """正向路径: 4 条全过 → True。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2._CGROUP_CONTROLLERS_PATH"
    ) as mock_path, patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.shutil.which",
        return_value="/usr/bin/systemd-run",
    ), patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.subprocess.run"
    ) as mock_run:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "cpu memory pids io"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        )
        assert is_cgroups_v2_available() is True


# ── CgroupsV2Sandbox.spawn_with_limits 命令构造 ──────────────────────────────


@pytest.mark.asyncio
async def test_cgroups_v2_sandbox_builds_correct_systemd_cmd() -> None:
    """spawn_with_limits 构造的 systemd-run 命令包含所有必需 properties + flags。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = MagicMock(pid=12345)

        sandbox = CgroupsV2Sandbox()
        await sandbox.spawn_with_limits(
            ["python", "-u", "-m", "fake_module"],
            cpu_seconds=5,
            memory_bytes=512 * 1024 * 1024,
        )

        # 提取 cmd args（mock_exec 第 1 个 positional arg 起）
        called_args = mock_exec.call_args.args
        assert called_args[0] == "systemd-run"
        assert "--user" in called_args
        assert "--scope" in called_args
        assert f"--slice={_SYSTEMD_SLICE}" in called_args
        assert "--quiet" in called_args
        assert "--collect" in called_args  # Pitfall 7

        # 资源属性 — bytes 数值传入
        assert f"--property=MemoryMax={512 * 1024 * 1024}" in called_args
        assert "--property=MemorySwapMax=0" in called_args  # 防 swap 绕过
        assert f"--property=CPUQuota={_CPU_QUOTA}" in called_args
        assert f"--property=TasksMax={_TASKS_MAX}" in called_args

        # 分隔符 + 透传 daemon cmd
        assert "--" in called_args
        assert "fake_module" in called_args


@pytest.mark.asyncio
async def test_cgroups_v2_sandbox_passes_env_and_cwd() -> None:
    """env + cwd 参数正确传入 asyncio.create_subprocess_exec。"""
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = MagicMock(pid=12345)

        sandbox = CgroupsV2Sandbox()
        await sandbox.spawn_with_limits(
            ["python", "-c", "print('ok')"],
            cpu_seconds=10,
            memory_bytes=100 * 1024 * 1024,
            env={"FOO": "bar"},
            cwd="/tmp/test",
        )

        # kwargs 包含 env + cwd
        assert mock_exec.call_args.kwargs["env"] == {"FOO": "bar"}
        assert mock_exec.call_args.kwargs["cwd"] == "/tmp/test"


def test_cgroups_v2_sandbox_implements_runner_protocol() -> None:
    """Protocol contract: CgroupsV2Sandbox 满足 SandboxRunner（runtime_checkable）。"""
    sb = CgroupsV2Sandbox()
    assert isinstance(
        sb, SandboxRunner
    ), "CgroupsV2Sandbox 必须满足 SandboxRunner Protocol"


# ── PlatformDaemonClient._choose_runner 3 分支 ────────────────────────────────


def test_choose_runner_picks_cgroups_when_use_cgroups_true_and_available() -> None:
    """use_cgroups=True + is_cgroups_v2_available()=True → CgroupsV2Sandbox。"""
    cfg = SandboxConfig(use_cgroups=True)
    client = PlatformDaemonClient("fake_module", sandbox_config=cfg)

    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.is_cgroups_v2_available",
        return_value=True,
    ):
        runner = client._choose_runner()

    assert isinstance(
        runner, CgroupsV2Sandbox
    ), f"use_cgroups=True 且可用应返回 CgroupsV2Sandbox，实际: {type(runner).__name__}"


def test_choose_runner_falls_back_when_cgroups_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """use_cgroups=True + is_cgroups_v2_available()=False → PosixResourceSandbox + warning."""
    cfg = SandboxConfig(use_cgroups=True)
    client = PlatformDaemonClient("fake_module", sandbox_config=cfg)

    with caplog.at_level(logging.WARNING), patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.is_cgroups_v2_available",
        return_value=False,
    ):
        runner = client._choose_runner()

    assert isinstance(
        runner, PosixResourceSandbox
    ), f"cgroups unavailable 应降级 PosixResourceSandbox，实际: {type(runner).__name__}"
    # 验证 warning log 含关键诊断信息（Pitfall 2 提示）
    assert any(
        "sandbox.cgroups_v2.unavailable" in record.message for record in caplog.records
    ), "降级时必须 log warning sandbox.cgroups_v2.unavailable"


def test_choose_runner_picks_posix_when_use_cgroups_false() -> None:
    """use_cgroups=False → PosixResourceSandbox 不调 is_cgroups_v2_available（spy 验证）。"""
    cfg = SandboxConfig(use_cgroups=False)
    client = PlatformDaemonClient("fake_module", sandbox_config=cfg)

    # spy is_cgroups_v2_available — 应完全不被调用
    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.is_cgroups_v2_available"
    ) as spy:
        runner = client._choose_runner()

    assert isinstance(runner, PosixResourceSandbox)
    assert spy.call_count == 0, (
        f"use_cgroups=False 时不应触发 is_cgroups_v2_available 调用，实际调用 {spy.call_count} 次"
    )


def test_choose_runner_picks_posix_when_no_sandbox_config() -> None:
    """sandbox_config=None → PosixResourceSandbox（5.A 兼容路径不实际进入此方法，
    但 _choose_runner 防御性返回 PosixResourceSandbox 不抛错）。"""
    client = PlatformDaemonClient("fake_module")
    # 不提供 sandbox_config 也不提供 sandbox_runner
    runner = client._choose_runner()
    assert isinstance(runner, PosixResourceSandbox)


def test_choose_runner_explicit_runner_injection_takes_priority() -> None:
    """显式注入 sandbox_runner 优先级最高（不调 _sandbox_config 路径）。"""
    cfg = SandboxConfig(use_cgroups=True)
    mock_runner = MagicMock(spec=SandboxRunner)

    client = PlatformDaemonClient(
        "fake_module", sandbox_config=cfg, sandbox_runner=mock_runner
    )

    with patch(
        "app.agent_builder.platforms.sandbox.cgroups_v2.is_cgroups_v2_available"
    ) as spy:
        runner = client._choose_runner()

    assert runner is mock_runner, "sandbox_runner 显式注入应优先于 cgroups 自动检测"
    assert spy.call_count == 0, "显式注入时不应触发 cgroups 检测"
