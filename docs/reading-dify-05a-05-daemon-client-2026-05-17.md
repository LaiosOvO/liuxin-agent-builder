# Dify 阅读笔记 — Plugin Daemon 通信协议

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit `c0bdd679`, local clone `/Users/admin/ai/ref/dify/repo/`)
> Stars: ~141k
> 关联仓库: https://github.com/langgenius/dify-plugin-daemon (Go 实现，仅看 README 概念，**不读源码避免 AGPL 沾染**)
>
> **License 严格 attribution**: Dify 是 **AGPL-3.0**，本项目 agent-builder 是 **Apache-2.0**（与 flock 一致）。
> 本笔记**仅借鉴设计模式 / 数据结构 / 边界考虑**，**严禁拷贝 Dify 源代码**到我们仓库；
> 5.A Plan 05 所有 `PlatformDaemonClient` / `capability_facades` / `MockPlatformPlugin` / `echo_daemon` 实现
> 均独立创作，仅在精神层面参考下述 Dify 模块。

---

## 项目概述（一句话）

Dify 是国内成熟的开源 AI agent + workflow 平台（141k stars），其 plugin 框架通过**独立 Go 进程 (`dify-plugin-daemon`) + gRPC/HTTP** 让第三方插件用 Python/Node 任意语言写，主进程 (Python FastAPI) 通过 HTTP 调用 daemon、daemon 启动 sandboxed plugin subprocess 跑业务代码。

---

## 技术栈（关键技术选择）

| 维度 | Dify 选择 | 5.A Plan 05 选择 |
| ---- | ---- | ---- |
| 主进程 ↔ daemon 通信 | HTTP REST API (`POST /plugin/{tenant_id}/management/install/...`) | **JSONRPC 2.0 over stdio** (本项目简化 — 内嵌 daemon 不需 HTTP) |
| daemon 进程语言 | Go 独立仓库 dify-plugin-daemon | **Python `python -u -m <module>` 子进程**（v1 简化；v2 可扩 Go/Node） |
| Request 编码 | JSON HTTP body | line-delimited JSON envelope |
| Response 类型化 | `PluginDaemonBasicResponse[T]` 泛型 BaseModel | dict 透传（v1 简化） |
| Error 协议 | `PluginDaemonError(error_type, message)` + `PluginDaemonInnerError(code, message)` | **JSONRPC 2.0 `error` 字段 `{code, message, data?}`** |
| Plugin install 进度 | `PluginInstallTask(status: pending/running/success/failed)` 异步 task | **v1 同步 invoke**（异步 install task 留 v2） |
| HTTP client pool | `httpx.Client` w/ `Limits(max_keepalive=50)` | asyncio.subprocess.PIPE（stdio 不需要 pool） |
| Process 生命周期 | daemon = 长进程（不重启）；plugin subprocess by daemon 管理 | **PlatformDaemonClient.start/close**；进程级 1:1（v1 不自动重启 — 5.B 加 restart policy） |
| Fault isolation | daemon crash → HTTP 500 + retry by HTTP client | **stdout EOF 检测 → 立即 fail 所有 pending future**（Pitfall 2 关键） |

**简化对比**：Dify HTTP-based daemon RPC（适合分布式 K8s 部署）；我们 5.A 内嵌 stdio JSONRPC（适合 monolith fastapi，1 plugin 1 进程，无 HTTP overhead）。

---

## 架构要点（核心架构模式）

```
┌─────────────────── Dify ──────────────────┐
│                                            │
│  FastAPI 主进程                            │
│    └─ BasePluginClient                     │
│         └─ httpx.Client (REST)             │
│              │ HTTP POST/GET               │
│              ▼                              │
│  dify-plugin-daemon (独立 Go 服务)         │
│    └─ PluginInstaller                      │
│         └─ subprocess.spawn(plugin)        │
│              ▼                              │
│  Plugin runtime (Python/Node SDK)          │
│    └─ tool/model/llm/agent... 各自实现      │
└────────────────────────────────────────────┘

┌──── agent-builder Plan 05/06 (本项目) ─────┐
│                                            │
│  FastAPI 主进程                            │
│    └─ PlatformDaemonClient                 │
│         └─ asyncio.create_subprocess_exec  │
│              │ stdin/stdout (line JSONRPC) │
│              ▼                              │
│  plugin daemon (Python 子进程)             │
│    └─ huly_plugin.py main()                │
│         └─ aiohttp → mock huly server      │
└────────────────────────────────────────────┘
```

**核心简化**：
- **去掉 daemon 中间层**：我们让 plugin 直接做 daemon（plugin = daemon）；Dify 是 plugin = daemon 管理的 subprocess。
- **去掉 HTTP**：stdio 比 HTTP 快 10x（无 TCP 握手 / HTTP header overhead）；单进程内嵌不需要网络穿透。
- **去掉 install task 异步**：plugin install 是文件系统操作（5.A discover() 启动期扫描），不需要 task queue。

---

## 可借鉴的设计模式（5 借鉴点，对应 Plan 05 落地）

### 借鉴点 #1: `PluginDaemonBasicResponse[T]` 泛型 → JSONRPC envelope.result 类型化思路

**Dify 源码**: `api/core/plugin/entities/plugin_daemon.py:23-30`

```python
class PluginDaemonBasicResponse[T: BaseModel | dict | list | bool | str](BaseModel):
    code: int
    message: str
    data: T | None = None
```

**借鉴**：每个 RPC 返回都通过统一 envelope 包装 + 类型化 result（泛型 T）。

**5.A Plan 05 落地**:
- 我们的 JSONRPC envelope 用 dict 透传 result（v1 简化，避免每个 capability 写 BaseModel）
- Capability facade 在调用端做 unmarshall（`result["plugin_name"]`, `result["native_id"]` → `MessageRef`）
- v2 升级路径：每个 method 定义 `pydantic.BaseModel` response schema → facade 反序列化更类型安全

**为什么不直接采纳泛型 BaseModel**：v1 plugin method 数量少（4 capability × 5 method ≈ 20 个）；每方法写一个 Response BaseModel 增加 ~200 行 boilerplate 但收益有限（runtime check 已经够）；v2 plugin 数量上去后再统一引入。

---

### 借鉴点 #2: `PluginDaemonError(error_type, message)` + `PluginDaemonInnerError(code, message)` → JSONRPC 2.0 error 字段对齐

**Dify 源码**: `api/core/plugin/entities/plugin_daemon.py:126-141`

```python
class PluginDaemonError(BaseModel):
    error_type: str
    message: str

class PluginDaemonInnerError(Exception):
    code: int
    message: str
```

**借鉴**：错误分两层（业务错 error_type 字符串 + 系统错 code 数字）；error_type 让客户端按字符串 dispatch，code 兼容标准协议。

**5.A Plan 05 落地**:
- **JSONRPC 2.0 标准 error 字段**: `{"code": <int>, "message": <str>, "data": <any>}`
- **code 约定**:
  - `-32601`: Method not found（JSONRPC 标准）
  - `-32602`: Invalid params（JSONRPC 标准）
  - `-32603`: Internal error（JSONRPC 标准）
  - `-32000` ~ `-32099`: 业务错误（plugin 自定义）
- **PluginInvocationError(error_payload: dict)** 在主进程 wrap dict → 业务 except 用 `e.error_payload["code"]` 分流
- echo_daemon fixture 实演 `-32601 Method not found` 路径

**关键区别**：Dify 错误有 `error_type` 字符串字段（如 `"InvokeAuthorizationError"`）让 HTTP client side mapping → Python 异常类；我们走 JSONRPC code 数字 + isinstance 子类型（已在 Plan 02 exceptions.py 定义 `PluginInvocationError` / `PluginDaemonExitedError`）。

---

### 借鉴点 #3: Dify daemon 跑独立 Go 进程 + HTTP/gRPC 通信 → 简化为 Python 子进程 + JSONRPC stdio（v1 决策）

**Dify 设计**: dify-plugin-daemon 是独立仓库（Go 实现），主 Python FastAPI 通过 httpx 调 daemon HTTP API；daemon 再 spawn plugin subprocess。

**为什么 Dify 这么设计**：
- 多语言 plugin（Go daemon 启动 Python/Node subprocess）
- 分布式部署（daemon 可独立 K8s pod，主进程 + daemon 网络通信）
- 进程级隔离（daemon crash 不影响主进程）

**5.A Plan 05 取舍**:
- v1 **Python only**（CONTEXT.md §Deferred Ideas 明确）
- 单 monolith 部署（daemon 与主进程同机）
- 不需要 HTTP overhead → stdio 更高效（约 10x latency 优势）
- daemon 进程 = plugin 进程（1:1，无中间层）— `plugins/huly/huly_plugin.py` 就是 daemon entry

**实现要点（Plan 05）**:
```python
asyncio.create_subprocess_exec(
    sys.executable, "-u", "-m", module_entry,  # "-u" = unbuffered，stdin/stdout 行级 flush
    stdin=PIPE, stdout=PIPE, stderr=PIPE,
    env=merged_env,  # 注入 HULY_ENDPOINT / AUTH_TOKEN 给 daemon
)
```

`-u` flag 关键 —— 否则 Python 默认 buffer stdout 64KB，JSONRPC response 不会立即返回主进程，导致 timeout。

---

### 借鉴点 #4: `PluginInstallTask` 异步进度（pending/running/success/failed）→ v1 同步 invoke（异步 task 留 v2）

**Dify 源码**: `api/core/plugin/entities/plugin_daemon.py:144-165`

```python
class PluginInstallTaskStatus(StrEnum):
    Pending = "pending"
    Running = "running"
    Success = "success"
    Failed = "failed"

class PluginInstallTask(BasePluginEntity):
    status: PluginInstallTaskStatus
    total_plugins: int
    completed_plugins: int
    plugins: list[PluginInstallTaskPluginStatus]
```

**借鉴**：plugin install 是长任务（下载 + 解压 + 验签 + 注册），用 task entity 持久化进度，client 轮询 status。

**5.A Plan 05 落地**:
- **v1 同步 invoke**: `await daemon.invoke("im", "send_card", **kwargs)` 直接 await response（30s timeout）
- **v2 异步 task pattern**: 适合 Plan 06+ HulyPlugin acid test 中长任务（如 batch sync 1000 employees），用 `daemon.invoke_async(task_id)` + 轮询 `daemon.poll_status(task_id)`
- 但 v1 仅需要 send_card 之类 < 1s 操作，没必要 task overhead

**为什么 v1 不引入 task**：plugin 操作 latency p99 < 2s（IM 卡片 / Doc 查询）；同步 RPC 更简单。Long-running ops 留 v2。

---

### 借鉴点 #5: dify-plugin-daemon 进程管理（spawn / restart on crash）→ v1 简化：crash 不自动重启（fault isolation 报错；5.B 加 restart policy）

**Dify 设计**（基于 dify-plugin-daemon Go README 概述，不读源码）:
- daemon 内部维护 plugin subprocess 池
- subprocess crash → daemon 自动 respawn（带 backoff）
- 主进程对 plugin install 无感知 daemon 内部进程切换

**5.A Plan 05 取舍**:
- v1 **crash 不自动重启**:
  - daemon 进程 crash → 主进程 `_read_loop` 检测 stdout EOF → 所有 pending future `set_exception(PluginDaemonExitedError)`
  - 调用方下一次 `invoke()` 触发 `await self.start()` 重新 spawn 新 daemon（test_invoke_after_close_starts_new 覆盖此场景）
  - 但 in-flight requests 都 fail —— 调用方需要 retry 业务（Phase 4 IM provider 已有 retry 模式可复用）
- **Pitfall 2 关键**: fault isolation 必须**快速失败**（< 2s），不能等 30s timeout
- 5.B 落地：daemon supervisor + restart policy + exponential backoff（不在本 plan scope）

**为什么 v1 简化**：
- 自动重启需要状态机（spawning / running / dying / dead），增加 ~200 LOC 代码 + 测试
- v1 huly acid test 只测 fault isolation（crash 应该 surface 给调用方），不测自动 recovery
- 5.B sandbox 时统一加 supervisor（与 cgroups / network policy 一起）

**Pitfall 2 实测要求**（Plan 05 必覆盖）:
```python
async def test_daemon_crash_fails_pending_future():
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=2.0)
    start = time.monotonic()
    with pytest.raises(PluginDaemonExitedError):
        await client.invoke("im", "crash")  # echo_daemon sys.exit(1)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0  # 不许走超时路径
```

---

## 与本项目的关系（如何应用到当前 plan）

| Dify 模块 | Plan 05 落地 module | 借鉴方式 |
| --- | --- | --- |
| `entities/plugin_daemon.py` PluginDaemonBasicResponse[T] | `backend/app/agent_builder/platforms/daemon_client.py` JSONRPC envelope | result 字段类型化（v1 dict 透传 / v2 BaseModel） |
| `entities/plugin_daemon.py` PluginDaemonError + Inner | `backend/app/agent_builder/platforms/exceptions.py` PluginInvocationError | error code/message 双字段 + isinstance 子类型分流 |
| `impl/base.py` BasePluginClient `_request` | `daemon_client.py` PlatformDaemonClient.invoke | 统一 envelope wrap + request_id 关联 future |
| `services/plugin/plugin_service.py` static methods | 已在 Plan 04 PlatformPluginRegistry classmethod-only 体现 | 进程级 singleton + tenant_id 第一参（已 Plan 04 实现） |
| dify-plugin-daemon README 概念 | `daemon_client.py` start/close lifecycle + read_loop | spawn / EOF 检测 / pending future 路由（自写实现） |

**编码原则**：
1. **JSONRPC 2.0 协议严格遵守**（`jsonrpc: "2.0"` / `id` / `method` / `params` / `result` / `error` 字段名 100% 标准）
2. **错误码 -32xxx 系列遵守 JSONRPC 标准**（-32601 method not found / -32602 invalid params / -32603 internal）
3. **stdio unbuffered**（`python -u`）+ line-delimited（`\n` 分隔单行 JSON）+ utf-8 编码
4. **stderr 独立 drain task**（防 buffer 满死锁 — Pitfall 8）
5. **Fault isolation 优先级 > Timeout**（daemon crash 不许走 30s 超时，必须立即 fail — Pitfall 2）
6. **Facade 层做 marshal/unmarshal**：dataclass → asdict() → JSONRPC params；result dict → dataclass 重建（bytes 字段需 base64 encode）

**License Attribution（再次强调）**：
- Dify AGPL-3.0 vs agent-builder Apache-2.0
- 本笔记 5 借鉴点 + 上述映射表 = **设计层面的精神参考**
- Plan 05 实现的 `PlatformDaemonClient` / `IMFacade` / `DocFacade` / `HRFacade` / `IdentityFacade` / `MockPlatformPlugin` / `echo_daemon` 全部独立创作
- 不引入 Dify Pydantic model（如 PluginDaemonBasicResponse）—— 我们用 stdlib dict + 自定义 PluginInvocationError 异常
- 不引入 Dify httpx HTTP client（我们用 asyncio.subprocess + stdio）
- 任何 Plan 05 commit 中**不出现 Dify 源代码片段**（即使是注释 attribution 形式也不行 —— 仅文档章节 reference 文件路径）

---

## 5 借鉴点摘要表（commit 时附此表给 reviewer 快速检索）

| # | Dify 源文件 | 借鉴模式 | Plan 05 落地 |
| --- | --- | --- | --- |
| 1 | `entities/plugin_daemon.py:23-30` PluginDaemonBasicResponse[T] | 泛型 envelope.result 类型化 | dict 透传 v1 + v2 升级到 BaseModel |
| 2 | `entities/plugin_daemon.py:126-141` PluginDaemonError + Inner | code + message 双字段错误协议 | JSONRPC 2.0 error 字段（code/message/data） |
| 3 | dify-plugin-daemon Go 独立进程 + HTTP | 简化为 Python 子进程 + JSONRPC stdio | asyncio.subprocess + line JSON + `python -u` unbuffered |
| 4 | `entities/plugin_daemon.py:144-165` PluginInstallTask 异步 | v1 同步 invoke（异步 task 留 v2） | await daemon.invoke(...) 直接返回 |
| 5 | dify-plugin-daemon spawn/restart 进程管理 | v1 crash 不自动重启（fault isolation 立即失败） | _read_loop 检测 EOF → _fail_all_pending(PluginDaemonExitedError) |

**Reading doc 完成 — Plan 05 Task 0 硬性 gate 通过；可以进入 Task 1 PlatformDaemonClient 实现。**
