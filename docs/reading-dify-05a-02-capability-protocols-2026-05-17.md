# Dify 阅读笔记 — Capability Protocols (Plan 05a-02 准备)

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> License: AGPL-3.0 (本项目 Apache-2.0 — 仅借鉴设计模式，不拷源代码 / attribution 已标注)

---

## 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 应用平台，其 `core.plugin` 子系统把 model provider / tool provider / datasource / agent / trigger 等异构外部能力统一抽象为「declaration（manifest）+ entity（runtime）+ daemon（沙箱进程）」三层模型，是 agent-builder Phase 5.A PlatformPlugin 框架的直接参考。

---

## 技术栈（关键技术选择）

| Dify 技术选择 | 本项目对应 |
| ---- | ---- |
| `Pydantic v2 BaseModel` + 各 capability 子类（ToolProviderEntityWithPlugin / DatasourceProviderEntityWithPlugin 等） | `@runtime_checkable Protocol` + `@dataclass(frozen=True)` 值对象 |
| `StrEnum`（PluginCategory / PluginInstallTaskStatus / InstallPluginMessage.Event） | `Literal[...]` 类型注解（更轻量，无需 import） |
| `PluginDaemonBasicResponse[T]` 泛型 envelope | JSON-RPC 2.0 envelope（Plan 06 实现） |
| Go 写的独立 `dify-plugin-daemon` 进程 | Python `asyncio.subprocess` daemon（Plan 06） |
| 一个 plugin 一类 capability（tool / model / agent 单选） | **一个 plugin 可声明多 capability**（Huly 一体化场景 — ADR §2 关键差异） |

---

## 架构要点（核心架构模式）

Dify 三层分离架构：

```
Manifest (YAML)              Declaration (Pydantic)             Entity (Runtime)
─────────────────            ───────────────────                ─────────────────
plugin.yaml                  PluginDeclaration                   PluginEntity
  name: huly                   name: str (regex 校验)             ↳ extends PluginInstallation
  category: tool              category: PluginCategory             tenant_id: str
  resource:                   resource: PluginResourceRequirements installation_id: str
    memory: 512MB             tool: ToolProviderEntity              plugin_unique_identifier
  plugins:                    model: ProviderEntity                 version + checksum
    tools: [...]              endpoint: EndpointProviderDecl        declaration: PluginDeclaration
                                                                    ↑↑↑（runtime 复制 declaration）
```

**关键洞察**：

1. **Declaration** 是 schema 校验层 — 只关心 manifest 字段类型 / 约束（Pydantic）
2. **Entity** 是运行时层 — 持 tenant_id / plugin_id / installation_id / 凭据状态
3. **每 capability 一个 Entity 子类** — `PluginToolProviderEntity` / `PluginModelProviderEntity` / `PluginAgentProviderEntity` / `PluginDatasourceProviderEntity` / `PluginTriggerProviderEntity` 平行 5 类
4. **Capability 调用经 daemon RPC envelope 中转** — `PluginDaemonBasicResponse[T]` 含 code / message / data 三字段，泛型 T 是各 capability 的 specific response 类型

---

## 可借鉴的设计模式（5 借鉴点）

### 1. PluginCategory 枚举 → 5.A capabilities 字段

**Dify 源文件**：`api/core/plugin/entities/plugin.py` 第 61-67 行
```python
class PluginCategory(StrEnum):
    Tool = auto()
    Model = auto()
    Extension = auto()
    AgentStrategy = "agent-strategy"
    Datasource = "datasource"
    Trigger = "trigger"
```

**5.A 借鉴**：
- `capabilities: list[Literal["im", "doc", "hr", "identity", "trigger", "tool"]]` 在 `PlatformManifest` 中（Plan 03）
- **关键差异**：Dify `category` 是**单值**（一 plugin 一类），本项目 `capabilities` 是**列表**（一 plugin 多 capability — 支持 Huly 一体化）
- 本 plan 02 不直接消费 capabilities 字段，但为 Plan 03 manifest 留口子：`Literal[...]` 集合必须与 capabilities/{im,doc,...}.py 文件名一致

**应用模块**：`backend/app/agent_builder/platforms/capabilities/im.py`、`doc.py`（每个 capability 一个 file，与 Dify "每 capability 一 Entity 子类" 思路一致）

---

### 2. EndpointDeclaration method 字段 → 5.A capability method 声明

**Dify 源文件**：`api/core/plugin/entities/endpoint.py` 第 11-18 行
```python
class EndpointDeclaration(BaseModel):
    path: str
    method: str             # HTTP method (GET/POST/...)
    hidden: bool = Field(default=False)
```

**5.A 借鉴**：
- Capability Protocol 内每方法就是一个 "declared method"（如 `IMCapability.send_card` 对应 Dify endpoint method）
- 本项目用 **Python Protocol 方法签名** 替代 Dify 的 `method: str` 字符串声明（更类型安全，IDE 可补全）
- 关键学习：**capability 声明 vs runtime invocation 分离** — Dify EndpointDeclaration 是声明，运行时通过 daemon RPC 调用；本项目 Protocol 是声明，runtime 通过 LegacyAdapter 或 PluginDaemonClient 调用

**应用模块**：`IMCapability.send_card` / `IMCapability.subscribe_events` / `DocCapability.replace_document_content` / `DocCapability.apply_document_delta` 等方法定义（不仅 Dify endpoint 的字符串方法，而是带类型的 Python async 方法签名）

---

### 3. 每 capability 一个 Entity 类 → 5.A 每 Protocol 一 file 组织

**Dify 源文件**：`api/core/plugin/entities/plugin_daemon.py` 第 47-67 行
```python
class PluginToolProviderEntity(BaseModel):
    provider: str
    plugin_unique_identifier: str
    plugin_id: str
    declaration: ToolProviderEntityWithPlugin

class PluginDatasourceProviderEntity(BaseModel):
    ...
    declaration: DatasourceProviderEntityWithPlugin

class PluginAgentProviderEntity(BaseModel):
    ...
    declaration: AgentProviderEntityWithPlugin
    meta: PluginDeclaration.Meta
```

**5.A 借鉴**：
- 每 capability 一个 Python 文件：`capabilities/im.py` / `capabilities/doc.py` / `capabilities/hr.py` / `capabilities/identity.py` / `capabilities/trigger.py` / `capabilities/tool.py`
- 每文件含 1 个 Protocol + 配套值对象（dataclass frozen=True）— RecipientSpec/NormalizedCard/MessageRef 之于 IM，DocRef/CRDTDelta/CommentRef/DocInfo 之于 Doc
- **关键差异**：Dify 用 Pydantic BaseModel（含校验），本项目用 dataclass frozen=True（更轻量，纯值对象语义）+ Protocol（duck typing）

**应用模块**：本 plan 02 直接产出 `capabilities/im.py` + `capabilities/doc.py` 两文件（每个 ≥ 90 LOC）

---

### 4. PluginInstallation 凭据 / runtime 字段流转 → 5.A workspace_plugin_installations.credentials_json

**Dify 源文件**：`api/core/plugin/entities/plugin.py` 第 143-154 行
```python
class PluginInstallation(BasePluginEntity):
    tenant_id: str
    endpoints_setups: int
    endpoints_active: int
    runtime_type: str
    source: PluginInstallationSource
    meta: Mapping[str, Any]
    plugin_id: str
    plugin_unique_identifier: str
    version: str
    checksum: str
    declaration: PluginDeclaration
```

**5.A 借鉴**：
- Plan 01 已建 `workspace_plugin_installations` 表对应 Dify `PluginInstallation` — workspace_id（tenant_id）/ plugin_name（plugin_unique_identifier）/ plugin_version / status / config_json / credentials_json
- 凭据从 manifest 静态声明 → 通过 install API 由 user 配置 → 存 `credentials_json` JSONB → daemon spawn 时通过环境变量 / RPC params 注入 capability 实现
- **关键学习**：声明（manifest）vs 安装实例（installation）分离 — 同一 plugin 可在不同 workspace 用不同凭据
- 本 plan 02 capability Protocol 不直接接 credentials，但 Protocol 方法签名（如 `send_card(*, recipient, card, idempotency_key)` 全 keyword-only）便于后续 LegacyAdapter / Daemon facade 从 closure 注入凭据

**应用模块**：`IMCapability.send_card` 不含 credentials 参数（由 plugin 实例 __init__ 时持有 — 参考 Phase 4 FeishuProvider 模式）

---

### 5. Capability Declaration vs Runtime Entity 分离 → 5.A Manifest 声明 vs Capability instance

**Dify 源文件**：`api/core/plugin/entities/plugin.py` 第 70-141 行（PluginDeclaration）+ 第 157-165 行（PluginEntity）+ `api/core/plugin/entities/plugin_daemon.py` 第 47-67 行（各 Provider Entity）
- `PluginDeclaration` — 静态 manifest 字段（plugins / category / resource / tool / model / endpoint / ...）
- `PluginInstallation` extends BasePluginEntity — 运行时 installation 实例（tenant_id / plugin_id / installation_id）
- `PluginEntity` extends PluginInstallation — 添加 name + installation_id + version

**5.A 借鉴**：
- **静态声明层**（manifest）：YAML → Pydantic `PlatformManifest`（Plan 03） — 含 capabilities 列表 + 每 capability 的 supports_* flags
- **运行时实例层**（Capability Protocol）：Python class 实现各 Protocol — 实例化时持 daemon client / credentials
- 本 plan 02 实现的**仅是 Protocol 类型本身**（运行时实例层的契约），不实现具体 plugin
- Mock plugin（Plan 04）/ HulyPlugin daemon（Plan 07）/ LegacyIMAdapter（Plan 05）将分别提供具体实现

**应用模块**：本 plan 02 `IMCapability` / `DocCapability` Protocol 定义（不含实现）；isinstance check 通过 runtime_checkable 校验任何实现类满足契约

---

## 与本项目的关系（如何应用到 plan 05a-02）

本 plan 02 实现 ADR-001 §3.1（IMCapability）+ §3.2（DocCapability）+ exceptions 集中定义，是 Phase 5.A 6 Capability Protocols 的前 2 个。

### 输出文件 → 借鉴点映射

| 文件 | Dify 借鉴点 |
| --- | --- |
| `backend/app/agent_builder/platforms/__init__.py` | — (空 docstring，标 Phase 5.A 起点) |
| `backend/app/agent_builder/platforms/exceptions.py` | 借鉴 Dify `PluginDaemonError` + `PluginDaemonInnerError` 集中定义（plugin_daemon.py 第 126-141 行） |
| `backend/app/agent_builder/platforms/capabilities/im.py` | 借鉴点 #2（method 声明 → Protocol 方法签名）+ #3（每 capability 一 file） |
| `backend/app/agent_builder/platforms/capabilities/doc.py` | 借鉴点 #3（每 capability 一 file）+ 本项目独有：双路径 replace_document_content vs apply_document_delta（解决 Huly CRDT gap，Dify 无对应模式） |
| `tests/platforms/test_capabilities_im.py` | 借鉴点 #5（Declaration vs Runtime — runtime_checkable Protocol 允许 mock 类不继承也 pass isinstance） |
| `tests/platforms/test_capabilities_doc.py` | 借鉴点 #5 + 本项目独有：双 plugin 风格（Outline 全量替换 vs Huly CRDT）测试覆盖 |

### 不借鉴的部分（明确边界）

1. **Pydantic 校验** — 本 plan 02 capability 是 Protocol（duck typing），不需要 Pydantic 校验；Plan 03 manifest schema 才用 Pydantic
2. **泛型 Response envelope** — 留 Plan 06 daemon client 实现
3. **PluginInstallation 多字段** — 已在 Plan 01 简化为 `workspace_plugin_installations` 9 字段
4. **I18nObject 多语言 label** — v1 仅中文，不引入 I18n 抽象（v2 留口子）
5. **PluginResourceRequirements** — Phase 5.B 沙箱才需要资源限制，本 plan 02 不涉及

### License attribution

Dify 是 **AGPL-3.0**，本项目是 **Apache-2.0** — **严禁拷贝 Dify 源代码**。本文档列出的借鉴点全部为**设计模式 / 数据结构思路 / 边界考虑**层面，具体实现（Protocol 方法签名 / dataclass 字段 / 文件组织）为独立创作。

每条借鉴点已明确标注 Dify 源文件路径 + 章节锚点，便于审计对照。

---

## 后续 plan 关联

| 后续 Plan | 依赖本 plan 02 产出 | 用途 |
| --- | --- | --- |
| Plan 03 (manifest schema) | `capabilities: list[Literal["im","doc",...]]` 字面值集合 | manifest `capabilities` 字段类型约束 |
| Plan 03 (capabilities/__init__.py) | im.py + doc.py 已建立模块 | __init__.py export 6 capability 全集 |
| Plan 04 (PluginRegistry) | `IMCapability` / `DocCapability` 类型 | `get_capability(IMCapability, ...)` 路由 |
| Plan 05 (LegacyIMAdapter) | `IMCapability` Protocol + RecipientSpec + NormalizedCard + MessageRef | 包装 Phase 4 IMProvider 为新 IMCapability 实例 |
| Plan 06 (Mock + DaemonClient) | `IMCapability` + `DocCapability` | MockPlatformPlugin 声明实现 + daemon facade |
| Plan 07 (HulyPlugin acid test) | `IMCapability` + `DocCapability` + `MessageRef` + exceptions | HulyPlugin 实现 IMCapability.send_card 端到端 |

---

*Reading doc 完成日期：2026-05-17*
*下一步：commit 本文档（Task 0 硬性 gate）→ Task 1 写 exceptions + im.py + 单测*
