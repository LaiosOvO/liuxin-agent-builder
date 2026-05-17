---
phase: 05c-doc-capability
plan: 02
type: execute
wave: 2
depends_on: ["01"]
files_modified:
  - docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md
  - plugins/huly/_internal/__init__.py
  - plugins/huly/_internal/constants.py
  - plugins/huly/_internal/tx_factory.py
  - plugins/huly/_internal/tx_operations.py
  - plugins/huly/_internal/rest_client.py
  - plugins/huly/_internal/platform_client.py
  - backend/tests/platforms/test_huly_internal_port.py
  - backend/tests/platforms_integration/test_huly_rest_client_integration.py
autonomous: true
requirements:
  - 5C-FW-02
  - 5C-FW-04
  - 5C-SC-3
must_haves:
  truths:
    - "hr-port reading doc 已 commit（CLAUDE.md §2.7 硬性 gate，必须早于任何代码 commit）"
    - "`plugins/huly/_internal/` 5 模块全部存在并独立可 import（constants / tx_factory / tx_operations / rest_client / platform_client）"
    - "TxFactory.create_tx_create_doc / create_tx_update_doc / create_tx_remove_doc / create_tx_collection_cud 4 方法构造的字典字段与 hr 等价（_id 24-char hex / _class / objectId / attributes 全齐）"
    - "TxOperations.create_doc → HulyRestClient.tx → mock httpx Response 200 端到端 work"
    - "HulyRestClient 内 `httpx.AsyncClient(transport=AllowlistTransport([host:port]))` —— 非白名单 host 出站 raise NetworkBlockedError（Phase 5.B 规约）"
    - "HulyRestClient.login + select_workspace + get_account 三步连续调用，aiohttp mock server 路由返回结构与 hr 等价"
    - "5 模块每个文件首注释含 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source`，audit 脚本 grep -L 输出为空"
    - "本 plan 不暴露任何 capability —— `_internal/` 仅供 plan 05 HulyPlugin 内部使用，对外接口 0 改动"
    - "Phase 5.A 271 platforms tests 0 regression + Phase 5.B sandbox + 5/5 huly acid test 0 regression"
  artifacts:
    - path: "docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md"
      provides: "hr huly/* 5 文件 port 阅读笔记 + Dify plugin internal module 借鉴 2 节标准模板 ≥100 行"
      min_lines: 100
    - path: "plugins/huly/_internal/__init__.py"
      provides: "_internal 子包入口 + 公开符号导出（HulyRestClient / HulyPlatformClient / TxFactory / TxOperations + constants 常量子集）"
      exports: ["HulyRestClient", "HulyPlatformClient", "AccountInfo", "TxFactory", "TxOperations", "generate_id", "connect_huly"]
    - path: "plugins/huly/_internal/constants.py"
      provides: "Huly 模型字符串常量（CORE_* / CONTACT_* / CHUNTER_* / DOCUMENT_*）"
      contains: "CORE_CLASS_TX_CREATE_DOC"
      min_lines: 60
    - path: "plugins/huly/_internal/tx_factory.py"
      provides: "TxFactory 5 工厂方法 + generate_id (24-char hex) + _now_ms helper"
      contains: "class TxFactory"
      min_lines: 180
    - path: "plugins/huly/_internal/tx_operations.py"
      provides: "TxOperations facade（create_doc / update_doc / remove_doc / add_collection / update_collection / remove_collection / create_mixin / update_mixin）"
      contains: "class TxOperations"
      min_lines: 150
    - path: "plugins/huly/_internal/rest_client.py"
      provides: "HulyRestClient (login / selectWorkspace / get_account / find_all / find_one / tx / ensure_person) + AllowlistTransport 注入 + HulyRestError"
      contains: "AllowlistTransport"
      min_lines: 260
    - path: "plugins/huly/_internal/platform_client.py"
      provides: "HulyPlatformClient dataclass + connect_huly factory（lifecycle 接 PlatformPlugin daemon `__init__`）"
      contains: "connect_huly"
      min_lines: 70
    - path: "backend/tests/platforms/test_huly_internal_port.py"
      provides: "Unit tests — TxFactory 5 工厂方法 + TxOperations 8 高阶方法 + HulyRestClient httpx.MockTransport 响应解析"
      contains: "test_"
      min_lines: 200
    - path: "backend/tests/platforms_integration/test_huly_rest_client_integration.py"
      provides: "Integration tests — aiohttp mock huly server + HulyRestClient.login + selectWorkspace + tx 端到端 + AllowlistTransport 白名单触发 NetworkBlockedError 回归"
      contains: "test_"
      min_lines: 150
  key_links:
    - from: "plugins/huly/_internal/rest_client.py"
      to: "backend/app/agent_builder/platforms/sandbox/network.py (AllowlistTransport)"
      via: "HulyRestClient.__init__ 接受 allow_list: list[str]，内部构造 httpx.AsyncClient(transport=AllowlistTransport(allow_list))"
      pattern: "httpx\\.AsyncClient\\([^)]*transport=AllowlistTransport"
    - from: "plugins/huly/_internal/tx_operations.py"
      to: "plugins/huly/_internal/rest_client.py + tx_factory.py"
      via: "TxOperations(rest, user).create_doc 构造 inner tx → 调 self.client.tx(tx)"
      pattern: "from \\.rest_client import HulyRestClient"
    - from: "plugins/huly/_internal/platform_client.py"
      to: "plugins/huly/_internal/rest_client.py + tx_operations.py"
      via: "connect_huly = login + select_workspace + get_account + TxOperations construct，返回 HulyPlatformClient dataclass"
      pattern: "async def connect_huly"
    - from: "plugins/huly/_internal/*.py"
      to: "hr/offboarding-flow license attribution"
      via: "每文件首行注释 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source`"
      pattern: "Inspired by hr/offboarding-flow design"
---

<objective>
把 hr/offboarding-flow B-full-channel `providers/huly/` 5 个 Python 文件（836 行）port 为 `plugins/huly/_internal/` 子包，作为 Plan 05 HulyPlugin daemon 真接 Doc / IM / Identity capability 的底层 client。

**核心改造**：
- `rest_client.py` 286 行内置 `AllowlistTransport`（Phase 5.B Wave 2 沙箱白名单 application-level enforcement）
- `tx_factory.py` 220 行 / `tx_operations.py` 182 行 / `constants.py` 72 行 **零改 port**
- `platform_client.py` 76 行 lifecycle 改造（PlatformPlugin daemon `__init__` 接入）

**AGPL 防御**（CONTEXT.md Decision 8 / RESEARCH §Pitfall 8 / CLAUDE.md §2.7）：
- 不复制 hr 源码 — 重写逻辑、保留结构与方法签名
- 每文件首行注释 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source`
- audit script 验证 attribution 全覆盖

**接口对外冻结**：本 plan 不暴露任何 capability，只提供 `_internal/*` 模块给 Plan 05 用 — `plugins/huly/huly_plugin.py` 不动（Phase 5.A acid test 5/5 仍走原 aiohttp fallback 路径）。

Purpose: Phase 5.C Wave 2 与 plan 03 (Outline) / plan 04 (Lark Docs) 并行 — 为 Wave 3 plan 05 (HulyPlugin 4-cap bundle 集成) 提供 hr 836 行验证过的 Huly REST + Tx 系统基础。
Output: docs/ 1 文件 + plugins/huly/_internal/ 6 文件（含 __init__.py）+ tests/ 2 文件（unit + integration） = 9 文件交付。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05c-doc-capability/05c-CONTEXT.md
@.planning/phases/05c-doc-capability/05c-RESEARCH.md
@CLAUDE.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@backend/app/agent_builder/platforms/sandbox/network.py
@backend/app/agent_builder/platforms/exceptions.py
@plugins/huly/huly_plugin.py
@plugins/huly/platform.yaml

<interfaces>
<!-- Plan 05 (HulyPlugin 4-cap bundle 集成) 将从 _internal 拿这些符号。 -->
<!-- 本 plan 必须提供这些 exports 与 method 签名，否则 Plan 05 阻塞。 -->

From plugins/huly/_internal/__init__.py（本 plan 创建）：
```python
__all__ = [
    "HulyRestClient",
    "HulyPlatformClient",
    "AccountInfo",
    "TxFactory",
    "TxOperations",
    "generate_id",
    "connect_huly",
    # constants 选择性 re-export
    "CORE_CLASS_TX_CREATE_DOC",
    "CORE_CLASS_TX_UPDATE_DOC",
    "CORE_CLASS_TX_REMOVE_DOC",
    "CORE_SPACE_TX",
    "CONTACT_CLASS_SOCIAL_IDENTITY",
    "CONTACT_MIXIN_EMPLOYEE",
    "CHUNTER_CLASS_CHANNEL",
    "CHUNTER_CLASS_CHAT_MESSAGE",
    "DOCUMENT_CLASS_DOCUMENT",
    "DOCUMENT_CLASS_TEAMSPACE",
    "DEMO_EMAIL_DOMAIN",
]
```

From plugins/huly/_internal/rest_client.py（本 plan 创建）：
```python
@dataclass(frozen=True)
class AccountInfo:
    uuid: str
    social_ids: tuple[str, ...]
    primary_social_id: str
    raw: dict[str, Any]

class HulyRestError(RuntimeError): ...

class HulyRestClient:
    def __init__(
        self,
        *,
        accounts_url: str,
        allow_list: list[str],            # <-- 新增（5.B AllowlistTransport 接入点）
        workspace_token: str | None = None,
        workspace_uuid: str | None = None,
        endpoint: str | None = None,
        timeout: float = 15.0,
    ) -> None: ...

    async def login(self, email: str, password: str) -> str: ...
    async def select_workspace(self, token: str, workspace_url: str) -> dict[str, Any]: ...
    async def get_account(self) -> AccountInfo: ...
    async def find_all(self, _class: str, query=None, options=None) -> list[dict[str, Any]]: ...
    async def find_one(self, _class: str, query=None, options=None) -> dict[str, Any] | None: ...
    async def tx(self, tx_obj: dict[str, Any]) -> Any: ...
    async def ensure_person(self, social_type, social_value, first_name, last_name) -> dict[str, Any]: ...
```

From plugins/huly/_internal/platform_client.py（本 plan 创建）：
```python
@dataclass
class HulyPlatformClient:
    rest: HulyRestClient
    account: AccountInfo
    ops: TxOperations
    @property
    def bot_account(self) -> str: ...

async def connect_huly(
    *,
    accounts_url: str,
    admin_email: str,
    admin_password: str,
    workspace_url: str,
    allow_list: list[str],                # <-- 新增 5.B 必传
    timeout: float = 15.0,
) -> HulyPlatformClient: ...
```

From backend/app/agent_builder/platforms/sandbox/network.py（5.B 已存在 — 本 plan 接入）：
```python
class AllowlistTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        allow_list: list[str],
        *,
        delegate: httpx.AsyncBaseTransport | None = None,
    ) -> None: ...

def make_sandboxed_http_client(
    allow_list: list[str],
    *,
    timeout: float = 10.0,
) -> httpx.AsyncClient: ...
```

From backend/app/agent_builder/platforms/exceptions.py（5.B 已存在 — 本 plan 用其异常类型）：
```python
class NetworkBlockedError(Exception):
    host: str
    port: int
    allowlist: list[str]
```
</interfaces>

<reference>
<!-- CLAUDE.md §2.7 Reference-First 必须先读后 implement。下列文件 Task 0 必读。 -->

hr 5 必读文件（本 plan port 目标 — 借鉴结构、不复制代码）：
- /Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/rest_client.py (286 行)
- /Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_factory.py (220 行)
- /Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_operations.py (182 行)
- /Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/platform_client.py (76 行)
- /Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/constants.py (72 行)

Dify 必读 2 文件（CLAUDE.md §2.7 Reference-First — plugin internal module 组织参考）：
- /Users/admin/ai/ref/dify/repo/api/services/plugin/installer/ 全目录（plugin 内部 module 组织模式）
- /Users/admin/ai/ref/dify/repo/api/core/model_runtime/model_providers/ 任一 provider（如 openai/）（provider 包内部 _internal vs public 分层模式）

参考实现先读哲学：本 plan 看似纯 port 工作，但 Dify plugin internal module 组织的 `_helpers/` `_internal/` 命名 convention 与本项目 `_internal/` 子包设计完全一致 — 必须读 Dify 实例确保不发明轮子。
</reference>
</context>

<tasks>

<task type="auto">
  <name>Task 0: hr huly/* 5 文件 + Dify plugin internal module 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md</files>
  <action>
**STOP — 这是本 plan 后续所有 commit 的前置 gate**。先 commit 此文档才允许写代码（CLAUDE.md §2.7）。

读以下文件（**仅 Read 不 grep**，重点理解结构与模式）：

**hr 必读（5 文件 — port 目标，全程不复制源码，仅借鉴结构/命名/方法签名）**：
1. `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/constants.py` (72 行)
2. `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/rest_client.py` (286 行 — 重点关注 AccountInfo dataclass / login 错误处理 / find_all dataType TotalArray 解构 / _get_json + _post_json helper 模式)
3. `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_factory.py` (220 行 — 重点 generate_id(24-char hex) / _now_ms / 5 工厂方法签名 / TxCollectionCUD 在 inner_tx spread 3 字段而非包外层的 TS-quirk)
4. `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_operations.py` (182 行 — 重点 createDoc/addCollection inner_tx 嵌套 pattern + 不做 hierarchy.isDerived 校验的简化决策)
5. `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/platform_client.py` (76 行 — 重点 connect_huly 三步流程 + HulyPlatformClient @dataclass 模式)

**Dify 必读（2 文件 — plugin internal module 组织借鉴）**：
1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/installer/` 子目录 ls + 主要 .py 头 100 行（plugin internal module 组织 convention）
2. `/Users/admin/ai/ref/dify/repo/api/core/model_runtime/model_providers/openai/` 任一 provider 子包结构 ls + `__init__.py` 头部 + 1 个 `_helpers/` 或 `_internal/` 子模块（看 Dify 如何分层 public vs internal API）

写到 `docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md`，**严格按 CLAUDE.md §2.7 5 节标准模板**，**≥100 行**：

```markdown
# 阅读笔记 — Phase 5.C Plan 02 — Huly internal port + Dify plugin internal module

> 日期: 2026-05-18
> hr 仓库: /Users/admin/ai/resume/interview/liuxin/hr (本地参考稿 — license 不明确，0 复制源码)
> Dify 仓库: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> Dify Stars: ~141k

## 项目概述（一句话）
hr/offboarding-flow B-full-channel 的 `providers/huly/` 是 286+220+182+76+72=836 行已 production-validated Python 实现，封装 Huly Account RPC + Transactor REST + Tx 系统；Dify 的 plugin internal module 组织 convention（`_helpers/` `_internal/` 子包私有化）。

## 技术栈（关键技术选择）
- Python 3.11+ asyncio
- httpx 0.28+（hr 用裸 AsyncClient；本 port 必接 5.B AllowlistTransport）
- @dataclass(frozen=True) for value object（AccountInfo）
- secrets.token_hex(12) 生成 24-char hex（Huly Ref<T> 兼容，hr §spike 已验证）
- Pydantic 否定 — 这里是直接 dict 操作（与 Huly server REST 接口 1:1 对应），Pydantic 在 Capability 层再用

## 架构要点
（用简图 + 5 段文字说明）

hr huly/* 5 文件分层：
```
HulyPlatformClient（facade dataclass）
  ├── rest: HulyRestClient（REST 调用层 — 7 endpoint + Account RPC）
  ├── account: AccountInfo（值对象 — uuid + social_ids + primary_social_id）
  └── ops: TxOperations（高阶 CRUD facade，串 TxFactory + rest.tx）
                ↓
             TxFactory（Tx 工厂 — 5 工厂方法构造 dict）
                ↓
             constants.py（class id / space id 字符串常量）
```

Dify model_provider 子包分层（参考点）：
```
api/core/model_runtime/model_providers/openai/
  ├── __init__.py（public exports）
  ├── _common.py（私有 helper）
  ├── llm/        ├── moderation/    ├── ...（按 capability 分子目录）
```
→ 本项目 `plugins/huly/` 借鉴此分层：
```
plugins/huly/
  ├── huly_plugin.py（public daemon entry — 已存在，Plan 05 改造）
  └── _internal/（私有 — 本 plan 创建，外部不可直接 import）
      ├── constants.py / rest_client.py / tx_factory.py / tx_operations.py / platform_client.py
```

## 可借鉴的设计模式（至少 7 条，hr 5 文件各 1 + Dify 2）

1. **`@dataclass(frozen=True) AccountInfo`**（hr/huly/rest_client.py L33-41）
   - 值对象不可变 + raw dict 保留用于 debugging
   - 目标 module：`plugins/huly/_internal/rest_client.py` AccountInfo（结构等价 — 不抄实现）

2. **`_rpc` / `_get_json` / `_post_json` 三层 helper**（hr/huly/rest_client.py L128-286）
   - HTTP 调用统一 try/except + status_code 检查 + json/text fallback
   - 目标 module：`plugins/huly/_internal/rest_client.py` 同三 helper 命名
   - **改造点**：本 plan 在 `__init__` 接受 `allow_list: list[str]` 并构造 `httpx.AsyncClient(transport=AllowlistTransport(allow_list))` — hr 裸 AsyncClient 不带 transport

3. **`generate_id = secrets.token_hex(12)`**（hr/huly/tx_factory.py L30-32）
   - 24-char hex 与 Huly Ref<T> 兼容；spike 已验证 server 接受
   - 目标 module：`plugins/huly/_internal/tx_factory.py`（**重要 Pitfall**：不要改成 uuid.uuid4().hex 或别的 16-char hex，Huly server 会 silent reject）

4. **`TxCollectionCUD` 不包外层、在 inner_tx spread 3 字段**（hr/huly/tx_factory.py L186-220）
   - TS quirk：`{...tx, collection, attachedTo, attachedToClass}` 而非 `{_class: TxCollectionCUD, tx: inner}`
   - 目标 module：`plugins/huly/_internal/tx_factory.py` create_tx_collection_cud（与 hr 等价）
   - **Pitfall 防护**：自然反应是套外层 `_class: 'core:class:TxCollectionCUD'`，但 Huly server 不接受

5. **TxOperations 不做 hierarchy.isDerived 校验**（hr/huly/tx_operations.py L7-15）
   - TS createDoc 会校验 `isDerived(class, AttachedDoc) === false`，Python 不做（少 load_model ~1MB JSON）
   - 决策：让 server 自己 reject — 简化客户端
   - 目标 module：`plugins/huly/_internal/tx_operations.py` 沿用同决策

6. **connect_huly = login + select_workspace + get_account 三步**（hr/huly/platform_client.py L40-77）
   - facade pattern：业务调用方只看到 HulyPlatformClient + bot_account property，不需要单独串联
   - 目标 module：`plugins/huly/_internal/platform_client.py` 同结构
   - **改造点**：本 plan 加 `allow_list: list[str]` 参数传给 HulyRestClient（PlatformPlugin daemon `__init__` 从 manifest sandbox.network 读取后注入）

7. **Dify provider 子包 `_helpers/` vs public**（Dify api/core/model_runtime/model_providers/openai/_common.py）
   - 双下划线前缀（实际 Dify 是单下划线 `_common` `_helpers`）— Python convention 私有
   - 目标：`plugins/huly/_internal/` 子包（外部模块不应直接 `from plugins.huly._internal.rest_client import ...`，应该走 `from plugins.huly._internal import HulyPlatformClient`）

8. **Dify plugin installer 服务层异常翻译**（Dify api/services/plugin/installer/）
   - 底层 HTTP / RPC 异常统一翻译为业务异常（如 PluginInstallError）
   - 目标 module：`plugins/huly/_internal/rest_client.py` HulyRestError + Plan 05 daemon dispatcher 翻译为 JSONRPC -32000

## 与本项目的关系
本 plan 是 Phase 5.C Wave 2 的 3 个并行任务之一（plan 02 = huly internal port，plan 03 = Outline，plan 04 = Lark Docs），为 Wave 3 plan 05 (HulyPlugin 4-cap bundle 集成) 提供底层 Huly REST + Tx 系统。
- Plan 05 将 `from plugins.huly._internal import HulyPlatformClient, connect_huly` 并在 daemon `_ensure_client` lazy 初始化时调用
- Plan 06 (collab_client + markdown_to_prosemirror) 走 Wave 3 — 复用本 plan 的 TxOperations 提交二步流程 update_doc

**License attribution**:
- hr 是研究稿、license 不明确 — 0 复制源码（每文件首注释 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source`）
- Dify 是 AGPL-3.0 — 仅借鉴 plugin 内部 module 组织 convention，0 复制代码
- 本项目 Apache-2.0 — 全 5 文件 100% 独立创作，结构/方法签名借鉴 hr 设计

## 实施约束
1. 每文件首行必须 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source`
2. rest_client.py `__init__` 必须接受 `allow_list: list[str]`（Plan 05 注入 manifest sandbox.network）
3. **不要**直接 copy-paste hr 任何代码片段 — 看完一段、关掉、自己写
4. method 签名（含参数顺序 + return type）与 hr 等价（便于 Plan 05 接入时心智一致）
5. 测试要 mock httpx + aiohttp，不依赖真 Huly server（本 plan 100% offline，集成测留 Plan 08 E2E）
```

文档**至少 100 行**、Dify 与 hr 借鉴点必须明确写出 source file → target module 的对应关系。**不要贴 hr / Dify 任何源代码片段**（license 风险）。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md && wc -l docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md | awk '{exit ($1 >= 100 ? 0 : 1)}' && grep -q "Inspired by hr/offboarding-flow" docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md && grep -q "AllowlistTransport" docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md && grep -q "可借鉴的设计模式" docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md && grep -c "目标 module" docs/reading-dify-05c-02-huly-internal-port-2026-05-18.md | awk '{exit ($1 >= 5 ? 0 : 1)}'</automated>
  </verify>
  <done>Reading doc 存在 ≥ 100 行 + 含 hr-port attribution + AllowlistTransport 借鉴说明 + 可借鉴的设计模式 ≥ 7 条 + 至少 5 条标注「目标 module」对应关系 + git commit hash 早于本 plan 后续所有 commit</done>
</task>

<task type="auto">
  <name>Task 1: _internal 子包骨架 + constants.py（零改 port）</name>
  <files>plugins/huly/_internal/__init__.py,plugins/huly/_internal/constants.py</files>
  <action>
**前提**：Task 0 reading doc 已 commit ✓（CLAUDE.md §2.7 gate 通过）。

### 1.1 `plugins/huly/_internal/__init__.py`（subpackage 入口 + public re-exports）

第一行注释 attribution，然后 re-export 后续 task 创建的符号（Task 2-6 完成后 import 才不报错；本任务先建占位 — 用 try/except ImportError 容错，或干脆延后到 Task 6 写 __init__）：

**实际写法**：本任务先建**最小** `__init__.py`，仅含 attribution + docstring，无 import；Task 6 platform_client 完成后回头补全 re-exports。这避免循环依赖。

```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
"""Huly 内部 module — Phase 5.C Plan 02 port from hr/offboarding-flow B-full-channel。

本子包仅供 plugins/huly/huly_plugin.py daemon 内部使用，外部模块不应直接 import
`plugins.huly._internal.rest_client` —— 通过 `plugins.huly._internal` 拿 public 符号。

模块组织（与 hr/huly/* 1:1 对应）:
- constants.py     Huly class id / space id / mixin id 字符串常量
- rest_client.py   7 REST endpoint + Account RPC（含 AllowlistTransport 沙箱白名单）
- tx_factory.py    Tx 对象工厂（5 工厂方法）
- tx_operations.py TxOperations facade（8 高阶 CRUD 方法）
- platform_client.py HulyPlatformClient + connect_huly（lifecycle 接 PlatformPlugin daemon）

License: 100% 独立创作 — 借鉴 hr 结构与方法签名，0 复制源码。
"""

from __future__ import annotations

# Task 6 补：from .constants import (...)
# Task 6 补：from .rest_client import HulyRestClient, HulyRestError, AccountInfo
# Task 6 补：from .tx_factory import TxFactory, generate_id
# Task 6 补：from .tx_operations import TxOperations
# Task 6 补：from .platform_client import HulyPlatformClient, connect_huly
```

### 1.2 `plugins/huly/_internal/constants.py`（零改 port — hr/huly/constants.py 72 行）

**写法**：先 Read 一次 hr 文件，关掉，自己用同样的常量名 + docstring 重写。**不复制 hr 任何代码片段**。

第一行：
```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
```

然后 docstring + 5 段常量（core / contact / chunter / document / tracker），最后 `DEMO_EMAIL_DOMAIN = "demo.local"`。

完整常量清单（必须全齐 — Plan 05 HulyPlugin 全 4 cap 都会用到）：
- **core 模块**（10 个）：CORE_CLASS_TX_CREATE_DOC / CORE_CLASS_TX_UPDATE_DOC / CORE_CLASS_TX_REMOVE_DOC / CORE_CLASS_TX_MIXIN / CORE_CLASS_TX_APPLY_IF / CORE_CLASS_DOC / CORE_CLASS_ATTACHED_DOC / CORE_CLASS_SPACE / CORE_SPACE_TX / CORE_SPACE_DERIVED_TX / CORE_SPACE_MODEL / CORE_SPACE_SPACE / CORE_SPACE_CONFIGURATION
- **contact 模块**（8 个）：CONTACT_CLASS_PERSON / CONTACT_CLASS_CONTACT / CONTACT_CLASS_SOCIAL_IDENTITY / CONTACT_CLASS_CHANNEL / CONTACT_MIXIN_EMPLOYEE / CONTACT_SPACE_CONTACTS / CONTACT_SPACE_EMPLOYEE / CONTACT_CHANNEL_PROVIDER_EMAIL
- **chunter 模块**（4 个）：CHUNTER_CLASS_DIRECT_MESSAGE / CHUNTER_CLASS_CHANNEL / CHUNTER_CLASS_CHAT_MESSAGE / CHUNTER_CLASS_THREAD_MESSAGE
- **document 模块**（4 个）：DOCUMENT_CLASS_TEAMSPACE / DOCUMENT_CLASS_DOCUMENT / DOCUMENT_IDS_NO_PARENT / DOCUMENT_TYPE_DEFAULT
- **tracker 模块**（2 个 — stub for Plan 05 future）：TRACKER_CLASS_PROJECT / TRACKER_CLASS_ISSUE
- **DEMO_EMAIL_DOMAIN = "demo.local"**

常量字符串值与 hr 完全一致（如 `CORE_CLASS_TX_CREATE_DOC = "core:class:TxCreateDoc"`） — 因为这是 Huly server 协议级 ID，**不是 hr 的代码** — Huly 自己规定的字符串。
  </action>
  <verify>
    <automated>test -f plugins/huly/_internal/__init__.py && test -f plugins/huly/_internal/constants.py && head -1 plugins/huly/_internal/__init__.py | grep -q "Inspired by hr/offboarding-flow" && head -1 plugins/huly/_internal/constants.py | grep -q "Inspired by hr/offboarding-flow" && cd /Users/admin/ai/resume/interview/liuxin/agent-builder && python -c "from plugins.huly._internal.constants import CORE_CLASS_TX_CREATE_DOC, CORE_SPACE_TX, CONTACT_MIXIN_EMPLOYEE, CHUNTER_CLASS_CHANNEL, DOCUMENT_CLASS_DOCUMENT, DEMO_EMAIL_DOMAIN; assert CORE_CLASS_TX_CREATE_DOC == 'core:class:TxCreateDoc', CORE_CLASS_TX_CREATE_DOC; assert CORE_SPACE_TX == 'core:space:Tx'; assert DEMO_EMAIL_DOMAIN == 'demo.local'; print('OK')" && wc -l plugins/huly/_internal/constants.py | awk '{exit ($1 >= 60 ? 0 : 1)}'</automated>
  </verify>
  <done>_internal/__init__.py + constants.py 存在；首行含 attribution；constants 共 28+ 个常量字符串值与 hr 等价（Huly server 协议级 ID）；python import 全 pass</done>
</task>

<task type="auto">
  <name>Task 2: tx_factory.py（零改 port — hr/huly/tx_factory.py 220 行）</name>
  <files>plugins/huly/_internal/tx_factory.py</files>
  <action>
**前提**：Task 1 constants.py 已存在（本 task import constants 常量）。

**写法**：Read hr/huly/tx_factory.py（220 行）一次，关掉，自己写。**不复制源码**。

第一行：
```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
```

然后实现：

### 2.1 模块级 helper
```python
import secrets
import time
from typing import Any

from .constants import (
    CORE_CLASS_TX_CREATE_DOC,
    CORE_CLASS_TX_UPDATE_DOC,
    CORE_CLASS_TX_REMOVE_DOC,
    CORE_CLASS_TX_MIXIN,
    CORE_SPACE_TX,
    CORE_SPACE_DERIVED_TX,
)


def generate_id() -> str:
    """生成 24 字符 hex id — 与 Huly Ref<T> 兼容（hr §spike 已验证 server 接受）。

    **Pitfall（reading doc 借鉴点 #3）**：不要改为 uuid.uuid4().hex（32 char）或
    其他长度 — Huly server 会 silent reject。必须 secrets.token_hex(12) = 24 char。
    """
    return secrets.token_hex(12)


def _now_ms() -> int:
    """当前毫秒时间戳（Huly Tx 协议要求 modifiedOn 是 ms 整数）。"""
    return int(time.time() * 1000)
```

### 2.2 `class TxFactory`（5 工厂方法 + __init__）

`__init__(self, account: str, *, is_derived: bool = False) -> None`:
- account = PersonId / SocialId 字符串（来自 AccountInfo.primary_social_id）
- is_derived=True → space=CORE_SPACE_DERIVED_TX；False → CORE_SPACE_TX
- 缓存 `self._tx_space`

**5 方法 method 签名（与 hr 完全等价 — 便于 Plan 05 接入心智一致）**：

1. `create_tx_create_doc(_class, space, attributes, object_id=None, modified_on=None, modified_by=None) -> dict[str, Any]`
   - 返回 dict 含：`_id` (generate_id) / `_class: CORE_CLASS_TX_CREATE_DOC` / `space: self._tx_space` / `objectId` (生成或传入) / `objectClass: _class` / `objectSpace: space` / `modifiedOn` / `modifiedBy` / `createdBy` / `createdOn` / `attributes`

2. `create_tx_update_doc(_class, space, object_id, operations, retrieve=False, modified_on=None, modified_by=None) -> dict[str, Any]`
   - 含 `operations` 字段（支持 $push/$pull/$inc/$unset Huly 修饰符）
   - `retrieve: bool` 透传

3. `create_tx_remove_doc(_class, space, object_id, modified_on=None, modified_by=None) -> dict[str, Any]`

4. `create_tx_mixin(object_id, object_class, object_space, mixin, attributes, modified_on=None, modified_by=None) -> dict[str, Any]`

5. `create_tx_collection_cud(_class, object_id, space, collection, inner_tx, modified_on=None, modified_by=None) -> dict[str, Any]`
   - **关键 TS quirk（reading doc 借鉴点 #4）**：浅 copy inner_tx + 加 `collection / attachedTo / attachedToClass` 3 字段 + override `modifiedOn / modifiedBy` — **不**包外层 `_class: TxCollectionCUD`
   - `space` 参数透传但实际未读（与 hr 签名对齐占位 — del space; 防 unused-arg 警告）

**注意事项**：
- 所有方法默认 modified_on = `_now_ms()` 当前时间
- 所有方法默认 modified_by = `self.account`
- created_* 仅 create_tx_create_doc 才有（其他 Tx 类型无 audit createdBy）
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder && head -1 plugins/huly/_internal/tx_factory.py | grep -q "Inspired by hr/offboarding-flow" && python -c "
from plugins.huly._internal.tx_factory import TxFactory, generate_id, _now_ms

# generate_id 24 char hex
i = generate_id()
assert len(i) == 24 and all(c in '0123456789abcdef' for c in i), i

# _now_ms 返回 int
assert isinstance(_now_ms(), int)

# TxFactory 5 方法签名
tf = TxFactory('user:1')
t1 = tf.create_tx_create_doc('chunter:class:Channel', 'core:space:Space', {'name': 'x'})
assert t1['_class'] == 'core:class:TxCreateDoc'
assert t1['objectClass'] == 'chunter:class:Channel'
assert t1['attributes'] == {'name': 'x'}
assert len(t1['_id']) == 24

t2 = tf.create_tx_update_doc('contact:class:Person', 'contact:space:Contacts', t1['objectId'], {'name': 'y'})
assert t2['_class'] == 'core:class:TxUpdateDoc'
assert t2['operations'] == {'name': 'y'}

t3 = tf.create_tx_remove_doc('contact:class:Person', 'contact:space:Contacts', t1['objectId'])
assert t3['_class'] == 'core:class:TxRemoveDoc'

t4 = tf.create_tx_mixin(t1['objectId'], 'contact:class:Person', 'contact:space:Contacts', 'contact:mixin:Employee', {'active': True})
assert t4['_class'] == 'core:class:TxMixin'

# TxCollectionCUD: 不包外层；spread inner_tx + 3 字段
inner = tf.create_tx_create_doc('chunter:class:ChatMessage', 'core:space:Space', {'message': 'hi'})
t5 = tf.create_tx_collection_cud('chunter:class:Channel', 'parent-id', 'space', 'messages', inner)
assert t5['collection'] == 'messages'
assert t5['attachedTo'] == 'parent-id'
assert t5['attachedToClass'] == 'chunter:class:Channel'
assert t5['_class'] == 'core:class:TxCreateDoc', t5['_class']  # inner 的 _class 保留

# is_derived → CORE_SPACE_DERIVED_TX
tf2 = TxFactory('user:1', is_derived=True)
td = tf2.create_tx_create_doc('a', 'b', {})
assert td['space'] == 'core:space:DerivedTx'

print('OK 5 method signatures verified')
"</automated>
  </verify>
  <done>tx_factory.py 存在；首行 attribution；TxFactory.create_tx_{create_doc,update_doc,remove_doc,mixin,collection_cud} 5 方法构造的 dict 字段全齐；TxCollectionCUD spread inner_tx 而非包外层；generate_id 24-char hex；测试 8 assert 全 pass</done>
</task>

<task type="auto">
  <name>Task 3: tx_operations.py（零改 port — hr/huly/tx_operations.py 182 行）</name>
  <files>plugins/huly/_internal/tx_operations.py</files>
  <action>
**前提**：Task 2 tx_factory.py 已存在（本 task import TxFactory）。本 task 还需要 `HulyRestClient` 类型注解 — 但 rest_client.py 尚未存在（Task 4 才创建）。解决：**用 `TYPE_CHECKING + from __future__ import annotations` 模式**。

**写法**：Read hr/huly/tx_operations.py（182 行）一次，关掉，自己写。**不复制源码**。

第一行：
```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
```

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .tx_factory import TxFactory

if TYPE_CHECKING:
    from .rest_client import HulyRestClient  # Task 4 创建

logger = logging.getLogger(__name__)


class TxOperations:
    """TxOperations facade — 串 TxFactory + HulyRestClient.tx 提供高阶 API。

    设计差异 vs TS @hcengineering/core/src/operations.ts（reading doc 借鉴点 #5）:
    - TS 用 hierarchy.isDerived(class, AttachedDoc) 校验 createDoc 不能创 AttachedDoc
      → Python 不做（少 load_model ~1MB JSON；让 server 自己 reject）
    - TS 用 hierarchy.findDomain(class) === DOMAIN_MODEL 校验 model space
      → Python 不做（同上）
    """

    def __init__(
        self,
        client: HulyRestClient,
        user: str,
        *,
        is_derived: bool = False,
    ) -> None:
        self.client = client
        self.user = user
        self.tx_factory = TxFactory(user, is_derived=is_derived)
```

### 8 高阶方法签名（与 hr 完全等价）

**单 Doc 操作 (3)**：
1. `async create_doc(_class, space, attributes, object_id=None) -> str`
   - 构造 inner = `self.tx_factory.create_tx_create_doc(...)` → `await self.client.tx(inner)` → 返回 `str(inner['objectId'])`

2. `async update_doc(_class, space, object_id, operations, retrieve=False) -> Any`
   - 返回 server 响应（透传 TxResult）

3. `async remove_doc(_class, space, object_id) -> Any`

**Collection 操作 (3)** — 内部用 TxCollectionCUD 嵌套 inner Tx：
4. `async add_collection(_class, space, attached_to, attached_to_class, collection, attributes, object_id=None) -> str`
   - inner = `create_tx_create_doc(_class, space, attributes, object_id)`
   - outer = `create_tx_collection_cud(attached_to_class, attached_to, space, collection, inner)`
   - `await client.tx(outer)` → 返回 `str(outer['objectId'])`

5. `async update_collection(_class, space, object_id, attached_to, attached_to_class, collection, operations, retrieve=False) -> str`
   - 返回 `attached_to`（与 TS 一致 — 不返回新生成的 id 因为 update 没新 id）

6. `async remove_collection(_class, space, object_id, attached_to, attached_to_class, collection) -> str`

**Mixin 操作 (2)**：
7. `async create_mixin(object_id, object_class, object_space, mixin, attributes) -> Any`

8. `async update_mixin(object_id, object_class, object_space, mixin, attributes) -> Any`
   - **注意**：与 hr 一致 — TS 实现里 create/update mixin 共用同一 Tx 类型；Python 同样 `return await self.create_mixin(...)`

**method 签名顺序、参数名、return type 必须与 hr 等价**（Plan 05 接入时心智一致）。
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder && head -1 plugins/huly/_internal/tx_operations.py | grep -q "Inspired by hr/offboarding-flow" && python -c "
import inspect
from plugins.huly._internal.tx_operations import TxOperations

# 8 method 签名存在
required = ['create_doc', 'update_doc', 'remove_doc',
            'add_collection', 'update_collection', 'remove_collection',
            'create_mixin', 'update_mixin']
for m in required:
    assert hasattr(TxOperations, m), f'missing {m}'
    method = getattr(TxOperations, m)
    assert inspect.iscoroutinefunction(method), f'{m} not async'

# create_doc 签名: (self, _class, space, attributes, object_id=None)
sig = inspect.signature(TxOperations.create_doc)
params = list(sig.parameters.keys())
assert params == ['self', '_class', 'space', 'attributes', 'object_id'], params

# add_collection 签名: (self, _class, space, attached_to, attached_to_class, collection, attributes, object_id=None)
sig = inspect.signature(TxOperations.add_collection)
params = list(sig.parameters.keys())
assert 'attached_to' in params and 'attached_to_class' in params and 'collection' in params

print('OK 8 methods verified')
"</automated>
  </verify>
  <done>tx_operations.py 存在；首行 attribution；TxOperations 8 async method 签名与 hr 等价；TYPE_CHECKING 模式避免与 rest_client.py 循环 import；测试 assert 全 pass</done>
</task>

<task type="auto">
  <name>Task 4: rest_client.py（hr 286 行 port + AllowlistTransport 改造，Phase 5.B Wave 2 接入）</name>
  <files>plugins/huly/_internal/rest_client.py</files>
  <action>
**前提**：Task 1 constants.py 存在；backend 已有 `app.agent_builder.platforms.sandbox.network.AllowlistTransport`（Phase 5.B Wave 2）。

**写法**：Read hr/huly/rest_client.py（286 行）一次，关掉，自己写。**不复制源码**。

第一行：
```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
```

### 4.1 模块级 imports + AllowlistTransport lazy import

```python
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountInfo:
    """Huly /api/v1/account 返回值 — 业务关心的子集（reading doc 借鉴点 #1）。"""
    uuid: str
    social_ids: tuple[str, ...]
    primary_social_id: str
    raw: dict[str, Any]


class HulyRestError(RuntimeError):
    """Huly REST/RPC 调用失败统一异常（reading doc 借鉴点 #8）。"""
```

### 4.2 `class HulyRestClient`（核心改造 — AllowlistTransport 注入）

**关键改造**（vs hr）：
- `__init__` 新增 `allow_list: list[str]` **必传**参数
- 内部构造**单一长生命周期** `httpx.AsyncClient(transport=AllowlistTransport(allow_list, delegate=None), timeout=httpx.Timeout(self._timeout))`，缓存到 `self._http_client`
- 移除所有方法内 `async with httpx.AsyncClient(...) as c:` 模式 → 改用 `self._http_client.post(...)` / `.get(...)`
- 新增 `async aclose(self)` 关闭 `self._http_client`（PlatformPlugin daemon `__init__` 关闭时调）

**为什么单实例而非 per-call new AsyncClient**:
- AllowlistTransport 在 `__init__` 解析 allow_list 构造 `_allow_set` — 单实例避免重复解析
- httpx connection pool keep-alive（daemon 长生命周期场景重要 — hr per-call new client 在 daemon 场景每次新 TCP handshake）
- 测试时 lazy import + delegate=httpx.MockTransport 可 inject mock

**lazy import**（与 huly_plugin.py 同模式 — backend PYTHONPATH 在测试时才注入）:
```python
def _build_http_client(allow_list: list[str], timeout: float) -> httpx.AsyncClient:
    """构造带 AllowlistTransport 的 httpx.AsyncClient（Plan 05b-03 沙箱白名单接入）。

    lazy import — backend.app.agent_builder 仅在 plugin daemon 内 PYTHONPATH 已注入时可用。
    单测可 monkeypatch 本函数返回 httpx.AsyncClient(transport=httpx.MockTransport(...))。
    """
    from app.agent_builder.platforms.sandbox.network import AllowlistTransport
    return httpx.AsyncClient(
        transport=AllowlistTransport(allow_list),
        timeout=httpx.Timeout(timeout),
    )
```

```python
class HulyRestClient:
    """Huly REST 客户端 — 复刻 hr/huly/rest_client.py + AllowlistTransport 沙箱（reading doc 借鉴点 #2）。

    生命周期:
    1. __init__(accounts_url=..., allow_list=..., ...)  # AllowlistTransport 注入
    2. await login(email, password)         → user token
    3. await select_workspace(token, ws)    → workspace_token (副作用缓存)
    4. await get_account()                  → AccountInfo
    5. 后续 find_all / tx / ensure_person 用 workspace_token Authorization Bearer
    6. await aclose()                       关闭底层 httpx client（daemon 关闭时调）

    AllowlistTransport 失败行为:
    - accounts_url host:port 不在 allow_list → NetworkBlockedError 即 raise（5.B 规约）
    - endpoint host:port 不在 allow_list → 同上
    - 因此 plugin manifest sandbox.network 必须含 huly_url:80 / huly_url:443 +
      transactor endpoint host:port
    """

    def __init__(
        self,
        *,
        accounts_url: str,
        allow_list: list[str],
        workspace_token: str | None = None,
        workspace_uuid: str | None = None,
        endpoint: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._accounts_url = accounts_url.rstrip("/")
        self._workspace_token = workspace_token
        self._workspace_uuid = workspace_uuid
        self._endpoint_http: str | None = (
            endpoint.replace("ws://", "http://").replace("wss://", "https://")
            if endpoint else None
        )
        self._timeout = timeout
        self._http_client: httpx.AsyncClient = _build_http_client(allow_list, timeout)

    async def aclose(self) -> None:
        """关闭底层 httpx.AsyncClient（daemon shutdown lifecycle 调）。"""
        await self._http_client.aclose()
```

### 4.3 7 endpoint 方法（与 hr 等价）

**property（3 个）** — `workspace_uuid` / `endpoint_http` / `workspace_token`，未 select_workspace 时 raise HulyRestError。

**Account RPC（2 个 — 走 accounts_url，独立 nginx /_accounts）**：
1. `async login(email: str, password: str) -> str` — POST {method: "login", params: {email, password}} → return token
2. `async select_workspace(token: str, workspace_url: str) -> dict[str, Any]` — POST {method: "selectWorkspace", params: {workspaceUrl}} → 副作用缓存 ws_token + ws_uuid + endpoint_http → return ws

**Transactor REST（5 个 — 走 endpoint_http，workspace-scoped）**：
3. `async get_account() -> AccountInfo` — GET /api/v1/account/{ws} → AccountInfo dataclass
4. `async find_all(_class, query=None, options=None) -> list[dict[str, Any]]` — GET /api/v1/find-all/{ws}?class=&query=&options= → list of docs（**注意 TS extractJson 解 `{dataType: TotalArray, value: [...]}` 模式 — 必须抽 value 数组返回；fallback 兼容 dict / list / 异常**）
5. `async find_one(_class, query=None, options=None) -> dict[str, Any] | None` — find_all + limit=1
6. `async tx(tx_obj: dict[str, Any]) -> Any` — POST /api/v1/tx/{ws} body=Tx → 透传 server 响应
7. `async ensure_person(social_type, social_value, first_name, last_name) -> dict[str, Any]` — POST /api/v1/ensure-person/{ws}

### 4.4 低层 helper（3 个）

- `_rpc(method, params, *, token=None) -> Any` — POST {accounts_url} {method, params}，自动注入 Authorization Bearer，HTTP 非 200 raise，业务 error 字段 raise
- `_get_json(path, *, params=None) -> Any` — GET {endpoint_http}{path}，注入 Authorization Bearer
- `_post_json(path, *, body) -> Any` — POST {endpoint_http}{path}，注入 Authorization Bearer + Content-Type

**Auth header**:
```python
def _auth_headers(self) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {self.workspace_token}",
        "accept-encoding": "gzip",
    }
```

**重要错误处理**（与 hr 等价）:
- 任何 HTTP status_code != 200 → raise HulyRestError(f"{method} HTTP {code}: {text[:300]}")
- body.get("error") 非空 → raise HulyRestError
- response 不是 JSON（tx 端点可能返回空 array / 单值）→ return r.text fallback
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder && head -1 plugins/huly/_internal/rest_client.py | grep -q "Inspired by hr/offboarding-flow" && grep -q "AllowlistTransport" plugins/huly/_internal/rest_client.py && grep -q "allow_list" plugins/huly/_internal/rest_client.py && wc -l plugins/huly/_internal/rest_client.py | awk '{exit ($1 >= 260 ? 0 : 1)}' && cd backend && python -c "
import sys
sys.path.insert(0, '.')  # backend/ for app.agent_builder.*
sys.path.insert(0, '..')  # repo root for plugins.*
from plugins.huly._internal.rest_client import HulyRestClient, AccountInfo, HulyRestError
import inspect

# AccountInfo dataclass
ai = AccountInfo(uuid='u', social_ids=('s1',), primary_social_id='s1', raw={})
assert ai.uuid == 'u'

# HulyRestClient __init__ 接受 allow_list
sig = inspect.signature(HulyRestClient.__init__)
params = list(sig.parameters.keys())
assert 'allow_list' in params, params
assert 'accounts_url' in params

# 7 method + aclose 存在
required = ['login', 'select_workspace', 'get_account', 'find_all', 'find_one', 'tx', 'ensure_person', 'aclose']
for m in required:
    assert hasattr(HulyRestClient, m), f'missing {m}'
    assert inspect.iscoroutinefunction(getattr(HulyRestClient, m)), f'{m} not async'

# 构造（allow_list 必传）
c = HulyRestClient(accounts_url='http://h:8087/_accounts', allow_list=['h:8087'])
assert c._accounts_url == 'http://h:8087/_accounts'

print('OK rest_client 7+1 methods + AllowlistTransport wiring')
"</automated>
  </verify>
  <done>rest_client.py ≥ 260 行；首行 attribution；HulyRestClient.__init__ 接受 allow_list: list[str] 必传；7 endpoint + aclose 全 async；内部 _build_http_client 调 AllowlistTransport；lazy import 模式（与 huly_plugin.py 一致）</done>
</task>

<task type="auto">
  <name>Task 5: platform_client.py（hr 76 行 port + lifecycle 改造）</name>
  <files>plugins/huly/_internal/platform_client.py</files>
  <action>
**前提**：Task 2 tx_factory / Task 3 tx_operations / Task 4 rest_client 全已存在。

**写法**：Read hr/huly/platform_client.py（76 行）一次，关掉，自己写。**不复制源码**。

第一行：
```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
```

### 5.1 `HulyPlatformClient` dataclass（reading doc 借鉴点 #6）

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from .rest_client import AccountInfo, HulyRestClient
from .tx_operations import TxOperations

logger = logging.getLogger(__name__)


@dataclass
class HulyPlatformClient:
    """已 connect 的 Huly 客户端 — 持 REST + Account + TxOperations。

    Plan 05 HulyPlugin daemon 用法（lifecycle 改造点）::

        # daemon entrypoint plugins/huly/huly_plugin.py _ensure_client（Plan 05 改造）
        _client = await connect_huly(
            accounts_url=os.environ["HULY_ACCOUNTS_URL"],
            admin_email=os.environ["HULY_ADMIN_EMAIL"],
            admin_password=os.environ["HULY_ADMIN_PASSWORD"],
            workspace_url=os.environ["HULY_WORKSPACE"],
            allow_list=os.environ["PLUGIN_NETWORK_ALLOW"].split(","),
            timeout=float(os.environ.get("HULY_HTTP_TIMEOUT", "15.0")),
        )
        doc_id = await _client.ops.create_doc(...)

    daemon shutdown 时调:
        await _client.rest.aclose()
    """
    rest: HulyRestClient
    account: AccountInfo
    ops: TxOperations

    @property
    def bot_account(self) -> str:
        """业务上 bot 的 PersonId / SocialId（用于审计 modifiedBy / Tx 提交者）。"""
        return self.account.primary_social_id

    async def aclose(self) -> None:
        """优雅关闭 — 委托 rest.aclose（PlatformPlugin daemon shutdown 调）。"""
        await self.rest.aclose()
```

### 5.2 `async connect_huly` factory

**关键改造**（vs hr）：
- 新增 `allow_list: list[str]` **必传**参数（PlatformPlugin daemon 从 manifest sandbox.network 读取后注入）
- 内部传给 `HulyRestClient(allow_list=allow_list)`

```python
async def connect_huly(
    *,
    accounts_url: str,
    admin_email: str,
    admin_password: str,
    workspace_url: str,
    allow_list: list[str],
    timeout: float = 15.0,
) -> HulyPlatformClient:
    """完整 connect 流程 — login + selectWorkspace + getAccount + 构造 TxOperations。

    失败抛 HulyRestError（HTTP 异常 / 业务字段缺失 / NetworkBlockedError 透传）。

    Args:
        accounts_url: Huly Account RPC URL，如 http://huly-internal:8087/_accounts
        admin_email: 管理员邮箱（已有 social id 的账号 — seed 脚本预置）
        admin_password: 密码
        workspace_url: workspace URL name（如 "laios"）
        allow_list: AllowlistTransport 白名单 ["host:port", ...]（Plan 05b-03 沙箱）
        timeout: 单次 HTTP 调用超时秒数

    Returns:
        HulyPlatformClient dataclass（rest + account + ops）
    """
    rest = HulyRestClient(
        accounts_url=accounts_url,
        allow_list=allow_list,
        timeout=timeout,
    )
    logger.info(
        "huly.connect.login email=%s workspace=%s",
        admin_email, workspace_url,
    )
    user_token = await rest.login(admin_email, admin_password)
    ws = await rest.select_workspace(user_token, workspace_url)
    logger.info(
        "huly.connect.selectWorkspace endpoint=%s workspace_uuid=%s",
        ws.get("endpoint"), ws.get("workspace"),
    )
    account = await rest.get_account()
    logger.info(
        "huly.connect.getAccount uuid=%s primary_social_id=%s social_ids=%d",
        account.uuid, account.primary_social_id, len(account.social_ids),
    )
    ops = TxOperations(rest, account.primary_social_id)
    return HulyPlatformClient(rest=rest, account=account, ops=ops)
```
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder && head -1 plugins/huly/_internal/platform_client.py | grep -q "Inspired by hr/offboarding-flow" && wc -l plugins/huly/_internal/platform_client.py | awk '{exit ($1 >= 70 ? 0 : 1)}' && cd backend && python -c "
import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')
import inspect
from plugins.huly._internal.platform_client import HulyPlatformClient, connect_huly

# HulyPlatformClient dataclass
import dataclasses
assert dataclasses.is_dataclass(HulyPlatformClient)
fields = {f.name for f in dataclasses.fields(HulyPlatformClient)}
assert {'rest', 'account', 'ops'}.issubset(fields), fields

# bot_account property + aclose async
assert isinstance(inspect.getattr_static(HulyPlatformClient, 'bot_account'), property)
assert inspect.iscoroutinefunction(HulyPlatformClient.aclose)

# connect_huly signature 含 allow_list 必传
sig = inspect.signature(connect_huly)
params = sig.parameters
assert 'allow_list' in params
assert params['allow_list'].default is inspect.Parameter.empty, 'allow_list must be required'
assert 'accounts_url' in params and 'admin_email' in params and 'workspace_url' in params

print('OK platform_client dataclass + connect_huly factory verified')
"</automated>
  </verify>
  <done>platform_client.py ≥ 70 行；首行 attribution；HulyPlatformClient 3 字段 dataclass + bot_account property + aclose async；connect_huly 接 allow_list 必传；lifecycle 三步 login/selectWorkspace/getAccount 全齐</done>
</task>

<task type="auto">
  <name>Task 6: _internal/__init__.py 公开 re-exports（5 模块全 commit 后补全）</name>
  <files>plugins/huly/_internal/__init__.py</files>
  <action>
**前提**：Task 1-5 全部 commit ✓（5 module 全可 import）。

补全 `plugins/huly/_internal/__init__.py` 的 re-exports — 让 Plan 05 一行 `from plugins.huly._internal import HulyPlatformClient, connect_huly` 即可。

```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
"""Huly 内部 module — Phase 5.C Plan 02 port from hr/offboarding-flow B-full-channel。

本子包仅供 plugins/huly/huly_plugin.py daemon 内部使用，外部模块不应直接 import
`plugins.huly._internal.rest_client` —— 通过 `plugins.huly._internal` 拿 public 符号。

模块组织（与 hr/huly/* 1:1 对应）:
- constants.py     Huly class id / space id / mixin id 字符串常量
- rest_client.py   7 REST endpoint + Account RPC（含 AllowlistTransport 沙箱白名单）
- tx_factory.py    Tx 对象工厂（5 工厂方法）
- tx_operations.py TxOperations facade（8 高阶 CRUD 方法）
- platform_client.py HulyPlatformClient + connect_huly（lifecycle 接 PlatformPlugin daemon）

License: 100% 独立创作 — 借鉴 hr 结构与方法签名，0 复制源码。
"""

from __future__ import annotations

from .constants import (
    CHUNTER_CLASS_CHANNEL,
    CHUNTER_CLASS_CHAT_MESSAGE,
    CHUNTER_CLASS_DIRECT_MESSAGE,
    CHUNTER_CLASS_THREAD_MESSAGE,
    CONTACT_CLASS_PERSON,
    CONTACT_CLASS_SOCIAL_IDENTITY,
    CONTACT_MIXIN_EMPLOYEE,
    CORE_CLASS_TX_CREATE_DOC,
    CORE_CLASS_TX_REMOVE_DOC,
    CORE_CLASS_TX_UPDATE_DOC,
    CORE_SPACE_DERIVED_TX,
    CORE_SPACE_SPACE,
    CORE_SPACE_TX,
    DEMO_EMAIL_DOMAIN,
    DOCUMENT_CLASS_DOCUMENT,
    DOCUMENT_CLASS_TEAMSPACE,
    DOCUMENT_IDS_NO_PARENT,
)
from .platform_client import HulyPlatformClient, connect_huly
from .rest_client import AccountInfo, HulyRestClient, HulyRestError
from .tx_factory import TxFactory, generate_id
from .tx_operations import TxOperations

__all__ = [
    # 平台 client
    "HulyPlatformClient",
    "connect_huly",
    # REST 层
    "HulyRestClient",
    "HulyRestError",
    "AccountInfo",
    # Tx 系统
    "TxFactory",
    "TxOperations",
    "generate_id",
    # Huly 协议常量（Plan 05 4 cap 全用）
    "CORE_CLASS_TX_CREATE_DOC",
    "CORE_CLASS_TX_UPDATE_DOC",
    "CORE_CLASS_TX_REMOVE_DOC",
    "CORE_SPACE_TX",
    "CORE_SPACE_DERIVED_TX",
    "CORE_SPACE_SPACE",
    "CONTACT_CLASS_PERSON",
    "CONTACT_CLASS_SOCIAL_IDENTITY",
    "CONTACT_MIXIN_EMPLOYEE",
    "CHUNTER_CLASS_CHANNEL",
    "CHUNTER_CLASS_CHAT_MESSAGE",
    "CHUNTER_CLASS_DIRECT_MESSAGE",
    "CHUNTER_CLASS_THREAD_MESSAGE",
    "DOCUMENT_CLASS_DOCUMENT",
    "DOCUMENT_CLASS_TEAMSPACE",
    "DOCUMENT_IDS_NO_PARENT",
    "DEMO_EMAIL_DOMAIN",
]
```
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "
import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')
from plugins.huly._internal import (
    HulyPlatformClient, connect_huly,
    HulyRestClient, HulyRestError, AccountInfo,
    TxFactory, TxOperations, generate_id,
    CORE_CLASS_TX_CREATE_DOC, CORE_SPACE_TX,
    CONTACT_MIXIN_EMPLOYEE, CHUNTER_CLASS_CHANNEL,
    DOCUMENT_CLASS_DOCUMENT, DEMO_EMAIL_DOMAIN,
)
from plugins.huly._internal import __all__
assert 'HulyPlatformClient' in __all__
assert 'connect_huly' in __all__
assert 'CORE_CLASS_TX_CREATE_DOC' in __all__
assert len(__all__) >= 20, f'__all__ too small: {len(__all__)}'
print(f'OK __all__ has {len(__all__)} symbols')
"</automated>
  </verify>
  <done>__init__.py re-export 20+ 符号；`from plugins.huly._internal import HulyPlatformClient, connect_huly` 一行可用；__all__ 完整</done>
</task>

<task type="auto">
  <name>Task 7: License attribution audit script + 全文件 attribution 验证</name>
  <files>plugins/huly/_internal/constants.py,plugins/huly/_internal/tx_factory.py,plugins/huly/_internal/tx_operations.py,plugins/huly/_internal/rest_client.py,plugins/huly/_internal/platform_client.py,plugins/huly/_internal/__init__.py</files>
  <action>
**前提**：Task 1-6 完成。

**目标**：CONTEXT.md Decision 8 + RESEARCH §Pitfall 8 AGPL 防御 — 验证 6 个文件**全部**含 attribution 注释。

```bash
# 1) 列出本 plan 创建的全部 _internal/* .py 文件
ls plugins/huly/_internal/*.py

# 2) audit：每个文件首 5 行内必须含 "Inspired by hr/offboarding-flow"
MISSING=$(grep -L "Inspired by hr/offboarding-flow" plugins/huly/_internal/*.py)
if [ -n "$MISSING" ]; then
    echo "❌ MISSING attribution: $MISSING"
    exit 1
fi
echo "✅ All 6 files have attribution"

# 3) audit：每个文件必须含 "under Apache-2.0 — not derived source"
MISSING2=$(grep -L "under Apache-2.0 — not derived source" plugins/huly/_internal/*.py)
if [ -n "$MISSING2" ]; then
    echo "❌ MISSING full attribution: $MISSING2"
    exit 1
fi

# 4) audit：rest_client.py 必须含 AllowlistTransport import / 使用
grep -q "AllowlistTransport" plugins/huly/_internal/rest_client.py || { echo "❌ rest_client missing AllowlistTransport"; exit 1; }

# 5) audit：no copy-paste from hr — 检查注释 hr 引用形式正确
# （sanity check：不能出现「Source:」或「Adapted from hr/」这种翻译式注释，应该是「Inspired by hr/」借鉴）
NOPATTERN=$(grep -lE "(Source: .*hr/offboarding|Adapted from hr/)" plugins/huly/_internal/*.py 2>/dev/null || true)
if [ -n "$NOPATTERN" ]; then
    echo "⚠️ WARNING: possible derived source attribution found in $NOPATTERN — should be 'Inspired by ... not derived source'"
fi

echo "✅ License attribution audit passed"
```

**如果任一文件缺 attribution**：返回对应 Task 重新加首行注释。**不要静默 patch** — 必须经过 git commit。

**Audit pass 标准**：
- 6 个 .py 文件全部 grep 命中 "Inspired by hr/offboarding-flow"
- 6 个 .py 文件全部 grep 命中 "under Apache-2.0 — not derived source"
- rest_client.py grep 命中 "AllowlistTransport"
- 无 "Source:" 或 "Adapted from hr/" 翻译式注释（防止有人写出 "Source: hr/huly/rest_client.py L100"）
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder && bash -c '
MISSING=$(grep -L "Inspired by hr/offboarding-flow" plugins/huly/_internal/*.py)
test -z "$MISSING" || { echo "MISSING attribution: $MISSING"; exit 1; }
MISSING2=$(grep -L "under Apache-2.0 — not derived source" plugins/huly/_internal/*.py)
test -z "$MISSING2" || { echo "MISSING full attribution: $MISSING2"; exit 1; }
grep -q "AllowlistTransport" plugins/huly/_internal/rest_client.py
COUNT=$(ls plugins/huly/_internal/*.py | wc -l | tr -d " ")
test "$COUNT" -eq 6 || { echo "expected 6 files, got $COUNT"; exit 1; }
echo "OK 6 files have attribution + rest_client wires AllowlistTransport"
'</automated>
  </verify>
  <done>6 文件全部含 "Inspired by hr/offboarding-flow" + "under Apache-2.0 — not derived source"；rest_client.py 含 AllowlistTransport；audit 脚本 0 exit code</done>
</task>

<task type="auto">
  <name>Task 8: Unit tests — TxFactory + TxOperations + HulyRestClient (httpx.MockTransport)</name>
  <files>backend/tests/platforms/test_huly_internal_port.py</files>
  <action>
**前提**：Task 1-7 全 commit ✓。

unit test 100% offline — 用 httpx.MockTransport inject 假 server response。

```python
"""Phase 5.C Plan 02 unit tests — Huly _internal port 行为验证。

测试维度（CLAUDE.md §2.2 三层测试 unit 层）:
1. TxFactory 5 方法构造字段正确性（_id 24-char hex / _class / objectId / attributes）
2. TxOperations 8 高阶方法 inner_tx 嵌套正确（TxCollectionCUD spread 而非外包）
3. HulyRestClient httpx.MockTransport inject — login/selectWorkspace/get_account 解 server response
4. AllowlistTransport 模拟拒绝场景（host 不在 allow_list）

每个 test 命名 test_<行为>，pytest.mark.asyncio 异步，独立运行。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

# repo root（上一级）加入 sys.path 让 plugins.* 可 import
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.huly._internal import (
    AccountInfo,
    HulyRestClient,
    HulyRestError,
    TxFactory,
    TxOperations,
    generate_id,
)
from plugins.huly._internal.constants import (
    CORE_CLASS_TX_CREATE_DOC,
    CORE_CLASS_TX_REMOVE_DOC,
    CORE_CLASS_TX_UPDATE_DOC,
    CORE_SPACE_DERIVED_TX,
    CORE_SPACE_TX,
)


# ── TxFactory 单测 ─────────────────────────────────────────────────────────────

class TestTxFactory:
    def test_generate_id_24_char_hex(self):
        """Pitfall: 必须 24 char hex（secrets.token_hex(12)）— Huly Ref<T> 兼容"""
        for _ in range(10):
            i = generate_id()
            assert len(i) == 24
            assert all(c in "0123456789abcdef" for c in i)

    def test_create_tx_create_doc_fields(self):
        tf = TxFactory("user:1")
        tx = tf.create_tx_create_doc(
            "chunter:class:Channel",
            "core:space:Space",
            {"name": "general", "private": False},
        )
        assert tx["_class"] == CORE_CLASS_TX_CREATE_DOC
        assert tx["space"] == CORE_SPACE_TX
        assert tx["objectClass"] == "chunter:class:Channel"
        assert tx["objectSpace"] == "core:space:Space"
        assert tx["attributes"] == {"name": "general", "private": False}
        assert tx["modifiedBy"] == "user:1"
        assert tx["createdBy"] == "user:1"
        assert tx["modifiedOn"] == tx["createdOn"]
        assert len(tx["_id"]) == 24
        assert len(tx["objectId"]) == 24

    def test_create_tx_create_doc_object_id_override(self):
        tf = TxFactory("user:1")
        tx = tf.create_tx_create_doc("a", "b", {}, object_id="custom-id-fixed")
        assert tx["objectId"] == "custom-id-fixed"

    def test_create_tx_update_doc_operations(self):
        tf = TxFactory("user:1")
        tx = tf.create_tx_update_doc(
            "contact:class:Person", "contact:space:Contacts", "obj-id",
            {"$push": {"members": "u2"}}, retrieve=True,
        )
        assert tx["_class"] == CORE_CLASS_TX_UPDATE_DOC
        assert tx["operations"] == {"$push": {"members": "u2"}}
        assert tx["retrieve"] is True

    def test_create_tx_remove_doc(self):
        tf = TxFactory("user:1")
        tx = tf.create_tx_remove_doc("contact:class:Person", "contact:space:Contacts", "obj-id")
        assert tx["_class"] == CORE_CLASS_TX_REMOVE_DOC
        assert tx["objectId"] == "obj-id"

    def test_create_tx_collection_cud_spreads_inner_not_wraps(self):
        """TS quirk: TxCollectionCUD spread inner_tx + 3 字段，不外包 _class: TxCollectionCUD"""
        tf = TxFactory("user:1")
        inner = tf.create_tx_create_doc(
            "chunter:class:ChatMessage", "core:space:Space", {"message": "hi"},
        )
        wrapper = tf.create_tx_collection_cud(
            "chunter:class:Channel", "parent-id", "core:space:Space",
            "messages", inner,
        )
        # inner 的 _class 保留（不被外层 TxCollectionCUD 覆盖）
        assert wrapper["_class"] == CORE_CLASS_TX_CREATE_DOC
        # 3 字段加上
        assert wrapper["collection"] == "messages"
        assert wrapper["attachedTo"] == "parent-id"
        assert wrapper["attachedToClass"] == "chunter:class:Channel"
        # inner 的 objectId 保留
        assert wrapper["objectId"] == inner["objectId"]

    def test_is_derived_uses_derived_tx_space(self):
        tf = TxFactory("user:1", is_derived=True)
        tx = tf.create_tx_create_doc("a", "b", {})
        assert tx["space"] == CORE_SPACE_DERIVED_TX

    def test_modified_by_override(self):
        tf = TxFactory("default-user")
        tx = tf.create_tx_create_doc("a", "b", {}, modified_by="override-user")
        assert tx["modifiedBy"] == "override-user"
        assert tx["createdBy"] == "override-user"


# ── TxOperations 单测（mock HulyRestClient.tx）──────────────────────────────────

class _FakeRestClient:
    """假 RestClient — 仅捕获 tx() 调用 + 返回 mock response，避免真起 HTTP。"""
    def __init__(self):
        self.calls: list[dict] = []
        self.response: object = []  # default empty tx result

    async def tx(self, tx_obj):
        self.calls.append(tx_obj)
        return self.response


class TestTxOperations:
    @pytest.mark.asyncio
    async def test_create_doc_returns_object_id(self):
        rest = _FakeRestClient()
        ops = TxOperations(rest, "user:1")
        doc_id = await ops.create_doc(
            "chunter:class:Channel", "core:space:Space",
            {"name": "general"},
        )
        assert len(rest.calls) == 1
        assert rest.calls[0]["_class"] == CORE_CLASS_TX_CREATE_DOC
        assert doc_id == rest.calls[0]["objectId"]

    @pytest.mark.asyncio
    async def test_add_collection_nests_tx_correctly(self):
        rest = _FakeRestClient()
        ops = TxOperations(rest, "user:1")
        msg_id = await ops.add_collection(
            "chunter:class:ChatMessage", "core:space:Space",
            "channel-id", "chunter:class:Channel",
            "messages", {"message": "hi"},
        )
        assert len(rest.calls) == 1
        outer = rest.calls[0]
        # outer 是 TxCollectionCUD spread — inner 的 _class 保留 + 加 3 字段
        assert outer["_class"] == CORE_CLASS_TX_CREATE_DOC
        assert outer["collection"] == "messages"
        assert outer["attachedTo"] == "channel-id"
        assert outer["attachedToClass"] == "chunter:class:Channel"
        assert msg_id == outer["objectId"]

    @pytest.mark.asyncio
    async def test_update_collection_returns_attached_to(self):
        rest = _FakeRestClient()
        ops = TxOperations(rest, "user:1")
        ret = await ops.update_collection(
            "chunter:class:ChatMessage", "core:space:Space",
            "msg-id", "channel-id", "chunter:class:Channel",
            "messages", {"reactions": ["👍"]},
        )
        assert ret == "channel-id"

    @pytest.mark.asyncio
    async def test_remove_doc(self):
        rest = _FakeRestClient()
        ops = TxOperations(rest, "user:1")
        await ops.remove_doc("a", "b", "obj-id")
        assert rest.calls[0]["_class"] == CORE_CLASS_TX_REMOVE_DOC

    @pytest.mark.asyncio
    async def test_create_mixin(self):
        rest = _FakeRestClient()
        ops = TxOperations(rest, "user:1")
        await ops.create_mixin("p-id", "contact:class:Person", "contact:space:Contacts",
                                "contact:mixin:Employee", {"active": True})
        assert rest.calls[0]["_class"] == "core:class:TxMixin"
        assert rest.calls[0]["attributes"] == {"active": True}

    @pytest.mark.asyncio
    async def test_update_mixin_uses_same_tx_as_create(self):
        rest = _FakeRestClient()
        ops = TxOperations(rest, "user:1")
        await ops.update_mixin("p-id", "contact:class:Person", "contact:space:Contacts",
                                "contact:mixin:Employee", {"active": False})
        # TS 实现 create/update mixin 共用同 Tx — Python 同
        assert rest.calls[0]["_class"] == "core:class:TxMixin"


# ── HulyRestClient 单测 (httpx.MockTransport inject) ─────────────────────────────

def _make_mock_client(handler, allow_list=None):
    """构造 HulyRestClient 但 monkey-patch _build_http_client 注入 MockTransport。"""
    if allow_list is None:
        allow_list = ["mock-huly:80", "mock-transactor:80"]
    rest = HulyRestClient(
        accounts_url="http://mock-huly:80/_accounts",
        allow_list=allow_list,
    )
    # monkey-patch：替换内部 httpx client 为 MockTransport
    rest._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return rest


class TestHulyRestClient:
    @pytest.mark.asyncio
    async def test_login_returns_token(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["method"] == "login"
            assert body["params"]["email"] == "admin@x"
            return httpx.Response(200, json={"result": {"token": "user-tok"}})

        rest = _make_mock_client(handler)
        token = await rest.login("admin@x", "pwd")
        assert token == "user-tok"
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_login_missing_token_raises(self):
        def handler(request):
            return httpx.Response(200, json={"result": {}})  # no token

        rest = _make_mock_client(handler)
        with pytest.raises(HulyRestError):
            await rest.login("a", "b")
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_login_business_error_raises(self):
        def handler(request):
            return httpx.Response(200, json={"error": "invalid credentials"})

        rest = _make_mock_client(handler)
        with pytest.raises(HulyRestError):
            await rest.login("a", "b")
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_login_http_500_raises(self):
        def handler(request):
            return httpx.Response(500, text="internal error")

        rest = _make_mock_client(handler)
        with pytest.raises(HulyRestError):
            await rest.login("a", "b")
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_select_workspace_caches_token_and_endpoint(self):
        def handler(request):
            return httpx.Response(200, json={
                "result": {
                    "token": "ws-tok-xxx",
                    "workspace": "uuid-1234",
                    "endpoint": "ws://mock-transactor:80",
                    "workspaceUrl": "laios",
                },
            })

        rest = _make_mock_client(handler)
        ws = await rest.select_workspace("user-tok", "laios")
        assert ws["token"] == "ws-tok-xxx"
        # 副作用缓存
        assert rest.workspace_token == "ws-tok-xxx"
        assert rest.workspace_uuid == "uuid-1234"
        assert rest.endpoint_http == "http://mock-transactor:80"  # ws:// → http://
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_get_account_returns_account_info(self):
        def handler(request):
            assert "/api/v1/account/" in str(request.url)
            assert request.headers.get("Authorization") == "Bearer ws-tok"
            return httpx.Response(200, json={
                "uuid": "person-uuid",
                "socialIds": ["s1", "s2"],
                "primarySocialId": "s1",
            })

        rest = _make_mock_client(handler)
        rest._workspace_token = "ws-tok"
        rest._workspace_uuid = "ws-uuid"
        rest._endpoint_http = "http://mock-transactor:80"
        acc = await rest.get_account()
        assert isinstance(acc, AccountInfo)
        assert acc.uuid == "person-uuid"
        assert acc.social_ids == ("s1", "s2")
        assert acc.primary_social_id == "s1"
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_find_all_extracts_value_from_total_array(self):
        """TS extractJson 解 {dataType: TotalArray, value: [...]} —— 抽 value 数组返回"""
        def handler(request):
            return httpx.Response(200, json={
                "dataType": "TotalArray",
                "total": 2,
                "value": [{"_id": "a"}, {"_id": "b"}],
            })

        rest = _make_mock_client(handler)
        rest._workspace_token = "ws-tok"
        rest._workspace_uuid = "ws-uuid"
        rest._endpoint_http = "http://mock-transactor:80"
        docs = await rest.find_all("contact:class:Person")
        assert docs == [{"_id": "a"}, {"_id": "b"}]
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_find_all_fallback_to_list_response(self):
        """server 返回裸 list 时也接受（兼容性）"""
        def handler(request):
            return httpx.Response(200, json=[{"_id": "a"}])

        rest = _make_mock_client(handler)
        rest._workspace_token = "ws-tok"
        rest._workspace_uuid = "ws-uuid"
        rest._endpoint_http = "http://mock-transactor:80"
        docs = await rest.find_all("contact:class:Person")
        assert docs == [{"_id": "a"}]
        await rest._http_client.aclose()

    @pytest.mark.asyncio
    async def test_tx_posts_to_workspace_endpoint(self):
        def handler(request):
            assert "/api/v1/tx/" in str(request.url)
            body = json.loads(request.content)
            assert body["_class"] == CORE_CLASS_TX_CREATE_DOC
            return httpx.Response(200, json=[])

        rest = _make_mock_client(handler)
        rest._workspace_token = "ws-tok"
        rest._workspace_uuid = "ws-uuid"
        rest._endpoint_http = "http://mock-transactor:80"
        tf = TxFactory("user:1")
        tx_obj = tf.create_tx_create_doc("a", "b", {})
        ret = await rest.tx(tx_obj)
        assert ret == []
        await rest._http_client.aclose()


# ── AllowlistTransport 集成（模拟）─────────────────────────────────────────────

class TestAllowlistTransportWiring:
    @pytest.mark.asyncio
    async def test_init_constructs_http_client_with_allow_list(self):
        """HulyRestClient.__init__ 真构造 AllowlistTransport（不 mock）"""
        rest = HulyRestClient(
            accounts_url="http://huly:8087/_accounts",
            allow_list=["huly:8087"],
        )
        assert rest._http_client is not None
        # transport 应是 AllowlistTransport（lazy import 检查）
        from app.agent_builder.platforms.sandbox.network import AllowlistTransport
        # httpx.AsyncClient.transport 存为 _transport（私有）
        assert isinstance(rest._http_client._transport, AllowlistTransport)
        await rest.aclose()

    @pytest.mark.asyncio
    async def test_blocked_host_raises_network_blocked_error(self):
        """allow_list 不含 endpoint host 时，HTTP 调用 raise NetworkBlockedError（透传）"""
        from app.agent_builder.platforms.exceptions import NetworkBlockedError
        # 注意：真发请求必拒（不需 mock），AllowlistTransport 自己 raise
        rest = HulyRestClient(
            accounts_url="http://untrusted-host:9999/_accounts",
            allow_list=["other:443"],  # 不含 untrusted-host:9999
        )
        with pytest.raises(NetworkBlockedError):
            await rest.login("a", "b")
        await rest.aclose()
```

**测试覆盖**:
- TxFactory: 8 tests（5 method + is_derived + override + generate_id Pitfall）
- TxOperations: 6 tests（8 method 覆盖 + nest 验证）
- HulyRestClient: 9 tests（login/selectWorkspace/getAccount/findAll/tx + 错误路径）
- AllowlistTransport wiring: 2 tests（构造 + NetworkBlockedError 触发）

**总计 25 unit tests**。
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_huly_internal_port.py -v 2>&1 | tail -40 && python -m pytest tests/platforms/test_huly_internal_port.py --collect-only -q 2>&1 | tail -3 | head -1 | grep -qE "[0-9]+ tests collected" && test $(python -m pytest tests/platforms/test_huly_internal_port.py --collect-only -q 2>&1 | grep -oE "[0-9]+ tests collected" | grep -oE "^[0-9]+") -ge 20</automated>
  </verify>
  <done>test_huly_internal_port.py 含 ≥ 20 tests；所有 test PASS；TxFactory 5 method / TxOperations 8 method / HulyRestClient 9 method / AllowlistTransport 2 wiring 全覆盖；总执行时间 < 5s（pure offline mock）</done>
</task>

<task type="auto">
  <name>Task 9: Integration tests — aiohttp mock huly server + 端到端 connect_huly + AllowlistTransport 真接</name>
  <files>backend/tests/platforms_integration/test_huly_rest_client_integration.py</files>
  <action>
**前提**：Task 1-8 全 commit ✓。

集成测起 aiohttp mock server 监听 127.0.0.1:free_port，HulyRestClient 真发 HTTP → AllowlistTransport 真路由（allow_list 含此端口）→ 验证 login + selectWorkspace + tx 端到端。

```python
"""Phase 5.C Plan 02 集成测试 — HulyRestClient 端到端（mock huly server）。

测试维度（CLAUDE.md §2.2 三层测试 integration 层）:
1. 真 aiohttp mock server + HulyRestClient.login + selectWorkspace + get_account 端到端
2. AllowlistTransport 真发请求（allow_list 含 mock server host:port）
3. AllowlistTransport NetworkBlockedError 回归（allow_list 不含 host → 即 raise）
4. connect_huly factory 三步流程端到端

不依赖真 Huly server — 全程 mock 协议级响应，offline 可跑。
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

# repo root（上 3 级 backend/tests/platforms_integration → backend → repo）
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.huly._internal import (
    AccountInfo,
    HulyPlatformClient,
    HulyRestClient,
    HulyRestError,
    TxFactory,
    connect_huly,
)
from plugins.huly._internal.constants import CORE_CLASS_TX_CREATE_DOC


@pytest.fixture
def free_port() -> int:
    """获取可用端口（mock huly server 用）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── mock huly server (aiohttp) ─────────────────────────────────────────────────


async def _accounts_handler(request: web.Request) -> web.Response:
    """模拟 Huly /_accounts JSONRPC 端点 — login + selectWorkspace。"""
    body = await request.json()
    method = body.get("method")
    if method == "login":
        if body["params"]["email"] == "admin@demo.local":
            return web.json_response({"result": {"token": "user-tok-integ"}})
        return web.json_response({"error": "invalid credentials"})
    if method == "selectWorkspace":
        if body["params"]["workspaceUrl"] == "laios":
            # endpoint 用 host header 回指自己（让 _endpoint_http 接同一 mock server）
            host = request.host  # "127.0.0.1:PORT"
            return web.json_response({
                "result": {
                    "token": "ws-tok-integ",
                    "workspace": "uuid-integ-1",
                    "endpoint": f"ws://{host}",
                    "workspaceUrl": "laios",
                },
            })
        return web.json_response({"error": "workspace not found"})
    return web.json_response({"error": f"unknown method {method}"})


async def _account_handler(request: web.Request) -> web.Response:
    """GET /api/v1/account/{ws} → AccountInfo JSON。"""
    return web.json_response({
        "uuid": "person-uuid-bot",
        "socialIds": ["email:admin@demo.local"],
        "primarySocialId": "email:admin@demo.local",
    })


async def _tx_handler(request: web.Request) -> web.Response:
    """POST /api/v1/tx/{ws} → TxResult（空 array 是 hr 协议正常响应）。"""
    body = await request.json()
    assert "_class" in body
    return web.json_response([])


async def _find_all_handler(request: web.Request) -> web.Response:
    """GET /api/v1/find-all/{ws}?class=... → TotalArray 响应。"""
    return web.json_response({
        "dataType": "TotalArray",
        "total": 1,
        "value": [{"_id": "doc-1", "_class": "contact:class:Person"}],
    })


@pytest.fixture
async def mock_huly_server(free_port):
    """启动 aiohttp mock huly server 监听 127.0.0.1:free_port。"""
    app = web.Application()
    app.router.add_post("/_accounts", _accounts_handler)
    app.router.add_get("/api/v1/account/{ws}", _account_handler)
    app.router.add_post("/api/v1/tx/{ws}", _tx_handler)
    app.router.add_get("/api/v1/find-all/{ws}", _find_all_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", free_port)
    await site.start()
    yield {
        "url": f"http://127.0.0.1:{free_port}",
        "host_port": f"127.0.0.1:{free_port}",
    }
    await runner.cleanup()


# ── HulyRestClient 端到端测试 ──────────────────────────────────────────────────


class TestHulyRestClientIntegration:
    @pytest.mark.asyncio
    async def test_login_end_to_end(self, mock_huly_server):
        rest = HulyRestClient(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            allow_list=[mock_huly_server["host_port"]],
        )
        try:
            token = await rest.login("admin@demo.local", "pwd")
            assert token == "user-tok-integ"
        finally:
            await rest.aclose()

    @pytest.mark.asyncio
    async def test_login_invalid_credentials_raises(self, mock_huly_server):
        rest = HulyRestClient(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            allow_list=[mock_huly_server["host_port"]],
        )
        try:
            with pytest.raises(HulyRestError):
                await rest.login("wrong@x", "wrong")
        finally:
            await rest.aclose()

    @pytest.mark.asyncio
    async def test_select_workspace_end_to_end(self, mock_huly_server):
        rest = HulyRestClient(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            allow_list=[mock_huly_server["host_port"]],
        )
        try:
            ws = await rest.select_workspace("user-tok", "laios")
            assert ws["token"] == "ws-tok-integ"
            assert rest.workspace_token == "ws-tok-integ"
            assert rest.endpoint_http == mock_huly_server["url"]
        finally:
            await rest.aclose()

    @pytest.mark.asyncio
    async def test_full_connect_huly_flow(self, mock_huly_server):
        """connect_huly = login + selectWorkspace + getAccount 三步流程"""
        client = await connect_huly(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            admin_email="admin@demo.local",
            admin_password="pwd",
            workspace_url="laios",
            allow_list=[mock_huly_server["host_port"]],
        )
        try:
            assert isinstance(client, HulyPlatformClient)
            assert isinstance(client.account, AccountInfo)
            assert client.account.primary_social_id == "email:admin@demo.local"
            assert client.bot_account == "email:admin@demo.local"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_tx_end_to_end(self, mock_huly_server):
        """connect → ops.create_doc → 真发 tx → mock server 回 [] → 返回 objectId"""
        client = await connect_huly(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            admin_email="admin@demo.local",
            admin_password="pwd",
            workspace_url="laios",
            allow_list=[mock_huly_server["host_port"]],
        )
        try:
            doc_id = await client.ops.create_doc(
                "chunter:class:Channel", "core:space:Space",
                {"name": "general", "private": False},
            )
            assert len(doc_id) == 24
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_find_all_returns_total_array_value(self, mock_huly_server):
        client = await connect_huly(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            admin_email="admin@demo.local",
            admin_password="pwd",
            workspace_url="laios",
            allow_list=[mock_huly_server["host_port"]],
        )
        try:
            docs = await client.rest.find_all("contact:class:Person")
            assert docs == [{"_id": "doc-1", "_class": "contact:class:Person"}]
        finally:
            await client.aclose()


# ── AllowlistTransport 真接回归 ────────────────────────────────────────────────


class TestAllowlistTransportRealRouting:
    @pytest.mark.asyncio
    async def test_blocked_host_raises_network_blocked(self, mock_huly_server):
        """allow_list 不含 mock server 端口 → NetworkBlockedError 真 raise（5.B 规约）"""
        from app.agent_builder.platforms.exceptions import NetworkBlockedError

        rest = HulyRestClient(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            allow_list=["other-host:443"],  # 故意不含 127.0.0.1:free_port
        )
        try:
            with pytest.raises(NetworkBlockedError) as exc_info:
                await rest.login("admin@demo.local", "pwd")
            assert exc_info.value.host == "127.0.0.1"
            assert "other-host:443" in exc_info.value.allowlist
        finally:
            await rest.aclose()

    @pytest.mark.asyncio
    async def test_whitelisted_host_succeeds(self, mock_huly_server):
        """allow_list 含 mock server 端口 → 请求放行 → login 正常返回 token"""
        rest = HulyRestClient(
            accounts_url=f"{mock_huly_server['url']}/_accounts",
            allow_list=[mock_huly_server["host_port"]],
        )
        try:
            token = await rest.login("admin@demo.local", "pwd")
            assert token == "user-tok-integ"
        finally:
            await rest.aclose()
```

**测试覆盖** (8 集成 tests):
- HulyRestClient end-to-end: 6（login / login fail / selectWorkspace / connect_huly / tx / find_all）
- AllowlistTransport routing: 2（blocked + whitelisted real routing）

总执行时间预计 < 10s（aiohttp 在 free_port 起停 ~每 test 200ms）。

**注意**：本 plan 不跑真 Huly server（hr 部署在 192.168.2.44:8087），那留给 Plan 08 E2E。本 plan 全程 offline mock。
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms_integration/test_huly_rest_client_integration.py -v 2>&1 | tail -30 && test $(python -m pytest tests/platforms_integration/test_huly_rest_client_integration.py --collect-only -q 2>&1 | grep -oE "[0-9]+ tests collected" | grep -oE "^[0-9]+") -ge 7</automated>
  </verify>
  <done>test_huly_rest_client_integration.py 含 ≥ 7 tests；所有 test PASS；HulyRestClient end-to-end + AllowlistTransport real routing 全通过；总执行 < 10s</done>
</task>

<task type="auto">
  <name>Task 10: Regression 验证 — Phase 5.A 271 platforms + Phase 5.B sandbox + 5/5 Huly acid test</name>
  <files>backend/tests/platforms/test_huly_internal_port.py,backend/tests/platforms_integration/test_huly_rest_client_integration.py</files>
  <action>
**前提**：Task 8-9 新测试全 PASS。

**目标**：DoD 硬性要求 — Phase 5.A 271 platforms tests + Phase 5.B 5/5 Huly acid test regression 全绿。

```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend

# 1) Phase 5.A 全 platforms 单测（不 mark linux_only）
python -m pytest tests/platforms tests/platforms_integration \
    -m "not linux_only" \
    --co -q 2>&1 | tail -3

# Expected: 至少 290+ tests collected（Phase 5.A 271 + 5.B 增量 + 本 plan 25+ unit + 8+ integration）

# 2) 跑全 platforms suite
python -m pytest tests/platforms tests/platforms_integration \
    -m "not linux_only" \
    --no-cov 2>&1 | tail -5

# Expected: passed (skipped 允许 linux_only 测试)

# 3) Huly acid test 5/5 必须 PASS
python -m pytest tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py \
    -v --no-cov 2>&1 | tail -15

# Expected: 5 passed (3 acid + 2 fault isolation)

# 4) AllowlistTransport regression
python -m pytest tests/platforms/sandbox/test_network.py tests/platforms_integration/test_network_allowlist.py \
    -v --no-cov 2>&1 | tail -10

# Expected: 17 passed (15 unit + 2 integration AllowlistTransport)

# 5) 本 plan 新增测试单独跑（确认无依赖问题）
python -m pytest tests/platforms/test_huly_internal_port.py tests/platforms_integration/test_huly_rest_client_integration.py \
    -v --no-cov 2>&1 | tail -10
```

**Acceptance**:
- 全 platforms suite 0 fail（含本 plan 新 25+ unit + 8+ integration）
- 5/5 Huly acid test PASS（plugins/huly/huly_plugin.py 未被本 plan 改 — 5.A 路径仍走 aiohttp fallback）
- 17 AllowlistTransport tests PASS
- 本 plan 新 ≥ 33 tests PASS

**如有 regression** → 立即 stop + 诊断（不要 force commit）。预期不会 — 因为：
1. `plugins/huly/_internal/` 是**新增 subpackage**，没有改 5.A 任何代码
2. `plugins/huly/huly_plugin.py` 0 改动（Plan 05 才改）
3. AllowlistTransport 0 改动（lazy import 模式与 huly_plugin.py 一致）
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py --no-cov -v 2>&1 | tail -8 | grep -qE "5 passed" && python -m pytest tests/platforms/sandbox/test_network.py tests/platforms_integration/test_network_allowlist.py --no-cov -q 2>&1 | tail -3 | head -1 | grep -qE "[0-9]+ passed" && python -m pytest tests/platforms/test_huly_internal_port.py tests/platforms_integration/test_huly_rest_client_integration.py --no-cov -q 2>&1 | tail -3 | head -1 | grep -qE "[0-9]+ passed"</automated>
  </verify>
  <done>5/5 Huly acid test PASS（plugins/huly/huly_plugin.py 0 改动）；AllowlistTransport 17 tests PASS；本 plan 新 33+ tests PASS；全 platforms suite 0 regression</done>
</task>

</tasks>

<verification>
Phase gate（plan 02 — Wave 2 与 plan 03 / plan 04 并行）：
- [ ] Task 0 Reading doc commit hash 早于 Task 1-10 任一代码 commit（CLAUDE.md §2.7 校验）
- [ ] `plugins/huly/_internal/*.py` 6 文件全部 grep -L "Inspired by hr/offboarding-flow" → 输出为空
- [ ] `python -c "from plugins.huly._internal import HulyPlatformClient, connect_huly, TxFactory, TxOperations, HulyRestClient, AccountInfo, generate_id"` 一行 import 0 错
- [ ] `python -m pytest backend/tests/platforms/test_huly_internal_port.py backend/tests/platforms_integration/test_huly_rest_client_integration.py -v --no-cov` ≥ 33 tests 全 PASS
- [ ] `python -m pytest backend/tests/platforms_integration/test_huly_acid_test.py backend/tests/platforms_integration/test_fault_isolation.py --no-cov` 5/5 PASS（regression）
- [ ] `python -m pytest backend/tests/platforms/sandbox/test_network.py backend/tests/platforms_integration/test_network_allowlist.py --no-cov` ≥ 15 PASS（AllowlistTransport regression）
- [ ] `plugins/huly/huly_plugin.py` 文件 diff vs git HEAD~10 = 0 行（本 plan 不改 daemon entrypoint）
- [ ] `plugins/huly/_internal/rest_client.py` 必须含 `from app.agent_builder.platforms.sandbox.network import AllowlistTransport`（lazy import OK）

Wave 2 并行其他 plan（plan 03 Outline / plan 04 Lark）也将独立产出 `plugins/outline/_internal/` / `plugins/lark_docs/_internal/` — 无文件冲突。
</verification>

<success_criteria>
- ✅ Task 0 reading doc ≥ 100 行 + 7+ 借鉴点（hr 5 + Dify 2）+ License attribution + 「目标 module」对应 ≥ 5 处 + commit 早于代码
- ✅ `plugins/huly/_internal/` 6 文件 port 完成（constants 60+ / tx_factory 180+ / tx_operations 150+ / rest_client 260+ / platform_client 70+ / __init__ re-exports 20+ 符号）
- ✅ 6 文件全部含 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source` attribution（audit script 全过）
- ✅ HulyRestClient.__init__ 接受 `allow_list: list[str]` 必传 + 内部 `httpx.AsyncClient(transport=AllowlistTransport(allow_list))`（Phase 5.B 接入）
- ✅ TxFactory 5 工厂方法 + TxOperations 8 高阶方法签名与 hr 等价
- ✅ Unit tests ≥ 25 PASS (TxFactory 8 + TxOperations 6 + HulyRestClient 9 + AllowlistTransport 2)
- ✅ Integration tests ≥ 8 PASS (HulyRestClient end-to-end 6 + AllowlistTransport routing 2)
- ✅ Phase 5.A 271 platforms 0 regression
- ✅ Phase 5.B 5/5 Huly acid test 0 regression（plugins/huly/huly_plugin.py 0 改动）
- ✅ AllowlistTransport 17 tests 0 regression
- ✅ 接口对外冻结：本 plan 不暴露任何 capability，`_internal/*` 仅供 Plan 05 用
</success_criteria>

<output>
完成后创建 `.planning/phases/05c-doc-capability/05c-02-SUMMARY.md`，至少含：

1. **Reading doc 链接 + commit hash**（CLAUDE.md §2.7 gate 验证）
2. **5 文件 port 行数对比表**：
   | 文件 | hr 源行数 | 本 port 行数 | 差异说明 |
   |------|---------|------------|--------|
   | constants.py | 72 | (实际) | 零改 |
   | tx_factory.py | 220 | (实际) | 零改 + docstring |
   | tx_operations.py | 182 | (实际) | 零改 + TYPE_CHECKING |
   | rest_client.py | 286 | (实际) | + AllowlistTransport 注入 + aclose lifecycle |
   | platform_client.py | 76 | (实际) | + allow_list 必传 + aclose 委托 |
3. **测试 pass 截图**：
   - Unit 25+ PASS
   - Integration 8+ PASS
   - 5/5 Huly acid test PASS（regression）
   - 17 AllowlistTransport PASS（regression）
4. **License attribution audit** 通过截图（`grep -L` 输出为空）
5. **Dify 参考点** 小节：列出 reading doc 中 Dify plugin internal module 借鉴点 + 指回 reading doc 章节锚点
6. **hr 借鉴点** 小节：列出 5 个 hr 文件每个的关键设计借鉴点（reading doc §可借鉴的设计模式 1-6 条）
7. **下一 plan 接续点**：Plan 05 HulyPlugin 4-cap bundle 集成可一行 `from plugins.huly._internal import HulyPlatformClient, connect_huly`
</output>
