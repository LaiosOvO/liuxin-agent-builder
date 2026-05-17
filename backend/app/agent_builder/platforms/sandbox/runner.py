"""SandboxRunner Protocol + PosixResourceSandbox（PLUG-FW-09）。

设计要点（RESEARCH §Pattern 1 + Pitfall 1/4 + reading doc 借鉴点）:

- **SandboxRunner Protocol** 让 Wave 3 watchdog 与 Plan 04 cgroups 通过同一接口注入
  daemon_client 升级时仅替换 `_runner` 字段，调用方逻辑零修改
- **PosixResourceSandbox** 用 `asyncio loop.subprocess_exec` + `preexec_fn` 注入 4 类 RLIMIT
  preexec_fn 在 fork 之后 / exec 之前在子进程上下文跑，注入限制后 exec 才会受其约束
- **os.setsid()** 让 daemon 成为新进程组 leader（Pitfall 4 fork bomb / 精准 killpg 整组）
- **macOS RLIMIT_AS/CPU 弱 enforcement**（Pitfall 1）— Linux CI 才跑真实限制
  本模块的 contract test 在 macOS 全平台跑（API 正确性），enforcement test 用
  `@pytest.mark.linux_only` + `@pytest.mark.skipif(sys.platform == 'darwin')`

与 5.A daemon_client 接口对齐:
- `cmd: list[str]` 对应 `[sys.executable, "-u", "-m", module_entry]`
- `env: dict[str, str] | None` 对应 `daemon_client._env` 注入
- `cwd: str | None` 对应 `daemon_client._cwd`（Phase 5.A acid test 用根目录注入）
- 返回 `asyncio.subprocess.Process` —— stdin/stdout/stderr PIPE 与 5.A 一致

License: 100% 独立创作，借鉴 Dify Go daemon 资源限制设计哲学
        （AGPL-3.0 不拷代码，详见 docs/reading-dify-05b-02-resource-runner-2026-05-17.md）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import resource
import subprocess
import sys
from asyncio import streams as _streams
from functools import partial
from typing import Protocol, runtime_checkable

_log = logging.getLogger(__name__)

_IS_DARWIN = sys.platform == "darwin"
"""macOS Darwin kernel 标识 — Pitfall 1 弱 enforcement 分支判断。

Darwin 行为差异（实测）:
- `setrlimit(RLIMIT_AS, (X, X))` 在非 root 上下文 **总是 raise ValueError("current limit
  exceeds maximum limit")** —— 即使 `getrlimit` 报告 `RLIM_INFINITY (2^63-1)`，Darwin 内核
  不允许从用户态降低 AS 上限（与 Linux 截然不同）
- `setrlimit(RLIMIT_CPU, ...)` 写入成功但实际不严格 enforce SIGXCPU

因此 macOS dev 路径**完全跳过** AS / CPU setrlimit（避免 ValueError 让 preexec_fn 失败导致
spawn 全失败），仅注入 NPROC / NOFILE（cross-platform 严格生效）+ setsid。
Linux CI 走完整 4 类 RLIMIT enforcement test 路径。
"""

# ── 默认 RLIMIT 值（cross-platform 严格 enforcement）──────────────────────────────

_DEFAULT_NPROC_LIMIT = 16
"""daemon 不能 fork 超 16 个子进程 — 防 fork bomb（RLIMIT_NPROC，macOS + Linux 均严格）。

设计权衡：
- 太小（如 4）：限制了 daemon 内 thread pool / IO multiplexing 灵活性
- 太大（如 100）：fork bomb 防护弱；plugin daemon 通常无需大量 fork
- 选 16：thread pool 默认（Python ThreadPoolExecutor 默认 cpu_count*5）+ 余量
"""

_DEFAULT_NOFILE_LIMIT = 256
"""daemon 文件描述符上限 — 防句柄泄漏（RLIMIT_NOFILE，macOS + Linux 均严格）。

设计权衡：
- 256 涵盖：stdin/stdout/stderr (3) + Python interpreter internal (~10) +
  httpx connection pool (50 keep-alive) + 业务文件 (~50) + 余量
- 真泄漏场景（如 forget close()）能很快触发 ulimit 而非耗尽 OS fd 表
"""


def _apply_posix_limits(cpu_seconds: int, memory_bytes: int) -> None:
    """preexec_fn — fork 后 / exec 前在子进程上下文跑。

    **关键约束**:
    - **无阻塞 + 无 async**：fork 后 event loop 不可用，任何 await 都会死锁
    - **无 logging**：fork 后 logger handler fd 状态不确定（可能死锁 / 部分写入）
    - **设定顺序**：先 setrlimit（失败时 raise 还能被 asyncio 捕获）；最后 setsid（之后报错难传回）

    **macOS vs Linux 行为差异（Pitfall 1 - HIGH severity）**:
    - `RLIMIT_CPU`: Linux 严格（超 SIGXCPU + 超 hard 后 SIGKILL）/ macOS Darwin 弱 enforce
    - `RLIMIT_AS`: Linux 严格（超限 malloc 返 ENOMEM）/ **macOS 完全不能 setrlimit**
      （实测 Darwin kernel raise ValueError "current limit exceeds maximum limit"，
      即使 getrlimit 报 RLIM_INFINITY；用户态无法降低 AS 上限）
    - `RLIMIT_NPROC`: cross-platform 严格 ✓
    - `RLIMIT_NOFILE`: cross-platform 严格 ✓

    **macOS 路径**: 跳过 AS / CPU setrlimit，仅注入 NPROC / NOFILE + setsid（避免
    preexec_fn raise 让整个 spawn 失败）。enforcement 走 Linux CI（`@pytest.mark.linux_only`）。

    Args:
        cpu_seconds: 累积 CPU 秒数（5.A parser.parse_cpu_seconds 转换得到）
        memory_bytes: 虚拟内存 bytes 上限（5.A parser.parse_memory 转换得到）
    """
    # RLIMIT_CPU / RLIMIT_AS：Linux 严格，macOS 不能 set（Darwin kernel 拒绝降低）
    # macOS 直接跳过；Linux 真注入（CI 跑真 enforcement test）
    if not _IS_DARWIN:
        # RLIMIT_CPU: 累积 CPU 秒数 — Linux 严格（超 soft 发 SIGXCPU；超 hard 强杀）
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        # RLIMIT_AS: 虚拟内存上限 — Linux 严格（超限 malloc 返 ENOMEM）
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    # RLIMIT_NPROC: 子进程数（防 fork bomb）— cross-platform 严格 ✓
    resource.setrlimit(
        resource.RLIMIT_NPROC, (_DEFAULT_NPROC_LIMIT, _DEFAULT_NPROC_LIMIT)
    )
    # RLIMIT_NOFILE: 文件描述符上限（防句柄泄漏）— cross-platform 严格 ✓
    resource.setrlimit(
        resource.RLIMIT_NOFILE, (_DEFAULT_NOFILE_LIMIT, _DEFAULT_NOFILE_LIMIT)
    )
    # 新进程组 leader — 让主进程 SIGTERM 能 killpg(pgid, SIGTERM) 整棵进程树（Pitfall 4）
    # **必须放最后**：前面 setrlimit 失败 raise 可被 asyncio 捕获；setsid 后任何错误难以传回
    os.setsid()


@runtime_checkable
class SandboxRunner(Protocol):
    """统一沙箱 spawn 接口 — PosixResourceSandbox / CgroupsV2Sandbox 共实现。

    Wave 3 (Plan 05b-04 CgroupsV2Sandbox) 通过实现本 Protocol 让 daemon_client 升级时
    只需 1 行替换（`self._runner = CgroupsV2Sandbox()` vs `PosixResourceSandbox()`），
    Protocol 静态类型检查保证接口一致性。

    与 `asyncio.create_subprocess_exec` 签名对齐（cmd + env + cwd），多 `cpu_seconds` /
    `memory_bytes` 显式资源限制参数。
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
        """spawn 受限子进程。

        Args:
            cmd: 命令行（如 `[sys.executable, "-u", "-m", "plugins.huly.huly_plugin"]`）
            cpu_seconds: RLIMIT_CPU 累积秒数（5.A parser.parse_cpu_seconds 转换得到）
            memory_bytes: RLIMIT_AS 虚拟内存上限（5.A parser.parse_memory 转换得到）
            env: 注入子进程的环境变量；None 时 merge `os.environ`（contract test 友好）
                **Wave 3 注意**：真 env_allowlist 过滤在 daemon_client._build_filtered_env 做
            cwd: 子进程工作目录；None 继承父进程
            docker_networks: spawn 后需要 attach 的 docker network 列表（None / [] = no attach）。
                Phase 5.C Pattern 4 / Pitfall 5 新增 — 实现区分如下：

                - **PosixResourceSandbox**: no-op + log info（daemon 是 host 进程，不在 container）
                - **CgroupsV2Sandbox**: 真做 docker network connect（仅当 daemon pid 在 container 内）

                Wave 2 三 plan（hr huly internal port / OutlinePlugin / LarkDocsPlugin）+
                Wave 3 HulyPlugin 4-cap bundle 通过此参数让 daemon attach `huly_huly_net` 等
                内部 bridge 网络（hr 教训 §4.4）。

        Returns:
            `asyncio.subprocess.Process` —— stdin/stdout/stderr 全 PIPE，可直接传给
            5.A daemon_client 的 `_read_loop` / `_stderr_drain` 路径
        """
        ...


# ── PosixResourceSandbox: cross-platform baseline ──────────────────────────────


class PosixResourceSandbox:
    """`resource.setrlimit` baseline — cross-platform（macOS dev + Linux prod）。

    实现要点:
    - `asyncio loop.subprocess_exec` 直接接收 `preexec_fn`（**注**：高层
      `asyncio.create_subprocess_exec` 不接受 `preexec_fn` 参数）
    - `SubprocessStreamProtocol` + `Process` wrapper 让返回值与 5.A `daemon_client`
      `asyncio.subprocess.Process` API 完全一致
    - `close_fds=True` 防 fd 从父进程泄漏到子进程（安全 baseline）
    - `merged_env = dict(os.environ)` 默认 merge — 让 contract test 简单（PATH 等基础
      env 不丢）；Wave 3 daemon_client 才做真 env_allowlist 过滤

    macOS dev 行为:
    - contract test only（API 不抛错 + 默认值正确 + setsid 生效）
    - RLIMIT_AS / RLIMIT_CPU 不严格 enforce（Pitfall 1）

    Linux prod 行为:
    - 真 enforcement test（200MB alloc 超 100MB → SIGKILL；busy loop 超 1s RLIMIT_CPU → SIGXCPU）
    - GitHub Actions ubuntu-latest CI 跑 @pytest.mark.linux_only 标记的集成测
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
        loop = asyncio.get_event_loop()
        # env 默认 merge os.environ 是为了 contract test 简单（PATH / PYTHONPATH 保留）
        # Wave 3 真 env_allowlist strip-all 过滤在 daemon_client._build_filtered_env 做
        merged_env = dict(os.environ) if env is None else dict(env)

        # functools.partial 绑定 cpu_seconds / memory_bytes 到 preexec_fn
        # 必须用 partial 而非 lambda — lambda 会闭包当前作用域，fork 后状态不确定
        preexec = partial(_apply_posix_limits, cpu_seconds, memory_bytes)

        # loop.subprocess_exec 是底层 API（asyncio.create_subprocess_exec 上层封装不接受 preexec_fn）
        # 返回 (transport, protocol) tuple — 必须用 asyncio.subprocess.Process 包装
        #
        # **关键**：subprocess_exec 第一个参数是 protocol_factory（callable that returns Protocol），
        # 不是 Protocol 类本身（class 直接传会 TypeError: missing 'limit' / 'loop' 参数）。
        # 标准 idiom 来自 asyncio.create_subprocess_exec 源码：
        #   protocol_factory = lambda: SubprocessStreamProtocol(limit=limit, loop=loop)
        protocol_factory = lambda: asyncio.subprocess.SubprocessStreamProtocol(  # noqa: E731
            limit=_streams._DEFAULT_LIMIT,
            loop=loop,
        )
        transport, protocol = await loop.subprocess_exec(
            protocol_factory,
            *cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            cwd=cwd,
            preexec_fn=preexec,
            close_fds=True,
        )
        proc = asyncio.subprocess.Process(transport, protocol, loop)
        _log.info(
            "sandbox.spawned pid=%s cpu_seconds=%d memory_bytes=%d cmd=%s",
            proc.pid,
            cpu_seconds,
            memory_bytes,
            cmd[:2],  # 只 log 前 2 元素防长 module path 污染日志
        )

        # Phase 5.C Pattern 4: docker_networks 处理（PosixResourceSandbox no-op）
        # daemon 在 PosixResourceSandbox 路径是 host 进程（非 container），
        # docker network attach 物理上无法生效 — log info 提示 + 返回（绝不 raise）。
        if docker_networks:
            _log.info(
                "sandbox.docker_networks ignored on PosixResourceSandbox "
                "(daemon pid=%d runs as host process, not container): %s",
                proc.pid,
                docker_networks,
            )
        return proc


__all__ = [
    "SandboxRunner",
    "PosixResourceSandbox",
    "_apply_posix_limits",
    "_DEFAULT_NPROC_LIMIT",
    "_DEFAULT_NOFILE_LIMIT",
]
