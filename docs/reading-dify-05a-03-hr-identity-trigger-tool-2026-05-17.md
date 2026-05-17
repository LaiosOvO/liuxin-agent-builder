# Dify 阅读笔记 — Trigger / Tool Capability 模式（Plan 05a-03 借鉴源）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify （commit `e7e6fe88` — local clone `/Users/admin/ai/ref/dify/repo/`）
> Stars: ~141k
> 适用范围: 05a-03 Plan — HR / Identity / Trigger / Tool 四个 Capability Protocol 设计

---

## License Attribution

Dify 是 **AGPL-3.0**，本项目 agent-builder 是 **Apache-2.0**。本文档严格遵循 CLAUDE.md §2.7 规则：

- **不直接拷贝**任何 Dify 源代码到本项目
- **仅借鉴**：设计模式 / 数据结构 / Capability 边界划分思路
- 所有最终落到 `backend/app/agent_builder/platforms/capabilities/` 的实现皆为**重新独立创作**（Python typing.Protocol + dataclass 风格，与 Dify Pydantic BaseModel 不同写法）

---

## 项目概述（一句话）

Dify 是国内最成熟的 AI agent / 工作流开源平台，其 Plugin 体系按 capability category（Tool / Model / Endpoint / Trigger / Datasource / Agent）切分 — 每类 capability 由独立 declaration entity + provider entity + invocation manager 组成。

## 技术栈（关键技术选择）

- **声明层**：Pydantic v2 `BaseModel` + YAML 配置（每 capability 一个 schema 文件）
- **运行时层**：每 capability 一个 `Tool` / `EventHandler` / `Endpoint` 类
- **dispatch 层**：`PluginXxxManager` 单例（PluginToolManager / PluginTriggerManager 等）通过 plugin daemon 调子进程
- **Endpoint 协议**：HTTP webhook（plugin 声明 path + method，dify 主进程注册 Flask route）
- **Trigger 协议**：subscribe + endpoint + event dispatch（plugin daemon 收 webhook → 反推 dify 主进程）

---

## 架构要点（核心架构模式 + 简图）

### Dify Plugin Capability 三层分层

```
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 1: Declaration (YAML / Pydantic Model)                        │
│  - PluginDeclaration (plugins/{tools, triggers, endpoints, ...})    │
│  - ToolProviderEntity / TriggerProviderEntity / EndpointDeclaration │
│  - 声明 capability 的存在 + parameter schema + credentials schema  │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ install / discover
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 2: Provider Entity (Runtime)                                  │
│  - ToolProviderEntityWithPlugin: tools[] + credentials              │
│  - TriggerProviderEntity: subscription_schema + events[]            │
│  - 持 plugin_id + 运行时凭据                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ invoke
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 3: Invocation Manager                                         │
│  - PluginToolManager.invoke(tenant_id, tool_provider, tool_name,    │
│                              credentials, tool_parameters)          │
│  - PluginTriggerManager.subscribe / unsubscribe / dispatch_event    │
│  - 通过 plugin daemon JSONRPC over stdio 调子进程                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Trigger 子系统数据流

```
plugin daemon ── HTTP webhook (gen URL via endpoint) ──→ dify endpoint
                                                              ↓
                                                       dispatch event to
                                                       workflow runtime
```

`TriggerProviderEntity` 含 `subscription_schema` + `subscription_constructor` + `events[]`，每 event 用 `EventEntity` 描述 payload schema。这是 push event 主动触发 workflow 的入口。

### Tool 子系统数据流

```
LLM node ── invoke tool ──→ PluginToolManager.invoke
                                  ↓
                          JSONRPC over stdio
                                  ↓
                          plugin daemon (python)
                                  ↓
                          tool implementation
                                  ↓
                          yield ToolInvokeMessage[]  (流式返回)
```

`ToolEntity` 含 `parameters: list[ToolParameter]` + `output_schema: Mapping[str, object]`（output_schema 是 dict 直接传 — 不强类型化，给 plugin 自由）。

---

## 可借鉴的设计模式（5+ 借鉴点 — 每条对应 5.A target）

### 1. PluginCategory 枚举 → 5.A `capabilities: list[Literal[...]]`

**Dify 源文件**：`api/core/plugin/entities/plugin.py:62-68`

```python
class PluginCategory(StrEnum):
    Tool = auto()
    Model = auto()
    Extension = auto()
    AgentStrategy = "agent-strategy"
    Datasource = "datasource"
    Trigger = "trigger"
```

**借鉴模式**：每 plugin 通过 enum 显式声明所属 capability category；启动期 discover 时按 category 路由到对应 manager。

**应用到 5.A Plan 03**：HRCapability / IdentityCapability / TriggerCapability / ToolCapability 在 `platforms/capabilities/__init__.py` 通过 `Literal["im","doc","hr","identity","trigger","tool"]` 集中枚举（manifest.yaml `capabilities` 字段）。Dify 用 StrEnum，我们用 Literal — 更轻量。

---

### 2. PluginToolProviderEntity 三段式 → 5.A ToolCapability.list_tools / invoke_tool

**Dify 源文件**：`api/core/plugin/entities/plugin_daemon.py:43-46`

```python
class PluginToolProviderEntity(BaseModel):
    provider: str
    plugin_unique_identifier: str
    plugin_id: str
    declaration: ToolProviderEntityWithPlugin  # 含 tools[] + credentials_schema
```

**借鉴模式**：plugin 不直接暴露 tool 列表给主进程，而是 wrapper 在 `ProviderEntity.declaration` 中 — 主进程通过 `list_tools()` 获取 declaration，再按需 `invoke_tool(name, args)`。这种 "declaration + invocation 分离" 让 plugin daemon 可懒加载 tool 实现。

**应用到 5.A Plan 03**：`ToolCapability` Protocol 含 `list_tools()` → `list[ToolSpec]` + `invoke_tool(tool_name, arguments)` → `ToolInvocationResult`。`ToolSpec.input_schema: dict[str, Any]` 直接复用 JSON Schema dict（不强类型化 — 与 Dify ToolEntity.output_schema 同思路）。

---

### 3. TriggerProviderEntity subscription + events → 5.A TriggerCapability.subscribe_events + verify_event_signature

**Dify 源文件**：`api/core/trigger/entities/entities.py:138-152` + `api/core/plugin/entities/endpoint.py:12-23`

```python
class TriggerProviderEntity(BaseModel):
    identity: TriggerProviderIdentity
    subscription_schema: list[ProviderConfig]
    subscription_constructor: SubscriptionConstructor | None
    events: list[EventEntity]

class EndpointDeclaration(BaseModel):
    path: str
    method: str  # HTTP method enum
    hidden: bool = False
```

**借鉴模式**：trigger 通过 HTTP webhook 接事件，每 endpoint 声明 `path + method`（HTTP method 是 plugin 自己声明，dify 主进程仅注册 Flask route）。事件订阅有 `subscription_schema`（plugin 收什么 event 类型）+ `events: list[EventEntity]`（每 event 的 payload schema）。

**应用到 5.A Plan 03**：`TriggerCapability` Protocol 含 `subscribe_events(event_types) -> AsyncIterator[TriggerEvent]`（async generator — pull 而非 push 给主进程，避免 Dify 那套 Flask route 注册的复杂）+ `verify_event_signature(headers, body) -> bool`（webhook / WS 签名校验，Phase 5.A 仅留 Protocol，实现留 Phase 5.D+）。我们的 `TriggerEvent` dataclass 比 Dify EventEntity 简化（只含 event_type / payload / occurred_at / source_extras 四字段，YAGNI）。

---

### 4. ToolEntity.parameters + output_schema：JSON Schema dict 直传 → 5.A ToolSpec.input_schema

**Dify 源文件**：`api/core/tools/entities/tool_entities.py:411-419`

```python
class ToolEntity(BaseModel):
    identity: ToolIdentity
    parameters: list[ToolParameter] = Field(default_factory=list)
    description: ToolDescription | None = None
    output_schema: Mapping[str, object] = Field(default_factory=dict)  # ← dict 直传，不强类型化
```

**借鉴模式**：output_schema 用 `Mapping[str, object]` 直传 — 让 plugin 开发者自由选择是 OpenAPI / JSON Schema / 自定义格式；主进程不解析。

**应用到 5.A Plan 03**：`ToolSpec` dataclass 含 `input_schema: dict[str, Any]` + `output_schema: dict[str, Any] | None`（output 可空 — 部分 tool 不需要严格 schema）。LLM 节点（Phase 5.D 起）调 `tool_call_function` 时直接把这两个 dict 喂给 LLM function calling format（OpenAI / Anthropic）。

---

### 5. PluginDaemonBasicResponse 错误码模式 → 5.A ToolInvocationResult success/error

**Dify 源文件**：`api/core/plugin/entities/plugin_daemon.py:23-29`

```python
class PluginDaemonBasicResponse[T: BaseModel | dict | list | bool | str](BaseModel):
    code: int
    message: str
    data: T | None = None
```

**借鉴模式**：plugin daemon 所有返回值有统一 envelope — `code != 0 = error`，`data = None` 时 message 含错误信息。这让主进程统一处理 plugin 错误（log + fallback）。

**应用到 5.A Plan 03**：`ToolInvocationResult` dataclass 含 `success: bool` + `result: dict | None` + `error_message: str | None`。成功时 `result` 有值；失败时 `success=False + error_message` 有值。比 Dify generic envelope 简化 — 不用泛型（YAGNI v1）。

---

### 6. Dify 无 HR / Identity capability（新疆域）

**关键差异**：Dify 是 AI agent + workflow 平台，**没有 HR / Identity 概念**。

- Dify 通过 OAuth + JWT 自己管 user identity（`api/models/account.py`），不抽象为 capability
- Dify 没有 HR 模块（员工 / 部门 / 假期）

**为什么 5.A 需要**：本项目是企业内 workflow 平台（HR 离职预置模板 / 部门审批链是核心场景）；Huly platform spike 验证了 HR 是首要 capability（Huly hr plugin index.ts 已确认）。Phase 5.D `dept:研发部` 表达式解析必须有 `HRCapability.resolve_department_members(expression)` 才能落地。

**应用到 5.A Plan 03**：HRCapability / IdentityCapability **完全是新疆域** — 设计参考 Huly platform spike 报告 + ADR-001 §3.3/§3.4，不直接借鉴 Dify。

- HRCapability 8 method（list_employees / get_employee / list_departments / `resolve_department_members(expression)` / list_leave_requests / create_leave_request）
- IdentityCapability 3 method + `is_source_of_truth: bool` flag（区分 Huly = True vs Phase 4 IM provider = False，决定 sync 方向）
- IdentityCapability `watch_user_changes()` 用 async generator 模式（与 TriggerCapability.subscribe_events 同 pattern — 长连接 push）

---

## 与本项目的关系（如何应用到 Plan 05a-03）

### 文件映射

| Plan 05a-03 产物 | Dify 参考点 | 关系 |
|---|---|---|
| `capabilities/hr.py` | (无 Dify 参考) | 完全新设计（参考 Huly spike + ADR §3.3）|
| `capabilities/identity.py` | (无 Dify 参考) | 完全新设计（参考 ADR §3.4）|
| `capabilities/trigger.py` | TriggerProviderEntity + EndpointDeclaration | 借鉴 push event 模式；用 async generator 简化（无 HTTP webhook route 注册）|
| `capabilities/tool.py` | PluginToolProviderEntity + ToolEntity | 借鉴 list_tools + invoke_tool 双 API 分离；input_schema dict 直传 |
| `capabilities/__init__.py` | PluginCategory enum | 借鉴用枚举声明 capability 集合（我们用 Literal） |

### 关键问题答（plan §Task 0 必答）

| 关键问题 | 答 |
|---|---|
| **Dify 有没有 HR / Identity 概念？** | **没有** — Dify 通过 OAuth + JWT 管 identity，无 HR module。HRCapability / IdentityCapability 是本项目 acid test 新增 |
| **Dify Trigger 怎么 dispatch event？** | webhook subscriber + EndpointDeclaration（path + method）；plugin daemon 收 webhook → 反推主进程 |
| **Dify Tool 怎么声明 invocation schema？** | `ToolEntity.parameters: list[ToolParameter]` + `output_schema: Mapping[str, object]`（dict 直传不强类型化）|
| **5.A 与 Dify 设计差异？** | (1) Trigger 用 async generator pull 而非 webhook push（少一层 Flask route 注册）；(2) 加 HR + Identity 两 capability；(3) Identity `is_source_of_truth` 解决双 plugin sync 方向冲突（Dify 无此问题）|

---

## Phase 5.D 解锁路径

Plan 03 落地后：

| Phase 5.D 任务 | 依赖 Plan 03 |
|---|---|
| `dept:研发部` 表达式解析 | `HRCapability.resolve_department_members(expression)` |
| Huly user 反向 sync | `IdentityCapability.is_source_of_truth=True` + `watch_user_changes()` async generator |
| HR 离职预置模板（Phase 7 success criteria） | `HRCapability.list_employees + list_leave_requests` |
| Trigger 节点 v1.1 真实接入 | `TriggerCapability.subscribe_events` + `verify_event_signature` |
| LLM Tool 节点 v1.1 真实接入 | `ToolCapability.list_tools + invoke_tool` |

---

## 阅读结论

- **HR / Identity 是本项目独有 capability** — Dify 无对应抽象，参考 Huly platform spike 报告独立设计
- **Trigger / Tool 借鉴 Dify 三层分层模式**（Declaration / Provider Entity / Invocation Manager），但用 Python typing.Protocol + async generator 简化（无 Pydantic provider entity + Flask route 注册）
- **5 借鉴点全部对应 5.A Plan 03 具体 module**：从 `PluginCategory` enum → `capabilities` Literal 枚举，到 `ToolEntity.parameters` 不强类型化 → `ToolSpec.input_schema: dict` 直传
- **Plan 03 实现路径清晰**：4 capability file（hr / identity / trigger / tool）+ 共享 `capabilities/__init__.py` 全 8 capability exports（IM + Doc 来自 Plan 02 + 4 个新）+ 3 测试 file
