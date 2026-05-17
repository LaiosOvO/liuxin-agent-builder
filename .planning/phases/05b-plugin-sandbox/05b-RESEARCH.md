# Phase 5.B: Plugin 沙箱 + Daemon 通信资源限制 - Research

**Researched:** 2026-05-17
**Domain:** OS-level Resource Limits / Network Whitelist / Watchdog / Process Lifecycle
**Confidence:** HIGH（基于 Phase 5.A 已落 daemon_client / fault isolation + Python stdlib `resource` + `signal` + httpx Transport API + cgroups v2 已上 RHEL 9 / Ubuntu 22 LTS 默认）

---

<user_constraints>
## User Constraints（直接拷贝自 CONTEXT.md，**不可协商**）

### Locked Decisions

#### 资源限制机制选择

**双轨抽象**：sandbox_runner 抽象层 + 平台适配
- **macOS dev / cross-platform baseline**: `resource.setrlimit` (RLIMIT_CPU + RLIMIT_AS) — Python 标准库，零依赖
- **Linux 生产可选**: cgroups v2（systemd-run --user 或直接 cgroup write）— manifest 显式 `sandbox.use_cgroups: true` enables it
- **不 Docker per-plugin**（运维 5 容器/plugin 太重；考虑 Phase 6 marketplace 大量 plugin 场景再上 docker）
- 不选 nsjail / firejail（cross-platform 不友好）

```python
class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self, cmd: list[str], *, cpu_seconds: int, memory_bytes: int, env: dict
    ) -> asyncio.subprocess.Process: ...

class PosixResourceSandbox: ...   # macOS + Linux fallback (resource.setrlimit preexec_fn)
class CgroupsV2Sandbox: ...       # Linux opt-in
```

#### 网络白名单实现

**v1: application-level httpx hook** — plugin daemon 启动时注入 httpx 默认 transport
- manifest `sandbox.network: ["huly.example.com:443", "*.feishu.cn:443"]` 解析为 host + port 白名单
- daemon entrypoint 加载时构造 `httpx.AsyncClient(transport=AllowlistTransport(allow_list))`
- AllowlistTransport.handle_async_request: 检查 url.host:port 在 allow_list，不在则 raise NetworkBlockedError
- 旧 plugin 用 `urllib.request` / `requests` 会绕过 — 留 v2 解决（提示 plugin 用 httpx）

#### 超时 + 强杀策略（三层防护）

1. **单 invoke timeout**（5.A 已实现，默认 30s）— 保留
2. **资源超限 SIGTERM → SIGKILL grace**：cgroups OOM kill 自动 / RLIMIT_CPU 触发 SIGXCPU / watchdog 每 5s 扫；超限先 SIGTERM 等 3s grace → 仍存活 SIGKILL
3. **idle daemon 回收**：last_invoke_at + 后台任务每 60s 扫描；idle > 300s 自动 close + 下次 lazy re-spawn

#### Manifest sandbox 段 schema

```yaml
sandbox:
  cpu_limit: "1.0"           # Docker style: float in cores; "0.5" = half core
  memory: "512Mi"            # k8s style: "Mi"/"Gi" 后缀 → bytes
  network: ["host:port"]     # list, exact match (v1 不支持通配符)
  timeout_invoke: 30         # seconds; per-invoke
  timeout_idle: 300          # seconds; idle daemon auto-close
  use_cgroups: false         # Linux opt-in; default false (走 setrlimit baseline)
```

**默认值**（manifest 未声明 sandbox 段时）：
- cpu_limit = "2.0", memory = "1Gi", network = [] (禁所有出站), timeout_invoke = 30, timeout_idle = 300, use_cgroups = false

### Claude's Discretion

- watchdog 任务实现：单独 asyncio task vs 集成到 PlatformDaemonClient (推荐独立 task)
- AllowlistTransport 实现：基于 httpx Transport API vs 子类 AsyncHTTPTransport
- cgroups v2 检测：try import + check /sys/fs/cgroup/cgroup.controllers
- memory bytes 解析库：自写 (10 行) vs `humanfriendly`
- env 变量传递：白名单 list (manifest 声明) vs strip all (安全) — 推荐 strip all 默认 + manifest 白名单 opt-in
- structured log: `sandbox.limit_exceeded` 事件用 logger.warning + extra dict (CPU/memory)

### Deferred Ideas（OUT OF SCOPE — 不能出现在 Phase 5.B 任何 plan）

- Docker container per plugin (Phase 6 marketplace 大量 plugin 场景才需要)
- cgroups v1 兼容（生产 Linux 都已是 cgroups v2，v1 不投入）
- 网络白名单 v2: iptables / nftables / namespace 隔离
- Plugin 间 RPC（plugin A 调 plugin B）— v2 plugin marketplace 接力
- Plugin hot reload / SIGHUP — v2
- LangGraph node 沙箱（节点跑用户代码）— **不属于 5.B**，是 plugin 跑用户代码场景的另一独立 phase（v3）
- 真实平台接入（DocCapability / HRCapability 留 5.C / 5.D）

</user_constraints>

<phase_requirements>
## Phase Requirements

> Phase 5.B 沿用 5.A 的 PLUG-FW-* / PLUG-* 命名空间扩展。沙箱相关需求 PLUG-FW-09 ~ PLUG-FW-13 在本 phase 首次出现；
> 主 REQUIREMENTS.md `PLUG-03`（Phase 6 marketplace 视角的"沙箱执行 - 子进程 + cgroups v2 + 网络白名单"）在本 phase **首次以基础设施形态落地**，Phase 6 marketplace 直接复用。

| ID | Description | Research Support |
|----|-------------|-----------------|
| **PLUG-FW-09** | `SandboxRunner` Protocol 抽象 + `PosixResourceSandbox`（`resource.setrlimit` baseline, macOS + Linux cross-platform） | §Standard Stack `resource` stdlib；§Pattern 1 preexec_fn 注入 |
| **PLUG-FW-10** | `CgroupsV2Sandbox`（Linux opt-in, `sandbox.use_cgroups: true`, systemd-run --user 或直接 cgroup write） | §Standard Stack cgroupsv2 detection；§Pattern 2 cgroups write |
| **PLUG-FW-11** | `AllowlistTransport`（httpx `AsyncBaseTransport` 子类化 + `mounts={}` 注入；plugin daemon entry 注入入口） | §Standard Stack httpx Transport API；§Pattern 3 transport mount |
| **PLUG-FW-12** | watchdog + 三层超时强杀（RLIMIT_CPU SIGXCPU / watchdog SIGTERM 3s grace → SIGKILL / idle > 300s auto-close） | §Pattern 4 watchdog 设计；§Pitfall 4 grace period |
| **PLUG-FW-13** | manifest `sandbox` 段 Pydantic schema 扩展（cpu_limit / memory / network / timeout_invoke / timeout_idle / use_cgroups + validators） | §Standard Stack Pydantic v2；§Pattern 5 validators |
| **PLUG-03** （来自 v1 主表，本 phase 首次实现） | Plugin 沙箱执行（子进程 + cgroups v2 + 网络白名单）— Phase 6 marketplace 直接复用 | 全 phase（PLUG-FW-09 ~ 13 即此条的基础设施） |

**每 ID 必须覆盖**：每 plan 的 frontmatter `requirements: []` 字段列出本 plan 实现的 ID 子集；plan-checker 会做 `Phase req IDs ⊆ Union(plan.requirements)` 校验。

</phase_requirements>

## Summary

Phase 5.B 是把 Phase 5.A 已落地的 `PlatformDaemonClient` (5/5 acid test pass) **加上**沙箱外壳：进程级资源限制 + 网络白名单 + 三层超时强杀 + manifest sandbox 段消费。**技术核心不是发明新机制**，而是 5 个具体工程任务：

1. **SandboxRunner Protocol** + `PosixResourceSandbox`（baseline，cross-platform `resource.setrlimit` via `subprocess.Popen` 的 `preexec_fn`，asyncio 路径用 `partial(_apply_limits, ...)`）
2. **CgroupsV2Sandbox**（Linux opt-in，检测 `/sys/fs/cgroup/cgroup.controllers` 后用 `systemd-run --user --scope --slice=plugin.slice -p MemoryMax=512M -p CPUQuota=100%`）
3. **AllowlistTransport**（httpx `AsyncBaseTransport` 子类，daemon `httpx.AsyncClient(mounts={"all://": AllowlistTransport(allow_list)})` 注入；daemon entrypoint 第 1 行注入 monkey-patch hook 给后续 `aiohttp` 等不直接走 httpx 的 plugin 留兜底 warn）
4. **Watchdog Task**（asyncio task 每 5s 读 `/proc/<pid>/status` RSS 或 cgroup `memory.current` → 超 `sandbox.memory` 发 SIGTERM 等 3s grace → SIGKILL；同时 idle scanner 每 60s 看 `last_invoke_at > 300s` close daemon）
5. **Manifest sandbox 段扩展**（5.A 已有 `SandboxConfig` 框架，本 phase 补齐 validators + 默认值 + 落地消费）

**关键风险点**：
- **macOS RLIMIT_CPU/AS 实测在 macOS 不严格** —— `resource.getrlimit` 返回 `RLIM_INFINITY (2^63-1)`，setrlimit 写入后子进程超限不一定 SIGXCPU。**测试必须 Linux CI**（GitHub Actions `ubuntu-latest`）跑真实 enforcement；本地 macOS dev 只做 contract test（API 不 raise，行为以 Linux 为准）。
- **cgroups v2 unprivileged write**：非 root 用户写 `/sys/fs/cgroup/<slice>/cgroup.subtree_control` 需 systemd-run --user delegation。**直接 cgroup write 在容器内运行（如 docker-compose）通常不能用**，必须走 systemd-run。
- **AllowlistTransport 旁路**：plugin 自由调 `socket.create_connection` / `urllib` / `requests` 不走 httpx → 应用层白名单失效。v1 接受此 trade-off（manifest 注释 + 教育用 httpx），v2 上 namespace 真隔离。
- **watchdog 同时检测多个 daemon**：100 个 daemon × 5s 扫描 = 20 reads/s × 100 = 2k reads/s（cgroup memory.current 即 cat 一文件，不到 1ms），主进程 event loop 不阻塞。

**Primary recommendation**：4-5 plans across 3-4 waves。Wave 1 Dify reading doc + sandbox 段 schema 扩展；Wave 2 并行 PosixResourceSandbox + AllowlistTransport；Wave 3 CgroupsV2Sandbox + watchdog；Wave 4 集成测 + Linux CI gate（GitHub Actions）。

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `resource` | 3.11+ stdlib | `setrlimit(RLIMIT_CPU, (sec, sec))` + `setrlimit(RLIMIT_AS, (bytes, bytes))` baseline | Python 标准库，零依赖；macOS + Linux 都有，行为差异由 OS 决定 |
| `signal` | stdlib | `SIGTERM` (15) / `SIGKILL` (9) / `SIGXCPU` 触发 | RLIMIT_CPU 超限时内核发 SIGXCPU（Linux 严格 / macOS 弱） |
| `asyncio.subprocess` | 3.11+ stdlib | `create_subprocess_exec` + `Process.terminate()` / `.kill()` / `.wait()` | Phase 5.A 已用；5.B 加 `preexec_fn` 参数（POSIX only，asyncio 路径需 kwds dispatch） |
| `httpx` | 0.28+ | `AsyncBaseTransport` 子类化 + `AsyncClient(mounts={"all://": ...})` | Phase 4 已用；Transport API 稳定 0.16+ |
| `pydantic` | 2.10+ | manifest `SandboxConfig` field_validator (cpu_limit regex / memory K8s 单位) | 5.A 已锁定 v2 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `os` | stdlib | `os.kill(pid, signal.SIGTERM)` / `os.environ` / `os.path.exists("/sys/fs/cgroup/cgroup.controllers")` | cgroups v2 检测 / 信号发送 |
| `pathlib.Path` | stdlib | `Path("/sys/fs/cgroup/<slice>/memory.current").read_text()` | cgroups stat 读取 |
| `re` | stdlib | k8s 内存单位解析 `^(\d+(?:\.\d+)?)(Ki\|Mi\|Gi\|Ti\|K\|M\|G\|T\|)$` | 10 行自写，比 humanfriendly 轻 |
| `functools.partial` | stdlib | `partial(_apply_setrlimit, cpu_seconds, memory_bytes)` 作 preexec_fn | asyncio.create_subprocess_exec 不直接收 preexec_fn，需 `subprocess.Popen` 包装或 `start_new_session` 配合 |
| `structlog` | 23+ (Phase 4 已用) | `sandbox.limit_exceeded` / `sandbox.idle_reaped` / `network.blocked` 事件 | Phase 7 Run Viewer 钩子 |
| `pytest-asyncio` | 0.24+ | watchdog / idle reaper task 测试 | 5.A 已用 |
| `aiohttp` | 3.11+ | 5.A HulyPlugin daemon 用 aiohttp；5.B 注意：aiohttp 默认不走 httpx，需 plugin 改用 httpx 才被白名单约束（v1 接受） | 兼容现状（5.A huly_plugin 已用 aiohttp） |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `resource.setrlimit` baseline | `psutil.Process(pid).rlimit()` | psutil 提供同等 API + 跨平台兼容更好；但是引入 18MB C 扩展依赖，资源限制场景 stdlib `resource` 已足够；v2 若要更细粒度统计（per-thread CPU）再上 psutil |
| 自写 k8s 内存单位解析 (10 LOC regex) | `humanfriendly` PyPI 库 | humanfriendly 100k+ DL/月稳定，但 10 行 regex 已可控 + 0 依赖；CLAUDE.md 鼓励无依赖优先 |
| 自写 cgroups v2 write | `cgroupspy` / `psutil.cpu_percent` | cgroupspy 主流 v1；v2 通常直接写 `/sys/fs/cgroup/<slice>/`；systemd-run 是 systemd 标准工具，免维护 cgroup 文件 |
| httpx `AsyncBaseTransport` 子类 | `aiohttp` middleware / DNS hijack | aiohttp 没有 transport mount 概念；DNS hijack 全局 monkey patch 影响主进程；httpx Transport API 是注入点最干净的 |
| 自写 watchdog asyncio task | `apscheduler` | apscheduler 是大头依赖；watchdog 逻辑 20 LOC asyncio.create_task + while sleep 即可 |
| systemd-run --user | 直接 `echo $$ > /sys/fs/cgroup/.../cgroup.procs` | unprivileged 容器内通常不能写 cgroup.subtree_control（需 cgroup delegation）；systemd-run 透明处理 user slice 创建 |
| `nsjail` / `firejail` | resource + httpx | 真隔离更强但 cross-platform 失败（仅 Linux）；v1 cross-platform baseline 优先；v3 marketplace untrusted 上 namespace |

**Installation:**
```bash
# 全部已在 backend/pyproject.toml — Phase 1-5.A 累积；无需新增依赖
# httpx, pydantic, structlog, aiohttp, pytest-asyncio 都已锁定
```

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/agent_builder/platforms/
├── sandbox/                                        # ← 新增 sandbox 子包
│   ├── __init__.py
│   ├── runner.py                                  # SandboxRunner Protocol + PosixResourceSandbox + CgroupsV2Sandbox
│   ├── parser.py                                  # parse_memory("512Mi") → bytes + parse_cpu("1.0") → millicores
│   ├── watchdog.py                                # asyncio task 每 5s 扫资源 + SIGTERM grace
│   ├── idle_reaper.py                             # asyncio task 每 60s 扫 last_invoke_at > timeout_idle
│   ├── network.py                                 # AllowlistTransport + NetworkBlockedError
│   └── cgroups_v2.py                              # cgroups v2 systemd-run helper + /sys/fs/cgroup 读写
├── daemon_client.py                               # ← 修改：构造时接受 sandbox config + runner 注入
├── manifest.py                                    # ← 修改：SandboxConfig 加 validators + 新字段
└── exceptions.py                                  # ← 增 NetworkBlockedError / SandboxLimitExceeded / IdleDaemonReaped

backend/tests/platforms_integration/               # ← 5.A 已建
├── test_resource_limits.py                        # PosixResourceSandbox SIGXCPU / OOM 真子进程跑
├── test_cgroups_v2_sandbox.py                     # Linux only, skip on macOS
├── test_network_allowlist.py                      # AllowlistTransport 拦截非白名单 host
├── test_watchdog_grace_period.py                  # SIGTERM 3s grace → SIGKILL
├── test_idle_reaper.py                            # idle > 300s 后 close
└── test_sandbox_manifest_validation.py            # Pydantic v2 validators
```

### Pattern 1: `resource.setrlimit` baseline via `preexec_fn`

**What:** Python `subprocess.Popen` 支持 `preexec_fn` 参数（fork 后 / exec 前调用，在子进程上下文跑）。但 `asyncio.create_subprocess_exec` **不直接接受 preexec_fn**（asyncio 接口比 subprocess 窄）。解决方式：用底层 `subprocess.Popen(preexec_fn=...)` 包装 + `asyncio.subprocess.Process` 适配；或者更简单：让 daemon entrypoint 第 1 行自己 `resource.setrlimit`（由 manifest 注入 env var）。

**Critical macOS vs Linux 差异**（HIGH 验证）：
- `RLIMIT_CPU` (CPU seconds soft/hard) — **Linux 严格**：超 soft 发 SIGXCPU，超 hard 发 SIGKILL；**macOS 实测 RLIM_INFINITY 默认且 setrlimit 写入可能被 OS 忽略**。测试必须 Linux CI 跑。
- `RLIMIT_AS` (Address Space) — **Linux 严格**：超限 malloc 返回 ENOMEM；**macOS 行为差** — Darwin kernel 不严格按 AS 限制。
- `RLIMIT_DATA` / `RLIMIT_RSS` — macOS 上 RLIMIT_RSS 是 advisory（行为同 RLIMIT_DATA），不真阻止；Linux 上 RLIMIT_DATA 严格。
- `RLIMIT_NOFILE` (file descriptors) / `RLIMIT_NPROC` (subprocess) — **cross-platform 严格** ✓

**When to use:** 所有 plugin daemon 启动；macOS dev contract test only（不期待严格 enforcement）。

**Example:**

```python
# backend/app/agent_builder/platforms/sandbox/runner.py
from __future__ import annotations

import asyncio
import os
import resource
import subprocess
from typing import Protocol


class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> asyncio.subprocess.Process: ...


def _apply_posix_limits(cpu_seconds: int, memory_bytes: int) -> None:
    """preexec_fn — fork 之后、exec 之前在子进程上下文跑。

    必须无阻塞 + 无 async（fork 后 event loop 不可用）。
    """
    # RLIMIT_CPU: soft/hard 都设；超 soft 发 SIGXCPU（子进程必须处理）
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    # RLIMIT_AS: virtual memory size — Linux 严格 / macOS 弱
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    # RLIMIT_NPROC: 子进程不能再 fork（防 fork bomb）
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
    # RLIMIT_NOFILE: 文件描述符上限（防句柄泄漏）
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    # 切到新进程组（让 SIGTERM 能精准 kill 这棵进程树）
    os.setsid()


class PosixResourceSandbox:
    """resource.setrlimit baseline — macOS dev + Linux fallback。

    实现要点：
    - asyncio.create_subprocess_exec 不收 preexec_fn → 用 loop.subprocess_exec + ChildWatcher 接管
    - 或更简单：用 subprocess.Popen + functools.partial → asyncio.subprocess.Process 包装

    本实现走第二条（兼容性更好 + 错误处理简单）。
    """

    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> asyncio.subprocess.Process:
        loop = asyncio.get_event_loop()
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)

        # 用 functools.partial 把 limits 绑给 _apply_posix_limits
        from functools import partial
        preexec = partial(_apply_posix_limits, cpu_seconds, memory_bytes)

        # asyncio loop.subprocess_exec 是底层 API，接受任意 Popen kwargs
        transport, protocol = await loop.subprocess_exec(
            asyncio.subprocess.SubprocessStreamProtocol,
            *cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            cwd=cwd,
            preexec_fn=preexec,    # ← 关键
            close_fds=True,         # 防 fd 泄漏
        )
        return asyncio.subprocess.Process(transport, protocol, loop)
```

**注意:**
- `preexec_fn` 在 Python 3.12+ 仅 POSIX（Windows 不支持）— 我们项目 Linux + macOS only ✓
- `os.setsid()` 让子进程成为新会话组 leader — close 时 `os.killpg(pgid, SIGTERM)` 能精准 kill 整棵进程树（防 daemon fork 子进程逃逸）

### Pattern 2: cgroups v2 via systemd-run --user

**What:** Linux 生产环境 opt-in 路径。manifest `sandbox.use_cgroups: true` 时走此分支。systemd-run --user 创建 transient user-scope cgroup，资源限制由 systemd 管理（免手写 cgroup 文件）。

**When to use:** Linux + manifest opt-in + systemd 可用（`pgrep systemd-userdbd > /dev/null` 检测）。

**Detection:**
```python
# backend/app/agent_builder/platforms/sandbox/cgroups_v2.py
from pathlib import Path

def is_cgroups_v2_available() -> bool:
    """检测 cgroups v2 + systemd-run --user 是否可用。

    必须满足 4 条：
    1. /sys/fs/cgroup/cgroup.controllers 存在（v2 统一层级）
    2. memory + cpu controllers 在 cgroup.controllers 中可用
    3. systemd-run 在 PATH 中
    4. systemd --user 在跑（user@<uid>.service active）
    """
    controllers = Path("/sys/fs/cgroup/cgroup.controllers")
    if not controllers.exists():
        return False
    available = controllers.read_text().split()
    if "memory" not in available or "cpu" not in available:
        return False
    import shutil
    return shutil.which("systemd-run") is not None
```

**Example:**

```python
class CgroupsV2Sandbox:
    """Linux opt-in cgroups v2 sandbox（systemd-run --user --scope）。

    资源限制走 systemd transient unit:
    - MemoryMax: 硬上限（OOM kill 自动）
    - MemorySwapMax: 0（防 swap 绕开 mem limit）
    - CPUQuota: % of single core（"100%" = 1 core, "50%" = half core）
    - TasksMax: 防 fork bomb
    """

    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,    # 在此实现里转换为 CPU quota（运行总时间靠 watchdog）
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> asyncio.subprocess.Process:
        # 注：cpu_seconds 是 CPU runtime（RLIMIT_CPU 概念）
        # cgroups v2 没直接对应字段；用 CPUQuota=100% 一个核 + watchdog 兜底
        systemd_cmd = [
            "systemd-run",
            "--user",
            "--scope",
            "--slice=agent-builder-plugin.slice",  # 单独 slice 隔离
            "--quiet",                              # 不打印 unit name
            f"--property=MemoryMax={memory_bytes}",
            f"--property=MemorySwapMax=0",
            f"--property=CPUQuota=100%",
            f"--property=TasksMax=32",
            "--",
            *cmd,
        ]
        return await asyncio.create_subprocess_exec(
            *systemd_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})},
            cwd=cwd,
        )
```

**关键约束:**
- **容器内运行需 cgroup delegation**：docker-compose 内运行时，cgroup namespace 默认未授权 user-scope 创建 — 必须 docker-compose 加 `privileged: true` 或精细 `--cgroup-parent` 配置
- **CI 环境（GitHub Actions ubuntu-latest）** 默认无 systemd-userdbd 跑，CgroupsV2Sandbox 测试需 `skip if not is_cgroups_v2_available()` 守护
- **OOM kill 行为**：内核 OOM killer 发 SIGKILL → daemon stdout EOF → 主进程 `_read_loop` 立即检测（5.A Pitfall 2 已防护）

### Pattern 3: AllowlistTransport (httpx Transport API)

**What:** httpx `AsyncBaseTransport` 是 transport 层抽象（HTTP 层与底层 connection 解耦）。子类化 + override `handle_async_request(request)` 即可在请求路径插入白名单检查。`mounts={"all://": AllowlistTransport(...)}` 让所有 URL 走自定义 transport。

**When to use:** plugin daemon entrypoint 第 1 行注入；plugin 显式用注入的 `httpx.AsyncClient` 才被约束。

**Example:**

```python
# backend/app/agent_builder/platforms/sandbox/network.py
from __future__ import annotations

import httpx
from urllib.parse import urlparse


class NetworkBlockedError(Exception):
    """非白名单 host 出站时 raise（plugin 内部可 catch + 返回业务错误）。"""


class AllowlistTransport(httpx.AsyncBaseTransport):
    """httpx Transport 子类 — 检查 url host:port 是否在 allow_list。

    实现注意:
    - 接受 list[str] 形式 "host:port"（manifest 解析）
    - "https://example.com" 默认 port 443；"http://example.com" 默认 port 80
    - port 为 None 时按 scheme 默认补齐
    - exact match（v1 不支持通配符 `*.example.com` — 留 v2）
    """

    def __init__(
        self,
        allow_list: list[str],
        *,
        delegate: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allow_set: set[tuple[str, int]] = set()
        for entry in allow_list:
            host, _, port_str = entry.partition(":")
            self._allow_set.add((host.lower(), int(port_str) if port_str else 443))
        # delegate 是真实底层 transport（默认 AsyncHTTPTransport）
        self._delegate = delegate or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if (host, port) not in self._allow_set:
            raise NetworkBlockedError(
                f"network blocked by sandbox: {host}:{port} not in allow_list"
            )

        return await self._delegate.handle_async_request(request)

    async def aclose(self) -> None:
        await self._delegate.aclose()


# Plugin daemon entrypoint 使用
def make_sandboxed_http_client(allow_list: list[str]) -> httpx.AsyncClient:
    """plugin 显式调用此 helper 拿到沙箱化的 httpx client。"""
    return httpx.AsyncClient(
        transport=AllowlistTransport(allow_list),
        timeout=httpx.Timeout(10.0),
    )
```

**测试方式（关键）:**

```python
# backend/tests/platforms_integration/test_network_allowlist.py
@pytest.mark.asyncio
async def test_allowlist_blocks_unlisted_host() -> None:
    client = make_sandboxed_http_client(["example.com:443"])
    with pytest.raises(NetworkBlockedError):
        await client.get("https://huly.io/api/...")  # 不在白名单

@pytest.mark.asyncio
async def test_allowlist_allows_whitelisted_host() -> None:
    # 用 httpx MockTransport 作 delegate 避免真发 HTTP
    mock = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    transport = AllowlistTransport(["example.com:443"], delegate=mock)
    client = httpx.AsyncClient(transport=transport)
    r = await client.get("https://example.com/api")
    assert r.json() == {"ok": True}
```

### Pattern 4: Watchdog Task + SIGTERM Grace Period

**What:** PlatformDaemonClient 启动时 spawn 独立 asyncio task `_watchdog_loop`，每 5s 读 `/proc/<pid>/status` (Linux RSS) 或 cgroup `memory.current` (cgroups v2 mode) 或调 `psutil.Process(pid).memory_info()` (cross-platform fallback)，超 `sandbox.memory` 触发强杀流程。

**关键设计 — 三层防护互不阻塞:**

```
Layer 1: invoke timeout (5.A 已有)
   └─ asyncio.wait_for(future, 30s)  → 走业务正常错误路径

Layer 2: 资源超限 (本 phase 新增)
   ├─ RLIMIT_CPU 超限 → 内核发 SIGXCPU → daemon 默认 terminate（行为同 SIGKILL）
   ├─ RLIMIT_AS / cgroups MemoryMax → malloc 返回 ENOMEM / OOM kill → daemon 直接死
   └─ watchdog 检测软超限（如 80% threshold warn / 100% SIGTERM grace 3s → SIGKILL）

Layer 3: idle daemon 回收 (本 phase 新增)
   └─ 每 60s 扫；last_invoke_at > 300s → close（不杀死，让 daemon 优雅退出）
```

**Example:**

```python
# backend/app/agent_builder/platforms/sandbox/watchdog.py
from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)

_DEFAULT_SCAN_INTERVAL = 5.0
_DEFAULT_GRACE_PERIOD = 3.0


class SandboxWatchdog:
    """监控 daemon 资源使用 — 超限发 SIGTERM 等 grace 后 SIGKILL。"""

    def __init__(
        self,
        pid: int,
        memory_limit_bytes: int,
        on_violation: Callable[[str], None] | None = None,
        *,
        scan_interval: float = _DEFAULT_SCAN_INTERVAL,
        grace_period: float = _DEFAULT_GRACE_PERIOD,
    ) -> None:
        self._pid = pid
        self._memory_limit = memory_limit_bytes
        self._on_violation = on_violation or (lambda msg: None)
        self._scan_interval = scan_interval
        self._grace_period = grace_period
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    def start(self) -> None:
        self._task = asyncio.create_task(
            self._loop(),
            name=f"sandbox-watchdog[pid={self._pid}]",
        )

    async def _loop(self) -> None:
        while not self._stopped:
            try:
                rss = self._read_rss()
                if rss is None:
                    # 进程已死，watchdog 自然退出
                    return
                if rss > self._memory_limit:
                    await self._terminate_with_grace(
                        f"memory exceeded: rss={rss} > limit={self._memory_limit}"
                    )
                    return
            except Exception as e:
                _log.warning("watchdog scan error: %s", e)
            await asyncio.sleep(self._scan_interval)

    def _read_rss(self) -> int | None:
        """Linux: /proc/<pid>/status → VmRSS。cross-platform fallback: psutil."""
        try:
            status = Path(f"/proc/{self._pid}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    # VmRSS:    1234 kB
                    return int(line.split()[1]) * 1024
        except (FileNotFoundError, PermissionError):
            # macOS / Windows / 进程已死
            return None
        return None

    async def _terminate_with_grace(self, reason: str) -> None:
        _log.warning(
            "sandbox.limit_exceeded pid=%s reason=%s — SIGTERM grace=%.1fs",
            self._pid,
            reason,
            self._grace_period,
        )
        self._on_violation(reason)

        # SIGTERM (15)
        try:
            os.killpg(os.getpgid(self._pid), signal.SIGTERM)
        except ProcessLookupError:
            return  # 已死

        # Grace period
        await asyncio.sleep(self._grace_period)

        # 检查是否还活着
        try:
            os.kill(self._pid, 0)  # signal 0 = 探活
        except ProcessLookupError:
            return  # 已优雅退出 ✓

        # SIGKILL (9) — 强杀
        _log.warning(
            "sandbox.force_kill pid=%s — grace expired, SIGKILL",
            self._pid,
        )
        try:
            os.killpg(os.getpgid(self._pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

    def stop(self) -> None:
        self._stopped = True
        if self._task and not self._task.done():
            self._task.cancel()
```

### Pattern 5: Idle Daemon Reaper

**What:** 独立 asyncio task（不与 watchdog 混在一个 loop），每 60s 扫所有 active daemon 的 `last_invoke_at`，超 300s 调 `daemon.close()`（不强杀，走 SIGTERM 正常退出路径）。下次 invoke 走 5.A 的 lazy spawn 重启 daemon。

**Example:**

```python
# backend/app/agent_builder/platforms/sandbox/idle_reaper.py
import asyncio
import time
import logging

_log = logging.getLogger(__name__)

class IdleDaemonReaper:
    """跟踪 daemon last_invoke_at；idle > timeout_idle 调 close。

    与 PlatformDaemonClient 集成方式（轻耦合）：
    - daemon_client 暴露 last_invoke_at: float 属性（在 invoke() 开头 self._last_invoke_at = time.monotonic()）
    - daemon_client 暴露 close() 协程（5.A 已有）
    - reaper 拿到 daemon 实例 list，每 60s 扫 + close idle
    """

    def __init__(
        self,
        get_daemons: Callable[[], list[PlatformDaemonClient]],
        timeout_idle: float = 300.0,
        scan_interval: float = 60.0,
    ) -> None:
        self._get_daemons = get_daemons
        self._timeout_idle = timeout_idle
        self._scan_interval = scan_interval
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="idle-daemon-reaper")

    async def _loop(self) -> None:
        while not self._stopped:
            now = time.monotonic()
            for daemon in self._get_daemons():
                last = getattr(daemon, "last_invoke_at", None)
                if last is None or daemon._proc is None:
                    continue
                if now - last > self._timeout_idle:
                    _log.info(
                        "sandbox.idle_reaped daemon=%s idle_secs=%.1f",
                        daemon._module_entry,
                        now - last,
                    )
                    try:
                        await daemon.close()  # 不阻塞主进程；5.A close 已 5s timeout 兜底
                    except Exception as e:
                        _log.warning("idle reap close error: %s", e)
            await asyncio.sleep(self._scan_interval)

    def stop(self) -> None:
        self._stopped = True
        if self._task:
            self._task.cancel()
```

### Pattern 6: Manifest sandbox 段扩展（Pydantic v2 validators）

5.A 已有 `SandboxConfig`（CONTEXT.md §Manifest sandbox 段 schema 引用），5.B 补 validators + 落地消费：

```python
# backend/app/agent_builder/platforms/manifest.py（修改 SandboxConfig）
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

_MEMORY_RE = re.compile(r"^(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti|K|M|G|T|)$")
_CPU_RE = re.compile(r"^\d+(\.\d+)?$")
_HOST_PORT_RE = re.compile(r"^[a-z0-9.-]+:\d+$")


class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_limit: str = Field(default="2.0", pattern=_CPU_RE.pattern)
    memory: str = Field(default="1Gi")
    network: list[str] = Field(default_factory=list)
    timeout_invoke: int = Field(default=30, gt=0, le=3600)
    timeout_idle: int = Field(default=300, gt=0, le=86400)
    use_cgroups: bool = False

    @field_validator("memory")
    @classmethod
    def memory_must_be_k8s_format(cls, v: str) -> str:
        if not _MEMORY_RE.match(v):
            raise ValueError(
                f"memory must be k8s format like '512Mi' / '1Gi', got {v!r}"
            )
        return v

    @field_validator("network")
    @classmethod
    def network_entries_must_be_host_port(cls, v: list[str]) -> list[str]:
        for entry in v:
            if not _HOST_PORT_RE.match(entry):
                raise ValueError(
                    f"network entry must be 'host:port' (lowercase), got {entry!r}"
                )
        return v

    @property
    def memory_bytes(self) -> int:
        """parse_memory("512Mi") → 536870912 bytes — 在 sandbox runner 中使用。"""
        m = _MEMORY_RE.match(self.memory)
        val, unit = m.group(1), m.group(2)
        multipliers = {
            "": 1, "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,
            "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
        }
        return int(float(val) * multipliers[unit])

    @property
    def cpu_limit_seconds(self) -> int:
        """cpu_limit "2.0" → RLIMIT_CPU 总秒数（保守 1h × cores 给 long-running）。

        注：RLIMIT_CPU 是总累积 CPU 秒，不是 quota；这里给 long-running plugin
        足够余量（3600s × 2 cores = 7200s）；真正 quota 限制走 cgroups v2 CPUQuota。
        """
        return int(float(self.cpu_limit) * 3600)
```

### Anti-Patterns to Avoid

- **直接拷贝 Dify dify-plugin-daemon Go 源码** — Dify daemon 是 AGPL-3.0 + Go 实现；本项目 Apache-2.0 + Python。仅借鉴**设计模式**（cgroups + namespace 思路），自写 Python 实现。
- **同步 `subprocess.Popen(preexec_fn=...).communicate()`** — block event loop（5.A Pitfall 1 重现）。必须走 asyncio loop.subprocess_exec。
- **manifest sandbox 字段 `extra=allow`** — Phase 5.A 已设 `extra=forbid`，5.B 不要倒退。
- **watchdog 频率 < 1s** — `/proc/<pid>/status` read 不是 0 成本；< 1s 间隔会让主进程 100 daemon 场景下 watchdog 占 CPU。5s 是合理 floor。
- **AllowlistTransport 默认 fallback 真发请求** — 默认必须拒绝未声明 host；只有 manifest 显式 allow 才放行。这是安全控制的核心。
- **idle reaper 用 wall clock** — 必须 `time.monotonic()`，否则 NTP 调时间导致误判。
- **watchdog 检测后直接 SIGKILL** — 必须先 SIGTERM 让 daemon 有机会 flush 日志 / drain pending future；3s grace 后 SIGKILL。
- **`os.kill(pid, SIGTERM)` 而非 `os.killpg(pgid, ...)`** — daemon 可能 fork 子进程；只 kill 父留下僵尸子。必须 `os.setsid()` + `os.killpg()` 整组 kill。
- **CgroupsV2Sandbox 在 macOS 跑** — `is_cgroups_v2_available()` 返回 False 时不允许 `use_cgroups: true`（manifest 时检测 + 启动时 fail-fast）。
- **AllowlistTransport 全局 monkey-patch httpx** — 应当 plugin 显式调 `make_sandboxed_http_client()` 拿 client；全局 patch 影响主进程 httpx 调用。

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 进程级资源限制 | 自写 LD_PRELOAD hook | `resource.setrlimit` stdlib（cross-platform）/ cgroups v2 systemd-run（Linux 生产） | stdlib 0 依赖 + cross-platform；cgroups 是 Linux 内核标准 |
| K8s 内存单位解析 | 自写 100 行 unit registry | 10 行 regex `^(\d+\.?\d*)(Ki\|Mi\|Gi\|Ti\|K\|M\|G\|T\|)$` + dict lookup | k8s 标准固定 8 个单位 + 空；10 行可读 |
| 网络白名单 v1 | 自写 socket monkey-patch | httpx `AsyncBaseTransport` 子类 + `mounts={"all://": ...}` | httpx Transport API 是注入点最干净；socket patch 影响主进程 |
| cgroups v2 文件读写 | 自写 cgroup tree 管理 | `systemd-run --user --scope` 单命令 | systemd 透明处理 user slice + cgroup delegation；免维护 cgroup 文件 |
| 子进程探活 | 轮询 `Popen.poll()` | `os.kill(pid, 0)`（signal 0）+ `Process.returncode` 监听 | signal 0 是 POSIX 标准探活方式，0 副作用 |
| 进程树 kill | 递归找子进程 | `os.setsid()` (启动时) + `os.killpg(pgid, sig)` (kill 时) | 进程组是 POSIX 内核机制；防 fork 子进程逃逸 |
| Linux RSS 读取 | psutil 完整依赖 | `Path("/proc/<pid>/status").read_text()` parse `VmRSS:` | /proc 是 Linux 内核标准接口；5 行可读；fallback psutil 仅 macOS dev 路径 |

**Key insight:** 5.B 90% 功能是组合 stdlib (`resource` / `signal` / `os` / `subprocess`) + Phase 5.A 已有抽象（PlatformDaemonClient 的 close / fault isolation）。唯一需要"判断设计"的是 watchdog 频率（5s）+ grace period (3s)，这两个值是 Linux container best practice（systemd `KillSignal=SIGTERM` + `TimeoutStopSec=3s` 默认行为参考）。

---

## Common Pitfalls

### Pitfall 1: macOS RLIMIT_CPU / RLIMIT_AS 弱 enforcement → false-pass

**What goes wrong:** macOS dev 跑 `resource.setrlimit(RLIMIT_AS, (100*1024*1024, ...))` 不抛错；但是 daemon malloc 1GB 也不被 OOM kill — 因为 Darwin kernel RLIMIT_AS 是 advisory（非强制）。本地 pytest 误以为 "限制生效"，CI Linux 时才暴露实际是不严格。

**Why it happens:** macOS XNU kernel 对 BSD-style rlimits 的实现弱于 Linux；RLIMIT_AS 在 macOS 实际无效（Darwin 只严格 RLIMIT_CORE / RLIMIT_NOFILE / RLIMIT_NPROC）。

**How to avoid:**
1. **Linux CI 必须 gate**：GitHub Actions `ubuntu-latest` 跑 `pytest tests/platforms_integration/test_resource_limits.py -v`；macOS local 跑同测试要 `@pytest.mark.skipif(sys.platform == "darwin", reason="...")`
2. **macOS dev 只跑 contract tests**：API call 不抛 / 默认值正确 / Pydantic validator 通过；不期待 enforcement
3. **集成测试 distinguish**：`@pytest.mark.linux_only` decorator 标 enforcement test；smoke test 全平台跑

**Warning signs:** macOS pytest 全绿 + Linux CI 红；OOM kill log 缺失；测试断言 `process.returncode == -9 (SIGKILL)` 在 macOS 跑出 returncode = 0。

### Pitfall 2: cgroups v2 unprivileged write 容器内失败

**What goes wrong:** docker-compose 内运行 agent-builder，`systemd-run --user --scope ...` raise `Failed to start transient scope unit: Permission denied` — 因为 docker 容器默认无 cgroup namespace + cgroup.subtree_control 写入授权。

**Why it happens:** cgroups v2 user-scope 创建需要 cgroup delegation；容器内默认未授权。

**How to avoid:**
1. **运行时检测**：`is_cgroups_v2_available()` 不仅查 `/sys/fs/cgroup/cgroup.controllers`，还要 `subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"], capture_output=True, timeout=2)` 真试一次
2. **优雅降级**：检测失败 → log warn + 降级到 PosixResourceSandbox；不 fail startup
3. **docker-compose 配置文档**：`deploy/docker-compose.yml` 加注释说明 cgroups v2 需要 `--privileged` 或 `--cgroup-parent` 配置（v1 dev 不要求；v2 生产文档化）
4. **CI 跳过 cgroups 测试**：`@pytest.mark.skipif(not is_cgroups_v2_available(), reason="cgroups v2 not available (likely container or non-Linux)")`

**Warning signs:** Linux CI 红 + 错误信息 `Failed to connect to bus`；生产环境 daemon spawn 失败 cascade。

### Pitfall 3: AllowlistTransport 旁路 — plugin 用 `requests` / `urllib`

**What goes wrong:** plugin 内 import `requests`; `requests.get("https://leaked-host.io/...")` — 不走 httpx → 完全绕开 AllowlistTransport。

**Why it happens:** Python 网络栈多元（urllib / socket / aiohttp / httpx 都各自维护 connection pool），单 transport 注入只覆盖 httpx。

**How to avoid:**
1. **v1 接受 trade-off + 教育**：manifest sandbox 段加注释 "v1 网络白名单仅约束 httpx 客户端；plugin 必须用 `make_sandboxed_http_client()`"
2. **CI lint hook**：plugin 代码 `grep -E "(import requests\|import urllib.request\|from urllib import request\|import aiohttp.*ClientSession\(\))"` 命中 → warn（非 fail，因 5.A huly_plugin 已用 aiohttp）
3. **v2 真隔离**：Phase 6 marketplace 上 nsjail / firejail / network namespace → kernel 层拦截所有 socket
4. **Plugin developer guide**：文档强调用注入 httpx client（Phase 5.A 已留 docs/plugin-developer-guide.md 槽位）

**Warning signs:** 集成测试发现 plugin 真发 HTTP 到非白名单 host；prod 日志出现 `requests.exceptions` 而非 `NetworkBlockedError`。

### Pitfall 4: SIGTERM 不达 daemon — 进程组未设

**What goes wrong:** daemon 启动后 fork 子进程（如 plugin 内 multiprocessing.Process），watchdog SIGTERM 只到 daemon 父进程，子进程残留为僵尸。

**Why it happens:** `os.kill(pid, SIGTERM)` 只杀单个进程；fork 子进程在父进程死后被 init 收养。

**How to avoid:**
1. **`_apply_posix_limits` 内 `os.setsid()`**：让 daemon 成为新 session leader + 进程组 leader（pgid = pid）
2. **watchdog kill 用 `os.killpg(os.getpgid(pid), SIGTERM)`**：发给整个进程组
3. **测试覆盖**：单测 spawn daemon → daemon 内 fork 子进程 → SIGTERM → 断言所有子进程 returncode 非 None

**Warning signs:** SIGKILL 后 `ps aux | grep huly_plugin` 仍有残留；docker stats 显示进程数不降。

### Pitfall 5: Watchdog SIGTERM 阻塞 _read_loop

**What goes wrong:** watchdog 发 SIGTERM 给 daemon → daemon 退出 → 5.A `_read_loop` 检测到 stdout EOF → `_fail_all_pending(PluginDaemonExitedError(...))`。但是当前 invoke 主线程仍在 `asyncio.wait_for(future, timeout=2.0)`，先收到 `PluginDaemonExitedError` 还是 `asyncio.TimeoutError`？

**Why it happens:** asyncio 多 task 并发；watchdog SIGTERM → daemon exit → read_loop fail future 是异步路径，主 invoke 路径在 timeout 计时。

**How to avoid:**
1. **timeout 设计层级**：`invoke_timeout (30s) > grace_period (3s) + scan_interval (5s) = 8s` 上限 → watchdog 必然先触发；主 invoke timeout 是兜底
2. **watchdog `on_violation` callback 集成 daemon_client**：watchdog 检测超限时先 `daemon._fail_all_pending(SandboxLimitExceeded(...))` 让主 invoke 立即 raise，再发 SIGTERM；保证 error 类型确定（不依赖竞态）
3. **测试覆盖**：spawn daemon → 模拟 high memory → watchdog 触发 → 断言 invoke raise `SandboxLimitExceeded`（不是 `TimeoutError`）

**Warning signs:** 集成测试间歇性失败，错误类型在 `SandboxLimitExceeded` / `PluginDaemonExitedError` / `TimeoutError` 间漂移。

### Pitfall 6: Idle reaper 与正在 invoke 的 daemon 竞争

**What goes wrong:** idle reaper 扫描时 daemon.last_invoke_at 是 320s 前，调 `daemon.close()`；同时 invoke 线程刚发完 envelope 在等响应 — close 让 stdin 关闭 → invoke raise `PluginDaemonExitedError`。

**Why it happens:** `last_invoke_at` 在 invoke() **开头**写入；invoke 期间（30s 上限）这个值不变，reaper 可能误判。

**How to avoid:**
1. **`last_invoke_at` 在 invoke() 结束时更新（finally 块）**：保证活跃 invoke 期间不计入 idle
2. **或者：daemon_client 暴露 `_pending` 长度**：reaper 跳过 `len(daemon._pending) > 0` 的 daemon
3. **timeout_idle 默认 300s 远大于 invoke_timeout 30s**：留 10× safety margin，竞态概率极低

**Warning signs:** 长时间运行后 invoke 偶发 `PluginDaemonExitedError("daemon closed by client")`；log `sandbox.idle_reaped` 紧跟 invoke timestamp。

### Pitfall 7: cgroups v2 OOM kill 但 daemon 不退

**What goes wrong:** cgroups v2 `MemoryMax=512M` 触发 OOM killer → 内核 SIGKILL daemon → daemon 死亡。但是 systemd-run --scope 的 wrapper process 仍在 — `Process.returncode` 来自 systemd-run 而非真实 plugin daemon。

**Why it happens:** systemd-run --scope 创建一个 cgroup scope，把 daemon 放进去；scope 是父进程 holding。

**How to avoid:**
1. **`systemd-run --quiet --scope --wait`** + `--collect`：等待 daemon 真正退出且 cgroup 释放
2. **检测 returncode**：OOM kill 时 returncode 为 137（SIGKILL = 9，128+9=137）；区分自然退出和 OOM
3. **优雅降级测试**：spawn cgroups daemon → daemon malloc 越限 → 断言主进程 `_read_loop` EOF + `PluginDaemonExitedError` 在 < 2s 触发

**Warning signs:** Linux CI 显示 `Process.returncode = 0` 但 dmesg 有 OOM kill；主进程 hang 等响应。

### Pitfall 8: env 变量泄漏 secret 给 plugin

**What goes wrong:** plugin daemon spawn 时 `env = dict(os.environ)` merge — 主进程 `HMAC_SECRET` / `DATABASE_URL` / OAuth credentials 全部泄漏给 plugin。

**Why it happens:** 5.A `daemon_client.py` 已 `merged_env = dict(os.environ); merged_env.update(self._env)` — secrets 直接传过去。

**How to avoid:**
1. **strip-all-allow-list pattern**：默认只传 `PATH` / `HOME` / `LANG` / `TZ` 等运行必需的；manifest `sandbox.env_allowlist: ["HULY_ENDPOINT", "FOO_API_KEY"]` 显式 opt-in
2. **主进程 secret 命名前缀**：`AGENT_BUILDER_*` / `INTERNAL_*` 默认 strip（即使 manifest 想 allow 也拒绝）
3. **测试覆盖**：spawn daemon → daemon 内 `os.environ` 不应含 `HMAC_SECRET`；CI 断言

**Warning signs:** plugin 内偶发能调主进程 admin API（说明拿到 HMAC_SECRET）。

---

## Code Examples

### Example 1: PlatformDaemonClient 集成 sandbox runner

```python
# backend/app/agent_builder/platforms/daemon_client.py（5.B 修改片段）
class PlatformDaemonClient:
    def __init__(
        self,
        module_entry: str,
        env: dict[str, str] | None = None,
        invoke_timeout: float = _DEFAULT_INVOKE_TIMEOUT,
        cwd: str | None = None,
        sandbox_config: SandboxConfig | None = None,
        sandbox_runner: SandboxRunner | None = None,
    ) -> None:
        # ... 5.A 既有字段
        self._sandbox_config = sandbox_config or SandboxConfig()
        self._sandbox_runner = sandbox_runner or self._choose_runner()
        self._watchdog: SandboxWatchdog | None = None
        self._last_invoke_at: float = 0.0

    def _choose_runner(self) -> SandboxRunner:
        """自动选择 runner：use_cgroups + 检测可用 → CgroupsV2Sandbox; 否则 PosixResourceSandbox。"""
        if self._sandbox_config.use_cgroups and is_cgroups_v2_available():
            return CgroupsV2Sandbox()
        return PosixResourceSandbox()

    async def start(self) -> None:
        async with self._lock:
            if self._proc is not None:
                return
            self._closed = False

            # 5.B: 走 sandbox runner 启动子进程
            self._proc = await self._sandbox_runner.spawn_with_limits(
                [sys.executable, "-u", "-m", self._module_entry],
                cpu_seconds=self._sandbox_config.cpu_limit_seconds,
                memory_bytes=self._sandbox_config.memory_bytes,
                env=self._build_filtered_env(),    # 5.B: 走 env_allowlist 过滤
                cwd=self._cwd,
            )
            # ... reader/stderr task spawn 5.A 既有

            # 5.B: spawn watchdog
            self._watchdog = SandboxWatchdog(
                pid=self._proc.pid,
                memory_limit_bytes=self._sandbox_config.memory_bytes,
                on_violation=lambda msg: self._fail_all_pending(
                    SandboxLimitExceeded(msg)
                ),
            )
            self._watchdog.start()
```

### Example 2: Linux-only integration test

```python
# backend/tests/platforms_integration/test_resource_limits.py
import sys
import pytest
from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox

pytestmark = pytest.mark.skipif(
    sys.platform == "darwin",
    reason="macOS RLIMIT_AS 弱 enforcement — 仅 Linux CI 跑真实限制测",
)

@pytest.mark.asyncio
async def test_rlimit_as_enforces_memory_cap() -> None:
    """Linux: 子进程 malloc 超 RLIMIT_AS 必然失败。"""
    sandbox = PosixResourceSandbox()
    proc = await sandbox.spawn_with_limits(
        [sys.executable, "-u", "-c",
         "x = b'a' * (200 * 1024 * 1024); print('alloc ok'); import sys; sys.stdout.flush()"],
        cpu_seconds=10,
        memory_bytes=100 * 1024 * 1024,    # 100MB limit
    )
    await proc.wait()
    # malloc 200MB 超 100MB → MemoryError / OOM
    assert proc.returncode != 0, "200MB alloc 超 100MB limit 必然失败"

@pytest.mark.asyncio
async def test_rlimit_cpu_triggers_sigxcpu() -> None:
    """RLIMIT_CPU 超限 → SIGXCPU → returncode = -24 (Linux SIGXCPU)."""
    sandbox = PosixResourceSandbox()
    proc = await sandbox.spawn_with_limits(
        [sys.executable, "-u", "-c",
         "while True: pass"],    # CPU 密集
        cpu_seconds=1,           # 1s 后超 RLIMIT_CPU
        memory_bytes=100 * 1024 * 1024,
    )
    await asyncio.wait_for(proc.wait(), timeout=5.0)
    # SIGXCPU = 24 on Linux; returncode = -24
    import signal
    assert proc.returncode == -signal.SIGXCPU or proc.returncode < 0
```

### Example 3: AllowlistTransport in plugin entry

```python
# plugins/huly/huly_plugin.py（5.B 修改片段）
import os
from app.agent_builder.platforms.sandbox.network import make_sandboxed_http_client

# 主进程通过 env 注入 network whitelist（manifest 解析后 join 成 ":"-sep str）
_NETWORK_ALLOW = os.environ.get("PLUGIN_NETWORK_ALLOW", "").split(",") if os.environ.get("PLUGIN_NETWORK_ALLOW") else []

async def im_send_card(params):
    # 用沙箱化 httpx client（替代之前 aiohttp.ClientSession）
    async with make_sandboxed_http_client(_NETWORK_ALLOW) as client:
        r = await client.post(f"{HULY_ENDPOINT}/api/v1/chunter/messages", json=body)
        r.raise_for_status()
        data = r.json()
    return {"plugin_name": "huly", "native_id": data["message_id"], "extras": {...}}
```

### Example 4: Watchdog grace period integration test

```python
# backend/tests/platforms_integration/test_watchdog_grace_period.py
@pytest.mark.asyncio
async def test_watchdog_sigterm_then_sigkill_after_grace() -> None:
    """超内存 → SIGTERM → daemon 故意不退（ignore SIGTERM）→ 3s grace → SIGKILL."""
    # daemon 启动时 signal.signal(SIGTERM, lambda *a: None) 故意忽略
    daemon = PlatformDaemonClient(
        module_entry="tests.platforms_integration.fixtures.sigterm_ignoring_daemon",
        sandbox_config=SandboxConfig(memory="50Mi", timeout_invoke=10),
    )
    await daemon.start()
    # 触发 watchdog
    start = time.monotonic()
    with pytest.raises(SandboxLimitExceeded):
        await daemon.invoke("test", "alloc_200mb")  # 故意超
    elapsed = time.monotonic() - start
    # 必须 < 8s（watchdog 5s + grace 3s）
    assert elapsed < 9.0, f"watchdog 强杀路径过慢: {elapsed:.1f}s"
    assert daemon._proc.returncode == -signal.SIGKILL
```

---

## State of the Art

| Old Approach (Phase 5.A) | Current Approach (Phase 5.B) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `asyncio.create_subprocess_exec` 直接 spawn，无资源限制 | `SandboxRunner.spawn_with_limits` 抽象层 + `resource.setrlimit` baseline | 2026-05-17 | daemon 不能消耗超 manifest 声明的资源 |
| daemon 子进程可自由出网 | `AllowlistTransport` 应用层白名单 + manifest `sandbox.network: [...]` | 2026-05-17 | plugin 出站受控（v1 仅 httpx 路径） |
| invoke timeout 30s 单层防护 | 三层防护：invoke timeout / watchdog SIGTERM 3s grace SIGKILL / idle reaper 300s | 2026-05-17 | 资源超限 8s 内强杀；idle 自动回收 |
| manifest sandbox 段 5.A 解析不强制 | 5.B 全字段 validators + 真实落地消费 | 2026-05-17 | k8s 风格内存单位 + cgroups opt-in |
| daemon 继承全部主进程 env | strip-all + manifest `env_allowlist` opt-in | 2026-05-17 | 主进程 secrets 不泄漏给 plugin |

**Deprecated/outdated:**
- 5.A `daemon_client._build_env()` 直接 merge `os.environ` — 5.B 改为白名单过滤
- 5.A plugin daemon 内直接 `aiohttp.ClientSession()` — 5.B 鼓励用 `make_sandboxed_http_client()`（aiohttp 仍可用但不被白名单约束，警告日志）

---

## Open Questions

1. **CgroupsV2Sandbox 在 docker-compose 内能跑通吗？**
   - What we know: `systemd-run --user --scope` 需要 cgroup delegation；docker 默认未授权
   - What's unclear: 我们的 docker-compose 是否在 dev / 生产都用？生产 K8s 部署时 cgroup 是否已是 v2？
   - **Recommendation**: 5.B 默认 `use_cgroups: false`；CgroupsV2Sandbox 仅在 dev Linux 物理机 / 生产 K8s pod (cgroupsv2 + privileged) 启用；docker-compose 全栈跑测试时优雅降级到 PosixResourceSandbox

2. **Watchdog 频率 5s 在 100 daemon 场景下 OK 吗？**
   - What we know: `/proc/<pid>/status` read ≈ 100µs；100 daemon × 5s = 20 reads/s ≈ 2ms/s CPU
   - What's unclear: cgroups `memory.current` read 是否同样廉价？
   - **Recommendation**: 5.B 不优化；watchdog 单 task 串行扫所有 daemon；100+ daemon 场景留 Phase 6 marketplace 优化（如分 shard）

3. **AllowlistTransport 是否应该集成到 daemon_client 而非 plugin entry?**
   - What we know: 5.A daemon_client 暴露 invoke API，不知道 plugin 内部用什么 HTTP 库
   - What's unclear: 主进程能否注入 `httpx._transports.default.AsyncHTTPTransport` 全局 patch?
   - **Recommendation**: 5.B 走 plugin entry 显式注入（`make_sandboxed_http_client(_NETWORK_ALLOW)`）；全局 patch v2 再考虑（影响主进程其他 httpx 调用）

4. **`os.setsid()` 后 daemon stdin/stdout pipe 仍工作吗？**
   - What we know: setsid 让子进程脱离主进程会话；理论上 pipe 是 fd 级别不受影响
   - What's unclear: 某些 OS 上 setsid 后 controlling tty 丢失是否影响 stdin readline?
   - **Recommendation**: 5.B 集成测试 explicit cover：spawn daemon with setsid → warmup invoke → 验证 pipe 正常；macOS + Linux 都验证

---

## Validation Architecture

> **Note**: workflow.nyquist_validation 在 5.A init JSON 不存在 → 默认 false。**本节按 false 处理，不强制 Nyquist 采样检查**，但仍按 CLAUDE.md §2.2 三层测试严格规划。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3 + pytest-asyncio 0.24（5.A 已就绪） |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/platforms/sandbox/ -x` (单测 ~ < 5s) |
| Full suite command | `pytest tests/platforms/sandbox/ tests/platforms_integration/test_resource_limits.py tests/platforms_integration/test_network_allowlist.py tests/platforms_integration/test_watchdog_grace_period.py tests/platforms_integration/test_idle_reaper.py -v` (~ < 90s) |
| Linux-only command | 同上但 GitHub Actions ubuntu-latest 跑 — 触发 macOS 跳过的 enforcement test |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| PLUG-FW-09 | SandboxRunner Protocol + PosixResourceSandbox（cross-platform contract test） | unit | `pytest tests/platforms/sandbox/test_runner.py -x` | ❌ Wave 0 |
| PLUG-FW-09 | RLIMIT_AS / RLIMIT_CPU 真 enforcement | integration (Linux only) | `pytest tests/platforms_integration/test_resource_limits.py -v` (skip on macOS) | ❌ Wave 0 |
| PLUG-FW-10 | CgroupsV2Sandbox systemd-run + MemoryMax OOM | integration (Linux + systemd) | `pytest tests/platforms_integration/test_cgroups_v2_sandbox.py -v` (skip if not available) | ❌ Wave 0 |
| PLUG-FW-11 | AllowlistTransport 拦截 + 通过 | unit | `pytest tests/platforms/sandbox/test_network.py -x` | ❌ Wave 0 |
| PLUG-FW-11 | plugin daemon 实跑 AllowlistTransport（注入） | integration | `pytest tests/platforms_integration/test_network_allowlist.py -v` | ❌ Wave 0 |
| PLUG-FW-12 | SandboxWatchdog SIGTERM 3s grace → SIGKILL | integration | `pytest tests/platforms_integration/test_watchdog_grace_period.py -v` | ❌ Wave 0 |
| PLUG-FW-12 | IdleDaemonReaper 300s timeout auto-close | integration | `pytest tests/platforms_integration/test_idle_reaper.py -v` | ❌ Wave 0 |
| PLUG-FW-13 | SandboxConfig validators (memory / cpu / network / timeouts) | unit | `pytest tests/platforms/test_manifest_schema.py::TestSandboxConfig -x` | ⚠️ 5.A 部分存在（SandboxConfig 已建，validators 待加） |
| PLUG-03 | 集成：5.A acid test 在 sandbox 下仍通过（regression） | integration | `pytest tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py -v` | ✅ 5.A 5/5 pass |

### Sampling Rate

- **Per task commit:** `pytest tests/platforms/sandbox/ -x` (单 plan 内仅本 plan 修改的目录)
- **Per wave merge:** `pytest tests/platforms/ tests/platforms_integration/ -x` (含 5.A 5/5 acid test regression)
- **Phase gate:**
  - macOS local: 全 suite 绿（含 skip Linux-only enforcement tests）
  - Linux CI (GitHub Actions ubuntu-latest): 全 suite 绿 + Linux-only enforcement test 真跑（验证 RLIMIT 严格行为）
  - Phase 4 81 IM 测试 + Phase 5.A 162 platforms 测试 0 regression

### Wave 0 Gaps

- [ ] `backend/app/agent_builder/platforms/sandbox/` 目录创建（5.A 未存在）
- [ ] `backend/tests/platforms/sandbox/` 单测目录创建
- [ ] `backend/tests/platforms_integration/fixtures/sigterm_ignoring_daemon.py` — watchdog test 用 daemon fixture
- [ ] `backend/tests/platforms_integration/fixtures/network_test_daemon.py` — AllowlistTransport 集成测 daemon
- [ ] `backend/.github/workflows/linux-ci.yml` 或现有 CI workflow 加 `pytest -m linux_only` 步骤（如果 GitHub Actions Linux runner 已配，仅加 marker 即可）
- [ ] `pyproject.toml` 加 markers: `linux_only`, `cgroups_v2`, `sandbox_integration`

---

## Phase 拓扑建议

### 推荐 4-5 plans across 3-4 waves

**Wave 1 — Reading doc + schema 扩展（顺序硬性 gate）**
- `05b-01-PLAN.md` — Dify dify-plugin-daemon reading doc（Go 实现概念 → Python 借鉴点） + SandboxConfig 字段扩展 + Pydantic validators + manifest 解析消费链路 + 默认值 + tests/platforms/test_manifest_schema.py::TestSandboxConfig 单测
  - **要求**: CLAUDE.md §2.7 reading doc gate（reading doc 必须先于代码 commit）
  - **requirements**: PLUG-FW-13
  - **wave 1 单独** — 是后续 plan 的 schema 前置

**Wave 2 — 并行（PosixResourceSandbox + AllowlistTransport）**
- `05b-02-PLAN.md` — SandboxRunner Protocol + PosixResourceSandbox（baseline cross-platform） + parser.py（k8s 内存单位解析）+ 单测（macOS smoke + Linux integration）
  - **requirements**: PLUG-FW-09
  - **依赖**: 05b-01（SandboxConfig 字段）

- `05b-03-PLAN.md` — AllowlistTransport（httpx AsyncBaseTransport 子类）+ NetworkBlockedError + make_sandboxed_http_client helper + 单测 + huly_plugin entry 注入示例
  - **requirements**: PLUG-FW-11
  - **依赖**: 05b-01

**Wave 3 — Watchdog + cgroups + 集成（顺序，依赖 Wave 2）**
- `05b-04-PLAN.md` — SandboxWatchdog（asyncio task SIGTERM grace SIGKILL）+ IdleDaemonReaper（300s auto-close）+ PlatformDaemonClient 集成（_choose_runner, env_allowlist, last_invoke_at）+ 三层防护集成测
  - **requirements**: PLUG-FW-12
  - **依赖**: 05b-02 + 05b-03（runner + network）

- `05b-05-PLAN.md` — CgroupsV2Sandbox（Linux opt-in, systemd-run --user）+ is_cgroups_v2_available 检测 + 优雅降级到 PosixResourceSandbox + Linux CI 集成测
  - **requirements**: PLUG-FW-10
  - **可与 05b-04 并行**（独立路径）

**Wave 4 — E2E gate（regression + manifest 落地）**
- 不单独 plan；最后 wave 跑 full suite：
  - 5.A 5/5 acid test 在 sandbox 下仍 pass
  - 5.A 162 platforms 测试 0 regression
  - Phase 4 81 IM 测试 0 regression
  - Linux CI 上 Linux-only enforcement test 真跑

### 并行性分析

**安全并行的 plan 对**：
- 05b-02 ⊥ 05b-03（不同模块：sandbox/runner.py vs sandbox/network.py）
- 05b-04 ⊥ 05b-05（不同 runner：watchdog 整合 vs cgroups runner；都依赖 02+03 完成）

**必须串行**：
- 05b-01 → 02/03（schema 是前置）
- 02+03 → 04/05（runner + network 是依赖）

---

## Sources

### Primary (HIGH confidence)

- `/Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05b-plugin-sandbox/05b-CONTEXT.md` — 用户 4 area 决策
- `/Users/admin/ai/resume/interview/liuxin/agent-builder/docs/plans/2026-05-17-platform-plugin-framework-ADR.md` — ADR-001 §5 Daemon
- `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/platforms/daemon_client.py` — 5.A 已实现 467 行 PlatformDaemonClient（5.B 扩展对象）
- `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/platforms/manifest.py` — 5.A 已建 SandboxConfig 框架（5.B 加 validators）
- `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/tests/platforms_integration/test_fault_isolation.py` — 5.A 已建 fault isolation 测试（5.B regression baseline）
- Python 3.11 stdlib `resource` 官方文档 — RLIMIT_CPU / RLIMIT_AS / setrlimit
- Python 3.11 stdlib `signal` — SIGXCPU / SIGTERM / SIGKILL semantics
- httpx 0.28 官方文档 — [Transports](https://www.python-httpx.org/advanced/transports/) + AsyncBaseTransport API

### Secondary (MEDIUM confidence)

- [HTTPX Transports docs](https://www.python-httpx.org/advanced/transports/) — mounts dict + custom transport pattern（官方）
- [encode/httpx GitHub Transport API source](https://github.com/encode/httpx/blob/master/docs/advanced/transports.md) — AllowlistTransport 子类化模式参考
- [systemd-run cgroups v2 user scope](https://www.linuxoperatingsystem.net/advanced-systemd-resource-limits) — systemd-run --user --scope 标准用法（2026-05 文章）
- [cgroups(7) Linux man page](https://www.man7.org/linux/man-pages/man7/cgroups.7.html) — cgroup.controllers / cgroup.subtree_control 内核接口
- [Sandlock processes for AI sandboxing](https://multikernel.io/2026/03/14/introducing-sandlock/) — 2026-03 业界讨论 namespace + cgroups + seccomp 组合（v2 marketplace 参考）
- [Run a systemd container using cgroupv2 (GitHub Gist)](https://gist.github.com/pinkeen/bba0a6790fec96d6c8de84bd824ad933) — docker-compose cgroup delegation 配置参考

### Tertiary (LOW confidence)

- Dify dify-plugin-daemon Go 实现 — 仅作概念参考；本项目 Python only
- [bubblewrap + cgroups v2 deepagents-sandbox](https://github.com/john221wick/deepagents-sandbox) — bubblewrap 是 v2 选项，本 phase 不投入

---

## Metadata

**Confidence breakdown:**
- SandboxRunner Protocol + PosixResourceSandbox: HIGH — `resource.setrlimit` 是 Python stdlib 标准 API，行为差异（macOS vs Linux）官方文档明确
- CgroupsV2Sandbox: MEDIUM-HIGH — systemd-run --user --scope 是 systemd 标准用法；docker-compose 内 cgroup delegation 是已知坑（CI 跳过 + 文档 mitigation）
- AllowlistTransport: HIGH — httpx Transport API 0.16+ 稳定；mounts dict + AsyncBaseTransport 子类是官方推荐路径
- SandboxWatchdog + IdleDaemonReaper: HIGH — asyncio.create_task + while sleep + os.kill/os.killpg 是标准模式；grace period 3s 参考 systemd KillSignal 默认
- Pitfalls: HIGH — 8 个 pitfall 来自 stdlib 文档 + 5.A 实战经验 + cgroups v2 业界已知坑

**Research date:** 2026-05-17
**Valid until:** 2026-06-17（Python stdlib / httpx / systemd 都稳定，30 天有效）

---

## RESEARCH COMPLETE
