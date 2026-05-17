# Dify 阅读笔记 — Plan 05b-02 SandboxRunner Protocol + PosixResourceSandbox

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit `e7e6fe88`, local clone `/Users/admin/ai/ref/dify/repo/`)
> 同时参考: dify-plugin-daemon Go 仓库（仅概念，不拷代码）

## 项目概述（一句话）

Dify 是国内最成熟的 LLM 工作流编排平台（141k+ stars，2 年生产打磨），其 plugin daemon **完全用独立 Go 二进制实现**（dify-plugin-daemon 仓库），Python 主进程仅通过 HTTP API 与 daemon 交互，资源限制和进程隔离全在 Go 侧（cgroups + 自管理 process 池）。

## 技术栈对照（Dify Go + cgroups vs 本项目 Python + resource.setrlimit）

| 维度 | Dify | agent-builder Plan 05b-02 |
|------|------|---------------------------|
| **daemon 语言** | Go 二进制（独立进程 / 独立仓库） | Python（与主进程同语言 + 独立 process） |
| **daemon 协议** | HTTP REST + SSE 流（`PLUGIN_DAEMON_URL` 配置） | JSONRPC 2.0 over stdio（5.A `PlatformDaemonClient`） |
| **进程隔离** | Go daemon 内部进程池 + cgroups（Go 层调用 Linux cgroup syscall） | Python `resource.setrlimit` + `preexec_fn`（fork-exec 时注入 RLIMIT） |
| **资源限制实现** | cgroups v2 直写 / OOM Killer + Go runtime monitor | `RLIMIT_CPU` + `RLIMIT_AS` + `RLIMIT_NPROC` + `RLIMIT_NOFILE` 4 类 |
| **fork bomb 防护** | cgroups `pids.max` | `RLIMIT_NPROC=16` + `os.setsid()` 进程组隔离（killpg 整组） |
| **跨平台** | Linux only（生产 = Linux 容器） | macOS dev contract test + Linux prod enforcement（双轨） |
| **超时机制** | HTTP-level timeout（httpx.Timeout 600s）+ Go daemon 内部 context cancel | Python invoke_timeout（5.A 默认 30s）+ asyncio.wait_for + watchdog（Wave 3） |
| **观测点** | HTTPXClientInstrumentor + traceparent header | Python `_log.info("sandbox.spawned ...")` + structured fields |

**核心差异**：Dify **不在 Python 层**实现 plugin 资源限制 — 完全交给 Go daemon 进程；本项目因 v1 不引入 Go 二进制，必须在 Python 层用 stdlib `resource` 模块实现 baseline。

## 架构要点（plugin spawn 链路简图 / preexec_fn 注入点）

### Dify 架构（Python 主 ↔ Go daemon ↔ plugin worker）

```
Python 主进程 (Flask)
    │
    │ HTTP POST /plugin/{tenant}/management/install
    │ httpx.Client + plugin_daemon_inner_api_baseurl + X-Api-Key
    ▼
Go daemon (dify-plugin-daemon 独立二进制)
    │
    │ Go 层：os.Exec + cgroups v2 + Go runtime
    │ 自管理 worker pool + 资源限制
    ▼
plugin worker 进程（Python plugin SDK 跑用户代码）
```

**关键观察**（`api/core/plugin/impl/base.py:42-58`）:
- Python 主进程**完全不管**子进程生命周期 — 只是 HTTP client 调 Go daemon REST API
- `httpx.Client(limits=httpx.Limits(max_keepalive_connections=50))` 复用 50 个 keep-alive 连接（Phase 5.A 类似 `_pending` 路由表，但走 HTTP 而非 stdio）
- `plugin_daemon_request_timeout = httpx.Timeout(600.0)` — **超时是 HTTP 层**，不涉及 OS 信号

### 本项目架构（Python 主 ↔ Python daemon，preexec_fn 注入点）

```
Python 主进程 (FastAPI)
    │
    │ 5.A: asyncio.create_subprocess_exec(sys.executable, "-u", "-m", module_entry)
    │     ↓
    │ 05b-02 升级: PosixResourceSandbox.spawn_with_limits()
    │              ↓ loop.subprocess_exec(preexec_fn=partial(_apply_posix_limits, ...))
    ▼
Python daemon 子进程
    │ (fork 之后 / exec 之前在子进程上下文调:)
    │   resource.setrlimit(RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    │   resource.setrlimit(RLIMIT_AS, (memory_bytes, memory_bytes))
    │   resource.setrlimit(RLIMIT_NPROC, (16, 16))
    │   resource.setrlimit(RLIMIT_NOFILE, (256, 256))
    │   os.setsid()  # 让 daemon 成新进程组 leader (Pitfall 4 防 fork 子进程逃逸)
    ▼
exec sys.executable -u -m <module_entry>  → 受限 daemon 运行
```

**Pitfall 1 关键点（reading 后确认）**:
- macOS `RLIMIT_AS` / `RLIMIT_CPU` 在 Darwin kernel **不严格 enforce**（`RLIM_INFINITY` 默认且写入被忽略）→ macOS dev 仅做 contract test，Linux CI 跑真 enforcement
- `RLIMIT_NPROC` / `RLIMIT_NOFILE` 在 macOS + Linux **都严格** ✓

**Pitfall 4 关键点（reading 后确认）**:
- `os.setsid()` 让 daemon 成新进程组 → 后续 `os.killpg(pgid, SIGTERM)` 能精准 kill 整棵进程树（含 daemon fork 出的子进程），防 fork bomb 子进程逃逸
- Dify 因走 Go daemon + cgroups `pids.max`，无此问题；本项目必须 Python 层 setsid 兜底

## 可借鉴的设计模式（5 条 + 1 条偏离）

### 1. HTTP client 连接池复用（`api/core/plugin/impl/base.py:56-58`）

**Dify 模式**:
```python
_httpx_client: httpx.Client = get_pooled_http_client(
    "plugin_daemon",
    lambda: httpx.Client(limits=httpx.Limits(max_keepalive_connections=50, max_connections=100), trust_env=False),
)
```

**借鉴点**: 单一 module-level client 实例 + `trust_env=False`（防本机代理污染）+ keep-alive 池化。
**本项目应用**: Phase 5.B Plan 03（AllowlistTransport）会用 httpx.AsyncClient — 同样 module-level 单例 + `trust_env=False`，防 plugin daemon 误用 HTTP_PROXY 绕过白名单。

### 2. timeout 配置化 + 类型 cast 兜底（`api/core/plugin/impl/base.py:42-52`）

**Dify 模式**:
```python
_plugin_daemon_timeout_config = cast(
    float | httpx.Timeout | None,
    getattr(dify_config, "PLUGIN_DAEMON_TIMEOUT", 600.0),
)
if _plugin_daemon_timeout_config is None:
    plugin_daemon_request_timeout = None
elif isinstance(_plugin_daemon_timeout_config, httpx.Timeout):
    plugin_daemon_request_timeout = _plugin_daemon_timeout_config
else:
    plugin_daemon_request_timeout = httpx.Timeout(_plugin_daemon_timeout_config)
```

**借鉴点**: 多类型 timeout（None / float / httpx.Timeout）的归一化处理 + `getattr` 默认值兜底。
**本项目应用**: Wave 3 watchdog `timeout_invoke` / `timeout_idle` 同样支持 `int | None`，启动期 normalize 一次避免每次 invoke 重判类型。

### 3. RPC 透明传输 + 业务错误码（`api/core/plugin/entities/plugin_daemon.py` — `PluginDaemonInnerError` 模式）

**Dify 模式**: HTTP 层 transport error（连不通 daemon）抛 `PluginDaemonInnerError(code=-500, message="...")`；业务层 error 走 envelope `{error_type, message}` 字段。

**借鉴点**: 区分 transport-level error（连接 / 超时）vs application-level error（plugin 业务逻辑错），用不同异常类承载。
**本项目应用**: 5.A 已实现 `PluginDaemonExitedError`（transport / process exit）+ `PluginInvocationError`（业务 error envelope）；Plan 05b-02 仅扩展 `SandboxLimitExceeded` 给 Wave 3 watchdog 用，**不真 raise**（仅占位定义）。

### 4. trace 注入 + 防重复 header（`api/core/plugin/impl/base.py:125-148`）

**Dify 模式**:
```python
def _inject_trace_headers(self, headers: dict[str, str]) -> None:
    if not dify_config.ENABLE_OTEL: return
    # Skip if already present (case-insensitive check)
    for key in headers:
        if key.lower() == "traceparent": return
    with contextlib.suppress(Exception):
        traceparent = generate_traceparent_header()
        if traceparent: headers["traceparent"] = traceparent
```

**借鉴点**: trace 字段优雅降级 + 防重复（case-insensitive 检查）+ `contextlib.suppress` 防 trace 子系统挂掉影响主流程。
**本项目应用**: Phase 7 Run Viewer 给 sandbox.spawned 事件埋 trace_id 时同样模式（trace 是可观测性，不能阻塞主路径）。

### 5. 单一职责 client 类层级（`api/core/plugin/impl/plugin.py` `PluginInstaller(BasePluginClient)`）

**Dify 模式**: `BasePluginClient` 提供 `_request` / `_stream_request` / `_prepare_request` 通用方法 → 业务子类（`PluginInstaller` / `PluginAssetManager` / `PluginDebuggingClient`）只声明业务端点 + 类型化响应。

**借鉴点**: HTTP/RPC 层封装与业务端点解耦 — 基类负责重试 / trace / error envelope，子类专注业务字段。
**本项目应用**: 当前 Phase 5.A `PlatformDaemonClient` 是单类 — 待 Phase 6 marketplace 真上时再考虑拆 `BaseDaemonClient` + `IMDaemonClient` / `DocDaemonClient`。Plan 05b-02 不引入此分层（YAGNI）。

### 6. 偏离：本项目用 `preexec_fn` + `os.setsid()` 替代 cgroups（核心架构差异）

**Dify**: Go daemon 进程池在 Linux 直接调 cgroups v2 syscall — `unshare(CLONE_NEWPID)` + 写 `cgroup.subtree_control` → 隔离严格。

**本项目**: Python 主进程 spawn 同语言 daemon → 通过 `loop.subprocess_exec(preexec_fn=partial(_apply_posix_limits, cpu_seconds, memory_bytes))` 在 fork-exec 之间注入 4 类 RLIMIT + `os.setsid()` 进程组隔离 → baseline cross-platform 但 macOS 弱 enforcement（Pitfall 1）。

**为什么偏离**:
1. v1 zero-dep 优先（CLAUDE.md §3 锁定 Python 3.11+ stdlib）— 不引入 Go 二进制 / 不依赖 systemd
2. dev 体验：macOS 本地能跑 contract test（虽 enforcement 弱），CI 真 enforcement 在 Linux GitHub Actions ubuntu-latest
3. Wave 3 `CgroupsV2Sandbox`（Plan 05b-04）作为 Linux opt-in 升级路径（`sandbox.use_cgroups: true`）— 此时通过 Protocol 接口替换，daemon_client 逻辑零修改

## 与本项目的关系（Phase 5.B PosixResourceSandbox 字段命名 + RLIMIT 选型 + 默认值如何对齐 / 偏离）

| 决策 | Dify | 本 Plan 05b-02 选择 | 理由 |
|------|------|---------------------|------|
| **runner 接口** | Go HTTP client `BasePluginClient` | Python Protocol `SandboxRunner` + `async spawn_with_limits` | 与 5.A asyncio 路径一致；Protocol 让 Wave 3 cgroups 实现可直接替换 |
| **资源限制 API** | Go 层 cgroups | Python `resource.setrlimit` (POSIX stdlib) | 0 依赖 + macOS dev 友好 |
| **CPU 限制单位** | cgroups `CPUQuota=100%` | `RLIMIT_CPU` 累积秒数（5.A parser 已转换 `cpu_limit="2.0"` → 7200s） | RLIMIT_CPU 是累积，cgroups 是 quota — 不同语义，文档中显式说明（Plan 05b-01 parser 已注释） |
| **内存限制单位** | cgroups `MemoryMax=512M` | `RLIMIT_AS` bytes（5.A parser 已转换 `memory="512Mi"` → 536870912） | K8s 风格字符串 + property 派生 int（Plan 05b-01 已建） |
| **NPROC 默认值** | cgroups `pids.max=100` | `RLIMIT_NPROC=16`（硬编码 `_DEFAULT_NPROC_LIMIT`） | daemon 通常无需 fork；16 足够 thread pool；防 fork bomb 留余量 |
| **NOFILE 默认值** | （Go runtime 自管） | `RLIMIT_NOFILE=256`（硬编码 `_DEFAULT_NOFILE_LIMIT`） | daemon 通常 stdin/stdout/stderr + 少量内部 fd；256 足够防句柄泄漏 |
| **进程组隔离** | cgroups namespace | `os.setsid()` 让 daemon 成 session leader | 防 daemon fork 子进程逃逸（Pitfall 4） |
| **env 注入策略** | Go daemon 自管 env（受 manifest 控制） | merge `os.environ`（contract test 友好）；Wave 3 真 env_allowlist 过滤在 daemon_client 做 | Plan 05b-01 已建 `env_allowlist` 字段；本 plan 不消费（Wave 3 才接入） |
| **跨平台行为** | Linux only | macOS contract test only + Linux CI enforcement | Pitfall 1：macOS RLIMIT_AS/CPU 弱；测试用 `@pytest.mark.linux_only` + `@pytest.mark.skipif(sys.platform == 'darwin')` |

**字段命名对齐**:
- `cpu_seconds: int`（与 Dify cgroups CPUQuota 不同语义但本项目 stdlib 风格）
- `memory_bytes: int`（5.A parser `parse_memory()` 返回值类型）
- `env: dict[str, str] | None`（与 5.A `daemon_client.py:120` 签名完全一致 — 直接替换 `create_subprocess_exec` 时零兼容性问题）
- `cwd: str | None`（同上）

**核心 API 设计**（来源 5.A daemon_client 的可平滑升级路径）:
```python
# 5.A 现状（daemon_client.py:161-171）:
self._proc = await asyncio.create_subprocess_exec(
    sys.executable, "-u", "-m", self._module_entry,
    stdin=PIPE, stdout=PIPE, stderr=PIPE,
    env=merged_env, cwd=self._cwd,
)

# Wave 3 升级（仅 1 行替换）:
self._proc = await self._runner.spawn_with_limits(
    [sys.executable, "-u", "-m", self._module_entry],
    cpu_seconds=self._sandbox.cpu_limit_seconds,
    memory_bytes=self._sandbox.memory_bytes,
    env=merged_env, cwd=self._cwd,
)
# _runner 注入：PosixResourceSandbox() 或 CgroupsV2Sandbox()（基于 sandbox.use_cgroups）
```

## License 与 attribution（Dify AGPL-3.0 + Go vs Apache-2.0 + Python — 100% 独立创作）

**核心说明**:
- Dify 仓库 (`/Users/admin/ai/ref/dify/repo/`) 是 **AGPL-3.0** 许可
- 本项目 agent-builder 是 **Apache-2.0** 许可（与 flock fork 一致）
- **严禁拷贝 Dify 源码** — 仅借鉴**设计模式 / 命名规范 / 数据结构思路**

**本 Plan 与 Dify 的关系**:
- `SandboxRunner` Protocol — **本项目独立创作**，Dify 没有 Python Protocol 等价物（Dify daemon 全是 Go HTTP API）
- `PosixResourceSandbox` 实现 — **100% Python 独立创作**，借鉴 Dify "client 分层 + timeout 归一化 + trace 优雅降级" 设计哲学，但实现完全不同（cgroups Go vs resource.setrlimit Python）
- `_apply_posix_limits` preexec_fn — **本项目原创**，Dify 完全无此概念（Dify 不通过 fork-exec 注入 RLIMIT）
- `SandboxLimitExceeded` / `NetworkBlockedError` 异常占位 — **本项目原创**，Dify 用 HTTP error envelope 区分错误类型

**Attribution**: 所有借鉴点在源码 docstring 中显式注明"借鉴 Dify XXX 设计模式 - AGPL-3.0 不拷代码"，遵守 CLAUDE.md §2.7 reference-first 纪律 + Apache-2.0 兼容性要求。

---

**文档完成**: 此 doc 是 Plan 05b-02 第一个 commit（Task 0），后续 `feat(05b-02): ...` commit 必须在此之后（CLAUDE.md §2.7 reference-first 硬性 gate）。
