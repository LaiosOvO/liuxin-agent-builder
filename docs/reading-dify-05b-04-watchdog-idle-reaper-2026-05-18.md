# Dify 阅读笔记 — Plugin Watchdog / Idle Reaper / 生命周期防护

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (commit e7e6fe88, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> 阅读范围: api/services/plugin/plugin_service.py + api/core/plugin/impl/{base.py, plugin.py}
> 关联 plan: Phase 5.B Plan 05b-04 (SandboxWatchdog + IdleDaemonReaper + daemon_client 集成)

---

## 项目概述

Dify 是 LLM 应用编排平台，2 年开源 + 141k stars + 数百贡献者。Plugin 子系统在 v0.15 之后从 in-process Python 调用重构为**独立 Go daemon 进程**（`dify-plugin-daemon` 项目），主 Python 进程通过 HTTP RPC 调用。

## 技术栈对照

| 关注点 | Dify 实现 | 本项目（agent-builder）实现 |
| ---- | ---- | ---- |
| **进程隔离** | 独立 Go daemon 进程（外部部署，docker compose 单容器跑所有 plugin） | Python `asyncio.subprocess` 每 plugin 1 个 daemon 进程，主进程 stdio JSONRPC |
| **资源限制** | Go daemon 内嵌 cgroups v2（Linux only）— 调度由 Go 侧管 | Python `resource.setrlimit` baseline + 主进程 asyncio task watchdog 软兜底（Plan 05b-04） |
| **超时管理** | 主进程 httpx 请求 timeout=600s（`plugin_daemon_request_timeout`） | 三层：invoke timeout (5.A) + watchdog grace SIGTERM→SIGKILL (5.B-04) + idle reaper (5.B-04) |
| **生命周期** | install/uninstall HTTP API → Go daemon 内进程管理 | Python 主进程 spawn/close + watchdog asyncio task + idle reaper asyncio task |
| **OOM 防护** | cgroups OOMKilled signal（Linux 内核） | watchdog 每 5s 读 `/proc/<pid>/status` VmRSS，超限 SIGTERM→SIGKILL grace |
| **kill 选型** | docker container kill（kills 整个 cgroup） | `os.killpg(os.getpgid(pid), SIGTERM)` 整组 kill（防 fork bomb 逃逸） |

## 架构要点

### 三层防护层级（本项目设计 vs Dify 比对）

```
┌────────────────────────────────────────────────────────────────┐
│             主进程（Python asyncio event loop）              │
├────────────────────────────────────────────────────────────────┤
│   Layer 1: invoke timeout (5.A asyncio.wait_for)              │
│     ├─ 默认 30s / fault isolation test 用 2.0s                 │
│     └─ daemon 正常活但慢 → asyncio.TimeoutError                │
├────────────────────────────────────────────────────────────────┤
│   Layer 2: watchdog grace (5.B Plan 05b-04 新加)              │
│     ├─ asyncio task 每 5s 读 /proc/<pid>/status VmRSS         │
│     ├─ 超 memory_limit_bytes:                                 │
│     │    1. on_violation callback → _fail_all_pending          │
│     │       (主 invoke 立即 raise SandboxLimitExceeded)        │
│     │    2. os.killpg(pgid, SIGTERM) 整组发                    │
│     │    3. await sleep(3s grace)                              │
│     │    4. os.kill(pid, 0) 探活 → ProcessLookupError 退出     │
│     │    5. os.killpg(pgid, SIGKILL) 强杀                      │
│     └─ Pitfall 4 防护：killpg 整组 kill 防 fork bomb 逃逸      │
├────────────────────────────────────────────────────────────────┤
│   Layer 3: idle reaper (5.B Plan 05b-04 新加)                 │
│     ├─ asyncio task 每 60s 扫所有 active daemon                │
│     ├─ now (time.monotonic) - daemon.last_invoke_at > 300s     │
│     │   AND daemon._pending 为空（无活跃 invoke）              │
│     │   → daemon.close() 回收（下次 invoke 触发 lazy re-spawn）│
│     └─ Pitfall 6 防护：跳过 _pending 非空，防与活跃 invoke 竞争 │
└────────────────────────────────────────────────────────────────┘
```

### Dify 对照层级（仅 1 层 client-side timeout）

```
┌────────────────────────────────────────────────────────────────┐
│           Dify Python 主进程（仅 HTTP client）                 │
├────────────────────────────────────────────────────────────────┤
│   Layer A: HTTP timeout (httpx)                                │
│     ├─ plugin_daemon_request_timeout = httpx.Timeout(600.0)    │
│     └─ daemon 慢 → httpx.TimeoutException                      │
├────────────────────────────────────────────────────────────────┤
│   ──────── Go daemon 进程边界 ────────                         │
├────────────────────────────────────────────────────────────────┤
│   Layer B: cgroups v2 (Linux only, Go daemon 管)               │
│     ├─ memory.max → OOMKilled signal                           │
│     └─ pids.max → fork bomb 防护                                │
└────────────────────────────────────────────────────────────────┘
```

**核心差异**: Dify 把进程隔离 + 资源限制全下沉 Go daemon，Python 主进程只是 HTTP 客户端。我们的项目坚持 Python-only 栈（CLAUDE.md §3 锁定），所以 watchdog / idle reaper 必须在 Python 主进程 asyncio task 实现。

## 可借鉴的设计模式

### 1. HTTP client 长 timeout（600s）作为外层兜底

**Dify 文件**: `api/core/plugin/impl/base.py:42-52`

```python
_plugin_daemon_timeout_config = cast(
    float | httpx.Timeout | None,
    getattr(dify_config, "PLUGIN_DAEMON_TIMEOUT", 600.0),
)
plugin_daemon_request_timeout: httpx.Timeout | None
if _plugin_daemon_timeout_config is None:
    plugin_daemon_request_timeout = None
...
```

**借鉴**: Dify 主进程的 600s timeout 是非常宽松的（10 分钟），证明其依赖 Go daemon 内部 cgroups 兜底。我们 Layer 1 invoke timeout 默认 30s 比 Dify 严格 20x，因为我们没有 cgroups 强制路径（除非 use_cgroups=True opt-in）。

### 2. uninstall 显式生命周期 API（不依赖 GC）

**Dify 文件**: `api/services/plugin/plugin_service.py:516-584`

```python
def uninstall(tenant_id: str, plugin_installation_id: str) -> bool:
    # Get plugin info before uninstalling to delete associated credentials
    ...
    return manager.uninstall(tenant_id, plugin_installation_id)
```

**借鉴**: Dify 强制显式 uninstall API（而非 GC 触发）。我们 IdleDaemonReaper 走同样思路：**显式 close() 后再 lazy re-spawn**，避免依赖 Python GC 不确定 destructor 时机；reaper 主动调 `daemon.close()`，不等 `__del__`。

### 3. trust_env=False 切断隐式代理旁路

**Dify 文件**: `api/core/plugin/impl/base.py:56-58`

```python
_httpx_client: httpx.Client = get_pooled_http_client(
    "plugin_daemon",
    lambda: httpx.Client(limits=httpx.Limits(...), trust_env=False),
)
```

**借鉴**: `trust_env=False` 防 HTTP_PROXY / HTTPS_PROXY env 隐式注入。我们 Pitfall 8 `_build_filtered_env` 借同样思路 — strip-all-allowlist 默认拒所有 env，manifest 显式 opt-in，**绝不传 HTTP_PROXY**（即使 plugin 想要也必须显式加 allowlist）。

### 4. 池化 HTTP client（限连接数防 socket 泄漏）

**Dify 文件**: `api/core/plugin/impl/base.py:56-58`

```python
httpx.Client(limits=httpx.Limits(max_keepalive_connections=50, max_connections=100), trust_env=False)
```

**借鉴**: Dify max_connections=100 上限。我们的 daemon 通信走 stdio 不是 HTTP，所以这一点直接借鉴到 5.B Plan 05b-03 已落的 AllowlistTransport（`make_sandboxed_http_client` 复用同样的连接池限制思路）。watchdog/reaper 本身不需要 HTTP client。

### 5. install_task 异步状态追踪（生命周期事件埋点）

**Dify 文件**: `api/services/plugin/plugin_service.py:238-269`

```python
def fetch_install_tasks(tenant_id, page, page_size) -> Sequence[PluginInstallTask]: ...
def fetch_install_task(tenant_id, task_id) -> PluginInstallTask: ...
def delete_install_task(tenant_id, task_id) -> bool: ...
```

**借鉴**: Dify 显式 task 状态机（install/running/failed/done）便于运维观测。我们的 watchdog/reaper 不做异步 task DB 持久化（v1 不需要），但**借鉴 structured log 思路**：

- `sandbox.limit_exceeded` event — watchdog 检测超限时
- `sandbox.force_kill` event — SIGTERM grace 失败 SIGKILL 时
- `sandbox.idle_reaped` event — reaper close 时

让运维 grep log 重建生命周期。

### 6. systemd KillSignal/TimeoutStopSec 默认值参考

**外部资料**（非 Dify code）: systemd man pages
- `KillSignal=SIGTERM`（默认）
- `TimeoutStopSec=90s`（默认服务）/ `DefaultTimeoutStopSec=10s`（user 默认）

**借鉴**: 我们的 `grace_period=3.0s` 比 systemd 短 30x，理由：
- plugin daemon 进程**预期**响应 SIGTERM 快（aiohttp / httpx 都有 graceful shutdown hook，< 1s）
- 3s 给足 hook 执行时间，但不让 RSS 持续增长造成 OOM 主进程
- 与 Docker 默认 `--stop-timeout=10s` 偏短，但 Docker 是面向陌生 image 的，我们的 daemon 是自家代码可控

## 与本项目的关系

### Pitfall 4 防护（fork bomb 进程组逃逸）

**文件**: `backend/app/agent_builder/platforms/sandbox/watchdog.py` (本 plan 新建)

```python
import os
import signal

# WRONG: 仅 kill 单进程，daemon fork 出的子进程逃逸
# os.kill(pid, signal.SIGTERM)

# RIGHT: kill 整个进程组（Plan 05b-02 PosixResourceSandbox 已 setsid 让 daemon 成为 pgid leader）
os.killpg(os.getpgid(pid), signal.SIGTERM)
```

**依赖关系**: 必须 Plan 05b-02 PosixResourceSandbox 的 `os.setsid()` 已经让 daemon 成为新 session leader（已落实，详见 `runner.py:_apply_posix_limits`）。

### Pitfall 5 防护（on_violation 顺序）

**文件**: `backend/app/agent_builder/platforms/sandbox/watchdog.py` + `daemon_client.py`

```python
# WRONG: 先 SIGTERM 让 daemon 立刻死，pending invoke 收到 stdout EOF → raise PluginDaemonExitedError
# 而不是 SandboxLimitExceeded — 类型不对，错误信号不准

# RIGHT: on_violation callback 先执行，主 invoke 立即 raise SandboxLimitExceeded
self._on_violation(reason)  # → _fail_all_pending(SandboxLimitExceeded(...))
os.killpg(os.getpgid(pid), signal.SIGTERM)  # 然后再 kill
```

### Pitfall 6 防护（idle reaper 与活跃 invoke 竞争）

**文件**: `backend/app/agent_builder/platforms/sandbox/idle_reaper.py` + `daemon_client.py`

```python
# WRONG: 用 time.time() — NTP 校正可能让 last_invoke_at 突然变小，误判 idle
# 或者: 不检查 _pending — 活跃 invoke 进行中被 close 导致 future 异常

# RIGHT: time.monotonic() + skip if _pending 非空
now = time.monotonic()  # 不受 NTP 影响
for daemon in get_daemons():
    if daemon._proc is None or daemon._pending:  # 跳过未启动 / 活跃 invoke
        continue
    if now - daemon.last_invoke_at > timeout_idle:
        await daemon.close()  # close 失败 swallow，reaper 不死
```

**daemon_client 配合**: `last_invoke_at` 在 `invoke()` 的 `finally` 块更新（不是 try 内）— 写在 try 内会因为 exception 不更新；finally 保证无论 success/exception 都刷新时间戳。

### Pitfall 8 防护（env_allowlist strip-all）

**文件**: `backend/app/agent_builder/platforms/daemon_client.py:_build_filtered_env`

```python
_SAFE_BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "PYTHONPATH", "PYTHONUNBUFFERED")
_FORBIDDEN_PREFIXES = ("AGENT_BUILDER_", "INTERNAL_", "HMAC_", "DATABASE_", "REDIS_", "SMTP_")
_FORBIDDEN_EXACT = ("HMAC_SECRET", "DATABASE_URL", "REDISL_URL", "OPENAI_API_KEY")
```

**借鉴 Dify trust_env=False 思路**: 即使 plugin 作者在 manifest `env_allowlist` 里写 `HMAC_SECRET`，我们也拒绝（FORBIDDEN_EXACT 黑名单覆盖）+ 记 warning log。**永远不允许通过 env_allowlist 漏出**。

### 5.A daemon_client 兼容性策略

**文件**: `backend/app/agent_builder/platforms/daemon_client.py`

```python
def __init__(self, ..., sandbox_config: SandboxConfig | None = None, ...):
    self._sandbox_config = sandbox_config
    self._watchdog: SandboxWatchdog | None = None
    self.last_invoke_at: float = 0.0  # public for reaper

async def start(self):
    ...
    if self._sandbox_config is not None:
        # 5.B 沙箱路径：sandbox runner + watchdog
        runner = self._choose_runner()
        self._proc = await runner.spawn_with_limits(cmd, ...)
        # 仅在沙箱路径起 watchdog（5.A 老路径不设 setsid，watchdog killpg 会误杀整个主进程）
        self._watchdog = SandboxWatchdog(self._proc.pid, ...)
        self._watchdog.start()
    else:
        # 5.A 兼容路径（不启动 watchdog）
        self._proc = await asyncio.create_subprocess_exec(...)
```

**关键约束**: 5.A 11 个既有测试**全部不传** `sandbox_config` → 全部走老路径 → 0 regression。这是 Plan 05b-04 必须坚持的设计原则。

## License

Dify 是 **AGPL-3.0**，本项目是 **Apache-2.0**。本 reading doc 仅借鉴**设计哲学**（trust_env=False / uninstall 显式 API / 池化 HTTP client / structured log event）和**外部 systemd 默认值数据点**。

**watchdog.py / idle_reaper.py / daemon_client.py 修改 100% 独立创作**，不拷贝任何 Dify 源代码。Dify 的实现（Go daemon）跟我们（Python asyncio task）技术栈完全不同，所以也没有可拷的余地。

---

*Plan 05b-04 first commit — CLAUDE.md §2.7 reading-doc gate*
*Authored: 2026-05-18*
