# Phase 5.B: Plugin 沙箱 + Daemon 通信资源限制 - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning
**Authoritative spec:** ADR-001 (`docs/plans/2026-05-17-platform-plugin-framework-ADR.md`) §5 Daemon

<domain>
## Phase Boundary

Phase 5.A `PlatformDaemonClient` 已落 subprocess spawn + JSONRPC stdio + SIGKILL fault isolation（5/5 acid test pass）。

**Phase 5.B 扩展**：
- 资源限制 (CPU / memory) — `resource.setrlimit` baseline + Linux 可选 cgroups v2
- 网络白名单 — application-level httpx transport mount
- 三层超时强杀 — invoke timeout / 资源超限 SIGTERM→SIGKILL grace / idle daemon 回收
- manifest `sandbox` 段消费 — Pydantic schema + 启动期注入

**Phase 5.B 不做**（边界）：
- 真实平台接入（DocCapability / HRCapability 留 5.C / 5.D）
- 第三方 plugin 上传 / marketplace（Phase 6）
- 节点级沙箱（LangGraph node 跑主进程不变 — 沙箱**仅**作用于 plugin daemon）
- frontend manifest 渲染（5.C 起）

**项目本质（用户 2026-05-17 framing）**：agent-builder = **Dify-style PlatformPlugin 框架 + LangGraph 执行引擎**。Phase 5.B 强化 Dify-style 层的沙箱，LangGraph 节点执行不在沙箱范围内。

</domain>

<decisions>
## Implementation Decisions

### 资源限制机制选择

**双轨抽象**：sandbox_runner 抽象层 + 平台适配
- **macOS dev / cross-platform baseline**: `resource.setrlimit` (RLIMIT_CPU + RLIMIT_AS) — Python 标准库，零依赖
- **Linux 生产可选**: cgroups v2（systemd-run --user 或直接 cgroup write）— manifest 显式 `sandbox.use_cgroups: true` enables it
- **不 Docker per-plugin**（运维 5 容器/plugin 太重；考虑 Phase 6 marketplace 大量 plugin 场景再上 docker）
- 不选 nsjail / firejail（cross-platform 不友好）

**实现**：
```python
class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self, cmd: list[str], *, cpu_seconds: int, memory_bytes: int, env: dict
    ) -> asyncio.subprocess.Process: ...

# 实现
class PosixResourceSandbox: ...   # macOS + Linux fallback (resource.setrlimit preexec_fn)
class CgroupsV2Sandbox: ...       # Linux opt-in
```

### 网络白名单实现

**v1: application-level httpx hook** — plugin daemon 启动时 monkey-patch httpx 默认 transport
- manifest `sandbox.network: ["huly.example.com:443", "*.feishu.cn:443"]` 解析为 host + port 白名单
- daemon entrypoint 加载时构造 `httpx.AsyncClient(transport=AllowlistTransport(allow_list))`
- AllowlistTransport.handle_async_request: 检查 url.host:port 在 allow_list，不在则 raise NetworkBlockedError
- 旧 plugin 用 `urllib.request` / `requests` 会绕过 — 留 v2 解决（提示 plugin 用 httpx）

**v2 增强**（不做）: cgroups v2 network namespace / iptables / DNS 拦截

### 超时 + 强杀策略

**三层防护**:
1. **单 invoke timeout** (Phase 5.A 已实现，默认 30s) — 保留；超时 raise PluginInvocationTimeout
2. **资源超限 SIGTERM → SIGKILL grace**：
   - cgroups v2 OOM kill 自动（Linux）
   - PosixResourceSandbox RLIMIT_CPU 触发 SIGXCPU
   - 主进程 watchdog 任务每 5s 检查 cgroup memory_usage / cpu_stat
   - 超限：先发 SIGTERM 给 daemon → 等 3s grace → 仍存活 SIGKILL
3. **idle daemon 回收**：
   - 主进程跟踪 last_invoke_at
   - 后台任务每 60s 扫描；idle > 300s (5min) 自动 close + 下次调用 lazy re-spawn
   - manifest 可覆盖 `sandbox.timeout_idle`

### Manifest sandbox 段 schema

**与 Phase 5.A manifest 风格一致（Pydantic v2 + extra=forbid）**:

```yaml
sandbox:
  cpu_limit: "1.0"           # Docker style: float in cores; "0.5" = half core
  memory: "512Mi"            # k8s style: "Mi"/"Gi" 后缀 → bytes
  network: ["host:port"]     # list, exact match (v1 不支持通配符)
  timeout_invoke: 30         # seconds; per-invoke
  timeout_idle: 300          # seconds; idle daemon auto-close
  use_cgroups: false         # Linux opt-in; default false (走 setrlimit baseline)
```

**Pydantic validators**:
- cpu_limit: regex `^\d+(\.\d+)?$` → float
- memory: regex `^\d+(Ki|Mi|Gi|Ti)?$` → bytes
- network: list[str] — 每条 regex `^[a-z0-9.-]+:\d+$`
- timeouts: int positive

**默认值** (manifest 未声明 sandbox 段时):
- cpu_limit = "2.0"
- memory = "1Gi"
- network = []  # 空白名单 = 禁所有出站
- timeout_invoke = 30
- timeout_idle = 300
- use_cgroups = false

### Claude's Discretion

- watchdog 任务实现：单独 asyncio task vs 集成到 PlatformDaemonClient (推荐独立 task)
- AllowlistTransport 实现：基于 httpx Transport API vs 子类 AsyncHTTPTransport
- cgroups v2 检测：try import + check /sys/fs/cgroup/cgroup.controllers
- memory bytes 解析库：自写 (10 行) vs `humanfriendly`
- env 变量传递：白名单 list (manifest 声明) vs strip all (安全) — 推荐 strip all 默认 + manifest 白名单 opt-in
- structured log: `sandbox.limit_exceeded` 事件用 logger.warning + extra dict (CPU/memory)

</decisions>

<specifics>
## Specific Ideas

- Dify dify-plugin-daemon 用 Go + cgroups — 我们 Python + resource.setrlimit baseline（v1 zero dep）
- Phase 5.A `PlatformDaemonClient.cwd` 参数已实现 — daemon 可在专用工作目录运行
- 测试 acid test 已建 `tests/platforms_integration/` — Phase 5.B 新增 sandbox 限制测试在此目录
- macOS dev 资源测试可能因 setrlimit 限制不严格而 false-pass；CI 必须在 Linux 跑（GitHub Actions ubuntu-latest）
- 网络白名单测试：daemon 跑一个尝试连 example.com:80 (不在白名单) 的 plugin，断言 NetworkBlockedError raise
- 用户 2026-05-17 framing："基于类似 Dify 的 LangGraph" — 沙箱仅 plugin daemon，LangGraph 节点仍在主进程内

</specifics>

<deferred>
## Deferred Ideas

- Docker container per plugin (Phase 6 marketplace 大量 plugin 场景才需要)
- cgroups v1 兼容（生产 Linux 都已是 cgroups v2，v1 不投入）
- 网络白名单 v2: iptables / nftables / namespace 隔离
- Plugin 间 RPC（plugin A 调 plugin B）— v2 plugin marketplace 接力
- Plugin hot reload / SIGHUP — v2
- LangGraph node 沙箱（节点跑用户代码）— **不属于 5.B**，是 plugin 跑用户代码场景的另一独立 phase（v3）

</deferred>

---

*Phase: 05b-plugin-sandbox*
*Context gathered: 2026-05-17*
