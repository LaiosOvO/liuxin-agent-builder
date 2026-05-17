"""CgroupsV2Sandbox + is_cgroups_v2_available（PLUG-FW-10）。

设计要点（RESEARCH §Pattern 2 + Pitfall 2/7 + reading doc 借鉴点）:

- **systemd-run --user --scope** 包裹 daemon spawn — 资源限制由 systemd 透明管理
  （免维护 /sys/fs/cgroup/<slice>/memory.max 等文件 + 容器 user slice 透明 delegation）
- **4 条 detection 检查 + 真试 systemd-run**（Pitfall 2 防容器 unprivileged 失败）
  - 任何一条失败都 silent return False（绝不 raise — 否则 _choose_runner 在容器内 crash）
- **优雅降级路径**：is_cgroups_v2_available() 返回 False 时 _choose_runner 自动 fallback
  PosixResourceSandbox + warning log（不 fail startup —— 用户在 docker-compose / macOS dev
  跑 use_cgroups: true 也不应中断）
- **MemoryMax + MemorySwapMax=0 + CPUQuota=100% + TasksMax=32** 四属性双保险
  - MemorySwapMax=0 防 swap 绕开 memory limit（设了 MemoryMax 但不限 swap 会 false-pass）
  - TasksMax=32 与 RLIMIT_NPROC=16 双重 fork bomb 防护（cgroups 内核层 + setrlimit fallback 层）
- **--scope 不能换成 --service**（service 模式 daemon stdout 走 systemd journal，
  主进程 5.A daemon_client 读不到 JSONRPC response → 通信失败）
- **--collect** 防 cgroup OOM 后 scope unit 残留（Pitfall 7 — 不加 --collect 会
  导致 cgroup tree 累积 + 下次 spawn EBUSY）
- **--quiet** 必须 — 不然 systemd-run 输出 unit name 到 stdout 污染 daemon JSONRPC pipe

License: 100% 独立创作；systemd-run 是 systemd 标准工具命令字符串可用；
        Dify Go dify-plugin-daemon cgroup 实现仅参考思路不拷代码（AGPL-3.0）。
        详见 docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)

# ── Phase 5.C Pattern 4: cgroup → docker container_id 解析 regex ────────────────
# /proc/<pid>/cgroup 行格式（兼容 cgroup v1 + v2）:
#   v1:                "12:devices:/docker/abc123def456..."
#   v2 (slash):        "0::/docker/abc123def456..."
#   v2 (systemd-slice): "0::/system.slice/docker-abc123def456.scope"
# 三种格式统一用 `/docker[/-]<hash>` 提取 container_id（16-64 hex chars）。
_CGROUP_DOCKER_RE = re.compile(r"/docker[/-]([0-9a-f]{12,64})")

# ── detection 常量 ────────────────────────────────────────────────────────────

_CGROUP_CONTROLLERS_PATH = Path("/sys/fs/cgroup/cgroup.controllers")
"""cgroups v2 unified hierarchy controllers 列表文件路径。

存在 + 含 memory + cpu = 启用 enforcement 前提（v2 统一层级标志）。
"""

_REQUIRED_CONTROLLERS = ("memory", "cpu")
"""最小必需 controllers — daemon 资源限制必须含 memory + cpu enforcement。"""

_PROBE_TIMEOUT_SECONDS = 2.0
"""systemd-run 真试 timeout（秒）— 容器内可能 hang 等 systemd-userdbd 响应；
2s 足够本地真机 + 容器 fast-fail（实测 systemd-run 正常情况 < 100ms）。
"""

# ── systemd-run 命令构造常量 ──────────────────────────────────────────────────

_SYSTEMD_SLICE = "agent-builder-plugin.slice"
"""独立 slice 名 — 让所有 plugin daemon 在同一 systemd slice 下隔离。

便于运维：`systemctl --user status agent-builder-plugin.slice` 查看所有 plugin 进程。
"""

_CPU_QUOTA = "100%"
"""默认 CPU quota — 1 个核（"100%"）。

cgroups v2 CPUQuota 是 % of single core；500% = 5 核；50% = 半核。
v1 锁定 100% 1 核，与 PosixResourceSandbox 行为对齐；多核场景留 v2 加 cpu_cores manifest 字段。
"""

_TASKS_MAX = "32"
"""TasksMax 防 fork bomb — 与 RLIMIT_NPROC=16 双重防护。

cgroups v2 TasksMax 在内核层强 enforcement（无视 user 权限）— 比 RLIMIT_NPROC 更强。
32 = daemon 主进程 + thread pool (~16) + IO worker (~10) + 余量。
"""

# ── detection 函数 ─────────────────────────────────────────────────────────────


def is_cgroups_v2_available() -> bool:
    """检测 cgroups v2 + systemd-run --user 是否可用（Pitfall 2 完整 4 条 + 真试）。

    检测流程（任一条失败 silent return False）:
    1. ``/sys/fs/cgroup/cgroup.controllers`` 文件存在（v2 unified hierarchy 标志）
    2. 文件内含 `memory` + `cpu` controllers（启用 enforcement 前提）
    3. ``shutil.which("systemd-run")`` 找到二进制（避免 alpine / minimal image 缺失）
    4. ``systemd-run --user --scope --quiet --quiet -- true`` 真试 returncode == 0
       （Pitfall 2 关键 — 容器内可能有前 3 条但执行时 EPERM）

    **关键不变量**：本函数**永不**抛任何异常（PermissionError / TimeoutExpired /
    FileNotFoundError / OSError 全 catch + return False）。否则 _choose_runner 在容器内
    crash → 整个 daemon spawn 失败。

    Returns:
        bool: True 当且仅当 cgroups v2 + systemd-run --user 完全可用；
              False 在 macOS / 容器无 cgroup delegation / 无 systemd / cgroup v1 等任意场景。

    Note:
        本函数是 _choose_runner 的 gate — 务必 silent fail。
        日志在 _choose_runner warning 处统一发，本函数不 log（避免 4 检查噪音）。
    """
    # 1. cgroups v2 unified hierarchy 存在
    if not _CGROUP_CONTROLLERS_PATH.exists():
        return False

    # 2. memory + cpu controllers 可用
    try:
        available = _CGROUP_CONTROLLERS_PATH.read_text().split()
    except (PermissionError, OSError):
        # 容器内可能存在文件但 user 不可读
        return False
    for required in _REQUIRED_CONTROLLERS:
        if required not in available:
            return False

    # 3. systemd-run 在 PATH（alpine / minimal image 可能缺）
    if shutil.which("systemd-run") is None:
        return False

    # 4. 真试一次 — Pitfall 2 防容器内 EPERM
    # capture_output=True 避免污染 pytest output；check=False 让 returncode 自行判断
    try:
        result = subprocess.run(  # noqa: S603 — systemd-run 是受信任工具
            ["systemd-run", "--user", "--scope", "--quiet", "--", "true"],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        # FileNotFoundError 双保险（shutil.which 后 race condition unlinked）
        # TimeoutExpired 容器内 systemd-userdbd 不响应（Pitfall 2）
        # OSError 其他 spawn 异常
        return False

    return result.returncode == 0


# ── CgroupsV2Sandbox: Linux opt-in runner ─────────────────────────────────────


class CgroupsV2Sandbox:
    """Linux opt-in cgroups v2 sandbox — systemd-run --user --scope 包裹 daemon spawn。

    实现 SandboxRunner Protocol（与 PosixResourceSandbox 并列），用户可在 manifest
    ``sandbox.use_cgroups: true`` opt-in；不可用环境 _choose_runner 自动降级。

    资源限制走 systemd transient unit:

    - ``MemoryMax``: 硬上限（cgroups v2 内核层 OOM kill 自动 — 比 RLIMIT_AS 更强）
    - ``MemorySwapMax=0``: 防 swap 绕开 MemoryMax（设 MemoryMax 但不限 swap = false-pass）
    - ``CPUQuota=100%``: 1 个核（cpu_seconds 累计走 watchdog 兜底，cgroups 无对应字段）
    - ``TasksMax=32``: 防 fork bomb（与 RLIMIT_NPROC=16 双重防护）
    - ``--slice=agent-builder-plugin.slice``: 独立 slice 隔离 + 便于 systemctl 查看
    - ``--collect``: cgroup 在 daemon 退出后自动清理（Pitfall 7 防 OOM 残留）
    - ``--quiet``: 抑制 systemd-run 输出 unit name 到 stdout（避免污染 JSONRPC pipe）
    - ``--scope``: 当前 shell 进程组（**不**用 --service — service 模式 stdout 走 journal
      主进程读不到 JSONRPC response 通信失败）

    Note:
        cpu_seconds 参数（cumulative CPU runtime）在 cgroups v2 没直接对应字段；
        本 sandbox 用 CPUQuota=100% 提供 rate 限制，超总时间走 watchdog（Plan 04）兜底。
        env / cwd 与 PosixResourceSandbox 行为一致（默认 merge os.environ）。
    """

    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        docker_networks: list[str] | None = None,
    ) -> asyncio.subprocess.Process:
        """spawn 受限子进程（systemd-run --user --scope 包裹）。

        Args:
            cmd: daemon 命令行（如 ``[sys.executable, "-u", "-m", "plugins.huly.huly_plugin"]``）
            cpu_seconds: 用于 SandboxRunner Protocol 一致性（cgroups 不直接 enforce 累计 CPU；
                走 CPUQuota=100% rate 限制 + watchdog 兜底）
            memory_bytes: MemoryMax 硬上限（cgroups v2 OOM kill 自动）
            env: 注入子进程的环境变量；None 时 merge ``os.environ``（contract test 友好）
            cwd: 子进程工作目录；None 继承父进程
            docker_networks: spawn 后需要 attach 的 docker network 列表（Phase 5.C Pattern 4）。
                None / [] 时走 5.B 行为（无 attach）；非空时调 `_attach_docker_networks` 真做
                `docker network connect <net> <container_id>`。任一失败 raise + terminate
                daemon（Pitfall 5 避免假成功）。

        Returns:
            asyncio.subprocess.Process —— stdin/stdout/stderr 全 PIPE，可直接传给
            5.A daemon_client _read_loop / _stderr_drain 路径
        """
        merged_env = dict(os.environ) if env is None else dict(env)

        systemd_cmd = [
            "systemd-run",
            "--user",
            "--scope",
            f"--slice={_SYSTEMD_SLICE}",
            "--quiet",  # 抑制 unit name 输出污染 stdout pipe
            "--collect",  # cgroup 自动清理（Pitfall 7）
            f"--property=MemoryMax={memory_bytes}",
            "--property=MemorySwapMax=0",  # 防 swap 绕过
            f"--property=CPUQuota={_CPU_QUOTA}",
            f"--property=TasksMax={_TASKS_MAX}",
            "--",
            *cmd,
        ]

        proc = await asyncio.create_subprocess_exec(
            *systemd_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            cwd=cwd,
        )
        _log.info(
            "sandbox.cgroups_v2.spawned pid=%s memory_bytes=%d cpu_seconds=%d cmd=%s",
            proc.pid,
            memory_bytes,
            cpu_seconds,
            cmd[:2],  # 只 log 前 2 元素防 module path 污染日志
        )

        # Phase 5.C Pattern 4: docker network attach（仅在 docker_networks 非空时做）
        if docker_networks:
            await self._attach_docker_networks(proc, docker_networks)

        return proc

    async def _attach_docker_networks(
        self,
        proc: asyncio.subprocess.Process,
        docker_networks: list[str],
    ) -> None:
        """spawn 后 attach docker networks（Phase 5.C Pattern 4 / Pitfall 5）。

        三种失败模式（每种独立诊断 + raise RuntimeError + terminate daemon 避免假成功）:

        1. docker daemon 不可用（CI / macOS dev）→ raise "docker daemon not available"
        2. network 不存在（拼写错 / Huly stack 未启）→ raise "docker network not found"
        3. daemon pid 不在 container（host process）→ raise "daemon pid not in container"

        **决策**（CONTEXT Decision 3 + RESEARCH §Pattern 4）:
        attach 失败必须 raise + terminate daemon — 不允许 "silently no network"
        否则 Huly 调用一直 ConnectionError 看起来像超时，难诊断。

        Args:
            proc: 5.B systemd-run 包裹的 daemon 子进程
            docker_networks: 要 attach 的 network 列表（非空 — 调用方已 if 过滤）

        Raises:
            RuntimeError: 三失败模式之一（错误信息含明确诊断）
        """
        # docker SDK import — 延迟到方法内（CI 不一定装；放方法内部 try/except ImportError）
        try:
            import docker
            from docker.errors import DockerException, NotFound
        except ImportError as e:
            proc.terminate()
            await proc.wait()
            raise RuntimeError(
                f"docker python SDK not installed but docker_networks={docker_networks!r} requested "
                f"(install with `pip install docker>=7.0`)"
            ) from e

        # 失败模式 1: docker daemon 不可用（ping 失败）
        try:
            client = docker.from_env()
            client.ping()
        except (DockerException, Exception) as e:
            proc.terminate()
            await proc.wait()
            raise RuntimeError(
                f"docker daemon not available "
                f"(cannot attach networks={docker_networks!r}): {e}"
            ) from e

        # 失败模式 3: daemon pid 不在 container（先查 pid → container，避免拿不到 id 还去查 network）
        container_id = self._resolve_container_for_pid(proc.pid)
        if container_id is None:
            proc.terminate()
            await proc.wait()
            raise RuntimeError(
                f"daemon pid={proc.pid} not in any docker container — "
                f"cannot attach networks={docker_networks!r}. "
                f"(Note: docker_networks 仅在 daemon 自身运行在 docker container 内时生效；"
                f"host process 部署请用 PosixResourceSandbox 并保持 docker_networks=[])"
            )

        # 逐个 attach network（任一失败 raise + terminate）
        for net_name in docker_networks:
            # 失败模式 2: network 不存在
            try:
                net = client.networks.get(net_name)
            except NotFound as e:
                proc.terminate()
                await proc.wait()
                raise RuntimeError(
                    f"docker network {net_name!r} not found "
                    f"(check spelling or docker-compose up <stack> first): {e}"
                ) from e

            # 真做 attach
            try:
                net.connect(container_id)
                _log.info(
                    "docker network attached: net=%s -> container=%s pid=%d",
                    net_name,
                    container_id[:12],
                    proc.pid,
                )
            except Exception as e:
                proc.terminate()
                await proc.wait()
                raise RuntimeError(
                    f"docker network {net_name!r} connect failed for "
                    f"container={container_id[:12]}: {e}"
                ) from e

    def _resolve_container_for_pid(self, pid: int) -> str | None:
        """读 /proc/<pid>/cgroup 提取 docker container_id（兼容 cgroup v1 + v2 格式）。

        cgroup 行格式三种（_CGROUP_DOCKER_RE 统一匹配）:
            v1:                 "12:devices:/docker/abc123def456..."
            v2 (slash):         "0::/docker/abc123def456..."
            v2 (systemd-slice): "0::/system.slice/docker-abc123def456.scope"

        Args:
            pid: daemon 子进程 pid

        Returns:
            container_id (full hash) 或 None（daemon 不在 container / pid 已死 / 无权读 /proc）
        """
        try:
            content = Path(f"/proc/{pid}/cgroup").read_text()
        except (FileNotFoundError, PermissionError, OSError):
            # FileNotFoundError: macOS / pid 已死
            # PermissionError: 容器内可能无权读其他 pid 的 /proc
            # OSError: 兜底
            return None

        for line in content.splitlines():
            m = _CGROUP_DOCKER_RE.search(line)
            if m:
                return m.group(1)
        return None


__all__ = [
    "is_cgroups_v2_available",
    "CgroupsV2Sandbox",
    "_CGROUP_CONTROLLERS_PATH",
    "_REQUIRED_CONTROLLERS",
    "_SYSTEMD_SLICE",
    "_CPU_QUOTA",
    "_TASKS_MAX",
    "_CGROUP_DOCKER_RE",  # Phase 5.C: expose for test mock
]
