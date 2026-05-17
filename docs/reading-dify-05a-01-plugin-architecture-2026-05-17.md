# Dify 阅读笔记 — Plugin Architecture（Phase 5.A 工程底座）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (local clone `/Users/admin/ai/ref/dify/repo/`, AGPL-3.0)
> Stars: ~141k
> 阅读范围: `api/core/plugin/entities/{plugin,bundle,endpoint,plugin_daemon}.py` + `api/services/plugin/plugin_service.py`

---

## 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 应用平台；其 plugin 系统通过 YAML **manifest + 外部 daemon 进程** 实现第三方扩展（model / tool / agent / endpoint / datasource / trigger），plugin 完全独立运行时、热加载、不依赖核心代码改动。

---

## 技术栈（关键技术选择）

| 维度 | Dify 实现 | 我们借鉴度 |
| --- | --- | --- |
| Manifest schema 校验 | Pydantic v2 `BaseModel` + `Field(pattern=...)` + `@field_validator` | ✅ 同栈复用 |
| Plugin 元数据 storage | PostgreSQL（`plugins` / `plugin_installations` 等表）+ Redis 缓存 | ✅ Phase 5.A 复用：`workspace_plugin_installations` 表 |
| RPC envelope | `PluginDaemonBasicResponse[T]` 泛型（`code` + `message` + `data: T`） | ✅ 5.A 借鉴：JSONRPC envelope schema |
| Daemon runtime | Go 实现的 `dify-plugin-daemon`（独立仓库） | ❌ 我们 Python only（v1） |
| Plugin discovery | 启动期 + Marketplace HTTP API | ✅ 启动期 file system scan |
| Install 状态机 | `PluginInstallationSource` enum（Github / Marketplace / Package / Remote）+ install task event stream | ✅ 5.A 简化：`status IN ('installed','disabled','error')` |
| 资源限制 | `PluginResourceRequirements`（memory + permission scopes） | ⏸ Phase 5.B 落地 cgroups v2 |

---

## 架构要点（核心架构模式）

Dify plugin 分 4 层（自顶向下）：

```
┌─────────────────────────────────────────────────────────────┐
│  1. Marketplace / Github / Package source                   │  ← 第三方发布渠道
└─────────────────────────────────────────────────────────────┘
                              ↓ download_plugin_pkg
┌─────────────────────────────────────────────────────────────┐
│  2. Declaration (static manifest)                           │
│     PluginDeclaration { name, version, author, category,    │
│                          resource, plugins, tool/model/... } │
└─────────────────────────────────────────────────────────────┘
                              ↓ install (per-tenant)
┌─────────────────────────────────────────────────────────────┐
│  3. Installation (DB row, per-tenant state)                 │
│     PluginInstallation { plugin_id, tenant_id, version,     │
│                          source, meta, ... }                 │
└─────────────────────────────────────────────────────────────┘
                              ↓ runtime invoke
┌─────────────────────────────────────────────────────────────┐
│  4. Daemon runtime (out-of-process)                         │
│     PluginEntity + PluginDaemonBasicResponse[T] over RPC    │
└─────────────────────────────────────────────────────────────┘
```

**关键观察**：

- **Declaration ≠ Installation ≠ Runtime Entity**：三个不同的 Pydantic model，分别对应 `manifest 文件`、`per-tenant DB row`、`daemon 实时返回`。**我们 Phase 5.A 复用此三层分离**，对应：
  - `PlatformManifest`（YAML manifest，静态声明）— 后续 Plan 03
  - `WorkspacePluginInstallation`（DB ORM model，per-workspace 启用态）— **本 plan 实现**
  - `PlatformPlugin`（runtime facade，含 daemon client）— 后续 Plan 05+
- **RPC envelope 用泛型**：`PluginDaemonBasicResponse[T: BaseModel | dict | list | bool | str]`，统一 `code` + `message` + `data` 三字段，错误码可解释。
- **Plugin discovery 启动期 scan + 懒加载 daemon**：避免启动慢 + plugin 异常拖死服务。
- **License 严格**：Dify 是 AGPL-3.0，我们 Apache-2.0；**禁止拷贝源码**，仅借鉴**设计模式 / 数据结构思路**。

---

## 可借鉴的设计模式

### 1. Declaration vs Installation 分离（plugin.py PluginDeclaration vs services/plugin_service.py PluginInstallation 流转）

**Dify 源文件**：`api/core/plugin/entities/plugin.py` 行 70-114（`PluginDeclaration`）+ `api/services/plugin/plugin_service.py` 行 16-30（`PluginInstallation` 流转）

**模式**：静态 manifest（plugin 本体声明）与 per-tenant 安装态（DB 持久化的"哪个 workspace 装了哪个 plugin 的哪个版本"）严格分离。Declaration 只读、跨 tenant 共享；Installation 可变、per-tenant。

**5.A 应用**：
- `PlatformManifest`（Pydantic schema）对应 Declaration — Plan 03 实现
- **本 plan 实现的 `WorkspacePluginInstallation` ORM** 对应 Installation — 字段 `workspace_id × plugin_name` 唯一约束保证 per-tenant 隔离 + `status` 状态机（installed/disabled/error）

**Target 模块**：`backend/app/agent_builder/models/workspace_plugin_installation.py`（本 plan Task 1）

---

### 2. PluginDaemonBasicResponse 泛型 envelope（plugin_daemon.py 行 23-30）

**Dify 源文件**：`api/core/plugin/entities/plugin_daemon.py` 行 23-30

**模式**：所有 daemon RPC 响应统一 envelope：
```
PluginDaemonBasicResponse[T] = { code: int, message: str, data: T | None }
```
泛型 T 约束 `result` 类型，调用方拿到结构化错误码 + 类型安全的 data。

**5.A 应用**：JSONRPC over stdio 的 envelope 借鉴 — Plan 06 daemon client 时按 JSON-RPC 2.0 规范实现 4 字段 envelope（`jsonrpc` / `id` / `method` / `params` 请求；`jsonrpc` / `id` / `result|error` 响应），错误码定义沿用 JSON-RPC 标准（-32601 method not found，-32603 internal error）。

**Target 模块**：`backend/app/agent_builder/platforms/daemon_client.py`（Plan 06 实现）

---

### 3. PluginInstallTask 状态机 enum（plugin_daemon.py InstallPluginMessage.Event）

**Dify 源文件**：`api/core/plugin/entities/plugin_daemon.py` 行 33-44（`InstallPluginMessage.Event`：`Info` / `Done` / `Error`）

**模式**：plugin install 是异步流程（download → verify → register → activate），用 event stream 推进状态机；终态 enum 强 typed。

**5.A 应用**：**本 plan migration 0006** `workspace_plugin_installations.status` 列 + CHECK constraint `status IN ('installed','disabled','error')`：
- `installed` — 装好可用
- `disabled` — 临时禁用（凭据失效 / 用户手动停用）
- `error` — 启动 daemon 失败 / manifest 校验失败

**Target 模块**：`backend/migrations/versions/0006_phase5a_plugin_installations.py`（本 plan Task 1）— `CheckConstraint("status IN ('installed', 'disabled', 'error')", name="ck_plugin_status")`

---

### 4. EndpointProviderDeclaration capability 按 type 分组（endpoint.py 行 21-27）

**Dify 源文件**：`api/core/plugin/entities/endpoint.py` 行 11-27（`EndpointDeclaration` + `EndpointProviderDeclaration`）

**模式**：manifest 中按 capability type（tool / model / endpoint / agent / datasource / trigger）分组声明能力；plugin 可选实现任意子集。

**5.A 应用**：`PlatformManifest.capabilities: list[Literal["im", "doc", "hr", "identity", "trigger", "tool"]]` —  plugin 在 manifest 中声明本 plugin 实现哪些 capability，Registry 启动期 isinstance 校验。**本 plan 不实现 manifest（Plan 03），但 `workspace_plugin_installations.config_json` JSONB 列设计为容纳各 capability 的 per-workspace 配置**（如 `{"endpoint": "https://huly.xxx", "auth_token": "..."}`）。

**Target 模块**：`backend/app/agent_builder/platforms/manifest.py`（Plan 03 实现）

---

### 5. PluginBundleDependency 跨 plugin 依赖声明（bundle.py 行 8-30）

**Dify 源文件**：`api/core/plugin/entities/bundle.py` 行 8-30（`PluginBundleDependency` + 3 source type：Github / Marketplace / Package）

**模式**：plugin 可声明依赖其他 plugin（bundle），install 时按依赖图拓扑序安装；3 种 source（Github / Marketplace / Package）覆盖不同分发渠道。

**5.A 应用（暂不做）**：**Phase 5.A 不实现 plugin bundle 依赖**（YAGNI — v1 只有 huly + legacy IM provider，没跨 plugin 依赖场景）。**留 Phase 6 marketplace 时实现** — Phase 6 PLUG-01..04 范畴。

**未来 Target 模块**：`backend/app/agent_builder/platforms/bundle.py`（Phase 6 实现）

---

## 与本项目的关系

本 plan（Plan 05a-01）是 Phase 5.A 的**工程底座**，对应借鉴点 #1（Declaration vs Installation 分离）和 #3（PluginInstallTask 状态机）：

| 本 plan 产出 | Dify 借鉴点 | 后续 plan 依赖 |
| --- | --- | --- |
| `WorkspacePluginInstallation` ORM | #1 Installation 层抽象 | Plan 04 Registry 用此表查 plugin 启用状态 |
| Migration 0006（workspace_id × plugin_name 唯一约束）| #1 per-tenant 隔离 | Plan 07 HulyPlugin acid test 需要持久化 install record |
| `status` 列 CHECK constraint | #3 PluginInstallTask 状态机简化 | Plan 04 install/disable 流程写状态 |
| `config_json` / `credentials_json` JSONB | #4 capability config 分组思路 | Plan 03 manifest config_schema 解析后写此列 |
| `tests/platforms/conftest.py` 共享 fixture | （工程实践，非 Dify 借鉴）| Plan 02-07 所有 platform 测试都用此 fixture |

后续 plan 02-07 实现 Capability Protocols / Manifest / Registry / Daemon Client / HulyPlugin acid test 时，都会写各自的 reading doc 借鉴 Dify 对应模块（详见 `05a-RESEARCH.md` 的 Dify Reference Mapping 表）。

---

## License attribution

**Dify** 是 **AGPL-3.0**（要求衍生闭源 SaaS 也需开源）；本项目 **agent-builder** 是 **Apache-2.0**（与 fork 源 flock 一致）。

**严守规则**（CLAUDE.md §2.7）：
- ✅ **可借鉴**：设计模式（如 declaration/installation 分离）、数据结构思路（如三层模型）、边界考虑（如 install 状态机 enum、capability 按 type 分组）
- ❌ **严禁拷贝**：Dify 源代码片段（哪怕是 1-2 行 Pydantic field 声明也不抄）
- 📝 **实现独立**：每条借鉴点都明确标注 source file → target module 的对应关系，确保是**独立创作**而非"换名字的复制"

每条借鉴点已明确写出 Dify 源文件路径 + 我们要写的目标模块路径，方便 code review 时机械化对照检查。

---

## 附录：本 plan 借鉴点速查表

| # | Dify 源文件 | 借鉴模式 | 5.A target 模块 | Status |
| - | --- | --- | --- | --- |
| 1 | `api/core/plugin/entities/plugin.py` (PluginDeclaration vs PluginInstallation) | Declaration vs Installation 分离 | `backend/app/agent_builder/models/workspace_plugin_installation.py` | ✅ 本 plan |
| 2 | `api/core/plugin/entities/plugin_daemon.py` (PluginDaemonBasicResponse 泛型) | RPC envelope 泛型约束 | `backend/app/agent_builder/platforms/daemon_client.py` | ⏸ Plan 06 |
| 3 | `api/core/plugin/entities/plugin_daemon.py` (InstallPluginMessage.Event) | Install 状态机 enum | `backend/migrations/versions/0006_phase5a_plugin_installations.py` (status CHECK) | ✅ 本 plan |
| 4 | `api/core/plugin/entities/endpoint.py` (EndpointProviderDeclaration) | Capability 按 type 分组 | `backend/app/agent_builder/platforms/manifest.py` | ⏸ Plan 03 |
| 5 | `api/core/plugin/entities/bundle.py` (PluginBundleDependency) | 跨 plugin 依赖（YAGNI v1 不做）| `backend/app/agent_builder/platforms/bundle.py` | ⏭ Phase 6 |

---

*Reading doc 完。本文档是 Plan 05a-01 的 Task 0 硬性 gate（CLAUDE.md §2.7），先 commit 才允许写代码。*
