"""Phase 5.C Plan 01 — SandboxRunner docker_networks 单元测试（mock 路径）。

覆盖（≥ 11 测试）:

- PosixResourceSandbox docker_networks 非空 → no-op + log info（含 "ignored"）
- PosixResourceSandbox docker_networks=None → 完全不 log（5.B regression 路径）
- _CGROUP_DOCKER_RE 四格式: v1 / v2 slash / v2 systemd-slice / non-docker
- _resolve_container_for_pid 三分支: 在 container / 不在 / 文件不存在
- _attach_docker_networks 三失败模式 + 一成功路径

CgroupsV2 真 docker integration test 走 test_sandbox_docker_networks_integration.py
（仅 Linux + docker 可用时跑，否则 skip）。

Reference: docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md
License: 100% 独立创作 — Dify AGPL-3.0 仅借鉴设计模式（不拷源代码）。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_builder.platforms.sandbox.cgroups_v2 import (
    CgroupsV2Sandbox,
    _CGROUP_DOCKER_RE,
)
from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox


# ── PosixResourceSandbox no-op 测试 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_posix_resource_docker_networks_no_op_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PosixResourceSandbox 收 docker_networks 非空：no-op + log info 含 "ignored"。"""
    caplog.set_level(logging.INFO)

    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-c", "import time; time.sleep(0.01)"],
        cpu_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        docker_networks=["huly_huly_net", "another_net"],
    )
    await proc.wait()

    # log info 必有 "ignored" 关键字
    assert any("docker_networks ignored" in r.message for r in caplog.records), (
        "PosixResourceSandbox 收 docker_networks 非空必须 log info 'ignored'，"
        f"实际 records: {[r.message for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_posix_resource_docker_networks_none_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PosixResourceSandbox 收 docker_networks=None：完全不 log docker_networks（5.B regression）。"""
    caplog.set_level(logging.INFO)

    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-c", "pass"],
        cpu_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        # 显式不传 docker_networks
    )
    await proc.wait()

    assert not any("docker_networks" in r.message for r in caplog.records), (
        f"docker_networks=None 路径不应 log 'docker_networks'，"
        f"实际: {[r.message for r in caplog.records]}"
    )


# ── _CGROUP_DOCKER_RE regex 测试 ──────────────────────────────────────────────


class TestCgroupDockerRegex:
    """_CGROUP_DOCKER_RE 兼容 cgroup v1 + v2 三格式。"""

    def test_cgroup_v1_format(self) -> None:
        """cgroup v1 行格式: '12:devices:/docker/<hash>'。"""
        line = "12:devices:/docker/abc123def4567890fedcba"
        m = _CGROUP_DOCKER_RE.search(line)
        assert m is not None
        assert m.group(1) == "abc123def4567890fedcba"

    def test_cgroup_v2_format_slash(self) -> None:
        """cgroup v2 行格式 (slash): '0::/docker/<hash>'。"""
        line = "0::/docker/abc123def4567890"
        m = _CGROUP_DOCKER_RE.search(line)
        assert m is not None
        assert m.group(1) == "abc123def4567890"

    def test_cgroup_v2_format_systemd_slice(self) -> None:
        """cgroup v2 行格式 (systemd-slice): '0::/system.slice/docker-<hash>.scope'。"""
        line = "0::/system.slice/docker-abc123def4567890.scope"
        m = _CGROUP_DOCKER_RE.search(line)
        assert m is not None
        assert m.group(1) == "abc123def4567890"

    def test_non_docker_cgroup_no_match(self) -> None:
        """非 docker cgroup 行（user.slice 等） → 无匹配。"""
        line = "0::/user.slice/user-1000.slice/session-1.scope"
        assert _CGROUP_DOCKER_RE.search(line) is None


# ── _resolve_container_for_pid 测试 ───────────────────────────────────────────


class TestResolveContainerForPid:
    """_resolve_container_for_pid 三分支: 在 container / 不在 / 文件不存在。"""

    def test_pid_not_in_container_returns_none(self) -> None:
        """daemon 是 host process（/proc/<pid>/cgroup 不含 docker 段）→ 返回 None。"""
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        fake_content = "0::/user.slice/user-1000.slice"
        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.return_value = fake_content
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(12345)
            assert result is None

    def test_pid_in_container_returns_id(self) -> None:
        """daemon 在 container → 返回完整 container_id。"""
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        fake_content = "0::/docker/abc123def4567890fedcba\n"
        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.return_value = fake_content
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(12345)
            assert result == "abc123def4567890fedcba"

    def test_pid_in_container_v1_format_returns_id(self) -> None:
        """cgroup v1 路径（'12:devices:/docker/<hash>'）也能解析。"""
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        fake_content = (
            "12:devices:/docker/abc123def4567890\n"
            "11:cpu,cpuacct:/docker/abc123def4567890\n"
        )
        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.return_value = fake_content
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(12345)
            assert result == "abc123def4567890"

    def test_proc_file_not_found_returns_none(self) -> None:
        """/proc/<pid>/cgroup 不存在（macOS 或 pid 已死）→ 返回 None。"""
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.side_effect = FileNotFoundError("no proc")
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(99999999)
            assert result is None

    def test_proc_file_permission_denied_returns_none(self) -> None:
        """/proc/<pid>/cgroup 无权读（容器内可能） → 返回 None。"""
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.side_effect = PermissionError(
                "EACCES"
            )
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(1)
            assert result is None


# ── _attach_docker_networks 三失败模式 + 一成功路径 ─────────────────────────


class TestAttachDockerNetworksFailures:
    """三失败模式（Pitfall 5）：docker 不可用 / network 不存在 / pid 不在 container。

    每模式独立 RuntimeError + terminate daemon + 错误信息含明确诊断。
    """

    def _make_mock_proc(self, pid: int = 12345) -> MagicMock:
        """构造一个完整的 mock asyncio.subprocess.Process（terminate sync + wait async）。"""
        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.pid = pid
        return mock_proc

    @pytest.mark.asyncio
    async def test_failure_mode_1_docker_daemon_unavailable(self) -> None:
        """模式 1: docker daemon ping 失败 → raise + terminate daemon。"""
        mock_proc = self._make_mock_proc()

        mock_docker_client = MagicMock()
        mock_docker_client.ping.side_effect = Exception(
            "Cannot connect to docker daemon"
        )

        with patch("docker.from_env", return_value=mock_docker_client):
            sb = CgroupsV2Sandbox()
            with pytest.raises(RuntimeError, match="docker daemon not available"):
                await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

        # daemon 必须被 terminate（防假成功）
        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_mode_2_network_not_found(self) -> None:
        """模式 2: network 不存在 → raise + terminate daemon。"""
        import docker.errors as derr

        mock_proc = self._make_mock_proc()

        mock_docker_client = MagicMock()
        mock_docker_client.ping.return_value = True
        mock_docker_client.networks.get.side_effect = derr.NotFound(
            "Network not found"
        )

        # mock 容器 id 解析成功（不是失败模式 3）
        with (
            patch("docker.from_env", return_value=mock_docker_client),
            patch.object(
                CgroupsV2Sandbox,
                "_resolve_container_for_pid",
                return_value="abc123def",
            ),
        ):
            sb = CgroupsV2Sandbox()
            with pytest.raises(
                RuntimeError, match="docker network 'huly_huly_net' not found"
            ):
                await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_mode_3_pid_not_in_container(self) -> None:
        """模式 3: daemon pid 不在 container → raise + terminate daemon。"""
        mock_proc = self._make_mock_proc(pid=12345)

        mock_docker_client = MagicMock()
        mock_docker_client.ping.return_value = True

        with (
            patch("docker.from_env", return_value=mock_docker_client),
            patch.object(
                CgroupsV2Sandbox,
                "_resolve_container_for_pid",
                return_value=None,
            ),
        ):
            sb = CgroupsV2Sandbox()
            with pytest.raises(
                RuntimeError, match="daemon pid=12345 not in any docker container"
            ):
                await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_mode_network_connect_raises_during_attach(self) -> None:
        """成功 get network 但 connect 时异常 → raise + terminate（边缘情况）。"""
        mock_proc = self._make_mock_proc()

        mock_network = MagicMock()
        mock_network.connect.side_effect = Exception("connect failed mid-way")

        mock_docker_client = MagicMock()
        mock_docker_client.ping.return_value = True
        mock_docker_client.networks.get.return_value = mock_network

        with (
            patch("docker.from_env", return_value=mock_docker_client),
            patch.object(
                CgroupsV2Sandbox,
                "_resolve_container_for_pid",
                return_value="abc123def",
            ),
        ):
            sb = CgroupsV2Sandbox()
            with pytest.raises(
                RuntimeError, match="docker network 'huly_huly_net' connect failed"
            ):
                await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

        mock_proc.terminate.assert_called_once()


# ── 成功路径 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attach_docker_networks_success_path() -> None:
    """成功路径: docker daemon 可用 + network 存在 + pid 在 container → net.connect 调一次。"""
    mock_proc = MagicMock(spec=asyncio.subprocess.Process)
    mock_proc.pid = 12345
    mock_proc.terminate = MagicMock()

    mock_network = MagicMock()
    mock_docker_client = MagicMock()
    mock_docker_client.ping.return_value = True
    mock_docker_client.networks.get.return_value = mock_network

    with (
        patch("docker.from_env", return_value=mock_docker_client),
        patch.object(
            CgroupsV2Sandbox,
            "_resolve_container_for_pid",
            return_value="abc123def456",
        ),
    ):
        sb = CgroupsV2Sandbox()
        await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

    # 真调 net.connect(container_id)
    mock_network.connect.assert_called_once_with("abc123def456")
    # 成功路径不应 terminate daemon
    mock_proc.terminate.assert_not_called()


@pytest.mark.asyncio
async def test_attach_docker_networks_multiple_networks_all_succeed() -> None:
    """多 network 全成功 → 每个独立 connect 一次。"""
    mock_proc = MagicMock(spec=asyncio.subprocess.Process)
    mock_proc.pid = 12345
    mock_proc.terminate = MagicMock()

    mock_net_a = MagicMock()
    mock_net_b = MagicMock()
    mock_docker_client = MagicMock()
    mock_docker_client.ping.return_value = True
    mock_docker_client.networks.get.side_effect = [mock_net_a, mock_net_b]

    with (
        patch("docker.from_env", return_value=mock_docker_client),
        patch.object(
            CgroupsV2Sandbox,
            "_resolve_container_for_pid",
            return_value="cid_xyz",
        ),
    ):
        sb = CgroupsV2Sandbox()
        await sb._attach_docker_networks(mock_proc, ["net_a", "net_b"])

    mock_net_a.connect.assert_called_once_with("cid_xyz")
    mock_net_b.connect.assert_called_once_with("cid_xyz")
    mock_proc.terminate.assert_not_called()
