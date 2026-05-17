# Phase 5.A: PlatformPlugin 框架（Dify-style） - Research

**Researched:** 2026-05-17
**Domain:** Plugin Architecture / Capability Protocols / JSONRPC over stdio / Pydantic Manifest
**Confidence:** HIGH（基于 ADR-001 已 Accepted + Dify 源码已 clone + Phase 4 真实 6 provider 实战 + Huly acid test 5 gap 已验证）

---

<user_constraints>
## User Constraints（直接拷贝自 CONTEXT.md，**不可协商**）

### Locked Decisions

#### Manifest 格式 + Plugin Discovery
- **Manifest 格式**：YAML（PyYAML，Phase 1 已是依赖）；内部 Pydantic schema 严格校验（`extra=forbid`）
- **Plugin 存储**：文件系统 `plugins/<plugin_name>/platform.yaml`（核心 plugins，git 同仓）+ DB `workspace_plugin_installations` 表（per-workspace 启用 / 凭据状态）
- **Discovery 时机**：启动期扫描 manifest（仅 metadata 入 PluginRegistry）+ 懒加载 daemon（首次 `get_capability()` 才 spawn daemon 进程；daemon spawn 后保活）
- **Schema 严格度**：`extra=forbid`（防 typo + 防隐式冲突）

#### Capability Negotiation
- **Protocol 风格**：`@runtime_checkable Protocol`（与 Phase 4 IMProvider 完全一致 — 鸭子类型 + isinstance 双保险）
- **多 capability facade**：lazy property + 共享底层 daemon client；`HulyPlugin.im / .doc / .hr / .identity` 4 facade 持同一个 `PlatformDaemonClient` 实例（1 进程 / 1 WS 池）
- **缺 capability 处理**：`registry.get_capability()` return `None` → 调用方显式 `if cap is None: log + skip / fallback`（registry 层 fail-quiet，不抛异常）
- **版本兼容**：manifest 声明 `agent_builder_version: ">=1.0"` + 启动期 SemVer 校验

#### LegacyAdapter 平滑迁移
- **Phase 4 6 家 IMProvider 永不强制迁移**：`register_provider("feishu", FeishuProvider)` 调用时自动 wrap 为 `LegacyIMProviderAdapter`
- **新老 plugin 共存**：完全共存；同一 workspace 可同时有"老 register_provider 注册的 feishu"和"新 manifest 注册的 huly"；capability_registry 按 `plugin_name` 路由
- **Protocol 演进**：SemVer（major 破坏 / minor 兼容 / patch 修复）；manifest 声明 `capability_versions: {im: "1.x"}`
- **弃用机制**：`docs/deprecation_warnings.md` 时间线 + manifest 字段 `deprecated: true` + `deprecated_since: "1.2"` + `removal_target: "2.0"`；v1 仅警告日志

#### HulyPlugin Acid Test 范围（用户 2026-05-17 三连质疑后硬性要求）
- **stub 深度**：最小 1 capability call 真实跑通；其他 3 capability 仅 facade 占位（NotImplementedError）
- **真实 Huly server vs mock**：mock huly server（Python aiohttp 本地 stub，监听端口模拟 Huly chunter API）；真实接入留 Phase 5.C
- **测试层级**：单测 mock JSONRPC client（不真 spawn daemon）+ 集成测真 spawn daemon 子进程 + mock huly server
- **DoD**：
  - [ ] HulyPlugin stub 真实运行：1 ainvoke 成功（端到端经过 JSONRPC stdio）
  - [ ] Fault isolation 验证：daemon process 崩溃，主进程不受影响 + capability call 返回明确错误
  - [ ] LegacyIMProviderAdapter 让 Phase 4 6 家 provider 通过新接口被调用，所有 Phase 4 测试 0 regression
  - [ ] 6 Capability Protocols 文件存在 + 单元测试覆盖 ≥ 80%
  - [ ] PlatformPluginRegistry per-workspace 隔离测试通过（双 workspace 互不串扰）

### Claude's Discretion

- **JSONRPC 实现**：推荐自写极简 dispatcher（async / await + asyncio subprocess + line-delimited JSON），原因：避免依赖外部库的 SemVer 风险；Dify dify-plugin-daemon 也是自写 — JSON-RPC 2.0 协议很简单，~150 LOC 可控
- **Manifest YAML 加载库**：`PyYAML`（Phase 1 已有依赖；safe_load 即可）
- **Capability Protocol 文件组织**：每 capability 一 file（`backend/app/agent_builder/platforms/capabilities/{im,doc,hr,identity,trigger,tool}.py`）— 便于演进 + 单 file LOC < 300
- **Mock huly server 实现**：复用 Phase 4 mock IM provider 模式（aiohttp web app）
- **structured log 字段命名**：`{"capability": str, "method": str, "latency_ms": int, "workspace_id": str, "plugin_name": str, "outcome": "success|error", "error_code": str | None}`（沿用 Phase 4 `im.card.send` schema 风格）
- **文档**：留 `docs/plugin-developer-guide.md` 给 Phase 6 写第三方开发者文档

### Deferred Ideas（OUT OF SCOPE — 不能出现在 Phase 5.A 任何 plan）

- Plugin 沙箱进程资源限制（cgroups v2 / memory cap）→ Phase 5.B
- DocCapability / HRCapability 真实平台接入（Outline / Lark / 飞书 / Huly 实写）→ Phase 5.C / 5.D
- 第三方 plugin marketplace（上传 zip / 安全审计 / 评分）→ Phase 6
- 画布节点配置 UI 自动渲染（manifest config_schema → React form）→ Phase 5.C 起
- Plugin runtime 多语言（Node.js / Go） → v2
- Plugin hot reload / SIGHUP → v2
- Plugin 跨 workspace 共享 daemon（每 workspace 独立 daemon 是 v1 决策）→ v1.5
- TriggerCapability / ToolCapability / WorkflowCapability 完整接口（v1.1 仅留 Protocol 骨架，真实接入留 Phase 5.D+）

</user_constraints>

<phase_requirements>
## Phase Requirements（**每个 ID 必须在至少 1 个 plan 的 `requirements` 字段出现**）

> 来源：CONTEXT.md `<domain>` 声明 + ROADMAP.md「新增 PLUG-* / IM-* 子集（Phase 5.A 阶段定义 v1.1）」
> 注：原 REQUIREMENTS.md 的 PLUG-01..04 是 Phase 6 marketplace 视角；Phase 5.A 新增的 v1.1 PLUG-FW-* 是**框架基础**（Phase 6 PLUG-01..04 的前置依赖）。IM-* 部分 ID 由 Phase 5.A LegacyAdapter 提供能力底座，5.D 落地。

| ID | Description | Research Support |
|----|-------------|-----------------|
| **PLUG-FW-01** | `PlatformPlugin` 顶层抽象类 + 6 Capability Protocols 完整定义（IM / Doc / HR / Identity / Trigger / Tool） | §3 Capability Protocols；ADR-001 §3；每 Protocol 单 file 组织 |
| **PLUG-FW-02** | `platform.yaml` manifest Pydantic schema（`extra=forbid`）+ YAML 解析 + 校验 | §4 Manifest Schema；ADR-001 §4 sample；PyYAML safe_load |
| **PLUG-FW-03** | `PlatformPluginRegistry` 启动期 discover + 懒加载 daemon + per-workspace 隔离 | §5 Registry；ADR-001 §6；workspace_plugin_installations 表 |
| **PLUG-FW-04** | `LegacyIMProviderAdapter` 让 Phase 4 6 家 IMProvider 通过新 IMCapability 接口被调用（**零 regression**） | §6 LegacyAdapter；ADR-001 §8；Phase 4 测试套 0 改动 |
| **PLUG-FW-05** | `PlatformDaemonClient` interface + JSONRPC over stdio 主进程↔daemon 通信（asyncio.subprocess + line-delimited JSON） | §7 Daemon Client；JSON-RPC 2.0 协议 |
| **PLUG-FW-06** | `MockPlatformPlugin` 测试用插件（声明多 capability，无 daemon，直接 in-process） | §8 Mock；用于单测 capability negotiation 路径 |
| **PLUG-FW-07** | **HulyPlugin stub acid test**：manifest + 4 facade + 1 capability call 真实跑通（mock huly server）+ fault isolation 验证 | §9 Acid Test；用户硬性要求 |
| **PLUG-FW-08** | `workspace_plugin_installations` 表 Alembic migration + RBAC 隔离 | §5.2 DB Schema；Alembic 0006_phase5a_plugin_installations.py |
| **IM-LEGACY-WRAP** | Phase 4 register_provider 注册自动 wrap 为 LegacyAdapter；新老 plugin 共存通过 capability_registry 按 plugin_name 路由 | §6；workspace_settings.default_im_plugin 选默认 |

**每 ID 必须覆盖**：每 plan 的 frontmatter `requirements: []` 字段列出本 plan 实现的 ID 子集；plan-checker 会做 `Phase req IDs ⊆ Union(plan.requirements)` 校验。

</phase_requirements>

## Summary

Phase 5.A 是把 Phase 4 已经落地的 IMProvider Protocol（6 家：飞书/企微/钉钉/Slack/Mattermost/Webhook）**升维**为 Dify-style 通用插件框架。技术核心**不是发明新机制**，而是 4 个具体工程任务：

1. **6 Capability Protocols** — 每个一 file，runtime_checkable Protocol，duck typing
2. **Manifest schema** — Pydantic v2 `BaseModel(extra=forbid)`，YAML safe_load 解析
3. **Registry + DB 表** — workspace_plugin_installations 表（Alembic 0006）+ 启动期 discover + 懒加载
4. **JSONRPC over stdio** — `asyncio.create_subprocess_exec` + 行分隔 JSON 双向通信 + asyncio.Future 关联 request_id → response

**关键风险点**：HulyPlugin acid test（用户硬性要求）必须真实跑通 — 不是 "mock 1 call OK"，是真起一个 Python daemon 子进程 + mock huly server + JSONRPC roundtrip + fault isolation。一旦这个跑通，5.B 沙箱 / 5.C Doc 接入 / 5.D HR 接入都是 fill-in-blanks。

**Primary recommendation**：6-9 plans across 4-6 waves。Wave 1 reading docs（Dify entities + Phase 4 baseline）+ migration；Wave 2 并行 6 Capability Protocols；Wave 3 manifest schema + Registry；Wave 4 LegacyAdapter + Daemon Client + MockPlugin；Wave 5 HulyPlugin acid test；Wave 6 E2E gate（manifest config_schema 解析 → 留 Phase 5.C 配 UI 钩子）。

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `typing` | 3.11+ stdlib | `Protocol`, `runtime_checkable`, `TypeVar`, `Generic` | Phase 4 IMProvider 已用 — 沿用 |
| `pydantic` | 2.10+ | Manifest schema 严格校验（`model_config = ConfigDict(extra="forbid")`） | Phase 1-4 已锁定 v2；FastAPI 同栈 |
| `PyYAML` | 6.0+ | YAML safe_load manifest | Phase 1 已是依赖 |
| `dataclasses` | stdlib `@dataclass(frozen=True)` | `RecipientSpec` / `MessageRef` / `DocRef` 等不可变值对象 | CLAUDE.md immutability 强制 |
| `asyncio` | 3.11+ stdlib | `subprocess.create_subprocess_exec`, `Future`, `StreamReader/Writer` | JSONRPC over stdio 主干 |
| `json` | stdlib | line-delimited JSON 编解码 | JSON-RPC 2.0 协议 |
| `uuid` | stdlib | `uuid.uuid4()` 生成 JSONRPC request_id | 标准 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sqlalchemy` | 2.0+ | `workspace_plugin_installations` 表 ORM + `select() with WorkspaceScopedQuery` | DB 持久化 |
| `alembic` | 1.13+ | migration 0006 创建表 | DB schema 迁移 |
| `structlog` | 23+ | capability call structured log（Phase 4 已用） | Phase 7 Run Viewer 钩子 |
| `pytest-asyncio` | 0.24+ | async 测试 | Phase 1 已用 |
| `aiohttp` | 3.11+ | mock huly server (web.Application + web.json_response) | Phase 4 mock 模式 |
| `pytest` | 8.3+ | 测试运行器 + fixture | Phase 1 已用 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 自写 JSONRPC | `jsonrpc-2.0-py`（PyPI） | 库 0.7k stars 维护一般；自写 ~150 LOC 可控（Dify 也自写）。CLAUDE.md §2.7 不直接拷 Dify 源码，但思路一致 |
| 自写 JSONRPC stdio | `mcp` (Model Context Protocol SDK) | MCP 是 stdio-based RPC 思路相近，但语义偏重（带 server/client lifecycle / capabilities negotiation）— 杀鸡用牛刀 |
| Pydantic | `attrs` | attrs 不带 schema validation；manifest 必须严格校验 |
| PyYAML | `ruamel.yaml` | ruamel 保留注释/格式（适合配置生成）；我们只 load 不 dump，PyYAML safe_load 足够 |

**Installation:**
```bash
# 全部已在 backend/pyproject.toml — Phase 1-4 累积；无需新增依赖
pip install pyyaml pydantic aiohttp pytest-asyncio
```

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/agent_builder/platforms/                      # ← 新增顶层模块
├── __init__.py
├── capabilities/                                          # Capability Protocols（每个一 file）
│   ├── __init__.py                                       # 集中 export + RecipientSpec/MessageRef 等公共类型
│   ├── im.py                                             # IMCapability + RecipientSpec, NormalizedCard, MessageRef
│   ├── doc.py                                            # DocCapability + DocRef, CRDTDelta, CommentRef
│   ├── hr.py                                             # HRCapability + Employee, Department, LeaveRequest, EmployeeRef
│   ├── identity.py                                       # IdentityCapability + UserPrincipal, UserChangeEvent
│   ├── trigger.py                                        # TriggerCapability（v1.1 留 Protocol 骨架）
│   └── tool.py                                           # ToolCapability（v1.1 留 Protocol 骨架）
├── manifest.py                                           # PlatformManifest Pydantic v2 schema
├── plugin.py                                             # PlatformPlugin 顶层类 + facade 模式
├── registry.py                                           # PlatformPluginRegistry
├── daemon_client.py                                      # PlatformDaemonClient (JSONRPC over stdio)
├── legacy_im_adapter.py                                  # Phase 4 IMProvider → IMCapability 适配层
├── mock_plugin.py                                        # MockPlatformPlugin（测试用）
└── exceptions.py                                         # PluginError, ManifestValidationError, CapabilityMissingError

backend/app/models/
└── workspace_plugin_installation.py                      # SQLAlchemy ORM 模型

backend/migrations/versions/
└── 0006_phase5a_plugin_installations.py                  # Alembic migration

plugins/                                                  # 文件系统核心 plugins（git 同仓）
└── huly/                                                 # Phase 5.A acid test stub
    ├── platform.yaml                                     # manifest
    ├── huly_plugin.py                                    # daemon entrypoint (Python)
    └── __init__.py

tests/
├── platforms/
│   ├── test_capabilities_im.py
│   ├── test_capabilities_doc.py
│   ├── test_capabilities_hr.py
│   ├── test_capabilities_identity.py
│   ├── test_manifest_schema.py
│   ├── test_registry.py
│   ├── test_daemon_client.py
│   ├── test_legacy_im_adapter.py
│   └── test_mock_plugin.py
└── platforms_integration/
    ├── test_huly_acid_test.py                            # 真起 daemon 子进程 + mock server
    ├── mock_huly_server.py                               # aiohttp stub
    └── test_fault_isolation.py
```

### Pattern 1: `runtime_checkable Protocol` for Duck Typing

**What:** Phase 4 `IMProvider` 已经用这套模式，5.A 直接沿用。Protocol 不需继承 — 实现类只要有匹配方法签名就 pass `isinstance(obj, IMCapability)`。

**When to use:** 所有 Capability 定义。

**Example（参考 Phase 4 `backend/app/agent_builder/notification/providers/base.py`）:**

```python
# backend/app/agent_builder/platforms/capabilities/im.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class RecipientSpec:
    """多态 recipient — 解决 Huly gap #a（channel ref / DM / thread）"""
    kind: Literal["channel", "dm_user", "thread"]
    id: str
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageRef:
    """Provider-agnostic 消息 handle — 用于 update_card 等后续操作"""
    plugin_name: str            # "huly" | "legacy:feishu" | ...
    native_id: str              # provider 内部消息 ID
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedCard:
    """平台无关卡片 schema — 各 Provider 适配为各家 markup"""
    title: str
    body_markdown: str
    actions: list[dict[str, str]]  # [{"action": "approve", "label": "批准", "url": "..."}]


@runtime_checkable
class IMCapability(Protocol):
    """对外通讯能力 — 发卡片 / DM / channel post / 接事件"""

    supports_native_buttons: bool
    supports_card_update: bool
    supports_threads: bool

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef: ...

    async def update_card(self, msg_ref: MessageRef, card: NormalizedCard) -> None: ...

    async def send_text(self, recipient: RecipientSpec, text: str) -> MessageRef: ...

    async def subscribe_events(
        self, event_types: list[str]
    ) -> AsyncIterator[dict[str, Any]]: ...
```

### Pattern 2: Pydantic v2 Manifest Schema with `extra=forbid`

**What:** YAML manifest 用 PyYAML.safe_load 转 dict，喂给 Pydantic v2 model `PlatformManifest(**dict)`；`ConfigDict(extra="forbid")` 让未声明字段直接 raise（防 typo）。

**When to use:** manifest discover 阶段 + plugin install 阶段。

**Example:**

```python
# backend/app/agent_builder/platforms/manifest.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["python"]  # v1 仅 Python；node/go 留 v2
    entry: str               # "huly_plugin:main"
    python_version: str = Field(default="3.11", pattern=r"^\d+\.\d+$")


class CapabilitySpec(BaseModel):
    """每个 capability 的版本与配置 — 按 capability 名做 union type 解析"""
    model_config = ConfigDict(extra="forbid")
    supports_native_buttons: bool | None = None  # IM
    supports_card_update: bool | None = None     # IM
    supports_threads: bool | None = None         # IM
    supports_collaborative_edit: bool | None = None  # Doc
    supports_comments: bool | None = None        # Doc
    is_source_of_truth: bool | None = None       # Identity


class SandboxConfig(BaseModel):
    """Phase 5.A 仅解析不强制 — Phase 5.B 落地"""
    model_config = ConfigDict(extra="forbid")
    cpu_limit: str | None = "1.0"
    memory_limit: str | None = "512Mi"
    network: list[str] = Field(default_factory=list)


class PlatformManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,31}$")  # 小写蛇形 / 32 字符
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")        # SemVer
    description: str
    license: str | None = None
    agent_builder_version: str = ">=1.0"
    runtime: RuntimeConfig
    capabilities: list[Literal["im", "doc", "hr", "identity", "trigger", "tool"]]
    config_schema: dict        # JSON Schema (passthrough — workspace 配 UI 用)
    im: CapabilitySpec | None = None
    doc: CapabilitySpec | None = None
    hr: CapabilitySpec | None = None
    identity: CapabilitySpec | None = None
    sandbox: SandboxConfig | None = None

    @field_validator("capabilities")
    @classmethod
    def at_least_one(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("plugin 必须声明至少 1 个 capability")
        return v
```

### Pattern 3: JSONRPC over stdio with asyncio Subprocess

**What:** 主进程 `asyncio.create_subprocess_exec(...)` 起 daemon，stdin/stdout 双向行分隔 JSON 通信。每 request 生成 UUID → 存 `dict[str, asyncio.Future]`；收到 response 时按 id 查 Future + set_result。

**When to use:** `PlatformDaemonClient.invoke(capability, method, **kwargs)`。

**Example:**

```python
# backend/app/agent_builder/platforms/daemon_client.py
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any


class PlatformDaemonClient:
    def __init__(self, manifest_path: str):
        self._manifest_path = manifest_path
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        # Phase 5.A：runtime.entry 解析为 "module:func"，subprocess 跑 python -c "import module; module.func()"
        # （Phase 5.B 加 cgroups v2 / network whitelist 等）
        self._proc = await asyncio.create_subprocess_exec(
            "python", "-u", "-m", self._resolve_module_entry(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def invoke(self, capability: str, method: str, **kwargs: Any) -> Any:
        if self._proc is None:
            await self.start()
        req_id = str(uuid.uuid4())
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        envelope = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": f"{capability}.{method}",
            "params": kwargs,
        }
        line = json.dumps(envelope).encode("utf-8") + b"\n"
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()
        return await asyncio.wait_for(future, timeout=30.0)

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while not self._closed:
            line = await self._proc.stdout.readline()
            if not line:
                # daemon exited — fault isolation：所有 pending future 失败
                for f in self._pending.values():
                    if not f.done():
                        f.set_exception(PluginDaemonExitedError(...))
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # log + skip 非法行
            rid = msg.get("id")
            if rid and rid in self._pending:
                fut = self._pending.pop(rid)
                if "error" in msg:
                    fut.set_exception(PluginInvocationError(msg["error"]))
                else:
                    fut.set_result(msg.get("result"))

    async def close(self) -> None:
        self._closed = True
        if self._proc:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
```

### Pattern 4: Lazy Facade on Shared Daemon

**What:** `HulyPlugin.im` / `.doc` / `.hr` / `.identity` 是 `@property` lazy facade — 都 wrap 同一个 `_daemon: PlatformDaemonClient`；4 个 facade 调任意 method 都走 `_daemon.invoke(capability, method, ...)`。

**Example:**

```python
# backend/app/agent_builder/platforms/plugin.py
class PlatformPlugin:
    def __init__(self, manifest: PlatformManifest, daemon: PlatformDaemonClient):
        self._manifest = manifest
        self._daemon = daemon
        self._cap_cache: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def im(self) -> "IMCapability | None":
        if "im" not in self._manifest.capabilities:
            return None
        if "im" not in self._cap_cache:
            from .capabilities.im_facade import IMFacade
            self._cap_cache["im"] = IMFacade(self._daemon, self._manifest.im)
        return self._cap_cache["im"]

    # ... doc / hr / identity 同模式
```

### Anti-Patterns to Avoid

- **直接拷贝 Dify 源码** — Dify 是 AGPL-3.0，本项目 Apache-2.0。仅借鉴**设计模式**（manifest YAML / capability negotiation / daemon facade），自己写实现。
- **register_provider 改造为强制 manifest 注册** — 违反 LegacyAdapter 平滑迁移决策。Phase 4 6 家 provider 永不强制改造。
- **同步 subprocess.Popen** — daemon I/O 必须全 asyncio；Popen 会 block event loop。
- **manifest extra=allow** — 未声明字段静默吞会导致 typo 难调试；严格 forbid。
- **daemon process 共享跨 workspace** — v1 决策每 workspace 独立 daemon。共享 daemon 会让 workspace 隔离失效。
- **Capability Protocol 加新 method 不带 default impl** — 会破老 plugin。新 method 必须有 default `raise NotImplementedError` + manifest version pin 校验。
- **acid test 只 mock 不 spawn 真 daemon** — 用户硬性要求 "1 ainvoke 端到端真跑通"。若只 mock JSONRPC client，抽象仍在纸面。

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSONRPC 协议解析 | 自写 200+ LOC parser | 自写 **~150 LOC** dispatcher（JSON-RPC 2.0 spec 极简，4 字段 jsonrpc/id/method/params） | Dify 也自写；外部库 (`jsonrpc-2.0-py`) 维护一般；杀鸡用牛刀（MCP SDK）；自写可控 + 0 依赖风险 |
| YAML 解析 | 写正则匹配 | `yaml.safe_load(open(path))` | PyYAML 是 Phase 1 锁定依赖；safe_load 防代码执行 |
| Manifest schema 校验 | 写一堆 `if not isinstance(...)` | Pydantic v2 `BaseModel(extra="forbid")` | 自动 error message + 类型转换 + JSON Schema export |
| Async subprocess 管理 | `os.spawn` / 同步 Popen | `asyncio.create_subprocess_exec` + StreamReader/StreamWriter | 必须非阻塞；event loop 不能停 |
| ORM workspace 隔离 | 在每查询写 `WHERE workspace_id = ?` | 沿用 Phase 1 `WorkspaceScopedQuery` 抽象 | 已存在 + Phase 1 测试覆盖 |
| structured logging | 写一坨 `logger.info(f"...")` | 沿用 Phase 4 `structlog` schema | Phase 7 Run Viewer 钩子已计划 |

**Key insight:** 5.A 90% 的功能是组合既有库 + Phase 1-4 已有抽象（WorkspaceScopedQuery / structlog / Alembic / Pydantic / Protocol）。只有 1 处确实需要"原创"：JSONRPC dispatcher（~150 LOC），且 Dify 已证可控。

---

## Common Pitfalls

### Pitfall 1: subprocess.Popen blocks event loop

**What goes wrong:** 用同步 `subprocess.Popen(["python", ...])` + 同步 `read()` 会冻结整个 FastAPI 进程。

**Why it happens:** Python 3.11 asyncio event loop 单线程。任何 sync I/O 都会 block 所有协程。

**How to avoid:** 全用 `asyncio.create_subprocess_exec` + `StreamReader`/`StreamWriter`。`process.stdin.write(data); await process.stdin.drain()`。

**Warning signs:** /healthz endpoint 间歇变 slow；`langgraph` SSE stream 卡顿。

### Pitfall 2: daemon process 崩溃不被检测

**What goes wrong:** plugin daemon segfault / Python 进程崩溃，主进程的 `_pending` dict 中 future 永远 pending → 调用方 await 卡死 30s 后 TimeoutError。

**Why it happens:** asyncio.subprocess 不自动 propagate child exit。

**How to avoid:** `_read_loop` 检测 `stdout.readline()` 返回空 bytes → daemon exited → 遍历 `_pending` 把所有 Future `set_exception(PluginDaemonExitedError)`；同时 spawn `wait_for_exit_task` 调 `process.wait()` 拿 returncode。

**Acid test 必须覆盖**：用户硬性要求 #2。

**Warning signs:** 调用方 await 卡 30s；`/healthz` plugin 状态接口报告 daemon 假死。

### Pitfall 3: manifest YAML 注入

**What goes wrong:** `yaml.load(open(path))` 默认 unsafe — 攻击者放置含 `!!python/object/apply:os.system [...]` 的 manifest 会执行任意代码。

**How to avoid:** 永远 `yaml.safe_load`（仅基本类型）。CI 增加 grep 检查：`grep -r "yaml.load(" backend/ | grep -v safe_load` 必须 0 命中。

**Warning signs:** 第三方 plugin manifest 上传时未走 safe_load。

### Pitfall 4: Pydantic `extra=forbid` 与 v1.1 演进冲突

**What goes wrong:** manifest 字段 `extra=forbid`，未来 v1.2 加 `oauth_config` 字段时旧 plugin manifest 不带它 → 仍然 pass（Optional），但 v1.2 plugin manifest 含它喂给 v1.1 框架时直接 raise。

**How to avoid:** 框架版本只升不降兼容（manifest 声明 `agent_builder_version: ">=1.0"`）；启动期框架版本校验 SemVer 在 manifest 之前；新字段默认值 None。**5.A 仅做 framework version 1.0；不主动升级 — 5.B/5.C 升 1.1+ 时再面对**。

### Pitfall 5: workspace 隔离失效（Phase 1 Pitfall 6 重现）

**What goes wrong:** `PlatformPluginRegistry.get_capability(workspace_id=...)` 实际从全局 `_plugins: dict[str, PlatformPlugin]` 取 — 任何 workspace 都拿同一 plugin 实例 → daemon 共享 → workspace_settings.plugin_config 串户。

**How to avoid:** Registry 内部 key 是 `(workspace_id, plugin_name)` tuple；每 workspace 独立 daemon 实例（v1 决策）；E2E 测试：双 workspace 互访 plugin 必须互不见。

**Warning signs:** 单测 mock 时单 workspace 跑通，双 workspace 集成测出 cross-tenant leak。

### Pitfall 6: LegacyAdapter 漏 wrap 导致 Phase 4 测试 regression

**What goes wrong:** Phase 4 测试套通过 `register_provider("feishu", FeishuProvider())` 注册，调用 `get_provider("feishu").send_card(...)`。若 5.A 改 `register_provider` 自动 wrap 为 LegacyAdapter 时签名不匹配（如旧 `send_hitl_card(recipient: str, ...)` vs 新 `send_card(recipient: RecipientSpec, ...)`），Phase 4 测试全 fail。

**How to avoid:**
1. **`register_provider` 接口保持不变**（旧测试不动）
2. **新增 `_PROVIDERS_AS_CAP: dict[str, IMCapability]`** 内部 wrap 一份；新代码走 `get_capability(IMCapability, prefer=name)`
3. **Phase 4 既有 `get_provider(name)` 路径保留 + 新 `get_capability(...)` 路径并存**
4. E2E gate：Phase 4 所有 81 IM 测试 + e2e_v2 26 specs 必须 0 regression

**Warning signs:** Phase 4 测试套出现 unrelated AttributeError。

### Pitfall 7: JSONRPC id 碰撞

**What goes wrong:** UUID4 32 字符理论上 0.000% 碰撞，但若用 `int(time.time())` 类 simple id 又跨进程同时调可能撞。

**How to avoid:** 永远 `uuid.uuid4().hex`。每 request_id 是 36 字符 hex。

### Pitfall 8: daemon stderr 阻塞 pipe buffer

**What goes wrong:** daemon 写大量 stderr（如 logger.warning 满负荷）→ pipe buffer 满 → daemon 进程被 OS block 在 write() → 整个 plugin 假死。

**How to avoid:** spawn 时 `stderr=asyncio.subprocess.PIPE` + 独立 `_stderr_drain_task` 持续读取 + 转发到主进程 logger。

**Warning signs:** plugin 跑一段时间后突然全 hang；stderr file size 大。

### Pitfall 9: HulyPlugin acid test 走 mock 而非真 daemon

**What goes wrong:** 偷懒在 acid test 直接 mock `PlatformDaemonClient.invoke` 返回值 — 表面 1 capability call 通过，实际抽象仍在纸面（用户三连质疑场景）。

**How to avoid:** acid test 必须：
1. 真起 `python -m huly_plugin` 子进程
2. 子进程内含 mock huly server（aiohttp.web 起本地端口） 或 daemon 直接调 mock server
3. 主进程 → daemon → mock server roundtrip
4. 验证：daemon kill -9 后主进程下次调用立刻 raise（不 hang 30s）

**Warning signs:** acid test 跑时间 < 200ms（说明根本没起 subprocess）。

---

## Code Examples

### Example 1: MockPlatformPlugin（测试用，无 daemon，in-process）

```python
# backend/app/agent_builder/platforms/mock_plugin.py
from __future__ import annotations

from typing import Any

from .capabilities.im import IMCapability, MessageRef, NormalizedCard, RecipientSpec
from .manifest import PlatformManifest


class MockIMCapability:
    """In-process IM capability — 单测用，不走 JSONRPC"""
    supports_native_buttons = True
    supports_card_update = True
    supports_threads = False

    def __init__(self) -> None:
        self.sent: list[tuple[RecipientSpec, NormalizedCard, str]] = []

    async def send_card(self, *, recipient, card, idempotency_key) -> MessageRef:
        self.sent.append((recipient, card, idempotency_key))
        return MessageRef(plugin_name="mock", native_id=f"mock-{len(self.sent)}")

    async def update_card(self, msg_ref, card) -> None:
        pass

    async def send_text(self, recipient, text) -> MessageRef:
        return MessageRef(plugin_name="mock", native_id=f"text-{recipient.id}")

    async def subscribe_events(self, event_types):
        if False:
            yield {}


class MockPlatformPlugin:
    """声明 IM + Doc + HR capability 的 mock；用于 Registry / Capability negotiation 单测"""
    def __init__(self, manifest: PlatformManifest):
        self._manifest = manifest
        self._im = MockIMCapability()

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def im(self) -> IMCapability | None:
        return self._im if "im" in self._manifest.capabilities else None
    # ... doc / hr 同模式
```

### Example 2: LegacyIMProviderAdapter（Phase 4 IMProvider → IMCapability）

```python
# backend/app/agent_builder/platforms/legacy_im_adapter.py
from __future__ import annotations

from typing import Any

from app.agent_builder.notification.providers.base import IMProvider

from .capabilities.im import IMCapability, MessageRef, NormalizedCard, RecipientSpec


class LegacyIMProviderAdapter:
    """把 Phase 4 IMProvider 包装为 IMCapability。
    
    保证 Phase 4 既有 register_provider() 调用 0 改动 + 0 测试 regression。
    新代码可通过 PlatformPluginRegistry.get_capability(IMCapability, prefer=name)
    走新接口；旧 NotificationService 仍可通过 get_provider(name) 走老接口。
    """

    def __init__(self, legacy: IMProvider):
        self._legacy = legacy
        self.supports_native_buttons = True  # Phase 4 6 家都支持原生卡片（webhook 除外）
        self.supports_card_update = getattr(legacy, "supports_card_update", False)
        self.supports_threads = False

    @property
    def name(self) -> str:
        return self._legacy.name

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef:
        # RecipientSpec → legacy str recipient（kind="channel" 时 .id 即 channel_user_id）
        legacy_recipient = recipient.id
        # NormalizedCard → legacy send_hitl_card 参数（解构 actions → deeplinks）
        deeplinks = [
            {"action": a["action"], "url": a["url"]}
            for a in card.actions
        ]
        result = await self._legacy.send_hitl_card(
            recipient=legacy_recipient,
            flow_title=card.title,
            node_title="",  # legacy 字段，新接口不再分
            applicant_name="",
            actor_name="",
            deadline_at="",
            description=card.body_markdown,
            deeplinks=deeplinks,
        )
        return MessageRef(
            plugin_name=f"legacy:{self._legacy.name}",
            native_id=result["message_id"],
            extras={"raw_response": str(result.get("raw_response", {}))},
        )

    async def update_card(self, msg_ref: MessageRef, card: NormalizedCard) -> None:
        if not self.supports_card_update:
            return  # silently no-op — legacy 已有降级路径
        await self._legacy.update_card(
            message_id=msg_ref.native_id,
            new_content={"text": card.body_markdown},
        )

    async def send_text(self, recipient: RecipientSpec, text: str) -> MessageRef:
        await self._legacy.send_supplement_text(
            recipient=recipient.id, text=text
        )
        return MessageRef(
            plugin_name=f"legacy:{self._legacy.name}",
            native_id="supplement",  # legacy 不返回 id
        )

    async def subscribe_events(self, event_types: list[str]):
        # Phase 4.5 留给业务层，5.A 不实现
        if False:
            yield {}
```

### Example 3: HulyPlugin acid test 入口（plugins/huly/huly_plugin.py）

```python
# plugins/huly/huly_plugin.py
"""HulyPlugin stub — daemon entrypoint。

启动后从 stdin 读 JSONRPC envelope，调用对应 capability 方法，
结果走 stdout 回（line-delimited JSON）。

Phase 5.A 仅实 1 个 IMCapability.send_card 端到端（mock huly server）。
其他 capability 返回 NotImplementedError。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

import aiohttp


HULY_ENDPOINT = os.environ.get("HULY_ENDPOINT", "http://localhost:18765")


async def im_send_card(params: dict) -> dict:
    """IMCapability.send_card 实现 — 调 mock huly chunter API"""
    recipient = params["recipient"]
    card = params["card"]
    idempotency_key = params["idempotency_key"]
    body = {
        "channel": recipient["id"],
        "message": f"## {card['title']}\n\n{card['body_markdown']}",
        "idempotency_key": idempotency_key,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{HULY_ENDPOINT}/api/v1/chunter/messages",
            json=body,
            timeout=aiohttp.ClientTimeout(total=5.0),
        ) as resp:
            data = await resp.json()
    return {
        "plugin_name": "huly",
        "native_id": data["message_id"],
        "extras": {"channel": recipient["id"]},
    }


METHODS = {
    "im.send_card": im_send_card,
    # 其他 capability 在 Phase 5.C 起实
}


async def main() -> None:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        method_name = envelope.get("method", "")
        handler = METHODS.get(method_name)
        if handler is None:
            response = {
                "jsonrpc": "2.0",
                "id": envelope.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {method_name}"},
            }
        else:
            try:
                result = await handler(envelope.get("params", {}))
                response = {"jsonrpc": "2.0", "id": envelope["id"], "result": result}
            except NotImplementedError as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": envelope["id"],
                    "error": {"code": -32603, "message": str(e)},
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": envelope["id"],
                    "error": {"code": -32000, "message": f"Internal error: {e}"},
                }
        line_out = (json.dumps(response) + "\n").encode("utf-8")
        writer.write(line_out)
        await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
```

### Example 4: Alembic Migration（workspace_plugin_installations）

```python
# backend/migrations/versions/0006_phase5a_plugin_installations.py
"""Phase 5.A: workspace_plugin_installations 表

Revision ID: 0006_phase5a_plugin_installations
Revises: 0005_phase4_chain_indexes
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_phase5a_plugin_installations"
down_revision = "0005_phase4_chain_indexes"


def upgrade() -> None:
    op.create_table(
        "workspace_plugin_installations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plugin_name", sa.Text, nullable=False),
        sa.Column("plugin_version", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="installed"),  # installed | disabled | error
        sa.Column("config_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("credentials_json", postgresql.JSONB, nullable=True),  # 加密存（Phase 4 IMCredentialsManager 复用）
        sa.Column("installed_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "plugin_name", name="uq_workspace_plugin"),
        sa.CheckConstraint("status IN ('installed', 'disabled', 'error')", name="ck_plugin_status"),
    )
    op.create_index(
        "ix_workspace_plugin_workspace_status",
        "workspace_plugin_installations",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_plugin_workspace_status")
    op.drop_table("workspace_plugin_installations")
```

---

## State of the Art

| Old Approach (Phase 4) | Current Approach (Phase 5.A) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `register_provider("feishu", FeishuProvider())` Python class + 改源码 PR | YAML manifest + daemon process + 文件系统 install | 2026-05-17 (本 phase) | 第三方平台无需改核心代码 |
| 一个 provider = 一类 capability | 一个 plugin 可声明多 capability（4 facade 共享 daemon） | 2026-05-17 | Huly 一体化平台 1 进程 / 1 WS 池 |
| 同进程 provider（fault 影响主） | 子进程沙箱（fault isolation；Phase 5.A 框架就位，Phase 5.B 加资源限制） | 2026-05-17 | plugin crash 不影响主进程 |
| 每 provider 写一套 frontend 配置面板 | manifest config_schema → JSON Schema（Phase 5.C 起前端自动渲染） | 2026-05-17 | 减少 100 行/plugin 配置代码 |
| 硬编码 supports_card_update 字段 | manifest 声明 + Registry 查能力 | 2026-05-17 | Capability negotiation 显式 |

**Deprecated/outdated:**
- Phase 4 `IMProvider.send_hitl_card(recipient: str, ...)` 不弃用，仅通过 LegacyAdapter wrap；正面新 API 是 `IMCapability.send_card(*, recipient: RecipientSpec, card: NormalizedCard, ...)`
- DocProvider 设计稿（`2026-05-17-doc-provider-abstraction-design.md`）已被 ADR-001 取代 — 不再单独抽象

---

## Open Questions

1. **HulyPlugin 在 acid test 是否需要真 OAuth / 鉴权？**
   - What we know: ADR-001 §4 manifest 示例含 `auth_token` 字段
   - What's unclear: stub acid test 是否模拟 token 验证
   - **Recommendation**: acid test 走 mock huly server，token 字段 plumbing 但不验签（5.C 实接入时再做）

2. **多 plugin 同 capability 时 default 选谁？**
   - What we know: `get_capability(IMCapability, prefer='huly')` API 已定（ADR-001 §6）
   - What's unclear: 没 prefer 时怎么选 — 第一个？workspace_settings.default_im_plugin？
   - **Recommendation**: workspace_settings.default_im_plugin → fallback 第一个 installed plugin → fallback Phase 4 legacy（按 register 顺序）

3. **daemon process 内存峰值上限**
   - What we know: Phase 5.B 才做资源限制
   - What's unclear: 5.A 是否需要 soft monitor（log warning if RSS > 500MB）
   - **Recommendation**: 5.A 不做监控（避免 scope creep）；5.B 加 cgroups v2 enforcement

4. **plugin 凭据加密复用 Phase 4 IMCredentialsManager 还是新增？**
   - What we know: ADR-001 §11.5 推荐复用
   - What's unclear: workspace_plugin_installations.credentials_json 是否走 IMCredentialsManager 包装
   - **Recommendation**: 5.A migration 字段先用 JSONB nullable；具体加密走 IMCredentialsManager + plugin_name 前缀（5.C 接入时再改 type → bytea 存密文）

---

## Phase 4 Baseline References（必读源文件）

| Phase 4 文件 | 5.A 复用点 |
|---|---|
| `backend/app/agent_builder/notification/providers/base.py` | IMProvider Protocol 模式 + Registry pattern → IMCapability 直接沿用风格 |
| `backend/app/agent_builder/notification/providers/feishu.py` | 真实 Provider 实现样例 → LegacyAdapter wrap 它 |
| `backend/app/agent_builder/notification/cards/*.py` | NormalizedCard 渲染 fallback 路径参考 |
| `backend/migrations/versions/0005_phase4_chain_indexes.py` | Alembic migration 风格 → 0006 沿用 |
| `tests/test_im_provider_*.py` | Phase 4 81 测试用例 → 0 regression 验证基线 |
| `backend/app/middleware/setup_redirect_middleware.py` | 启动期校验模式 → plugin discover 启动期校验同结构 |

---

## Dify Reference Mapping（必读，每 plan 走 Task 0 reading doc）

| 5.A 模块 | Dify 必读源文件 | 借鉴点 |
|---|---|---|
| **Capability Protocols** | `api/core/plugin/entities/plugin.py` (PluginDeclaration / PluginEntity) | declaration vs runtime entity 拆分 |
| **Manifest schema** | `api/core/plugin/entities/bundle.py` (PluginBundleDependency) + `api/core/plugin/manifest_schema/{plugin,tool,model,agent}.yaml` | Pydantic + YAML 双层 + 严格校验思路 |
| **Daemon Client** | `api/core/plugin/entities/plugin_daemon.py` (PluginDaemonBasicResponse / PluginInstallTask) + Dify dify-plugin-daemon Go 实现概念 | RPC envelope + 错误传播 |
| **Registry** | `api/services/plugin/plugin_service.py` (PluginService) + `api/services/plugin/plugin_permission_service.py` | install / list / get_capability 调度 |
| **JSONRPC protocol** | `api/core/plugin/entities/plugin_daemon.py` 各 Response 类 | 错误码 / status enum |
| **Endpoint declaration** | `api/core/plugin/entities/endpoint.py` (EndpointDeclaration / EndpointProviderDeclaration) | capability 声明在 manifest 中的 idiom |

**License 注意**：Dify 是 AGPL-3.0，本项目 Apache-2.0 — **不能拷源码**，仅借鉴**设计模式 / 数据结构 / 边界考虑**。每 plan Task 0 reading doc 必须明确列出借鉴点 + attribution。

**Reading doc 文件名规范**（沿用 Phase 1-4 习惯）：
- `docs/reading-dify-05a-{NN}-{topic}-2026-05-17.md`
- 例：`docs/reading-dify-05a-02-capability-protocols-2026-05-17.md`

---

## Validation Architecture

> **Note**: workflow.nyquist_validation 在 init JSON 不存在（key not found）→ 默认 false。**本节按 false 处理，不强制 Nyquist 采样检查**，但仍按 CLAUDE.md §2.2 三层测试 + E2E 严格规划。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3 + pytest-asyncio 0.24 |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/platforms/ -x` (单测 ~ < 10s) |
| Full suite command | `pytest tests/platforms/ tests/platforms_integration/ -v` (含 acid test ~ < 60s) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| PLUG-FW-01 | 6 Capability Protocols 类型签名 | unit | `pytest tests/platforms/test_capabilities_*.py -x` | ❌ Wave 0 |
| PLUG-FW-02 | YAML manifest Pydantic 校验 (含 extra=forbid) | unit | `pytest tests/platforms/test_manifest_schema.py -x` | ❌ Wave 0 |
| PLUG-FW-03 | Registry per-workspace 隔离 | integration | `pytest tests/platforms/test_registry.py -v` | ❌ Wave 0 |
| PLUG-FW-04 | LegacyAdapter Phase 4 6 家 0 regression | unit + integration | `pytest tests/platforms/test_legacy_im_adapter.py tests/test_im_provider_*.py -x` | ❌ Wave 0 / Phase 4 ✓ |
| PLUG-FW-05 | JSONRPC over stdio 双向通信 | integration | `pytest tests/platforms/test_daemon_client.py -v` | ❌ Wave 0 |
| PLUG-FW-06 | MockPlatformPlugin 多 capability | unit | `pytest tests/platforms/test_mock_plugin.py -x` | ❌ Wave 0 |
| PLUG-FW-07 | HulyPlugin acid test 端到端 + fault isolation | integration (E2E) | `pytest tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py -v` | ❌ Wave 0 |
| PLUG-FW-08 | Alembic migration 0006 upgrade/downgrade | integration | `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` | ❌ Wave 0 |
| IM-LEGACY-WRAP | register_provider 自动 wrap + 共存 | unit | `pytest tests/platforms/test_legacy_im_adapter.py::test_coexistence -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/platforms/ -x` (单 plan 内仅本 plan 修改的目录)
- **Per wave merge:** `pytest tests/platforms/ tests/platforms_integration/ tests/test_im_provider_*.py -x` (含 Phase 4 regression 检查)
- **Phase gate:** Full suite green + Phase 4 81 IM 测试 + Phase 1-4 e2e_v2 26 specs 0 regression

### Wave 0 Gaps

- [ ] `tests/platforms/` 目录创建 + `conftest.py` 共享 fixture
- [ ] `tests/platforms_integration/` 目录创建 + `mock_huly_server.py` aiohttp stub
- [ ] `tests/platforms/conftest.py` — workspace fixture / mock daemon fixture
- [ ] Alembic migration 0006 文件（Wave 1 任务）— 必须先建表才能跑 Registry per-workspace 测试

---

## Sources

### Primary (HIGH confidence)

- `/Users/admin/ai/resume/interview/liuxin/agent-builder/docs/plans/2026-05-17-platform-plugin-framework-ADR.md` — ADR-001 Accepted 完整 spec
- `/Users/admin/ai/resume/interview/liuxin/agent-builder/docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md` — Huly acid test 5 gap 报告（每 gap → ADR §7 对应解决）
- `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/notification/providers/base.py` — Phase 4 IMProvider Protocol 实战（212 行 + 81 测试覆盖）
- `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/{plugin,bundle,endpoint,plugin_daemon}.py` — Dify plugin entities（AGPL，仅借鉴模式）
- `.planning/phases/05a-platform-plugin-framework/05a-CONTEXT.md` — 用户 4 area 决策
- Python 3.11 stdlib `asyncio.subprocess` 官方文档 — `create_subprocess_exec` API

### Secondary (MEDIUM confidence)

- JSON-RPC 2.0 spec (https://www.jsonrpc.org/specification) — 协议简单，4 字段 envelope
- Pydantic v2 docs `ConfigDict(extra="forbid")` 用法 — Phase 1-4 已实战
- SQLAlchemy 2.0 `UniqueConstraint` + JSONB 字段类型 — Phase 1-4 已用

### Tertiary (LOW confidence)

- Dify plugin daemon repository (https://github.com/langgenius/dify-plugin-daemon) Go 实现 — 仅作概念参考；本项目 Python only

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Phase 1-4 已锁定全部依赖（pydantic v2 / PyYAML / asyncio / SQLAlchemy 2.0 / structlog）
- Architecture: HIGH — Protocol + Registry + LegacyAdapter 模式已在 Phase 4 IMProvider 实战验证
- Pitfalls: HIGH — 9 个 pitfall 来自 Phase 4 实战 + Huly acid test 5 gap + Dify 源码 review
- HulyPlugin acid test：HIGH — JSONRPC over stdio 模式标准（MCP / Dify daemon 均验证）；mock huly server 即 Phase 4 mock 模式复用

**Research date:** 2026-05-17
**Valid until:** 2026-06-17 (Pydantic / FastAPI / SQLAlchemy 均稳定，30 天有效)
