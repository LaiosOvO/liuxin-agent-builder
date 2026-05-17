# Dify 阅读笔记 — Capability Dispatch + Plugin Installer + Manager Lifecycle

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> Stars: ~141k
> Plan: Phase 5.C plan 07（capability-fallback / Wave 4）
> 必读文件: `api/core/workflow/node_factory.py` (24KB) / `api/services/plugin/plugin_service.py` (23KB) / `api/core/plugin/impl/plugin.py` (PluginInstaller) / `api/core/plugin/impl/base.py` (BasePluginClient daemon HTTP)

## 项目概述（一句话）

Dify 通过 **PluginService (services 层 orchestration + 权限/作用域控制) → PluginInstaller (core 层 daemon RPC client) → 远端 dify-plugin-daemon (Go) 进程** 三层架构管 plugin lifecycle；`DifyNodeFactory.create_node()` 在节点 config → Node 实例之间做 dispatch（基于 NodeType + version 双 key 查 registry + 注入 per-node-type init kwargs），跨各 NodeType 抽象统一执行入口 —— 我们 plan 07 借鉴这套**「services 层 orchestrate + per-tenant 隔离 + factory 内部 dispatch」**分层模式做 `DocCapabilityDispatcher`（业务 ↔ DocFacade 双路径路由）+ `PluginDiscoveryService`（workspace ↔ Registry/installations 表 wiring）。

## 技术栈（关键技术选择）

- **Pydantic v2 model**: PluginEntity / PluginInstallation / PluginInstallTask / PluginDeclaration / PluginDecodeResponse 校验所有 install request + daemon response（schema 化边界 — 我们对应 `PluginMetadata` / `InstalledPluginInfo` dataclass）
- **PostgreSQL + SQLAlchemy 2.0 Session**: `tenant_id` 作为所有 plugin 表的隔离 key（Provider / ProviderCredential / TenantPreferredModelProvider 全部按 `tenant_id` 切片）— 我们对应 `workspace_id` UUID（CLAUDE.md §2.4 多租户基线）
- **HTTPX Client (pooled)**: `BasePluginClient._request` 用模块级 pooled httpx.Client 调远端 daemon（`PLUGIN_DAEMON_URL` + `X-Api-Key` header + W3C `traceparent` 注入分布式 trace）— 我们对应 `PlatformDaemonClient` (Phase 5.A plan 05 freeze) 走 stdin/stdout JSONRPC subprocess
- **Redis SETEX 5min TTL**: `LatestPluginCache` 用 `plugin_service:latest_plugin:{plugin_id}` 缓存远端 marketplace 元数据，避免重复网络调用 — 我们对应 plan 07 `PluginDiscoveryService.list_available_plugins()` 由 `PlatformPluginRegistry.list_manifests()` 内存返回（manifest 已 Phase 5.A discover 时载入，无需 Redis）
- **任务状态枚举**: `PluginInstallTask` 含 `pending / running / success / failed` 状态机（异步 install）—— 我们 plan 07 install 是同步（无 marketplace 下载），所以 enum 简化为 `installed / disabled / error`
- **lru_cache(maxsize=1) registry bootstrap**: `register_nodes()` 用 `@lru_cache(maxsize=1)` 确保节点 self-register 只跑一次 —— 我们对应 `PlatformPluginRegistry._registered_plugins: dict` class-level 内存 store + `clear()` 测试钩子

## 架构要点

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Dify 四层（reference）             vs    agent-builder 三层（plan 07 借鉴）  │
├────────────────────────────────────────────────────────────────────────────┤
│  Console API controllers           │   FastAPI router (plan 04.5 加 wiring) │
│           ↓                        │           ↓                            │
│  services/plugin/PluginService     │   services/PluginDiscoveryService      │
│   (orchestrate + scope check)      │    (list/install/uninstall/list_installed)
│           ↓                        │           ↓                            │
│  core/plugin/impl/PluginInstaller  │   platforms/PlatformPluginRegistry     │
│   (HTTP RPC to dify-plugin-daemon) │    (in-process plugin instance pool)   │
│           ↓                        │           ↓                            │
│  远端 Go daemon process            │   stdin/stdout JSONRPC subprocess      │
│                                    │   (PlatformDaemonClient Phase 5.A)     │
└────────────────────────────────────────────────────────────────────────────┘

DifyNodeFactory.create_node() 节点 dispatch ↔  DocCapabilityDispatcher.write_document() 双路径 dispatch
─────────────────────────────────────────────────────────────────────────────
node_type → registry[NodeType][version] → Node 类  │  facade.supports_collaborative_edit + content kind →
       + per-node-type init_kwargs                  │  decide outcome → invoke right facade method
       (CODE / HTTP_REQUEST / HUMAN_INPUT / ...)    │   + structured log outcome
```

**Dispatcher 6 行为路径矩阵（plan 07 service layer 核心）：**

| 输入 content kind | facade.supports_collaborative_edit | outcome 标签                    | service 行为                                                                  |
|------------------|------------------------------------|---------------------------------|------------------------------------------------------------------------------|
| markdown         | False (Outline / Lark)             | `REPLACE_DIRECT`                | 直接 `facade.replace_document_content(doc_ref, markdown)`                     |
| markdown         | True (Huly)                        | `CONVERT_TO_DELTA`              | `markdown_to_prosemirror(markdown)` → CRDTDelta(format='prosemirror-json') → `facade.apply_document_delta(...)` |
| CRDTDelta        | False (Outline / Lark)             | `FALLBACK_TO_REPLACE`           | `prosemirror_to_markdown(delta.payload)` → markdown → `facade.replace_document_content(...)`（plan 05 forward 的镜像） |
| CRDTDelta        | True (Huly)                        | `DELTA_DIRECT`                  | 直接 `facade.apply_document_delta(doc_ref, delta)`                            |
| CRDTDelta (非 prosemirror-json) | False (Outline / Lark) | `ERROR_UNSUPPORTED_DELTA`       | 不能 fallback（无 forward serializer），raise `UnsupportedDeltaFormatError` + outcome log |
| 任意             | plugin 未在 workspace install      | `ERROR_PLUGIN_NOT_FOUND`        | `PluginDiscoveryService` 拒 install 触发；dispatcher 调 `registry.get_capability()` 返 None → raise `PluginNotInstalledError` |

每条路径都打 structured log（Pattern 7 §schema：`plugin_name + workspace_id + capability + method + latency_ms + outcome`），Phase 7 Run Viewer 可直接消费 outcome 字段画"实际走了哪条路"图。

## 可借鉴的设计模式

1. **Dispatch envelope vs. direct facade call**（`api/core/workflow/node_factory.py:359` `DifyNodeFactory.create_node` + `:379` `node_init_kwargs_factories` Mapping）— Dify NodeFactory 在 graph_config dict → Node 实例之间塞一层 dispatcher 做（a）NodeType → 类查找（b）per-NodeType init_kwargs 注入两件事，业务（graphon 图引擎）无需感知 13 种 NodeType 各自的构造细节。**5.C plan 07 借鉴 → `backend/app/agent_builder/services/doc_capability_dispatcher.py`**：DocCapabilityDispatcher 在业务（DAG `doc_write` 节点 / 直接 service 调用）和 DocFacade 之间塞一层做（a）supports_collaborative_edit 路由（b）delta↔markdown 自动 serialize 两件事。业务调 `dispatcher.write_document(workspace_id, doc_ref, content)`，不感知 3 plugin 哪个支持 CRDT。**不拷代码，仅借鉴分层 + 内部 mapping 的工厂模式**。

2. **install_plugin 幂等性 + ON CONFLICT 升级**（`api/services/plugin/plugin_service.py:277` `upgrade_plugin_with_marketplace` 先 `fetch_plugin_manifest` 检测已装 → 若装过仅 record event 不重下，未装才 download + upload + `install_from_identifiers`）— Dify 同 plugin 重复 install 自动走 upgrade 分支，对客户端幂等。**5.C plan 07 借鉴 → `backend/app/agent_builder/services/plugin_discovery.py`** `install_plugin(workspace_id, plugin_name, config)`：先 SELECT `workspace_plugin_installations WHERE (workspace_id, plugin_name)`；若存在则 UPDATE `version + config_json + updated_at=NOW()`，不存在则 INSERT；语义即 UPSERT，对调用者幂等（同 plugin 重复 install 不报错，仅升级 config）。SQLAlchemy 2.0 用 `insert(...).on_conflict_do_update(...)` postgres dialect 写法。

3. **list_plugins 返回字段 schema（Pydantic 边界 + 必要字段抽取）**（`api/services/plugin/plugin_service.py:163` `list` / `:172` `list_with_total` + `api/core/plugin/impl/plugin.py:60` `PluginInstaller.list_plugins` 返回 `PluginEntity` 列表）— Dify 给前端的 plugin metadata 含 `plugin_id / plugin_unique_identifier / declaration / version / status / installation_id / source / tenant_id / installed_at`，**clear separation between 已装实例 (PluginInstallation) vs 静态 manifest (PluginDeclaration)**。**5.C plan 07 镜像 → 两个 dataclass**：(a) `PluginMetadata` 用于 `list_available_plugins()` 返回 `(name, version, capabilities: list[str], supports_collaborative_edit: bool, sandbox_required: bool)` —— 从 manifest 静态读，不含 workspace state；(b) `InstalledPluginInfo` 用于 `list_installed(workspace_id)` 返回 `(name, version, status, installed_at, config_keys: list[str]（脱敏，仅 key 不含 value）)` —— 从 `workspace_plugin_installations` 表读。**前端可分别画"市场列表"与"已装管理"两个 UI**，与 Dify Marketplace + 工作区已装两 tab 一致。

4. **Plugin lifecycle daemon 优雅 dispose + force-kill 兜底**（`api/core/plugin/impl/plugin.py:247` `PluginInstaller.uninstall` POST `/uninstall` + `api/services/plugin/plugin_service.py:516` `PluginService.uninstall` 先 `list_plugins` 查 `installation_id` → 然后 `with Session(...).begin()` 事务级清 ProviderCredential + Provider.credential_id → 最后才调 `manager.uninstall(...)` 关 daemon）— Dify uninstall 是**三阶段**：① 查到对象 ② 先在 DB 事务内清所有衍生记录 ③ 最后才让 daemon 关掉远端进程；**顺序很关键 — 不让"daemon 已关但 DB 还引用"成为可能状态**。**5.C plan 07 借鉴 → `PluginDiscoveryService.uninstall_plugin(workspace_id, plugin_name)`** 也分三阶段：① SELECT 拿 `WorkspacePluginInstallation` 行；② `PlatformPlugin = await PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)`；③ 顺序 `await plugin.detach_daemon()`（内部走 `PlatformDaemonClient.close()` Phase 5.A plan 05）→ UPDATE `status='disabled'` → 不删行（保留 audit）。Phase 5.B `IdleDaemonReaper` 是 force-kill 兜底（idle 阈值 5min 自动回收）— **显式 uninstall 路径 + 隐式 reaper 双路径**与 Dify "uninstall RPC + daemon 主动 GC" 双路径设计一致。

5. **per-tenant scoping 第一参数纪律**（`api/services/plugin/plugin_service.py` 所有 `@staticmethod` 第一参数都是 `tenant_id: str`；`api/core/plugin/impl/plugin.py` 所有 PluginInstaller 方法也都首参 `tenant_id: str`，URL path 内嵌 `f"plugin/{tenant_id}/management/..."`）— Dify 把多租户隔离做成**纪律式 API 形状**：你想调 plugin 任意操作必须先有 `tenant_id`，从静态方法到 daemon HTTP URL 一路传到底。**5.C plan 07 镜像 → CLAUDE.md §2.4 基线**：`PluginDiscoveryService` 所有方法**第一参数 `workspace_id: UUID`**，下传给 `PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)` 触发 lazy spawn（registry 维护 `(workspace_id, plugin_name) → PlatformPlugin` 字典）。**关键差异**：(i) 我们用 `UUID` 不用 `str`（类型更强）；(ii) 我们的隔离粒度是 `workspace`（项目空间）而非 Dify 的 `tenant`（租户）—— 概念对齐但范围更细。**与 `WorkspaceScopedQuery`（CLAUDE.md §2.4）配合**：所有 `select(WorkspacePluginInstallation)` 自动注入 `WHERE workspace_id = :current_workspace`，双层防护（service 层显式参数 + ORM 层透明过滤），双 workspace 互访某 plugin = 必 0 行返回。

6. **Structured logging outcome 字段 + Phase 7 Run Viewer 钩子**（`api/core/plugin/impl/base.py:54` 模块级 `logger = logging.getLogger(__name__)` + 各方法 `logger.exception(...)` 在异常路径打 trace + `_inject_trace_headers` 注 W3C `traceparent` 给 daemon 端 OTEL collector 接力）— Dify 把每条 daemon RPC 都通过 traceparent 串成跨进程 trace，前端 Run Viewer 能完整还原一次 plugin call 的端到端时间线。**5.C plan 07 借鉴 → 05c-RESEARCH.md §Pattern 7 structured log schema**：`DocCapabilityDispatcher.write_document()` 用 `log_capability_call(plugin_name, capability='doc', method='write_document', latency_ms, outcome)` 装饰 — `outcome` 必填取值 = 上面 6 路径矩阵的 6 个标签之一（`REPLACE_DIRECT / FALLBACK_TO_REPLACE / CONVERT_TO_DELTA / DELTA_DIRECT / ERROR_UNSUPPORTED_DELTA / ERROR_PLUGIN_NOT_FOUND`）。**Phase 7 Run Viewer UI 直接消费 `outcome` 字段画桑基图**：业务调用→实际走的路径分布，运维一眼看出"Outline 用户多少 % 在写 delta 触发 fallback"，可指导后续是否换 Huly。`workspace_id` 由 `contextvars.ContextVar` 注入（FastAPI middleware 设 → 异步透传 — 跨 task 边界仍可读到），不污染方法签名。

## 与本项目的关系

本 plan 07 实现 service layer 双能力（**capability dispatch + plugin discovery**），是 Phase 5.C plan 03（Outline）/04（Lark Docs）/05（Huly）三 plugin facade 的**统一用户入口**。没有 plan 07，三 plugin facade 是"孤儿组件" — 业务 / DAG 节点不知道哪个 facade 支持 CRDT、不知道收 delta 时该怎么 fallback、不知道 plugin 怎么按 workspace 装上来。

- **服务于 Wave 4 并行 plan 06**：plan 06 扩 DocCapability Protocol v1.1 加 `ai_suggest_mentions`，plan 07 仅用 v1 接口做路由 — 两 plan 在 capabilities/ 目录正交（plan 06 改 Protocol 定义，plan 07 只读 Protocol 写 service），可真并行不冲突。
- **服务于 v1.5 DAG 节点接入**：当 Phase 5.C 末或 v1.5 引入 `doc_write` / `doc_mention` 节点时，节点 handler 只需调 `DocCapabilityDispatcher.write_document(...)` 一次，不感知 3 plugin 哪个支持 CRDT — 与 Dify NodeFactory 节点 → runtime dispatch 思想一致。
- **服务于 Phase 7 Run Viewer**：dispatcher structured log outcome 字段直接喂前端运行可视化（CLAUDE.md §节点可视化硬性要求），不需 v1.5 再额外加埋点。
- **服务于多租户隔离基线**：`PluginDiscoveryService` 所有方法首参 `workspace_id` + `WorkspaceScopedQuery` 透明过滤（CLAUDE.md §2.4），与 Dify per-tenant 纪律一致；E2E 双 workspace 互访 plugin install 行必 403 / 空集。

**License attribution**: Dify 是 **AGPL-3.0**；本项目（agent-builder）是 **Apache-2.0**（与 flock 一致）。本 plan 07 **不引入任何 Dify import**、**不拷贝任何源代码**；仅借鉴：(i) 三层分层架构思想（services orchestrate / impl RPC client / daemon process）；(ii) per-tenant 第一参数纪律；(iii) install 幂等 UPSERT 设计；(iv) uninstall 三阶段顺序（DB 清理先于 daemon 关闭）；(v) 跨进程结构化 log + trace 注入思想；(vi) NodeFactory 内部 dispatch + per-type init_kwargs 工厂模式思想。每条借鉴点上面已明确写出 source file → target module 对应关系。每个新代码文件首注释加 `# Inspired by Dify (AGPL-3.0) design patterns; reimplemented under Apache-2.0; no source code copied.`（与 Phase 5.C plan 02-05 hr/offboarding-flow port 一致防御口径）。
