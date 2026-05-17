# Dify 阅读笔记 — Plugin Manifest + PluginService + Permission（Phase 5.A Plan 04 必读）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> Phase 5.A 适用范围：Plan 04 — PlatformManifest schema + PlatformPluginRegistry per-workspace 隔离

## License Attribution（强制硬性）

- **Dify 仓库 License**: AGPL-3.0
- **本项目 License**: Apache-2.0
- **本笔记内容**：仅借鉴**设计模式 / 数据结构思路 / 边界考虑**；**严禁直接拷贝任何 Dify 源代码**到本项目仓库
- 后续 Plan 04 实现 PlatformManifest / PlatformPluginRegistry 时，所有代码 100% 独立创作（即使「几乎一样」也重写一遍换语法），仅在 docstring 中注明 "Reference: Dify XXX (AGPL-3.0)"

## 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 应用平台（141k stars），其 plugin 子系统提供 marketplace / github / package 三种安装来源、tenant-scoped 隔离、daemon 子进程沙箱、resource quota 限制 — 是本项目 5.A Plan 04 PlatformPluginRegistry 的核心参考样本（CLAUDE.md §2.7 强制 reference-first）。

## 阅读源文件

| Dify 源文件 | 行数 | 阅读重点 |
|---|---|---|
| `api/core/plugin/entities/plugin.py` | 204 | PluginDeclaration / PluginInstallation / PluginEntity 三段式 + PluginResourceRequirements 资源限制结构 + StrEnum auto pattern |
| `api/services/plugin/plugin_service.py` | 600 | static method-only Service 风格 / tenant_id 显式入参 / Installer 子模块代理 / 多 source（marketplace/github/package）install 流程 |
| `api/services/plugin/plugin_permission_service.py` | 35 | TenantPluginPermission 简化 ACL（install_permission / debug_permission 二字段）/ session_factory + session.begin() transaction 模式 |

## 技术栈

- **Pydantic v2**: BaseModel + Field validator + model_validator(mode="before") + StrEnum auto
- **packaging.version**: SemVer 校验（InvalidVersion 异常专门处理）
- **SQLAlchemy 2.0**: Session 接口（sync style，Dify 是 sync ORM；本项目走 AsyncSession）
- **Redis**: LatestPluginCache TTL 缓存（5min）+ marketplace manifest 缓存
- **嵌套类**: PluginDeclaration.Plugins / Meta，PluginResourceRequirements.Permission.Tool/Model/Node/Endpoint/Storage — 多层嵌套表达 Permission grants 矩阵

## 架构要点

```
┌─────────────────────────────────────────────────┐
│ Layer 1: Declaration（静态层，manifest 共享）    │
│   PluginDeclaration                              │
│   ├── meta (minimum_dify_version, version)       │
│   ├── plugins.{tools, models, endpoints, ...}    │
│   ├── tool / model / endpoint / datasource ...   │
│   └── resource.permission.{tool, model, ...}     │
└─────────────────────────────────────────────────┘
                       │
                       ▼ 实例化（per tenant）
┌─────────────────────────────────────────────────┐
│ Layer 2: Installation（per-tenant 持久化）      │
│   PluginInstallation                             │
│   ├── tenant_id (key)                            │
│   ├── plugin_id / plugin_unique_identifier       │
│   ├── version / checksum                         │
│   ├── declaration (frozen snapshot at install)   │
│   ├── source (Github/Marketplace/Package/Remote) │
│   └── runtime_type                               │
└─────────────────────────────────────────────────┘
                       │
                       ▼ 运行时
┌─────────────────────────────────────────────────┐
│ Layer 3: Entity（运行时实例）                    │
│   PluginEntity(PluginInstallation)               │
│   ├── name / installation_id                     │
│   └── @model_validator(mode='after')             │
│       └── set_plugin_id() —— 回填 declaration.tool.plugin_id │
└─────────────────────────────────────────────────┘

PluginService.{list, install, upgrade, delete, ...}（静态方法层）
  ↓ 代理给
PluginInstaller (impl/plugin.py)
  ↓ HTTP/gRPC 通信
PluginDaemon (独立 Go 进程)
  ↓ 启动子进程
PluginProcess (Python sandbox)
```

## 可借鉴的设计模式

### 1. PluginDeclaration 用 Pydantic BaseModel + Field validator → 5.A PlatformManifest 沿用

**Dify 源 (`plugin.py:70-141`)**：
- `PluginDeclaration(BaseModel)` 含 `version: str = Field(...)` + `@field_validator("version")` 用 `packaging.version.Version(v)` 校验 SemVer
- `name` 用 pattern: `r"^[a-z0-9_-]{1,128}$"` —— Dify 比我们宽松（允许首字符为数字）
- `author` 用 pattern: `r"^[a-zA-Z0-9_-]{1,64}$"` —— Dify 允许大小写

**5.A Plan 04 应用**：
- 我们 `PlatformManifest.name = Field(pattern=r"^[a-z][a-z0-9_-]{2,31}$")` —— 首字符强制小写字母 + 长度 ≥ 3 + ≤ 32（更严，便于 daemon 进程名 / 文件路径生成）
- `version = Field(pattern=r"^\d+\.\d+\.\d+$")` —— 仅接受三段 SemVer（Dify 用 `Version()` 接受 dev/rc 后缀，我们 v1 简化）
- 沿用 `@field_validator + raise ValueError` 模式让错误信息 surfaceable

**License**: Dify 该段实现 AGPL-3.0；我们独立用 Pydantic 标准 API 重写，不拷代码

### 2. PluginCategory StrEnum auto → 5.A capabilities Literal multi-select

**Dify 源 (`plugin.py:61-67`)**：
```python
class PluginCategory(StrEnum):
    Tool = auto()
    Model = auto()
    Extension = auto()
    AgentStrategy = "agent-strategy"
    Datasource = "datasource"
    Trigger = "trigger"
```
StrEnum + auto() 自动用类属性名小写化；显式覆盖（如 `"agent-strategy"`）混合用法。
注意 Dify 的 plugin **单 category**（一个 plugin 只能是 Tool 或 Model 或 ...）。

**5.A 关键差异**：我们的 plugin 是**多 capability** —— 一个 HulyPlugin 同时含 im + doc + hr + identity 4 capability。
所以 5.A Plan 04 用 `list[Literal["im","doc","hr","identity","trigger","tool"]]` 而非 StrEnum 单选。
Plan 03 已在 capabilities/__init__.py 完成 6 capability re-export，Plan 04 manifest 消费它们做 capabilities 字段。

**License**: 借鉴 Literal multi-select 思路（独立创作，非 Dify 设计）

### 3. PluginInstallation 含 tenant_id × plugin_id 唯一 → 5.A workspace_plugin_installations 表对应

**Dify 源 (`plugin.py:143-154`)**：
```python
class PluginInstallation(BasePluginEntity):
    tenant_id: str
    plugin_id: str
    plugin_unique_identifier: str
    version: str
    checksum: str
    declaration: PluginDeclaration  # frozen snapshot
    source: PluginInstallationSource  # github/marketplace/package
    runtime_type: str
```
关键：
- `declaration` 字段是 **frozen snapshot**（install 那一刻的 manifest），不是动态指针 —— 防 marketplace 升级 manifest 把已装 plugin 玩坏
- `tenant_id` 显式列（不依赖 ORM relationship 隐式加 WHERE）
- `checksum` 防 manifest tamper

**5.A Plan 01 已实现 `workspace_plugin_installations` 表**：
- `workspace_id` × `plugin_name` 唯一约束（对应 Dify tenant_id × plugin_id）
- `plugin_version` TEXT NOT NULL（对应 Dify version）
- `config_json` JSONB（对应 Dify declaration.runtime config，但简化无 frozen snapshot —— v1 不做 declaration snapshot，依赖 plugins/ 文件系统 git 同源审计）
- 未来 v2 若加 marketplace 上传场景再加 checksum + manifest_snapshot_json

**5.A Plan 04 应用**：
- `PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)` 内部 key 是 `(workspace_id, plugin_name)` tuple —— **Pitfall 5 防护**（双 workspace 不串）
- v1.1 plan 04 暂不强制查 DB `workspace_plugin_installations` 表（plan 05+ install lifecycle 加入后再校验）

**License**: 借鉴 tenant scoping 模式（独立用 SQLAlchemy 2.0 + AsyncSession 重写，不拷 Dify ORM）

### 4. PluginService.{list, install, ...} static method-only → 5.A PlatformPluginRegistry classmethod-only

**Dify 源 (`plugin_service.py:45+)**：
- `class PluginService` 内全部 `@staticmethod` 或 `@classmethod`
- 不持实例状态 —— state 全在 `PluginInstaller()` 子模块 / DB / Redis
- `tenant_id: str` 永远是第一参 —— **显式 tenant 隔离**（不依赖 ThreadLocal / ContextVar 隐式）

**5.A Plan 04 应用**：
- `PlatformPluginRegistry` 也用 `@classmethod` 全静态 + 模块级 `_MANIFESTS / _PLUGINS` dict
- `workspace_id: uuid.UUID` 永远是 `get_plugin / get_capability` 第一参 —— 同样**显式 workspace 隔离**
- 不引入 PluginInstaller 中间层（v1 不做 marketplace install 流程，plugins/ 直接文件系统扫）

**对比 Dify 的取舍**：Dify 多 source（marketplace / github / package / remote）→ 需要 PluginInstaller 抽象层封装通信细节；本项目 v1 仅 git 同仓 plugins/，直接 `load_manifest(path)` 简化

**License**: 借鉴 static method + tenant_id 显式入参模式（独立创作 PlatformPluginRegistry，不拷 PluginService 代码）

### 5. plugin_permission_service per-tenant ACL 思路 → 5.A 双 workspace 隔离测试

**Dify 源 (`plugin_permission_service.py`)**：
- `TenantPluginPermission` 表：tenant_id × install_permission × debug_permission
- `get_permission(tenant_id)` 必显式 `WHERE tenant_id == ...`
- `change_permission` 在事务内 `session.begin()` 保证 atomic update

**5.A Plan 04 应用**（Pitfall 5 核心防护测试）：
- `test_two_workspaces_isolated`：双 workspace 调 `get_plugin` 必拿不同 instance（`plugin_a is not plugin_b`）
- `test_get_capability` 在 prefer 参数走 candidates 列表时按 workspace_id 严格 scope
- 未来 v2 + plugin marketplace 上传 → 加入 `WorkspacePluginPermission` 表（参考 Dify 的 install_permission / debug_permission）

**License**: 借鉴 per-tenant ACL 显式 scope 思路（独立用 pytest fixture 写测试，不拷 Dify 实现）

### 6. 启动期 vs 懒加载分离 → 5.A discover 启动期 / get_capability 才 spawn daemon

**Dify 源 (推断自 `PluginInstaller.list_plugins` 调用模式)**：
- Dify 启动期不主动 spawn daemon —— PluginDaemon 是独立 Go 进程，由 Kubernetes / supervisor 启动
- `PluginService.list(tenant_id)` 只查 DB metadata（不触发 plugin 进程）
- 运行时 `invoke_tool(...)` 时才走 daemon 通信

**5.A Plan 04 应用**（CONTEXT.md 决策：「启动期扫描 manifest + 懒加载 daemon」）：
- `PlatformPluginRegistry.discover(plugins_root)` 启动期 scan plugins/*/platform.yaml → 仅 load manifest 入 _MANIFESTS dict（**不 spawn daemon**）
- `PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)` 首次调用才 `PlatformPlugin(manifest, daemon=None)`（v1.1 Plan 04 daemon 暂 None；Plan 05 注入真 client）
- `PlatformPlugin.im / .doc / ...` lazy property + cache —— 二次访问同一 capability 返回同一 facade instance（cache）

**性能收益**：启动期 manifest 校验 + Registry 注册 = O(N plugins) 文件 I/O；daemon 进程仅在真用时启 —— 1000 个 plugins 安装但只有 10 个被用时省 990 个进程

**License**: 借鉴启动期分离 + 懒加载思路（独立 Python 实现，不拷 Dify）

## 与本项目的关系

### Plan 04 直接应用清单

1. **PlatformManifest Pydantic schema**（借鉴点 #1）：
   - 文件 `backend/app/agent_builder/platforms/manifest.py`
   - `model_config = ConfigDict(extra="forbid")` 严格模式（CONTEXT.md 强制决策；防 typo）
   - 字段：name / version / description / license / agent_builder_version / runtime / capabilities / config_schema / im / doc / hr / identity / sandbox
   - 嵌套 `RuntimeConfig` / `CapabilitySpec` / `SandboxConfig`（沿用 Dify 嵌套类组织风格，但**字段语义独立**）

2. **load_manifest(path) 函数**（借鉴点 #1 + #3）：
   - 走 `yaml.safe_load`（Pitfall 3 防注入）
   - 异常翻译为 `ManifestValidationError`（沿用 Phase 5.A Plan 02 已建 PluginError 家族）
   - 返回 frozen PlatformManifest instance —— **v1 暂不做 declaration snapshot 加密**（plugins/ 文件系统 git 同源审计）

3. **PlatformPlugin lazy facade**（借鉴点 #6）：
   - `backend/app/agent_builder/platforms/plugin.py`
   - `@property im / doc / hr / identity` —— 都 wrap 同一个 `_daemon: PlatformDaemonClient | None`
   - Plan 04 实现时 `_daemon = None`，留 Plan 05 注入
   - `_cap_cache: dict[str, Any]` —— 同 workspace 二次访问 .im 返回同 facade instance

4. **PlatformPluginRegistry**（借鉴点 #3 + #4 + #5 + #6）：
   - `backend/app/agent_builder/platforms/registry.py`
   - 模块级 classmethod-only：`_MANIFESTS: dict[str, PlatformManifest]` + `_PLUGINS: dict[tuple[uuid.UUID, str], PlatformPlugin]`
   - 4 核心方法：`discover(plugins_root)` / `get_plugin(workspace_id, plugin_name)` / `get_capability(workspace_id, capability_type, prefer)` / `clear()` (测试用)
   - **Pitfall 5 防护**：`_PLUGINS` key 是 (workspace_id, plugin_name) tuple —— 测试 `test_two_workspaces_isolated` 必证

5. **capability_facades stub**（Plan 04 新增需求）：
   - `backend/app/agent_builder/platforms/capability_facades.py`
   - IMFacade / DocFacade / HRFacade / IdentityFacade —— 实现各 Capability Protocol 方法签名但全 raise NotImplementedError
   - **Plan 05 替换为真 daemon 转发**（`async def send_card(...): return await self._daemon.invoke("im", "send_card", ...)`）
   - 本 plan 4 facade 共享 `_BaseFacade.__init__(daemon, manifest)` 父类

### Phase 5.A Plan 05+ 演进路径（对接点）

- **Plan 05**：`capability_facades.py` 各 facade 方法替换为 `await self._daemon.invoke(...)` 真转发
- **Plan 05**：`PlatformPlugin.attach_daemon(daemon)` 让 Registry 在懒加载时注入 PlatformDaemonClient 实例
- **Plan 06**：`PlatformDaemonClient` JSONRPC over stdio + Pitfall 8 stderr 独立 drain（Dify 用 Go daemon 走 HTTP/gRPC，本项目 v1 用 Python subprocess + stdio）
- **Plan 07**：HulyPlugin acid test —— Registry.discover() → get_plugin → im.send_card() 经 Plan 04/05/06 全链路真跑通

## 注意事项 / 边界考虑

1. **YAML 注入风险（Pitfall 3）**：`yaml.safe_load` 永远不能改 `yaml.load`，CI 自动 grep 检查
2. **extra=forbid 演进风险（Pitfall 4）**：未来 v1.2 加字段时，旧 plugin manifest 不带它仍 pass（Optional default None）；本项目 v1 不主动升 minor，留 v2 处理
3. **Registry 进程级 singleton**：测试用 `PlatformPluginRegistry.clear()` fixture 隔离；生产期单进程多 workspace 共享同一 _MANIFESTS dict（manifest 是只读的，并发安全）
4. **discover 失败 fail-fast**：任一 plugin manifest 校验失败 → raise PluginError 阻断启动（Dify 类似策略，防生产期半挂状态）
5. **重复 plugin name 检测**：两个 plugin 目录都声明 name=huly → 第二个 discover 时 raise（Pitfall 不出现的关键防护）

## 6 借鉴点总结表（Plan 04 落地映射）

| # | Dify 源文件 | 借鉴模式 | 5.A Plan 04 落地 |
|---|---|---|---|
| 1 | `plugin.py:70-141` (PluginDeclaration) | Pydantic v2 BaseModel + Field validator + SemVer | `PlatformManifest` + `@field_validator` |
| 2 | `plugin.py:61-67` (PluginCategory StrEnum) | 单选枚举 → 多选 Literal | `capabilities: list[Literal[...]]` |
| 3 | `plugin.py:143-154` (PluginInstallation) | tenant_id × plugin_id 唯一约束 | `_PLUGINS: dict[(workspace_id, plugin_name)]` |
| 4 | `plugin_service.py:45+` (PluginService static) | static method-only + tenant_id 第一参 | `PlatformPluginRegistry` classmethod-only |
| 5 | `plugin_permission_service.py:7-13` (get_permission) | per-tenant 显式 WHERE | `test_two_workspaces_isolated` 防 Pitfall 5 |
| 6 | `plugin.py` + `plugin_service.py` (启动期 vs 运行时) | discover 不 spawn / 懒加载 daemon | `discover()` 仅 load manifest / `get_plugin()` 才实例化 |

每条借鉴点对应 Plan 04 具体 module 路径 + 实现方法名。

## 不复制 vs 借鉴的边界

| Dify 做的 | 我们也做（借鉴） | 我们不做（差异） |
|---|---|---|
| Pydantic v2 manifest | ✓ PlatformManifest | ✗ 不引入 I18nObject（中文优先单语言） |
| tenant scoping | ✓ workspace scoping | ✗ 不引入 TenantPluginPermission 表（v1 RBAC 简化） |
| 嵌套 BaseModel | ✓ RuntimeConfig/CapabilitySpec/SandboxConfig | ✗ 不引入 PluginResourceRequirements.Permission 多层（v1 安全简化） |
| StrEnum 单选 category | ✗ 用 Literal 多选 capabilities | （差异：多 capability 是核心创新） |
| 多 source install | ✗ v1 仅 plugins/ 文件系统 | （差异：marketplace 留 Phase 6） |
| Go daemon HTTP/gRPC | ✗ Python subprocess + stdio | （差异：v1 简化运维） |
| Marketplace cache (Redis 5min TTL) | ✗ v1 无 marketplace | （差异：留 Phase 6） |
| extra=allow 宽松 | ✗ extra=forbid 严格 | （差异：本项目用户决策强制） |

## 参考文档链接

- **本项目 ADR-001**: `docs/plans/2026-05-17-platform-plugin-framework-ADR.md`（§4 manifest spec + §6 Registry spec）
- **本项目 Plan 05a-04 PLAN.md**: `.planning/phases/05a-platform-plugin-framework/05a-04-PLAN.md`
- **Phase 5.A Plan 02 SUMMARY**: IMCapability / DocCapability Protocol 已实现（本 plan 消费）
- **Phase 5.A Plan 03 SUMMARY**: HRCapability / IdentityCapability + 完整 capabilities/__init__.py（本 plan 消费 24 exports）
- **Dify manifest schema 目录**: `/Users/admin/ai/ref/dify/repo/api/core/plugin/manifest_schema/`（若存在；Dify 0.7+ 提供 manifest YAML 样例）

---

**Reading doc 完成 ✓**
**License attribution**: Dify AGPL-3.0 → 本项目 Apache-2.0 — **仅借鉴设计模式 / 数据结构 / 边界思路，严禁拷源代码**
**借鉴点数量**: 6（≥ 5 PLAN.md 硬性要求）
**行数**: > 200（≥ 60 PLAN.md 硬性要求）
**下一步**：Plan 04 Task 1 — PlatformManifest Pydantic schema + load_manifest + 3 fixture YAML + 8 单测
