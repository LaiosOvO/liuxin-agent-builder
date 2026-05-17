# ADR-001: PlatformPlugin 通用插件框架（Dify-style）

> **状态**：Accepted (用户 2026-05-17 明确指令："要设置成 dify 一样的通用的平台来解决")
> **作者**：基于 Phase 4 IMProvider 实测 + Huly acid test gap 暴露 + Dify plugin architecture 借鉴
> **取代**：
> - [`2026-05-17-doc-provider-abstraction-design.md`](./2026-05-17-doc-provider-abstraction-design.md) — DocProvider 不再单独抽象，统一进 PlatformPlugin
> - [`2026-05-17-platform-abstractions-overview.md`](./2026-05-17-platform-abstractions-overview.md) — overview 升级
> **不取代**：
> - [`2026-05-17-im-bot-abstraction-design.md`](./2026-05-17-im-bot-abstraction-design.md) — bot dispatcher 仍独立（业务层 ≠ provider 层）
> - Phase 4 IMProvider Protocol 实现 — **向后兼容**，可平滑演进

---

## 0. Why this ADR exists

用户三连质疑后追加的硬性指令：
> "记得要设置成 dify 一样的通用的平台来解决哦"

含义：当前 Provider 抽象（IMProvider / DocProvider / HRProvider）按"每个 capability 一个 Protocol + Registry"切分，
**外部第三方平台开发新 provider 需要写 Python 类 + 提交 PR**。Dify 不是这样 — Dify 的 plugin 是**完全外部、独立运行时、manifest-driven、热加载**的。

agent-builder 必须达到同等水平：
- 第三方平台（如 Huly / Notion / Linear / 任何新 SaaS）能**不改 agent-builder 核心代码**接入
- Plugin 跑在**沙箱进程**（fault isolation），核心进程不被 plugin 异常影响
- Plugin 通过 **YAML manifest** 声明能力（IM/Doc/HR/Workflow/Tool 任意组合）
- 配置 UI **自动生成**（schema-driven）— 不需要每个 plugin 写一套 React 面板

---

## 1. Dify plugin architecture 借鉴点

读取 `/Users/admin/ai/ref/dify/repo/api/core/plugin/` 后提取的关键模式：

| Dify 模式 | 在 agent-builder 的对应 |
|---|---|
| `api/core/plugin/entities/plugin.py` — Plugin 元实体 | `PlatformPlugin` 顶层抽象 |
| `api/core/plugin/entities/bundle.py` — Plugin Bundle manifest | `platform.yaml` manifest |
| `api/core/plugin/entities/plugin_daemon.py` — daemon gRPC 协议 | `PlatformDaemonClient` (gRPC / HTTP) |
| `api/core/plugin/entities/endpoint.py` — endpoint 注册 | `Capability` 声明（IM/Doc/HR/...）|
| `api/services/plugin/plugin_service.py` — install/upgrade/remove | `PlatformPluginService` |
| `dify-plugin-daemon` 独立仓库 — 沙箱 runtime | Phase 6 plugin 沙箱机制（与本 ADR 合流） |
| `api/core/tools/plugin_tool/` — Tool plugin 子类 | `Capability` Protocol 集合 |

**关键差异 / 我们的扩展**：
- Dify plugin 主要服务 **model providers + tools**；本 ADR 扩展为 **平台 + 工具 + 工作流引擎 + UI 注入** 五大 capability
- Dify plugin 跑 Python；本 ADR 允许 Python / Node.js / Go（按 manifest 声明 runtime）
- Dify 一个 plugin 通常一个 capability；本 ADR 允许一个 plugin 声明**多 capability bundle**（解决 Huly 一体化平台问题）

---

## 2. 顶层抽象：PlatformPlugin

```
PlatformPlugin (一个外部平台 / 工具 / 服务)
├── manifest.yaml          ← 静态声明：name / version / runtime / capabilities[] / config_schema
├── daemon process         ← 沙箱独立进程（Phase 6 沙箱机制）
└── capabilities (implements)
     ├── IMCapability      ← 可选 — 平台支持聊天 / 卡片 / DM
     ├── DocCapability     ← 可选 — 平台支持协作文档
     ├── HRCapability      ← 可选 — 平台支持员工 / 部门 / 假期
     ├── TriggerCapability ← 可选 — 平台能 push 事件触发 workflow
     ├── ToolCapability    ← 可选 — 平台提供 RPC tools 给 LLM 调用
     ├── WorkflowCapability ← 可选 — 平台是 workflow engine（可执行 sub-workflow）
     └── IdentityCapability ← 可选 — 平台是 user / group source-of-truth
```

**关键设计决策**：
- **一个 plugin 可声明多 capability** — Huly 一个 manifest 声明 IM + Doc + HR + Identity 共 4 个 capability，跑一个 daemon，共享底层 client
- **Capability 是 Protocol（duck typing）** — plugin 只需实现声明的 capability 方法，没声明的不实现
- **Capability negotiation** — 节点配置时按需查询 `plugin.has(IMCapability)`，按能力路由

---

## 3. Capability Protocols（精简版 — 每个 ≤ 8 方法）

### 3.1 IMCapability

```python
@runtime_checkable
class IMCapability(Protocol):
    """对外通讯能力 — 发卡片 / DM / channel post / 接事件"""

    supports_native_buttons: bool      # 卡片按钮原生 vs markdown 链接降级
    supports_card_update: bool         # 决策后 update 卡片为只读
    supports_threads: bool             # thread reply 模式

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,      # 多态：channel / dm / thread / mention
        card: NormalizedCard,          # 平台无关卡片 schema
        idempotency_key: str,
    ) -> MessageRef: ...

    async def update_card(self, msg_ref: MessageRef, card: NormalizedCard) -> None: ...
    async def send_text(self, recipient: RecipientSpec, text: str) -> MessageRef: ...
    async def subscribe_events(self, event_types: list[str]) -> AsyncIterator[IMEvent]: ...
```

**对照 Phase 4 IMProvider**：
- 新增 `RecipientSpec` 多态（Huly gap #a）
- 新增 `supports_native_buttons` cap flag（Huly gap #b）
- 新增 `subscribe_events`（IM bot 入站，Phase 4.5 设计稿对应）

### 3.2 DocCapability

```python
@runtime_checkable
class DocCapability(Protocol):
    """协作文档能力"""

    supports_collaborative_edit: bool  # Y.js CRDT vs 全量 replace 区分 ← Huly gap #DocProvider 30% fit
    supports_comments: bool

    async def create_document(self, *, title, markdown, owners=None) -> DocRef: ...

    async def replace_document_content(    # 全量替换（Outline / Lark 等）
        self, doc_ref: DocRef, markdown: str
    ) -> None: ...

    async def apply_document_delta(        # CRDT delta（Huly / Notion）
        self, doc_ref: DocRef, delta: CRDTDelta
    ) -> None: ...

    async def add_comment(
        self,
        *,
        doc_ref: DocRef,
        body: str,
        mentions: list[UserRef],
    ) -> CommentRef: ...

    async def get_document(self, doc_ref: DocRef) -> DocInfo | None: ...
```

**对照之前 DocProvider 设计稿**：
- 修复 Y.js CRDT 全量替换冲突（acid test #2）— 拆 `replace` + `apply_delta`
- 移除 `update_document` 含糊语义

### 3.3 HRCapability（新）

```python
@runtime_checkable
class HRCapability(Protocol):
    """人事能力 — 员工 / 部门 / 假期"""

    async def list_employees(self, *, filter: EmployeeFilter | None = None) -> list[Employee]: ...
    async def get_employee(self, employee_ref: EmployeeRef) -> Employee | None: ...
    async def list_departments(self) -> list[Department]: ...
    async def resolve_department_members(
        self, expression: str    # "dept:研发部" / "role:manager" / "id:xxx"
    ) -> list[EmployeeRef]: ...
    async def list_leave_requests(self, *, employee_ref) -> list[LeaveRequest]: ...
    async def create_leave_request(self, *, employee_ref, ...) -> LeaveRequest: ...
```

**新增动机**（acid test #3）：
- Huly hr plugin 完全无对应抽象
- Phase 5 `dept:研发部` 表达式解析的天然 home（resolve_department_members）
- 飞书 / 企微 / 钉钉 都有 HR module，HRCapability 是普遍需求

### 3.4 IdentityCapability（新）

```python
@runtime_checkable
class IdentityCapability(Protocol):
    """身份源能力 — 平台是否 user / group 主权威"""

    is_source_of_truth: bool       # True: 反向 sync to us; False: passive target

    async def list_users(self) -> list[UserPrincipal]: ...
    async def resolve_user(self, identifier: str) -> UserPrincipal | None: ...
    async def watch_user_changes(self) -> AsyncIterator[UserChangeEvent]: ...
```

**新增动机**（acid test #4 — 身份反向 sync）：
- `user_platform_mappings` 表当前假设 sync-to；Huly / 飞书 是 source-of-truth 强制反向
- `is_source_of_truth` flag 让 sync 编排器决定方向

### 3.5 TriggerCapability + ToolCapability + WorkflowCapability

- **TriggerCapability**：平台 push 事件触发 workflow（Webhook / WS / Polling）— Phase 4.5 IM bot 抽象的 `subscribe` 升级
- **ToolCapability**：plugin 提供 RPC tools 供 LLM 节点调用（参考 Dify `api/core/tools/`）
- **WorkflowCapability**：plugin 自身是 workflow engine（如对接 n8n / Make / Dify Workflow）

详细签名留 v1.1 — 本 ADR 重点是顶层框架。

---

## 4. Manifest Schema (platform.yaml)

```yaml
# plugins/huly/platform.yaml
name: huly
version: 1.0.0
description: "Huly all-in-one platform (chat + docs + HR + project)"
license: EPL-2.0

runtime:
  type: python                          # python | node | go
  entry: huly_plugin:main
  python_version: "3.11"

capabilities:                            # ← 关键：一个 plugin 声明多 capability
  - im
  - doc
  - hr
  - identity

# 每个声明的 capability 必须 implement 对应 Protocol
# Plugin daemon 进程启动时框架做 isinstance(plugin, IMCapability) 校验

config_schema:                           # JSON Schema for workspace config UI
  type: object
  required: [endpoint, auth_token]
  properties:
    endpoint:
      type: string
      format: uri
      description: "Huly server endpoint (e.g. https://huly.example.com)"
    auth_token:
      type: string
      format: password
      description: "Service account token"
    workspace_handle:
      type: string
      description: "Huly workspace identifier"

# Capability-specific 配置
im:
  supports_native_buttons: false        # Huly chunter 用 markdown
  supports_card_update: true
  supports_threads: true

doc:
  supports_collaborative_edit: true     # ← Y.js CRDT
  supports_comments: true

identity:
  is_source_of_truth: true              # ← Huly 强制反向 sync

# Phase 6 sandbox 资源限制
sandbox:
  cpu_limit: "1.0"
  memory_limit: "512Mi"
  network: ["huly.example.com:443"]
```

**对比 Phase 4 IMProvider 配置**：
- Phase 4: Python class + hardcoded register_provider("feishu", FeishuProvider)
- 本 ADR: YAML manifest + daemon process + 配置 UI 自动生成

---

## 5. 共享 PlatformClient + Multi-Capability Bundle

解决 Huly acid test #4 "一体化平台共享 client" 问题：

```python
class PlatformDaemonClient:
    """每 plugin 一个 daemon process，主进程通过此 client 跟它通信。
    所有 capability call 走同一条 RPC，daemon 内部共享底层连接（如 WebSocket）。
    """

    def __init__(self, manifest: PlatformManifest, sandbox: SandboxRuntime):
        self._proc = sandbox.spawn(manifest.runtime)
        self._rpc = JSONRPCOverStdio(self._proc.stdin, self._proc.stdout)

    async def invoke(self, capability: str, method: str, **kwargs) -> Any:
        return await self._rpc.call(f"{capability}.{method}", kwargs)

    async def close(self) -> None:
        await self._rpc.call("__lifecycle__.close")
        self._proc.terminate()

class HulyPlugin(PlatformPlugin):
    """框架包装 — 业务代码不直接构造，由 PluginRegistry 实例化。"""
    name = "huly"
    capabilities = [IMCapability, DocCapability, HRCapability, IdentityCapability]

    def __init__(self, daemon: PlatformDaemonClient):
        self._daemon = daemon

    @property
    def im(self) -> IMCapability:
        return _IMFacade(self._daemon)

    @property
    def doc(self) -> DocCapability:
        return _DocFacade(self._daemon)

    @property
    def hr(self) -> HRCapability:
        return _HRFacade(self._daemon)

    @property
    def identity(self) -> IdentityCapability:
        return _IdentityFacade(self._daemon)
```

**单 plugin 实例 → 单 daemon process → 单 Huly WS 连接** — 4 个 facet 共享，不开 4 连接。

---

## 6. Plugin Registry + 动态发现

```python
class PlatformPluginRegistry:
    """中央插件登记表 — 启动期扫描 plugins/ 目录 + DB workspace_plugin_installations 表"""

    @classmethod
    async def discover(cls) -> list[PlatformManifest]:
        """扫描 plugins/ + DB installations。"""

    @classmethod
    async def install(cls, workspace_id: UUID, manifest_path: str) -> InstallResult:
        """1. 解析 manifest → 校验 schema
           2. 沙箱 dry-run（启 daemon + capability handshake）
           3. 入 DB workspace_plugin_installations + workspace_settings.plugin_config[name]
           4. 标 status=installed"""

    @classmethod
    async def get_plugin(
        cls, workspace_id: UUID, plugin_name: str
    ) -> PlatformPlugin | None: ...

    @classmethod
    async def get_capability(
        cls, workspace_id: UUID, capability: type, *, prefer: str | None = None
    ) -> Any | None:
        """按 workspace 默认选择实现 capability 的 plugin。
        例：get_capability(ws_id, IMCapability, prefer='huly') → HulyPlugin.im"""
```

**节点配置时使用**：
```python
# DAG 节点 im_card_notify 配置
config:
  capability: im
  provider: ${workspace.default_im_plugin}    # 或显式 "huly"
  recipient: ...
  card: ...

# 节点执行时
plugin_im = await registry.get_capability(ctx.workspace_id, IMCapability, prefer=cfg.provider)
await plugin_im.send_card(recipient=cfg.recipient, card=cfg.card, idempotency_key=...)
```

---

## 7. 解决 Huly acid test 5 个 gap — 逐条对照

| Acid test gap | 本 ADR 解决方式 |
|---|---|
| **#1 IMProvider 60% fit** | `IMCapability` 加 `RecipientSpec` 多态 + `supports_native_buttons` flag + `subscribe_events` 长连入口 |
| **#2 DocProvider Y.js CRDT 冲突 (30% fit)** | `DocCapability` 拆 `replace_document_content` + `apply_document_delta` + `supports_collaborative_edit` cap flag |
| **#3 HRProvider 不存在** | 新增 `HRCapability` Protocol（8 method 含 resolve_department_members 解决 Phase 5 dept: 表达式） |
| **#4 一体化平台 vs 分割 provider** | 一个 plugin manifest 声明多 capability + 共享 `PlatformDaemonClient`（HulyPlugin.im/.doc/.hr/.identity facet 模式） |
| **#5 身份反向 sync** | 新增 `IdentityCapability` + `is_source_of_truth: bool` flag + `watch_user_changes` 反向同步 stream |

---

## 8. 与现有代码的平滑演进

**Phase 4 已实现的 IMProvider Protocol + 6 家 provider 不需要重写**：

```python
# 适配层 — Phase 4 IMProvider → 新 IMCapability
class LegacyIMProviderAdapter:
    """把 Phase 4 IMProvider 包装成 IMCapability。"""

    def __init__(self, legacy: IMProvider):
        self._legacy = legacy
        self.supports_native_buttons = getattr(legacy, "supports_card_update", False)
        self.supports_card_update = legacy.supports_card_update
        self.supports_threads = False

    async def send_card(self, *, recipient: RecipientSpec, card, idempotency_key):
        # RecipientSpec → legacy channel_user_id
        cuid = recipient.to_channel_user_id()
        msg_id = await self._legacy.send_card(cuid, card.to_legacy_payload(), idempotency_key)
        return MessageRef(plugin="legacy:" + self._legacy.provider_name, native_id=msg_id)

    # ... 其他方法
```

**Registry 在过渡期同时识别两种 provider**：
- 老的 `register_provider("feishu", FeishuProvider)` → 内部包装为 LegacyIMProviderAdapter
- 新的 plugin manifest YAML → 直接 PlatformPlugin

这允许我们 **一个 plugin 一个 plugin 迁移**，不是 big bang。

---

## 9. Phase 拆分（修订）

合并 / 修订之前 IM bot + DocProvider + Phase 6 plugin 沙箱的 phase 拆分：

| Phase | 内容 | 与之前比 |
|---|---|---|
| **Phase 4** ✓ | IM 出站卡片（Phase 4 IMProvider）| **不变** — 平滑演进 |
| **Phase 4.5** | IM bot 入站 dispatcher + LLM intent router | **不变** — 业务层（Capability 之上）|
| **Phase 5.A — PlatformPlugin 框架** ⭐ NEW | PlatformPlugin / Capability Protocols / Manifest / Registry / LegacyAdapter | **新增** — 替代之前 DocProvider 设计 |
| **Phase 5.B — 沙箱 + 远程进程** | PlatformDaemonClient + JSONRPC over stdio + 资源限制 | **合并 Phase 6 沙箱** |
| **Phase 5.C — DocCapability 真接入** | Outline plugin + Lark plugin + Huly plugin（含 IM/Doc/HR/Identity 4 capabilities） | **替代** 之前 Phase 5.B/C |
| **Phase 5.D — HRCapability + Identity 反向 sync** | HR plugins（飞书 / 企微 / 钉钉 / Huly）+ user_platform_mappings 反向 sync | **新增 + 替代** 之前 Phase 5 IM 目录同步 |
| **Phase 6 — Plugin Marketplace + 第三方插件** | 上传 zip / dry-run / 注册 / 画布动态加载 | **不变**（Phase 5.B 沙箱基础完成后接力）|

---

## 10. 验收准则（DoD for Phase 5.A）

- [ ] `PlatformPlugin` + 6 Capability Protocols 完整定义 + 单元测试
- [ ] `platform.yaml` manifest schema + Pydantic 校验
- [ ] `PlatformPluginRegistry` discover / install / get_capability
- [ ] `LegacyIMProviderAdapter` 让 Phase 4 6 家 IMProvider 通过新 IMCapability 接口被调用，**零测试 regression**
- [ ] `MockPlatformPlugin` 用于测试，声明多 capability
- [ ] Acid test：**真实写一个 HulyPlugin stub**（manifest + 4 facade + JSONRPC over stdio）+ 至少 1 个 capability call 通过单元测试
- [ ] DocCapability 设计稿 + 单测覆盖 replace / apply_delta 双路径
- [ ] HRCapability 设计稿 + Mock 单测

---

## 11. 开放问题

1. **Manifest 用 YAML 还是 JSON Schema？** YAML 更友好但 Dify 用 JSON manifest；推荐 YAML（人友好）+ 内部 schema 校验
2. **Daemon 通信协议**：JSONRPC over stdio（轻）vs gRPC（重但强类型）— 推荐 JSONRPC v1，gRPC v2
3. **Plugin language**：v1 Python only？还是开放 Node / Go？— 推荐 v1 Python 优先，多 runtime 留 v2
4. **第三方 plugin 上传**：v1 文件系统 / Phase 6 marketplace；推荐 v1 本地 manifest，marketplace v1.5
5. **凭据加密存**：复用 Phase 4 IMCredentialsManager 还是新设计？— 推荐复用，加 plugin_name 前缀
6. **Capability 演进破坏性**：Capability Protocol 加新 method 时如何不破老 plugin？— 推荐 default impl + version pin in manifest

---

## 12. 参考资料

| 来源 | 路径 |
|---|---|
| Dify plugin entities | `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/{plugin,bundle,endpoint,plugin_daemon}.py` |
| Dify plugin service | `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` |
| Dify plugin daemon | https://github.com/langgenius/dify-plugin-daemon |
| Huly acid test 报告 | `./2026-05-17-huly-spike-abstraction-acid-test.md` |
| Phase 4 IMProvider 实现 | `backend/app/agent_builder/notification/providers/base.py` + 6 家 provider |
| IM bot abstraction（仍有效） | `./2026-05-17-im-bot-abstraction-design.md` — bot dispatcher 在 Capability 之上 |
| 之前 DocProvider 设计（被本 ADR 取代） | `./2026-05-17-doc-provider-abstraction-design.md` |

---

## 13. 总结：从 Provider 到 Plugin 的范式跃迁

| 维度 | Phase 4 现状 | 本 ADR (Phase 5.A) |
|------|--------------|---------------------|
| **接入方式** | Python class + register_provider() + PR | YAML manifest + daemon process + 文件系统 install |
| **粒度** | 一个 provider = 一类 capability | 一个 plugin 可声明多 capability |
| **隔离** | 同进程（fault 影响主） | 沙箱独立进程（Phase 5.B） |
| **配置 UI** | 每 provider 写一套 frontend | manifest config_schema → JSON Schema → React 自动渲染 |
| **第三方接入** | 改源码 PR | 上传 plugin zip |
| **Capability negotiation** | 硬编码字段 supports_card_update | manifest 声明 + Registry 查能力 |
| **跨平台共享 client** | 不支持 | PlatformDaemonClient bundle facet |
| **身份反向 sync** | 不支持 | IdentityCapability is_source_of_truth |
| **协作编辑 (CRDT)** | 不支持 | DocCapability apply_document_delta + supports_collaborative_edit |
| **HR 抽象** | 不存在 | HRCapability 8 method |

**核心承诺**：第三方平台开发者只需写一份 `platform.yaml` + 实现声明的 capability 即可让 agent-builder 接入，**零核心代码改动**。

这就是用户要求的"像 Dify 一样的通用平台"。

---

*ADR 完*
