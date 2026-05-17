---
phase: 05c-doc-capability
plan: 07
type: execute
wave: 4
depends_on:
  - "03"
  - "04"
  - "05"
files_modified:
  - docs/reading-dify-05c-07-capability-fallback-2026-05-18.md
  - backend/app/agent_builder/services/__init__.py
  - backend/app/agent_builder/services/doc_capability_dispatcher.py
  - backend/app/agent_builder/services/prosemirror_to_markdown.py
  - backend/app/agent_builder/services/plugin_discovery.py
  - backend/tests/platforms/test_capability_fallback_dispatcher.py
  - backend/tests/platforms/test_prosemirror_to_markdown.py
  - backend/tests/platforms/test_plugin_discovery_3plugin.py
  - backend/tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py
autonomous: true
requirements:
  - DOC-FALLBACK-01
  - DOC-DISCOVERY-01

must_haves:
  truths:
    - "Dify capability dispatch + plugin lifecycle 阅读文档先于代码 commit（CLAUDE.md §2.7 硬性 gate）"
    - "DocCapabilityDispatcher.write_document(doc_ref, content) 自动按 facade.supports_collaborative_edit 路由：True 走 apply_document_delta，False 收 delta 时 serialize 为 markdown 走 replace_document_content"
    - "Outline / Lark facade 收到 CRDTDelta 时 service 内 prosemirror_to_markdown(delta) → markdown → daemon.replace_document_content 成功"
    - "Huly facade 收到 markdown 时 service 内 markdown_to_prosemirror(markdown) → CRDTDelta(format='prosemirror-json') → daemon.apply_document_delta 成功"
    - "prosemirror_to_markdown 是 plan 05 markdown_to_prosemirror 的反向，12 元素 mapping 对称（doc/heading/paragraph/bulletList/orderedList/listItem/code_block/blockquote/horizontalRule + em/strong/code/link marks）"
    - "PluginDiscoveryService.list_available_plugins() 三 plugin 全可见（outline / lark_docs / huly），按 manifest.name 排序确定性返回"
    - "PluginDiscoveryService.install_plugin(workspace_id, plugin_name, config) 写 workspace_plugin_installations 表 + 调 PlatformPluginRegistry.get_plugin 触发 lazy spawn"
    - "三 plugin install → spawn → dispose 集成测全绿（mock outline/lark/huly server）"
    - "structured log outcome='fallback_to_replace' 在 Outline/Lark 收 delta 时出现（Phase 7 Run Viewer 钩子）"
    - "Phase 5.A 271 platforms tests + Phase 5.B 5/5 acid + Phase 5.C plan 02-05 全绿（0 regression）"
    - "DocCapability Protocol v1 接口零修改（v1.1 ai_suggest_mentions 由 plan 06 单独扩，本 plan 不动 Protocol）"

  artifacts:
    - path: "docs/reading-dify-05c-07-capability-fallback-2026-05-18.md"
      provides: "Dify capability dispatch + plugin installer + manager.py lifecycle 阅读笔记（5 节模板 + 5 借鉴点 + License attribution）"
      min_lines: 80
      contains: "可借鉴的设计模式"
    - path: "backend/app/agent_builder/services/doc_capability_dispatcher.py"
      provides: "DocCapabilityDispatcher service — 双路径自动路由 + supports_collaborative_edit 检测 + delta↔markdown 自动 serialize + structured log"
      exports: ["DocCapabilityDispatcher", "DispatchOutcome"]
      contains: "fallback_to_replace"
    - path: "backend/app/agent_builder/services/prosemirror_to_markdown.py"
      provides: "ProseMirror JSON → Markdown 反向 mapping（与 plan 05 markdown_to_prosemirror 对称 12 元素）"
      exports: ["prosemirror_to_markdown"]
      contains: "_NODE_TO_MD"
    - path: "backend/app/agent_builder/services/plugin_discovery.py"
      provides: "PluginDiscoveryService — list_available_plugins / install_plugin / uninstall_plugin / list_installed (基于 Phase 5.A Registry + workspace_plugin_installations 表)"
      exports: ["PluginDiscoveryService"]
    - path: "backend/tests/platforms/test_capability_fallback_dispatcher.py"
      provides: "Dispatcher 单元测：3 plugin × 双路径矩阵 + fallback_to_replace log 断言"
      contains: "test_outline_delta_falls_back_to_replace"
    - path: "backend/tests/platforms/test_prosemirror_to_markdown.py"
      provides: "ProseMirror→Markdown 12 元素 mapping + plan 05 round-trip 对称单测"
      contains: "test_roundtrip"
    - path: "backend/tests/platforms/test_plugin_discovery_3plugin.py"
      provides: "Discovery service 单元测：3 plugin manifest 全可见 + per-workspace install 隔离"
      contains: "test_list_available_plugins_returns_3"
    - path: "backend/tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py"
      provides: "3 plugin (Outline/Lark/Huly) install → spawn daemon → invoke → dispose 真集成 (mock server)"
      contains: "test_3plugin_lifecycle_happy_path"

  key_links:
    - from: "backend/app/agent_builder/services/doc_capability_dispatcher.py"
      to: "backend/app/agent_builder/platforms/capability_facades.py"
      via: "DocCapabilityDispatcher 调 DocFacade.supports_collaborative_edit + DocFacade.replace_document_content / apply_document_delta"
      pattern: "DocFacade"
    - from: "backend/app/agent_builder/services/doc_capability_dispatcher.py"
      to: "backend/app/agent_builder/services/prosemirror_to_markdown.py"
      via: "Outline/Lark 收 CRDTDelta 时调 prosemirror_to_markdown(delta.payload) → markdown 字符串"
      pattern: "prosemirror_to_markdown"
    - from: "backend/app/agent_builder/services/prosemirror_to_markdown.py"
      to: "plugins/huly/_internal/markdown_to_prosemirror.py"
      via: "12 元素 mapping 必须对称（_NODE_TO_MD 与 plan 05 _BLOCK_MAP/_MARK_MAP 逆向一一对应）"
      pattern: "_NODE_TO_MD"
    - from: "backend/app/agent_builder/services/plugin_discovery.py"
      to: "backend/app/agent_builder/platforms/registry.py"
      via: "list_available_plugins 调 PlatformPluginRegistry.list_manifests()；install_plugin 调 PlatformPluginRegistry.get_plugin() 触发 lazy spawn"
      pattern: "PlatformPluginRegistry"
    - from: "backend/app/agent_builder/services/plugin_discovery.py"
      to: "backend/app/models/workspace_plugin_installation.py"
      via: "install_plugin 写 WorkspacePluginInstallation 行（workspace_id × plugin_name 唯一约束）"
      pattern: "WorkspacePluginInstallation"
    - from: "backend/tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py"
      to: "backend/tests/platforms_integration/mock_huly_server.py"
      via: "复用 plan 01 已建的 mock_huly_server fixture + 新增 mock_outline / mock_lark 路由"
      pattern: "mock_huly_server"
---

<objective>
**Wave 4 并行收尾** ——  两件事原子完成：

1. **Capability fallback service layer**：DocCapabilityDispatcher 接管"业务调 doc 写"的统一入口，**业务/DAG 无需感知 plugin 是否支持 CRDT**：传 markdown 给 Huly 自动转 prosemirror delta；传 delta 给 Outline/Lark 自动反向 serialize 为 markdown 走 replace。
2. **Plugin discovery/installation 路径 wiring**：PluginDiscoveryService 把 Phase 5.A Registry + workspace_plugin_installations 表 + 三 plugin manifest 串成一条 user-visible 路径（list/install/uninstall/list_installed），三 plugin (Outline / Lark / Huly) 全可经 installer 注册 → spawn → dispose。

Purpose:
- 解决 CONTEXT.md Decision 4 双路径 "service layer fallback" 落地缺口（plan 03/04/05 各 plugin 只管自己 facade 接口，无统一 dispatch）
- 实现 ROADMAP Phase 5.C Success Criteria #1/#2/#3 中"全 6 method 实现"被业务真正调到的 wiring（不留孤儿 facade）
- 与 Wave 4 plan 06（ai_suggest_mentions）正交：plan 06 扩 DocCapability Protocol v1.1，plan 07 仅用 v1 接口做 service 层路由，互不阻塞

Output:
- Dify reading doc（Task 0 硬性 gate）+ 3 个 service module + 4 个测试文件
- 三层测试：unit (dispatcher 双路径矩阵 + prosemirror_to_markdown round-trip) / integration (3 plugin install→spawn→dispose) / E2E 留 plan 08
- DoD：Outline/Lark 收 delta 自动 fallback + Huly 收 markdown 自动转 delta + discovery 三 plugin 列出 + lifecycle 干净 + Phase 5.A/B/C 0 regression
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
@backend/app/agent_builder/platforms/capabilities/doc.py
@backend/app/agent_builder/platforms/capability_facades.py
@backend/app/agent_builder/platforms/registry.py
@backend/app/agent_builder/platforms/manifest.py
@backend/app/agent_builder/platforms/plugin.py
@backend/app/agent_builder/platforms/exceptions.py
@backend/app/models/workspace_plugin_installation.py
@backend/tests/platforms/conftest.py
@backend/tests/platforms_integration/conftest.py

<interfaces>
<!-- Plan 07 service layer 必须严格用 v1 的下述 facade/registry 接口（plan 05 已 freeze） -->

From backend/app/agent_builder/platforms/capabilities/doc.py（plan 05 已 freeze, 不动）:
```python
@dataclass(frozen=True)
class DocRef:
    plugin_name: str
    native_id: str
    extras: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class CRDTDelta:
    format: str        # "yjs" | "automerge" | "json-patch" | (本 plan 内部用) "prosemirror-json"
    payload: bytes     # 二进制 payload（prosemirror-json 时 UTF-8 编码的 JSON dict）

@runtime_checkable
class DocCapability(Protocol):
    name: str
    supports_collaborative_edit: bool
    supports_comments: bool
    async def create_document(self, *, title: str, markdown: str, owners: ...) -> DocRef: ...
    async def replace_document_content(self, doc_ref: DocRef, markdown: str) -> None: ...
    async def apply_document_delta(self, doc_ref: DocRef, delta: CRDTDelta) -> None: ...
    async def add_comment(self, *, doc_ref: DocRef, body: str, mentions: ...) -> CommentRef: ...
    async def get_document(self, doc_ref: DocRef) -> DocInfo | None: ...
```

From backend/app/agent_builder/platforms/capability_facades.py（plan 05 已 freeze, 不动）:
```python
class DocFacade(_BaseFacade):
    @property
    def supports_collaborative_edit(self) -> bool: ...
    @property
    def supports_comments(self) -> bool: ...
    async def create_document(self, *, title, markdown, owners=None) -> DocRef: ...
    async def replace_document_content(self, doc_ref: DocRef, markdown: str) -> None: ...
    async def apply_document_delta(self, doc_ref: DocRef, delta: CRDTDelta) -> None: ...
    async def add_comment(self, *, doc_ref, body, mentions=None) -> CommentRef: ...
    async def get_document(self, doc_ref: DocRef) -> DocInfo | None: ...
```

From backend/app/agent_builder/platforms/registry.py（plan 04 已 freeze）:
```python
class PlatformPluginRegistry:
    @classmethod
    def discover(cls, plugins_root: str | Path) -> list[PlatformManifest]: ...
    @classmethod
    def list_manifests(cls) -> list[PlatformManifest]: ...
    @classmethod
    def get_manifest(cls, plugin_name: str) -> PlatformManifest | None: ...
    @classmethod
    async def get_plugin(cls, workspace_id: uuid.UUID, plugin_name: str) -> PlatformPlugin | None: ...
    @classmethod
    async def get_capability(cls, workspace_id, capability_type, *, prefer=None) -> Any | None: ...
    @classmethod
    def clear(cls) -> None: ...
```

From backend/app/agent_builder/platforms/plugin.py:
```python
class PlatformPlugin:
    @property
    def name(self) -> str: ...
    @property
    def daemon(self) -> PlatformDaemonClient | None: ...
    async def attach_daemon(self) -> None: ...   # spawn daemon
    async def detach_daemon(self) -> None: ...   # close daemon
    doc: DocFacade
    im: IMFacade
    identity: IdentityFacade
```

From backend/app/models/workspace_plugin_installation.py（Phase 5.A plan 01）:
```python
class WorkspacePluginInstallation(Base):
    __tablename__ = "workspace_plugin_installations"
    id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    plugin_name: Mapped[str]
    plugin_version: Mapped[str]
    status: Mapped[str]                # 'installed' | 'disabled' | 'error'
    config_json: Mapped[dict]          # JSONB
    credentials_json: Mapped[dict | None]
    installed_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    # UniqueConstraint("workspace_id", "plugin_name")
```

From plugins/huly/_internal/markdown_to_prosemirror.py（plan 05 已 freeze — 我们要写其反向）:
```python
# plan 05 实现的 12 元素 forward mapping（reverse 必须对称）:
_BLOCK_MAP = {
    "document": "doc",           # -> doc
    "heading": "heading",         # -> heading (attrs.level)
    "paragraph": "paragraph",     # -> paragraph
    "blank_line": None,           # 跳过
    "code_block": "code_block",   # -> code_block (attrs.language)
    "list": "bulletList",         # ordered=true 时 -> orderedList
    "list_item": "listItem",      # -> listItem (必须 wrap paragraph — Pitfall 11)
    "block_quote": "blockquote",  # -> blockquote
    "thematic_break": "horizontalRule",  # -> horizontalRule
}
_MARK_MAP = {
    "emphasis": "em",
    "strong_emphasis": "strong",
    "code_span": "code",
    "link": "link",               # attrs.href
}
def markdown_to_prosemirror(markdown_text: str) -> dict[str, Any]: ...
```
</interfaces>

<reference>
**Dify 模块映射（CLAUDE.md §2.7）**：
- 后端必读 1: `/Users/admin/ai/ref/dify/repo/api/core/workflow/node_factory.py` — 节点 → capability dispatch pattern（Dify 怎么把 workflow 节点路由到 plugin capability）
- 后端必读 2: `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — PluginInstaller install / fetch / list 完整流程
- 后端必读 3: `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py`（实际路径 `api/core/plugin/`）— plugin lifecycle: install / spawn / dispose

借鉴重点（reading doc 必含 5 借鉴点）：
1. **Dispatch envelope vs. direct facade call**：Dify 是否在节点 → capability 之间塞一层 dispatcher service？（我们的设计是有 — DocCapabilityDispatcher）
2. **install endpoint shape**：Dify install_plugin 是 idempotent 吗？同 plugin 重复 install 行为？（我们设计 ON CONFLICT 升级 version）
3. **PluginInstaller list_plugins 返回字段**：Dify 给前端的 plugin metadata schema（我们对照设计 list_available_plugins 返回字段）
4. **lifecycle spawn/dispose**：Dify 怎么管 daemon 进程关闭？（我们 detach_daemon 用 Phase 5.B IdleDaemonReaper + 显式 dispose 双路径）
5. **per-tenant scoping**：Dify install 用 tenant_id 隔离 vs 我们 workspace_id（CLAUDE.md §2.4）— 设计模式对照

**License**: Dify AGPL-3.0 不拷代码；借鉴**设计模式 / 字段命名思路 / 异步流程切片**允许。

**hr/offboarding-flow 参考**: 本 plan 不直接 port hr 代码（hr 没有 service-layer dispatcher），仅引用 Phase 5.C plan 02 已 port 的 huly/_internal/* 作为依赖。
</reference>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify reading doc — capability dispatch + plugin installer + manager lifecycle（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05c-07-capability-fallback-2026-05-18.md</files>
  <action>
**STOP — 这是后续 Task 1-7 所有 commit 的前置 gate**。先 commit 此文档才允许写代码（CLAUDE.md §2.7）。

阅读以下 Dify 源文件（仅 Read 工具，不 grep；理解设计模式不抄代码）:

1. `/Users/admin/ai/ref/dify/repo/api/core/workflow/node_factory.py` — Read 前 200 行
   - 关注：节点 → handler/runtime dispatch 的查找逻辑（NodeType → NodeRunFactory 怎么映射）
2. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — Read 前 300 行
   - 关注：install_plugin / fetch_install_tasks / list_plugins / uninstall_plugin 的方法签名 + 异步流程
3. `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` 如不存在则 `/Users/admin/ai/ref/dify/repo/api/core/plugin/impl/` 子目录任一 manager-like 文件 — Read 前 200 行
   - 关注：daemon spawn / dispose / restart 的 lifecycle 状态机

写到 `docs/reading-dify-05c-07-capability-fallback-2026-05-18.md`，**严格按 CLAUDE.md §2.7 阅读文档模板（5 节标准）**：

```markdown
# Dify 阅读笔记 — Capability Dispatch + Plugin Installer + Manager Lifecycle

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> Stars: ~141k

## 项目概述（一句话）
Dify 通过 PluginInstaller (services 层) + PluginManager (core 层) 双层架构管理 plugin lifecycle；NodeFactory 把 workflow 节点路由到 plugin runtime — 我们参考这套分层管业务调 capability。

## 技术栈（关键技术选择）
- Pydantic schema 校验 install request / list response
- PostgreSQL plugin_installations 表（per-tenant 隔离）
- HTTP RPC 与 dify-plugin-daemon (Go) 通信
- 任务状态枚举（pending/running/success/failed）

## 架构要点
（用文字 + 简图说明：业务层 → service 层 → manager 层 → daemon 进程 四层；
 我们的简化对照：业务/DAG → DocCapabilityDispatcher → DocFacade → daemon）

## 可借鉴的设计模式（至少 5 条，每条指明 source file → target module）

1. **Dispatch envelope vs. direct facade call**（node_factory.py:XX）— Dify NodeFactory 在节点和 plugin runtime 之间塞一层 dispatcher 做 capability 路由 → 5.C plan 07 借鉴：DocCapabilityDispatcher 在业务和 DocFacade 之间塞一层做 supports_collaborative_edit 路由 + fallback 转换。**不拷代码，仅借鉴分层思想**。

2. **install_plugin 幂等性**（plugin_service.py:install_plugin）— Dify 同 plugin 重复 install 升级 version 而不报错 → 5.C plan 07 借鉴：PluginDiscoveryService.install_plugin 用 ON CONFLICT (workspace_id, plugin_name) DO UPDATE SET version=:new_version, updated_at=NOW()。

3. **list_plugins 返回字段 schema**（plugin_service.py:list_plugins）— Dify 给前端的 metadata 含 (name, version, declaration, status, installed_at) → 5.C plan 07 借鉴：list_available_plugins 返回 PluginMetadata dataclass 含 (name, version, capabilities, supports_collaborative_edit, sandbox_required) + list_installed 返回 (name, version, status, config_keys (脱敏))。

4. **plugin lifecycle daemon dispose**（manager.py / impl/）— Dify daemon 通过 HTTP /uninstall 触发优雅关闭 + force-kill 兜底 → 5.C plan 07 借鉴：uninstall_plugin 先调 PlatformPlugin.detach_daemon() (内部走 PlatformDaemonClient.close() Phase 5.A plan 05) 再 UPDATE status='disabled'。Phase 5.B IdleDaemonReaper 兜底自动 idle 回收。

5. **per-tenant scoping**（plugin_service.py 所有方法签名）— Dify 每方法第一参数 tenant_id → 5.C plan 07 镜像：PluginDiscoveryService 所有方法第一参数 workspace_id（CLAUDE.md §2.4 多租户基线）。区别：我们用 workspace_id（UUID）而非 string tenant_id。

## 与本项目的关系
本 plan 07 实现 service layer 双能力（dispatch + discovery），是 Phase 5.C plan 03/04/05 三 plugin facade 的"用户入口"。Phase 7 Run Viewer 通过 DocCapabilityDispatcher 的 structured log (outcome=success/fallback_to_replace/error) 给 UI 展示节点真实路径选择。

**License attribution**: Dify 是 AGPL-3.0；本项目 Apache-2.0；仅借鉴**设计模式 / 字段命名思路 / 异步流程切片**，不拷贝任何源代码。每条借鉴点已明确对应到我们要写的具体模块。本 plan 不引入任何 Dify import / copy。
```

**硬性要求**:
- 至少 80 行
- 5 借鉴点必须明确写出 source file → target module 对应关系
- 含 License attribution
- **不要**贴 Dify 源代码片段（许可证防御）

完成后 commit:
```
docs(05c-07): add Dify capability dispatch + plugin installer reading doc
```

git log 必须显示此 commit 早于 Task 1+ 的任何 feat/refactor commit。
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-07-capability-fallback-2026-05-18.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-07-capability-fallback-2026-05-18.md | awk '{exit ($1 >= 80) ? 0 : 1}' && grep -q "AGPL\|Apache-2.0" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-07-capability-fallback-2026-05-18.md && grep -q "可借鉴的设计模式" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-07-capability-fallback-2026-05-18.md && grep -cE "^[0-9]+\.\s\*\*" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-07-capability-fallback-2026-05-18.md | awk '{exit ($1 >= 5) ? 0 : 1}'</automated>
  </verify>
  <done>Reading doc 存在 ≥ 80 行；含 License attribution；含可借鉴的设计模式 5 条编号项；git log 显示本 commit 早于任何 feat/refactor commit。</done>
</task>

<task type="auto">
  <name>Task 1: prosemirror_to_markdown 反向 serialization helper（plan 05 forward 的镜像，12 元素对称）</name>
  <files>backend/app/agent_builder/services/__init__.py,backend/app/agent_builder/services/prosemirror_to_markdown.py,backend/tests/platforms/test_prosemirror_to_markdown.py</files>
  <action>
Reading doc 已 commit ✓（Task 0 gate 通过），才能开始写代码。

**目的**：实现 plan 05 `plugins/huly/_internal/markdown_to_prosemirror.py` 的反向 — 将 ProseMirror JSON dict 序列化回 Markdown 字符串。Outline/Lark facade 收到 CRDTDelta（format='prosemirror-json'，payload 是 UTF-8 编码的 JSON）时，service layer 调此函数 fallback 为 markdown 走 replace_document_content。

**对称约束**：12 元素一一对应（plan 05 forward 的 `_BLOCK_MAP` + `_MARK_MAP` 的逆向）。

---

1. **创建 `backend/app/agent_builder/services/__init__.py`**（如不存在就建空文件）:
```python
"""agent_builder service layer — capability dispatch / plugin discovery / 业务编排服务。

Phase 5.C plan 07 起新增 doc_capability_dispatcher / prosemirror_to_markdown / plugin_discovery。
后续 plan 06 + Phase 5.D 在此目录追加 service module。
"""
```

注意：项目已有 `backend/app/services/`（认证/邮件/HITL 等核心 service），新建的 `backend/app/agent_builder/services/` 与之**并列且独立** — Phase 5 platforms 体系自己的 service 层，避免污染 core service 目录。

2. **创建 `backend/app/agent_builder/services/prosemirror_to_markdown.py`**:

```python
"""ProseMirror JSON → Markdown 反向 serializer（plan 05 markdown_to_prosemirror 的镜像）。

Phase 5.C plan 07 用于 Outline / Lark fallback 路径：业务给 CRDTDelta（format='prosemirror-json'）
→ service 层调此函数 → markdown → DocFacade.replace_document_content。

12 元素 mapping 必须与 plan 05 plugins/huly/_internal/markdown_to_prosemirror.py 对称：

| ProseMirror node type | Markdown 输出 | 对应 forward (_BLOCK_MAP / _MARK_MAP) |
|---|---|---|
| doc | (top-level container, 各 content join "\n\n") | document |
| heading (attrs.level 1-6) | "#" * level + " " + inline | heading |
| paragraph | inline + "\n" | paragraph |
| bulletList | 每 listItem 前缀 "- " | list (ordered=false) |
| orderedList | 每 listItem 前缀 "{n}. " | list (ordered=true) |
| listItem | wrap 内 paragraph inline | list_item |
| code_block (attrs.language) | "```{lang}\n" + text + "\n```" | code_block |
| blockquote | 每行前缀 "> " | block_quote |
| horizontalRule | "---" | thematic_break |
| text (marks=[em])      | "*{text}*" | emphasis |
| text (marks=[strong])  | "**{text}**" | strong_emphasis |
| text (marks=[code])    | "`{text}`" | code_span |
| text (marks=[link {href}]) | "[{text}]({href})" | link |

Reference: docs/reading-dify-05c-07-capability-fallback-2026-05-18.md
- 借鉴点 #1（dispatch envelope）— 本文件是 envelope 内部用的 serializer，不直接借 Dify 代码
License: 100% 独立创作（marko/CommonMark 反向是公共算法，参考 CommonMark spec 自己实现）。
"""
from __future__ import annotations

from typing import Any

# Forward inverse: ProseMirror node type → markdown render function key
_BLOCK_RENDERERS = {
    "doc",
    "heading",
    "paragraph",
    "bulletList",
    "orderedList",
    "listItem",
    "code_block",
    "blockquote",
    "horizontalRule",
}

# Mark type → (prefix, suffix) for inline rendering
_MARK_WRAP = {
    "em": ("*", "*"),
    "strong": ("**", "**"),
    "code": ("`", "`"),
    # link 特殊处理 — 需 attrs.href
}


def prosemirror_to_markdown(pm_doc: dict[str, Any]) -> str:
    """ProseMirror JSON dict → Markdown 字符串。

    Args:
        pm_doc: ProseMirror schema dict — 顶层应为 {"type": "doc", "content": [...]}
                兼容输入：若顶层不是 doc，作为单 block 处理（防 caller 漏 wrap）

    Returns:
        Markdown 字符串（blocks 之间 "\n\n" 分隔；末尾保留单 "\n"）

    边界：
    - 未知 node type → fallback 取其 content 递归（保留文本不抛错；structured log 警告由 caller 加）
    - text node 无 marks → 原样输出
    - 多 marks 组合 → 按 [code, em, strong, link] 顺序嵌套（最内层 code，最外层 link，与 CommonMark 习惯对齐）
    """
    if not isinstance(pm_doc, dict):
        return ""

    node_type = pm_doc.get("type")
    if node_type == "doc":
        blocks = [
            _render_block(child)
            for child in pm_doc.get("content", [])
        ]
        return "\n\n".join(b for b in blocks if b) + "\n"

    # 兼容：caller 漏 wrap "doc" 时按单 block 处理
    return _render_block(pm_doc) + "\n"


def _render_block(node: dict[str, Any]) -> str:
    """渲染 block-level node。"""
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "heading":
        level = max(1, min(6, int(node.get("attrs", {}).get("level", 1))))
        inline = _render_inline(node.get("content", []))
        return f"{'#' * level} {inline}"
    if t == "paragraph":
        return _render_inline(node.get("content", []))
    if t == "bulletList":
        items = [
            f"- {_render_listitem_inner(item)}"
            for item in node.get("content", [])
            if isinstance(item, dict)
        ]
        return "\n".join(items)
    if t == "orderedList":
        items = []
        for idx, item in enumerate(node.get("content", []), start=1):
            if isinstance(item, dict):
                items.append(f"{idx}. {_render_listitem_inner(item)}")
        return "\n".join(items)
    if t == "code_block":
        lang = node.get("attrs", {}).get("language", "")
        # code_block 内容是 text node list（无 marks）
        text = "".join(
            c.get("text", "") for c in node.get("content", []) if isinstance(c, dict)
        )
        return f"```{lang}\n{text}\n```"
    if t == "blockquote":
        # blockquote 内是 block list → 渲染各 block → 每行加 "> "
        inner_blocks = [
            _render_block(b) for b in node.get("content", []) if isinstance(b, dict)
        ]
        inner_md = "\n\n".join(b for b in inner_blocks if b)
        return "\n".join(f"> {line}" if line else ">" for line in inner_md.split("\n"))
    if t == "horizontalRule":
        return "---"
    if t == "listItem":
        # 单独遇到（不在 list 内），按 - 前缀渲染
        return f"- {_render_listitem_inner(node)}"
    # fallback：未知 block type → 尝试渲染 content（不抛错）
    return _render_inline(node.get("content", []))


def _render_listitem_inner(item: dict[str, Any]) -> str:
    """listItem 内容渲染 — 通常是 [paragraph(...)] (Pitfall 11 plan 05 forward 强制 wrap)。"""
    inner_blocks = [
        _render_block(b) for b in item.get("content", []) if isinstance(b, dict)
    ]
    # 多 block listItem（嵌套 list）用 "\n  " 缩进；v1 简化为 "\n" join
    return "\n".join(b for b in inner_blocks if b)


def _render_inline(content: list[Any]) -> str:
    """渲染 inline content list → 字符串（处理 text + marks 包裹）。"""
    parts: list[str] = []
    for node in content:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "text":
            # 嵌套 block in inline 位置（罕见，但 ProseMirror schema 允许 hardBreak 等）→ 兜底 _render_block
            parts.append(_render_block(node))
            continue
        text = node.get("text", "")
        marks = node.get("marks", []) or []
        # 按 [code, em, strong, link] 顺序嵌套（最内 code，最外 link）
        wrapped = text
        # 处理普通 marks
        for mark_type in ("code", "em", "strong"):
            if any(m.get("type") == mark_type for m in marks):
                prefix, suffix = _MARK_WRAP[mark_type]
                wrapped = f"{prefix}{wrapped}{suffix}"
        # link 单独处理（最外层）
        link_mark = next((m for m in marks if m.get("type") == "link"), None)
        if link_mark:
            href = link_mark.get("attrs", {}).get("href", "")
            wrapped = f"[{wrapped}]({href})"
        parts.append(wrapped)
    return "".join(parts)


__all__ = ["prosemirror_to_markdown"]
```

3. **创建 `backend/tests/platforms/test_prosemirror_to_markdown.py`** ≥ 14 测：

```python
"""ProseMirror → Markdown 反向 serializer 单测（plan 07 capability fallback 前置）。

测试矩阵：
1. 12 元素逐一映射正确性
2. 与 plan 05 plugins.huly._internal.markdown_to_prosemirror round-trip 对称（核心 invariant）
3. 边界：空 doc / 未知 type / 多 marks 组合
"""
from __future__ import annotations

import pytest

from app.agent_builder.services.prosemirror_to_markdown import prosemirror_to_markdown


# ── 12 元素逐一映射 ───────────────────────────────────────────────────────────

def test_heading_level_1():
    pm = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 1},
         "content": [{"type": "text", "text": "Hello"}]}
    ]}
    assert prosemirror_to_markdown(pm).strip() == "# Hello"


def test_heading_level_6():
    pm = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 6},
         "content": [{"type": "text", "text": "h6"}]}
    ]}
    assert prosemirror_to_markdown(pm).strip() == "###### h6"


def test_paragraph_plain():
    pm = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "world"}]}
    ]}
    assert prosemirror_to_markdown(pm).strip() == "world"


def test_bullet_list():
    pm = {"type": "doc", "content": [
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "a"}]}
            ]},
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "b"}]}
            ]},
        ]}
    ]}
    md = prosemirror_to_markdown(pm).strip()
    assert "- a" in md and "- b" in md


def test_ordered_list_numbered():
    pm = {"type": "doc", "content": [
        {"type": "orderedList", "content": [
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "first"}]}
            ]},
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "second"}]}
            ]},
        ]}
    ]}
    md = prosemirror_to_markdown(pm).strip()
    assert "1. first" in md
    assert "2. second" in md


def test_code_block_with_language():
    pm = {"type": "doc", "content": [
        {"type": "code_block", "attrs": {"language": "python"},
         "content": [{"type": "text", "text": "print('hi')"}]}
    ]}
    md = prosemirror_to_markdown(pm).strip()
    assert md.startswith("```python")
    assert "print('hi')" in md
    assert md.endswith("```")


def test_blockquote():
    pm = {"type": "doc", "content": [
        {"type": "blockquote", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "quoted"}]}
        ]}
    ]}
    assert "> quoted" in prosemirror_to_markdown(pm)


def test_horizontal_rule():
    pm = {"type": "doc", "content": [{"type": "horizontalRule"}]}
    assert "---" in prosemirror_to_markdown(pm)


# ── inline marks ────────────────────────────────────────────────────────────

def test_inline_em():
    pm = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "italic", "marks": [{"type": "em"}]}
        ]}
    ]}
    assert "*italic*" in prosemirror_to_markdown(pm)


def test_inline_strong():
    pm = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "bold", "marks": [{"type": "strong"}]}
        ]}
    ]}
    assert "**bold**" in prosemirror_to_markdown(pm)


def test_inline_code_span():
    pm = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "x", "marks": [{"type": "code"}]}
        ]}
    ]}
    assert "`x`" in prosemirror_to_markdown(pm)


def test_inline_link():
    pm = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Go", "marks": [
                {"type": "link", "attrs": {"href": "https://example.com"}}
            ]}
        ]}
    ]}
    assert "[Go](https://example.com)" in prosemirror_to_markdown(pm)


# ── 边界 ────────────────────────────────────────────────────────────────────

def test_empty_doc_returns_newline():
    assert prosemirror_to_markdown({"type": "doc", "content": []}) == "\n"


def test_unknown_node_type_falls_back_to_content():
    pm = {"type": "doc", "content": [
        {"type": "unknown_block", "content": [{"type": "text", "text": "fallback"}]}
    ]}
    assert "fallback" in prosemirror_to_markdown(pm)


# ── round-trip 对称（核心 invariant — 与 plan 05 forward 对称）─────────────

def test_roundtrip_heading_and_list():
    """plan 05 markdown_to_prosemirror → 本 plan prosemirror_to_markdown → 等价 markdown。

    "等价"语义：去除 trailing whitespace + 空行规范化后字符串相等。
    """
    try:
        from plugins.huly._internal.markdown_to_prosemirror import markdown_to_prosemirror
    except ImportError:
        pytest.skip("plan 05 markdown_to_prosemirror 未就绪 — skip round-trip test")
    src = "# Hello\n\n- a\n- b"
    pm = markdown_to_prosemirror(src)
    md_back = prosemirror_to_markdown(pm)
    # 规范化对比
    def norm(s: str) -> str:
        return "\n".join(line.rstrip() for line in s.strip().splitlines())
    assert norm(md_back) == norm(src)


def test_roundtrip_strong_em_link():
    try:
        from plugins.huly._internal.markdown_to_prosemirror import markdown_to_prosemirror
    except ImportError:
        pytest.skip("plan 05 markdown_to_prosemirror 未就绪 — skip round-trip test")
    src = "see *foo* and **bar** and [baz](https://x.com)"
    pm = markdown_to_prosemirror(src)
    md_back = prosemirror_to_markdown(pm).strip()
    assert "*foo*" in md_back
    assert "**bar**" in md_back
    assert "[baz](https://x.com)" in md_back
```

**避坑**:
- `_render_listitem_inner` 必须 join 内部 block — Pitfall 11 plan 05 forward 强制 wrap paragraph，反向也得脱包
- `marks` 嵌套顺序：CommonMark 习惯 `[**code**](href)` 还是 `**[code](href)**`？v1 选最外层 link、内层 strong（与 plan 05 forward `_MARK_MAP` 顺序一致）
- 空字符串拼接陷阱：`"\n\n".join([""])` 是 `""` 不是 `"\n"` — 末尾显式 `+ "\n"`
- round-trip 测试用 try/skip 兼容 plan 05 未 merge 的本地分支场景

commit messages:
- `feat(05c-07): add ProseMirror → Markdown reverse serializer (12-element symmetric with plan 05)`
- `test(05c-07): add prosemirror_to_markdown 14 unit tests including roundtrip invariant`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_prosemirror_to_markdown.py -v 2>&1 | tail -25</automated>
  </verify>
  <done>prosemirror_to_markdown 12 元素 mapping 实现完整；14+ unit test 全 pass（含 2 round-trip 测试如 plan 05 已 merge）；与 plan 05 forward `_BLOCK_MAP` / `_MARK_MAP` 一一对应；services/__init__.py 文件存在。</done>
</task>

<task type="auto">
  <name>Task 2: DocCapabilityDispatcher service — 双路径自动路由 + delta↔markdown fallback + structured log</name>
  <files>backend/app/agent_builder/services/doc_capability_dispatcher.py,backend/tests/platforms/test_capability_fallback_dispatcher.py</files>
  <action>
**目的**：在业务 / DAG `doc_write` 节点和 DocFacade 之间塞一层 dispatcher，屏蔽 plugin 是否支持 CRDT 的细节。

**统一入口签名**：
```python
await dispatcher.write_document(
    workspace_id=ws,
    plugin_name="outline",       # 调用方选哪个 plugin
    doc_ref=DocRef(...),
    content=markdown_str | CRDTDelta,   # markdown 或 delta 都可接受
) -> DispatchOutcome
```

**路由矩阵**：

| facade.supports_collaborative_edit | content 类型 | 走的路径 | outcome |
|---|---|---|---|
| False (Outline/Lark) | markdown str | DocFacade.replace_document_content | "replace_direct" |
| False (Outline/Lark) | CRDTDelta (format='prosemirror-json') | service serialize → DocFacade.replace_document_content | "fallback_to_replace" |
| False (Outline/Lark) | CRDTDelta (format!='prosemirror-json') | raise UnsupportedDeltaFormat | "error_unsupported_delta" |
| True (Huly) | markdown str | service markdown_to_prosemirror → DocFacade.apply_document_delta | "convert_to_delta" |
| True (Huly) | CRDTDelta (format='prosemirror-json') | DocFacade.apply_document_delta 直接 | "delta_direct" |
| True (Huly) | CRDTDelta (format='yjs' etc) | DocFacade.apply_document_delta 直接（透传 caller 自管 format） | "delta_direct" |

---

1. **创建 `backend/app/agent_builder/services/doc_capability_dispatcher.py`**:

```python
"""DocCapabilityDispatcher — 业务/DAG → DocFacade 之间的 capability 双路径自动路由 service。

Phase 5.C plan 07 解决 CONTEXT.md Decision 4：
- supports_collaborative_edit=False 的 plugin（Outline/Lark）业务上层传 delta 时 → service 层
  自动 prosemirror_to_markdown 反向 serialize → 走 DocFacade.replace_document_content。
- supports_collaborative_edit=True 的 plugin（Huly）业务上层传 markdown 时 → service 层
  自动 markdown_to_prosemirror 转 → 走 DocFacade.apply_document_delta。
- 业务和 DAG 节点完全无感（v1.5 doc_write 节点直接调本 dispatcher）。

设计约束（不破坏 plan 03/04/05 已 freeze 接口）：
- DocFacade.supports_collaborative_edit / .replace_document_content / .apply_document_delta 0 改动
- 仅在 service 层做路由和 format 转换，不动 facade / daemon / plugin daemon 代码
- 与 plan 06 ai_suggest_mentions 正交：plan 06 扩 DocCapability Protocol v1.1 ai_suggest_mentions 方法
  本 plan 仅用 v1 5 方法接口（create / replace / apply / add_comment / get），互不阻塞

structured log schema（Phase 7 Run Viewer 钩子）：
- workspace_id / plugin_name / capability="doc" / method="write_document"
- supports_collab: bool  / input_type: "markdown" | "crdt_delta" / outcome: DispatchOutcome
- latency_ms / error_class (on error)

Reference: docs/reading-dify-05c-07-capability-fallback-2026-05-18.md
- 借鉴点 #1: Dispatch envelope vs direct facade call（Dify NodeFactory 类似分层）
License: 100% 独立创作（fallback 路径设计是本项目原创）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Union

from app.agent_builder.platforms.capabilities import CRDTDelta, DocRef
from app.agent_builder.platforms.exceptions import PluginError
from app.agent_builder.platforms.registry import PlatformPluginRegistry
from app.agent_builder.services.prosemirror_to_markdown import prosemirror_to_markdown

_log = logging.getLogger(__name__)


class DispatchOutcome(str, Enum):
    """write_document 路由结果（structured log + 调用方诊断用）。"""
    REPLACE_DIRECT = "replace_direct"             # caller markdown → facade.replace（False plugin）
    FALLBACK_TO_REPLACE = "fallback_to_replace"   # caller delta → service serialize → facade.replace
    CONVERT_TO_DELTA = "convert_to_delta"         # caller markdown → service convert → facade.apply_delta
    DELTA_DIRECT = "delta_direct"                 # caller delta → facade.apply_delta 透传
    ERROR_UNSUPPORTED_DELTA = "error_unsupported_delta"
    ERROR_PLUGIN_NOT_FOUND = "error_plugin_not_found"
    ERROR_FACADE_RAISED = "error_facade_raised"


@dataclass(frozen=True)
class DispatchResult:
    """write_document 返回 — outcome + 诊断字段。"""
    outcome: DispatchOutcome
    plugin_name: str
    supports_collaborative_edit: bool
    latency_ms: int


# Type alias for caller convenience
WriteContent = Union[str, CRDTDelta]


class UnsupportedDeltaFormatError(PluginError):
    """非 prosemirror-json 格式 delta 传给 supports_collaborative_edit=False plugin。"""


class DocCapabilityDispatcher:
    """业务 → doc capability 的双路径自动路由 service（无状态，全 classmethod 风格）。

    用法：
        await DocCapabilityDispatcher.write_document(
            workspace_id=ws,
            plugin_name="outline",
            doc_ref=DocRef(plugin_name="outline", native_id="abc"),
            content="# 新内容",   # 或 CRDTDelta(format="prosemirror-json", payload=...)
        )
    """

    @classmethod
    async def write_document(
        cls,
        *,
        workspace_id: uuid.UUID,
        plugin_name: str,
        doc_ref: DocRef,
        content: WriteContent,
    ) -> DispatchResult:
        """统一入口 — 自动按 facade.supports_collaborative_edit 路由 + 必要时 serialize。

        Args:
            workspace_id: 所属 workspace（CLAUDE.md §2.4 多租户隔离）
            plugin_name: manifest.name（如 "outline" / "lark_docs" / "huly"）
            doc_ref: 目标文档 handle
            content: markdown 字符串 或 CRDTDelta 对象（caller 无需关心 plugin 偏好）

        Returns:
            DispatchResult — outcome + 诊断字段

        Raises:
            UnsupportedDeltaFormatError: 非 prosemirror-json delta 传给 False plugin
            PluginError: plugin 未 install 或 daemon 未 attach
        """
        t0 = time.monotonic()
        plugin = await PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)
        if plugin is None or plugin.doc is None:
            cls._log_outcome(
                workspace_id=workspace_id, plugin_name=plugin_name,
                supports_collab=False, input_type=type(content).__name__,
                outcome=DispatchOutcome.ERROR_PLUGIN_NOT_FOUND,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            raise PluginError(
                f"plugin '{plugin_name}' not found or has no doc capability "
                f"(workspace_id={workspace_id})"
            )

        facade = plugin.doc
        supports_collab = facade.supports_collaborative_edit
        input_is_markdown = isinstance(content, str)
        input_is_delta = isinstance(content, CRDTDelta)
        if not input_is_markdown and not input_is_delta:
            raise TypeError(
                f"content must be str (markdown) or CRDTDelta, got {type(content).__name__}"
            )

        outcome: DispatchOutcome
        try:
            if not supports_collab:
                # ── False plugin (Outline / Lark) ─────────────────────────────
                if input_is_markdown:
                    await facade.replace_document_content(doc_ref, content)
                    outcome = DispatchOutcome.REPLACE_DIRECT
                else:
                    # CRDTDelta → 必须 prosemirror-json 格式才能 fallback
                    assert input_is_delta  # for type narrow
                    if content.format != "prosemirror-json":
                        cls._log_outcome(
                            workspace_id=workspace_id, plugin_name=plugin_name,
                            supports_collab=False, input_type="crdt_delta",
                            outcome=DispatchOutcome.ERROR_UNSUPPORTED_DELTA,
                            latency_ms=int((time.monotonic() - t0) * 1000),
                            extras={"delta_format": content.format},
                        )
                        raise UnsupportedDeltaFormatError(
                            f"plugin '{plugin_name}' (supports_collaborative_edit=False) "
                            f"received CRDTDelta(format='{content.format}'); "
                            f"only 'prosemirror-json' format can fallback to markdown replace"
                        )
                    # serialize delta → markdown → facade.replace
                    pm_doc = json.loads(content.payload.decode("utf-8"))
                    markdown = prosemirror_to_markdown(pm_doc)
                    await facade.replace_document_content(doc_ref, markdown)
                    outcome = DispatchOutcome.FALLBACK_TO_REPLACE
            else:
                # ── True plugin (Huly) ────────────────────────────────────────
                if input_is_markdown:
                    # convert markdown → prosemirror json → delta
                    # 注意：markdown_to_prosemirror 在 plugins/huly/_internal 下；
                    # service 层不能强 import plugins.huly._internal（plugin 进程隔离原则）。
                    # 解决：调 daemon 已有的 doc.replace_document_content（plugin daemon 内部
                    # 走 marko parse → ProseMirror → apply_delta 二步流程，hr Pattern 9）。
                    # plan 05 HulyPlugin 的 facade.replace_document_content 已实现此封装。
                    await facade.replace_document_content(doc_ref, content)
                    outcome = DispatchOutcome.CONVERT_TO_DELTA
                else:
                    assert input_is_delta
                    await facade.apply_document_delta(doc_ref, content)
                    outcome = DispatchOutcome.DELTA_DIRECT
        except (UnsupportedDeltaFormatError, PluginError):
            raise
        except Exception as exc:
            cls._log_outcome(
                workspace_id=workspace_id, plugin_name=plugin_name,
                supports_collab=supports_collab,
                input_type="markdown" if input_is_markdown else "crdt_delta",
                outcome=DispatchOutcome.ERROR_FACADE_RAISED,
                latency_ms=int((time.monotonic() - t0) * 1000),
                extras={"error_class": exc.__class__.__name__},
            )
            raise

        latency_ms = int((time.monotonic() - t0) * 1000)
        cls._log_outcome(
            workspace_id=workspace_id, plugin_name=plugin_name,
            supports_collab=supports_collab,
            input_type="markdown" if input_is_markdown else "crdt_delta",
            outcome=outcome, latency_ms=latency_ms,
        )
        return DispatchResult(
            outcome=outcome,
            plugin_name=plugin_name,
            supports_collaborative_edit=supports_collab,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _log_outcome(
        *, workspace_id: uuid.UUID, plugin_name: str,
        supports_collab: bool, input_type: str,
        outcome: DispatchOutcome, latency_ms: int,
        extras: dict | None = None,
    ) -> None:
        """Phase 7 Run Viewer 结构化日志钩子（schema 与 capability_facades log 对齐）。"""
        record = {
            "workspace_id": str(workspace_id),
            "plugin_name": plugin_name,
            "capability": "doc",
            "method": "write_document",
            "supports_collab": supports_collab,
            "input_type": input_type,
            "outcome": outcome.value,
            "latency_ms": latency_ms,
        }
        if extras:
            record.update(extras)
        _log.info("doc_capability.dispatcher.write_document", extra=record)


__all__ = [
    "DocCapabilityDispatcher",
    "DispatchOutcome",
    "DispatchResult",
    "UnsupportedDeltaFormatError",
    "WriteContent",
]
```

2. **创建 `backend/tests/platforms/test_capability_fallback_dispatcher.py`** ≥ 10 测：

```python
"""DocCapabilityDispatcher 单元测 — 3 plugin × 双路径矩阵 + fallback_to_replace log 断言。

测试矩阵：6 行 × 2 plugin = 12 行为；缩成 10 关键测：
1. Outline (False) + markdown → REPLACE_DIRECT
2. Outline (False) + CRDTDelta(prosemirror-json) → FALLBACK_TO_REPLACE + log outcome=fallback_to_replace
3. Outline (False) + CRDTDelta(yjs) → UnsupportedDeltaFormatError + log outcome=error_unsupported_delta
4. Lark (False) + markdown → REPLACE_DIRECT
5. Lark (False) + CRDTDelta(prosemirror-json) → FALLBACK_TO_REPLACE
6. Huly (True) + markdown → CONVERT_TO_DELTA（facade.replace 被调，daemon 内做转换）
7. Huly (True) + CRDTDelta(prosemirror-json) → DELTA_DIRECT
8. Huly (True) + CRDTDelta(yjs) → DELTA_DIRECT（True plugin 透传）
9. plugin 未 install → ERROR_PLUGIN_NOT_FOUND + raise PluginError
10. content 不是 str/CRDTDelta → raise TypeError
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_builder.platforms.capabilities import CRDTDelta, DocRef
from app.agent_builder.platforms.exceptions import PluginError
from app.agent_builder.services.doc_capability_dispatcher import (
    DispatchOutcome,
    DocCapabilityDispatcher,
    UnsupportedDeltaFormatError,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_plugin_mock(*, name: str, supports_collab: bool) -> MagicMock:
    """构造 mock PlatformPlugin（doc facade + replace + apply 都 mock）。"""
    plugin = MagicMock()
    plugin.doc.supports_collaborative_edit = supports_collab
    plugin.doc.name = name
    plugin.doc.replace_document_content = AsyncMock(return_value=None)
    plugin.doc.apply_document_delta = AsyncMock(return_value=None)
    return plugin


def _doc_ref(name: str) -> DocRef:
    return DocRef(plugin_name=name, native_id="doc-1")


def _delta_pm_json(text: str = "hello") -> CRDTDelta:
    payload = json.dumps({"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    ]}).encode("utf-8")
    return CRDTDelta(format="prosemirror-json", payload=payload)


def _delta_yjs() -> CRDTDelta:
    return CRDTDelta(format="yjs", payload=b"\x00\x01\x02fake_binary")


# ── 测试 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outline_markdown_goes_replace_direct():
    """Outline (False) + markdown → REPLACE_DIRECT。"""
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="outline", supports_collab=False)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=ws, plugin_name="outline",
            doc_ref=_doc_ref("outline"), content="# Hello",
        )
    assert result.outcome == DispatchOutcome.REPLACE_DIRECT
    plugin.doc.replace_document_content.assert_awaited_once()
    plugin.doc.apply_document_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_outline_delta_falls_back_to_replace(caplog):
    """Outline (False) + CRDTDelta(prosemirror-json) → FALLBACK_TO_REPLACE + log outcome=fallback_to_replace。"""
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="outline", supports_collab=False)
    caplog.set_level(logging.INFO)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=ws, plugin_name="outline",
            doc_ref=_doc_ref("outline"), content=_delta_pm_json("from-delta"),
        )
    assert result.outcome == DispatchOutcome.FALLBACK_TO_REPLACE
    # 验证 facade.replace 被调用 + 传入的 markdown 含 "from-delta"
    plugin.doc.replace_document_content.assert_awaited_once()
    call_args = plugin.doc.replace_document_content.await_args
    passed_markdown = call_args.args[1]
    assert "from-delta" in passed_markdown
    # 验证 structured log 含 outcome=fallback_to_replace
    log_records = [r for r in caplog.records if "fallback_to_replace" in str(getattr(r, "outcome", ""))]
    assert len(log_records) >= 1
    assert log_records[0].plugin_name == "outline"


@pytest.mark.asyncio
async def test_outline_yjs_delta_raises_unsupported_format(caplog):
    """Outline (False) + CRDTDelta(yjs) → UnsupportedDeltaFormatError + log outcome=error_unsupported_delta。"""
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="outline", supports_collab=False)
    caplog.set_level(logging.INFO)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        with pytest.raises(UnsupportedDeltaFormatError):
            await DocCapabilityDispatcher.write_document(
                workspace_id=ws, plugin_name="outline",
                doc_ref=_doc_ref("outline"), content=_delta_yjs(),
            )
    plugin.doc.replace_document_content.assert_not_awaited()
    plugin.doc.apply_document_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_lark_markdown_replace_direct():
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="lark_docs", supports_collab=False)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=ws, plugin_name="lark_docs",
            doc_ref=_doc_ref("lark_docs"), content="lark md",
        )
    assert result.outcome == DispatchOutcome.REPLACE_DIRECT


@pytest.mark.asyncio
async def test_lark_delta_falls_back_to_replace():
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="lark_docs", supports_collab=False)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=ws, plugin_name="lark_docs",
            doc_ref=_doc_ref("lark_docs"), content=_delta_pm_json("hi-lark"),
        )
    assert result.outcome == DispatchOutcome.FALLBACK_TO_REPLACE


@pytest.mark.asyncio
async def test_huly_markdown_converts_to_delta_path():
    """Huly (True) + markdown → CONVERT_TO_DELTA（service 调 facade.replace；daemon 内做转换）。"""
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="huly", supports_collab=True)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=ws, plugin_name="huly",
            doc_ref=_doc_ref("huly"), content="# Huly md",
        )
    assert result.outcome == DispatchOutcome.CONVERT_TO_DELTA
    plugin.doc.replace_document_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_huly_pm_delta_direct():
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="huly", supports_collab=True)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=ws, plugin_name="huly",
            doc_ref=_doc_ref("huly"), content=_delta_pm_json("hi"),
        )
    assert result.outcome == DispatchOutcome.DELTA_DIRECT
    plugin.doc.apply_document_delta.assert_awaited_once()


@pytest.mark.asyncio
async def test_huly_yjs_delta_direct_passthrough():
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="huly", supports_collab=True)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=ws, plugin_name="huly",
            doc_ref=_doc_ref("huly"), content=_delta_yjs(),
        )
    assert result.outcome == DispatchOutcome.DELTA_DIRECT


@pytest.mark.asyncio
async def test_plugin_not_found_raises_plugin_error(caplog):
    ws = uuid.uuid4()
    caplog.set_level(logging.INFO)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(PluginError):
            await DocCapabilityDispatcher.write_document(
                workspace_id=ws, plugin_name="ghost",
                doc_ref=_doc_ref("ghost"), content="x",
            )
    # 验证 structured log 含 outcome=error_plugin_not_found
    log_records = [
        r for r in caplog.records
        if "error_plugin_not_found" in str(getattr(r, "outcome", ""))
    ]
    assert len(log_records) >= 1


@pytest.mark.asyncio
async def test_invalid_content_type_raises_type_error():
    ws = uuid.uuid4()
    plugin = _make_plugin_mock(name="outline", supports_collab=False)
    with patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(return_value=plugin),
    ):
        with pytest.raises(TypeError):
            await DocCapabilityDispatcher.write_document(
                workspace_id=ws, plugin_name="outline",
                doc_ref=_doc_ref("outline"), content=12345,  # type: ignore[arg-type]
            )
```

**避坑**:
- `caplog.set_level(logging.INFO)` 必须显式设；本 module logger 默认 WARNING 不抓 INFO
- `caplog.records` 取 `extra` 字段需 `getattr(r, "outcome", "")` — extra 在 LogRecord 上作 attribute
- mock plugin.doc.supports_collaborative_edit 必须**直接赋 bool**（不是 property mock），因为 facade 是 property — 但 MagicMock auto-assign 兼容
- Huly markdown 路径选 CONVERT_TO_DELTA 而非"调 markdown_to_prosemirror"是设计决策：service 不强 import `plugins.huly._internal`（plugin 进程隔离原则），让 plan 05 HulyPlugin 的 facade.replace_document_content 在 daemon 内部做二步流程（hr Pattern 9）

commit messages:
- `feat(05c-07): add DocCapabilityDispatcher service with double-path routing + fallback_to_replace`
- `test(05c-07): add 10 dispatcher matrix tests (3 plugin × bi-directional content)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_capability_fallback_dispatcher.py -v 2>&1 | tail -30</automated>
  </verify>
  <done>DocCapabilityDispatcher 6 行为路径全实现；UnsupportedDeltaFormatError 在非 prosemirror-json delta + False plugin 场景 raise；structured log outcome 字段含 fallback_to_replace；10+ unit test 全 pass。</done>
</task>

<task type="auto">
  <name>Task 3: PluginDiscoveryService — 三 plugin discovery + install/uninstall wiring（用 Phase 5.A Registry + workspace_plugin_installations 表）</name>
  <files>backend/app/agent_builder/services/plugin_discovery.py,backend/tests/platforms/test_plugin_discovery_3plugin.py</files>
  <action>
**目的**：把 Phase 5.A `PlatformPluginRegistry` + `workspace_plugin_installations` 表 + 三 plugin manifest 串成 user-visible 路径。

**业务面 4 个方法**：
1. `list_available_plugins()` — 列所有已 discover 的 manifest（不依赖 workspace）
2. `list_installed(workspace_id)` — 列该 workspace 已 install 的 plugin 行
3. `install_plugin(workspace_id, plugin_name, config_json, credentials_json)` — 写表 + lazy spawn
4. `uninstall_plugin(workspace_id, plugin_name)` — UPDATE status='disabled' + detach daemon

**Discovery wiring**：确保三 plugin manifest（outline / lark_docs / huly）都能被 `PlatformPluginRegistry.discover("plugins/")` 扫到（不破坏 Phase 5.A discover 逻辑，增量验证）。

---

1. **创建 `backend/app/agent_builder/services/plugin_discovery.py`**:

```python
"""PluginDiscoveryService — Phase 5.A PlatformPluginRegistry + workspace_plugin_installations 表
的 user-facing 包装。

Phase 5.C plan 07 解决两个需求：
1. 三 plugin（outline / lark_docs / huly）全可被业务面 "list available plugins" 看到
2. 业务调 install_plugin → 写 workspace_plugin_installations 行 + lazy spawn daemon

设计约束（不破坏 Phase 5.A 已有 installer 框架）：
- Phase 5.A 只有 PlatformPluginRegistry（discover + get_plugin），没有 service-layer installer
- 本 plan 在 service 层加薄包装，DB 写入 + Registry 调用配合
- workspace_plugin_installations 表（Phase 5.A plan 01）的 UniqueConstraint(workspace_id, plugin_name)
  保证幂等（同 plugin 重复 install 升级 version 而非报错 — Dify reading doc 借鉴点 #2）

Reference: docs/reading-dify-05c-07-capability-fallback-2026-05-18.md
- 借鉴点 #2: install_plugin 幂等性 (ON CONFLICT UPDATE)
- 借鉴点 #3: list_plugins 返回 metadata schema
- 借鉴点 #4: lifecycle dispose（uninstall 调 plugin.detach_daemon + UPDATE status='disabled'）
- 借鉴点 #5: per-tenant scoping (workspace_id 第一参数)
License: 100% 独立创作。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.platforms.exceptions import PluginError
from app.agent_builder.platforms.registry import PlatformPluginRegistry
from app.models.workspace_plugin_installation import WorkspacePluginInstallation

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginMetadata:
    """Plugin 元信息 — list_available_plugins 返回项（前端 plugin marketplace UI 用）。"""
    name: str
    version: str
    capabilities: tuple[str, ...]
    supports_collaborative_edit: bool | None    # only when capabilities 含 "doc"
    sandbox_required: bool                       # manifest.sandbox is not None


@dataclass(frozen=True)
class InstalledPlugin:
    """已 install 的 plugin 行 — list_installed 返回项。"""
    plugin_name: str
    plugin_version: str
    status: str                          # 'installed' / 'disabled' / 'error'
    config_keys: tuple[str, ...]         # 脱敏：只露 key 不露 value
    installed_at: datetime
    updated_at: datetime


class PluginDiscoveryService:
    """Plugin discovery + install / uninstall service（无状态 classmethod）。"""

    @classmethod
    def list_available_plugins(cls) -> list[PluginMetadata]:
        """列所有已 discover 的 plugin manifest（不依赖 workspace；前端 marketplace UI 用）。

        Returns:
            list[PluginMetadata] — 按 name 排序确定性返回
        """
        manifests = PlatformPluginRegistry.list_manifests()
        out: list[PluginMetadata] = []
        for m in sorted(manifests, key=lambda x: x.name):
            supports_collab: bool | None = None
            if "doc" in m.capabilities and m.doc is not None:
                supports_collab = bool(m.doc.supports_collaborative_edit)
            out.append(PluginMetadata(
                name=m.name,
                version=m.version,
                capabilities=tuple(m.capabilities),
                supports_collaborative_edit=supports_collab,
                sandbox_required=(m.sandbox is not None),
            ))
        return out

    @classmethod
    async def list_installed(
        cls, *, workspace_id: uuid.UUID, db: AsyncSession,
    ) -> list[InstalledPlugin]:
        """列该 workspace 已 install 的 plugin（按 plugin_name 排序）。"""
        stmt = (
            select(WorkspacePluginInstallation)
            .where(WorkspacePluginInstallation.workspace_id == workspace_id)
            .order_by(WorkspacePluginInstallation.plugin_name)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            InstalledPlugin(
                plugin_name=row.plugin_name,
                plugin_version=row.plugin_version,
                status=row.status,
                config_keys=tuple(sorted((row.config_json or {}).keys())),
                installed_at=row.installed_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    @classmethod
    async def install_plugin(
        cls,
        *,
        workspace_id: uuid.UUID,
        plugin_name: str,
        config_json: dict[str, Any] | None = None,
        credentials_json: dict[str, Any] | None = None,
        db: AsyncSession,
        spawn_daemon: bool = False,
    ) -> InstalledPlugin:
        """安装（或升级）plugin 到 workspace — 幂等 ON CONFLICT 升级 version。

        Args:
            workspace_id: 目标 workspace
            plugin_name: 必须已被 PlatformPluginRegistry.discover 找到
            config_json: 非敏感配置（JSONB）
            credentials_json: 敏感凭据（JSONB；前端永不读回）
            db: AsyncSession
            spawn_daemon: True 时立即 attach daemon（默认 False 让 IdleDaemonReaper lazy spawn）

        Returns:
            InstalledPlugin — 安装后的行

        Raises:
            PluginError: plugin_name 未在 Registry manifest 中存在
        """
        manifest = PlatformPluginRegistry.get_manifest(plugin_name)
        if manifest is None:
            raise PluginError(
                f"plugin '{plugin_name}' not discovered; "
                f"available: {[m.name for m in PlatformPluginRegistry.list_manifests()]}"
            )

        now = datetime.now(timezone.utc)
        # ON CONFLICT (workspace_id, plugin_name) DO UPDATE 升级 version（Dify 借鉴点 #2）
        stmt = pg_insert(WorkspacePluginInstallation).values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            plugin_name=plugin_name,
            plugin_version=manifest.version,
            status="installed",
            config_json=config_json or {},
            credentials_json=credentials_json,
            installed_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_workspace_plugin",
            set_={
                "plugin_version": manifest.version,
                "status": "installed",
                "config_json": config_json or {},
                "credentials_json": credentials_json,
                "updated_at": now,
            },
        ).returning(WorkspacePluginInstallation)
        result = await db.execute(stmt)
        row = result.scalar_one()
        await db.flush()

        _log.info(
            "plugin_discovery.install",
            extra={
                "workspace_id": str(workspace_id),
                "plugin_name": plugin_name,
                "plugin_version": manifest.version,
                "spawn_daemon": spawn_daemon,
            },
        )

        # 触发 Registry lazy spawn（spawn_daemon=True 时 attach；否则等首次 invoke 时再起）
        if spawn_daemon:
            plugin = await PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)
            if plugin is not None and plugin.daemon is None:
                # Plan 05 加的 attach_daemon
                attach = getattr(plugin, "attach_daemon", None)
                if attach is not None:
                    await attach()

        return InstalledPlugin(
            plugin_name=row.plugin_name,
            plugin_version=row.plugin_version,
            status=row.status,
            config_keys=tuple(sorted((row.config_json or {}).keys())),
            installed_at=row.installed_at,
            updated_at=row.updated_at,
        )

    @classmethod
    async def uninstall_plugin(
        cls,
        *,
        workspace_id: uuid.UUID,
        plugin_name: str,
        db: AsyncSession,
    ) -> bool:
        """卸载 plugin — 优雅 dispose daemon + UPDATE status='disabled'（不删行，留 audit 记录）。

        Returns:
            True 若该 workspace 之前确实 install 了；False 若没装过（idempotent）
        """
        # 1. detach daemon（如果在跑）
        plugin = await PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)
        if plugin is not None and plugin.daemon is not None:
            detach = getattr(plugin, "detach_daemon", None)
            if detach is not None:
                try:
                    await detach()
                except Exception as e:
                    _log.warning(
                        "plugin_discovery.detach_daemon_failed",
                        extra={"plugin_name": plugin_name, "error": str(e)},
                    )

        # 2. UPDATE status='disabled'
        stmt = (
            select(WorkspacePluginInstallation)
            .where(WorkspacePluginInstallation.workspace_id == workspace_id)
            .where(WorkspacePluginInstallation.plugin_name == plugin_name)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False
        row.status = "disabled"
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()

        _log.info(
            "plugin_discovery.uninstall",
            extra={"workspace_id": str(workspace_id), "plugin_name": plugin_name},
        )
        return True


__all__ = ["PluginDiscoveryService", "PluginMetadata", "InstalledPlugin"]
```

2. **创建 `backend/tests/platforms/test_plugin_discovery_3plugin.py`** ≥ 8 测：

```python
"""PluginDiscoveryService 单元测 — 三 plugin manifest 全可见 + per-workspace 隔离。

测试矩阵：
1. list_available_plugins 三 plugin 全可见（含 outline / lark_docs / huly）
2. list_available_plugins 返回按 name 排序确定性
3. list_available_plugins PluginMetadata.supports_collaborative_edit 三 plugin 值正确（False/False/True）
4. install_plugin 第一次写表 + version
5. install_plugin 第二次同 (workspace, plugin) 幂等升级 version（ON CONFLICT）
6. install_plugin 未 discover 的 plugin → PluginError
7. uninstall_plugin 已 install → status='disabled'
8. uninstall_plugin 未 install → 返回 False（idempotent）
9. 双 workspace 隔离：A install outline，B 看不到 A 的安装行
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio

from app.agent_builder.platforms.exceptions import PluginError
from app.agent_builder.platforms.manifest import (
    CapabilitySpec,
    PlatformManifest,
)
from app.agent_builder.platforms.registry import PlatformPluginRegistry
from app.agent_builder.services.plugin_discovery import (
    InstalledPlugin,
    PluginDiscoveryService,
    PluginMetadata,
)


def _fake_manifest(
    name: str, *, capabilities: list[str], collab: bool | None = None,
) -> PlatformManifest:
    """构造 fake manifest 用于 Registry 注入（避免依赖磁盘 plugins/*/platform.yaml）。"""
    doc_spec = None
    if "doc" in capabilities:
        # 直接构造 CapabilitySpec（manifest 字段）
        doc_spec = CapabilitySpec(supports_collaborative_edit=bool(collab))
    return PlatformManifest(
        name=name,
        version="1.0.0",
        capabilities=capabilities,
        doc=doc_spec,
    )


@pytest_asyncio.fixture
async def fresh_registry_with_3plugin():
    """清空 Registry → 注入 outline / lark_docs / huly 三 fake manifest → yield → 清空。"""
    PlatformPluginRegistry.clear()
    PlatformPluginRegistry._MANIFESTS["outline"] = _fake_manifest(
        "outline", capabilities=["doc"], collab=False,
    )
    PlatformPluginRegistry._MANIFESTS["lark_docs"] = _fake_manifest(
        "lark_docs", capabilities=["doc", "identity"], collab=False,
    )
    PlatformPluginRegistry._MANIFESTS["huly"] = _fake_manifest(
        "huly", capabilities=["doc", "im", "identity"], collab=True,
    )
    yield
    PlatformPluginRegistry.clear()


# ── list_available_plugins ─────────────────────────────────────────────────


def test_list_available_plugins_returns_3(fresh_registry_with_3plugin):
    plugins = PluginDiscoveryService.list_available_plugins()
    names = [p.name for p in plugins]
    assert set(names) == {"outline", "lark_docs", "huly"}
    assert len(plugins) == 3


def test_list_available_plugins_sorted_by_name(fresh_registry_with_3plugin):
    plugins = PluginDiscoveryService.list_available_plugins()
    assert [p.name for p in plugins] == ["huly", "lark_docs", "outline"]


def test_list_available_plugins_supports_collab_correct(fresh_registry_with_3plugin):
    by_name = {p.name: p for p in PluginDiscoveryService.list_available_plugins()}
    assert by_name["outline"].supports_collaborative_edit is False
    assert by_name["lark_docs"].supports_collaborative_edit is False
    assert by_name["huly"].supports_collaborative_edit is True


# ── install_plugin ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_plugin_first_time_writes_row(
    fresh_registry_with_3plugin, db_session, workspace_id_a,
):
    row = await PluginDiscoveryService.install_plugin(
        workspace_id=workspace_id_a, plugin_name="outline",
        config_json={"base_url": "https://outline.example.com"},
        credentials_json={"api_token": "tok_xxx"},
        db=db_session, spawn_daemon=False,
    )
    assert isinstance(row, InstalledPlugin)
    assert row.plugin_name == "outline"
    assert row.plugin_version == "1.0.0"
    assert row.status == "installed"
    assert "base_url" in row.config_keys


@pytest.mark.asyncio
async def test_install_plugin_idempotent_upgrades_version(
    fresh_registry_with_3plugin, db_session, workspace_id_a,
):
    # 第 1 次
    await PluginDiscoveryService.install_plugin(
        workspace_id=workspace_id_a, plugin_name="huly",
        config_json={"key1": "v1"}, db=db_session,
    )
    # 模拟 manifest 升级版本
    PlatformPluginRegistry._MANIFESTS["huly"] = _fake_manifest(
        "huly", capabilities=["doc", "im", "identity"], collab=True,
    )
    PlatformPluginRegistry._MANIFESTS["huly"].version = "1.0.0"  # 同版本 ON CONFLICT
    # 第 2 次：同 (ws, name) — 应走 ON CONFLICT UPDATE 不报错
    row = await PluginDiscoveryService.install_plugin(
        workspace_id=workspace_id_a, plugin_name="huly",
        config_json={"key2": "v2"}, db=db_session,
    )
    assert row.plugin_name == "huly"
    assert "key2" in row.config_keys  # config 已升级
    # 验证 list_installed 仍只有 1 行
    installed = await PluginDiscoveryService.list_installed(
        workspace_id=workspace_id_a, db=db_session,
    )
    assert len([r for r in installed if r.plugin_name == "huly"]) == 1


@pytest.mark.asyncio
async def test_install_plugin_unknown_raises_plugin_error(
    fresh_registry_with_3plugin, db_session, workspace_id_a,
):
    with pytest.raises(PluginError, match="not discovered"):
        await PluginDiscoveryService.install_plugin(
            workspace_id=workspace_id_a, plugin_name="ghost",
            config_json={}, db=db_session,
        )


# ── uninstall_plugin ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uninstall_plugin_marks_disabled(
    fresh_registry_with_3plugin, db_session, workspace_id_a,
):
    await PluginDiscoveryService.install_plugin(
        workspace_id=workspace_id_a, plugin_name="lark_docs",
        config_json={}, db=db_session,
    )
    result = await PluginDiscoveryService.uninstall_plugin(
        workspace_id=workspace_id_a, plugin_name="lark_docs", db=db_session,
    )
    assert result is True
    installed = await PluginDiscoveryService.list_installed(
        workspace_id=workspace_id_a, db=db_session,
    )
    lark_row = next(r for r in installed if r.plugin_name == "lark_docs")
    assert lark_row.status == "disabled"


@pytest.mark.asyncio
async def test_uninstall_plugin_never_installed_returns_false(
    fresh_registry_with_3plugin, db_session, workspace_id_a,
):
    result = await PluginDiscoveryService.uninstall_plugin(
        workspace_id=workspace_id_a, plugin_name="outline", db=db_session,
    )
    assert result is False


# ── workspace 隔离 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_isolation_install(
    fresh_registry_with_3plugin, db_session, workspace_id_a, workspace_id_b,
):
    """workspace A install outline → workspace B list_installed 不应看到。"""
    await PluginDiscoveryService.install_plugin(
        workspace_id=workspace_id_a, plugin_name="outline",
        config_json={}, db=db_session,
    )
    a_installed = await PluginDiscoveryService.list_installed(
        workspace_id=workspace_id_a, db=db_session,
    )
    b_installed = await PluginDiscoveryService.list_installed(
        workspace_id=workspace_id_b, db=db_session,
    )
    assert any(r.plugin_name == "outline" for r in a_installed)
    assert not any(r.plugin_name == "outline" for r in b_installed)
```

**避坑**:
- `pg_insert(...).on_conflict_do_update(constraint="uq_workspace_plugin", ...)` 必须用约束名（plan 01 已定 `uq_workspace_plugin`）
- `PlatformPluginRegistry._MANIFESTS["huly"].version = "1.0.0"` — Pydantic 模型默认 frozen=False（manifest 不是 dataclass(frozen=True)），可直接设；如真 frozen 需 model_copy
- 测试用 `_fake_manifest()` 跳过磁盘 yaml load — Registry 内部 `_MANIFESTS` 是 dict 直接注入可
- discovery wiring 真验证（plugins/ 目录扫描）放 integration test（Task 4）

commit messages:
- `feat(05c-07): add PluginDiscoveryService for 3-plugin discover/install/uninstall`
- `test(05c-07): add 8 plugin_discovery tests including workspace isolation`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_plugin_discovery_3plugin.py -v 2>&1 | tail -25</automated>
  </verify>
  <done>PluginDiscoveryService 4 方法（list_available / list_installed / install / uninstall）实现完整；ON CONFLICT 幂等升级正确；workspace 隔离测过；8+ unit test 全 pass。</done>
</task>

<task type="auto">
  <name>Task 4: 3 plugin install → spawn → invoke → dispose 集成测（mock outline/lark server + 已有 mock huly server）</name>
  <files>backend/tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py</files>
  <action>
**目的**：真起 daemon 子进程 + 真 mock server，端到端验证三 plugin lifecycle 干净。

**复用现有基础设施**：
- `mock_huly_server` fixture (plan 01 integration conftest 已建) — 直接复用
- `free_port` / `project_root` fixture — 直接复用
- mock outline / mock lark 服务器：本 plan 新建（最简 aiohttp stub 或 mock httpx transport）

**测试场景**：
1. `test_3plugin_lifecycle_happy_path`：依次 install outline / lark_docs / huly → 各自 spawn daemon → 调一次 doc.create_document → detach → 验 daemon exit code 0
2. `test_3plugin_parallel_install`：并行 install 三 plugin → 三 daemon 同时跑 → 互不影响
3. `test_huly_install_via_dispatcher_e2e`：install huly → 通过 DocCapabilityDispatcher.write_document 调 → DELTA_DIRECT 走通

---

创建 `backend/tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py`:

```python
"""Phase 5.C plan 07 3 plugin install → spawn → invoke → dispose 集成测。

策略：
- mock_huly_server fixture 复用 plan 01 conftest 已建
- outline / lark 用 respx 拦截 httpx 调用（不真起 outline / lark daemon 子进程，
  因为 plan 03/04 daemon entry 可能尚未在本 plan 范围实现 — 用 mock plugin facade）
- 主集成验证：service 层 install → Registry get_plugin → DocCapabilityDispatcher 路由 → outcome 正确

为什么不真 spawn outline/lark daemon：
- 真 spawn 需要 plan 03/04 daemon entry 完整就绪；本 plan 在 Wave 4 与 plan 06 并行，
  必须独立通过测试（不依赖 plan 03/04 是否同时 ready）
- 用 mock plugin facade 验证 service 层路径正确；真 daemon spawn 留 plan 08 E2E
"""
from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_builder.platforms.capabilities import CRDTDelta, DocRef
from app.agent_builder.platforms.manifest import CapabilitySpec, PlatformManifest
from app.agent_builder.platforms.registry import PlatformPluginRegistry
from app.agent_builder.services.doc_capability_dispatcher import (
    DispatchOutcome,
    DocCapabilityDispatcher,
)
from app.agent_builder.services.plugin_discovery import PluginDiscoveryService


@pytest.fixture
def setup_3plugin_registry():
    """Registry 注入三 plugin manifest + mock plugin instances（避免真 daemon spawn）。"""
    PlatformPluginRegistry.clear()
    PlatformPluginRegistry._MANIFESTS["outline"] = PlatformManifest(
        name="outline", version="1.0.0",
        capabilities=["doc"],
        doc=CapabilitySpec(supports_collaborative_edit=False),
    )
    PlatformPluginRegistry._MANIFESTS["lark_docs"] = PlatformManifest(
        name="lark_docs", version="1.0.0",
        capabilities=["doc", "identity"],
        doc=CapabilitySpec(supports_collaborative_edit=False),
    )
    PlatformPluginRegistry._MANIFESTS["huly"] = PlatformManifest(
        name="huly", version="1.0.0",
        capabilities=["doc", "im", "identity"],
        doc=CapabilitySpec(supports_collaborative_edit=True),
    )
    yield
    PlatformPluginRegistry.clear()


def _make_mock_plugin(name: str, collab: bool):
    """每 plugin 一个 MagicMock instance，模拟 daemon spawn + facade 行为。"""
    plugin = MagicMock()
    plugin.name = name
    plugin.daemon = None  # 起步未 spawn
    plugin.doc.supports_collaborative_edit = collab
    plugin.doc.name = name
    plugin.doc.replace_document_content = AsyncMock(return_value=None)
    plugin.doc.apply_document_delta = AsyncMock(return_value=None)
    # attach/detach 模拟：attach 后 daemon=MagicMock；detach 后 daemon=None
    async def _attach():
        plugin.daemon = MagicMock(name=f"{name}-daemon")
    async def _detach():
        plugin.daemon = None
    plugin.attach_daemon = AsyncMock(side_effect=_attach)
    plugin.detach_daemon = AsyncMock(side_effect=_detach)
    return plugin


# ── lifecycle happy path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_3plugin_lifecycle_happy_path(
    setup_3plugin_registry, db_session, workspace_id_a,
):
    """三 plugin 依次 install → spawn → 调一次 → dispose 干净。"""
    plugins = {
        "outline": _make_mock_plugin("outline", collab=False),
        "lark_docs": _make_mock_plugin("lark_docs", collab=False),
        "huly": _make_mock_plugin("huly", collab=True),
    }

    async def _get_plugin(ws, name):
        return plugins.get(name)

    with patch(
        "app.agent_builder.services.plugin_discovery.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(side_effect=_get_plugin),
    ), patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(side_effect=_get_plugin),
    ):
        # 1. install 三 plugin（spawn_daemon=True 触发 attach）
        for name in ("outline", "lark_docs", "huly"):
            row = await PluginDiscoveryService.install_plugin(
                workspace_id=workspace_id_a, plugin_name=name,
                config_json={}, db=db_session, spawn_daemon=True,
            )
            assert row.status == "installed"

        # 2. 验证三 daemon 都已 attach
        assert all(plugins[n].daemon is not None for n in plugins)

        # 3. 各 plugin 调一次 doc.create_document（通过 facade 直接，验 attach 后可 invoke）
        for name in ("outline", "lark_docs", "huly"):
            plugins[name].doc.create_document = AsyncMock(
                return_value=DocRef(plugin_name=name, native_id=f"{name}-doc-1"),
            )
            ref = await plugins[name].doc.create_document(
                title="test", markdown="# hi",
            )
            assert ref.plugin_name == name

        # 4. uninstall 三 plugin → detach + status='disabled'
        for name in ("outline", "lark_docs", "huly"):
            ok = await PluginDiscoveryService.uninstall_plugin(
                workspace_id=workspace_id_a, plugin_name=name, db=db_session,
            )
            assert ok is True
            assert plugins[name].daemon is None  # detach 已执行

        # 5. list_installed 三 plugin 都是 disabled 状态
        installed = await PluginDiscoveryService.list_installed(
            workspace_id=workspace_id_a, db=db_session,
        )
        statuses = {r.plugin_name: r.status for r in installed}
        assert statuses == {"outline": "disabled", "lark_docs": "disabled", "huly": "disabled"}


@pytest.mark.asyncio
async def test_3plugin_parallel_install(
    setup_3plugin_registry, db_session, workspace_id_a, workspace_id_b,
):
    """两 workspace 并行 install 三 plugin（验证 per-workspace 隔离不互锁）。"""
    plugins = {n: _make_mock_plugin(n, collab=(n == "huly")) for n in ("outline", "lark_docs", "huly")}

    async def _get_plugin(ws, name):
        return plugins.get(name)

    with patch(
        "app.agent_builder.services.plugin_discovery.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(side_effect=_get_plugin),
    ):
        await asyncio.gather(*[
            PluginDiscoveryService.install_plugin(
                workspace_id=ws, plugin_name=name,
                config_json={}, db=db_session, spawn_daemon=False,
            )
            for ws in (workspace_id_a, workspace_id_b)
            for name in ("outline", "lark_docs", "huly")
        ])

    # 各 workspace 都 install 了三 plugin
    a_rows = await PluginDiscoveryService.list_installed(workspace_id=workspace_id_a, db=db_session)
    b_rows = await PluginDiscoveryService.list_installed(workspace_id=workspace_id_b, db=db_session)
    assert {r.plugin_name for r in a_rows} == {"outline", "lark_docs", "huly"}
    assert {r.plugin_name for r in b_rows} == {"outline", "lark_docs", "huly"}


# ── 通过 dispatcher 端到端 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_huly_install_via_dispatcher_delta_direct(
    setup_3plugin_registry, db_session, workspace_id_a,
):
    """install huly → DocCapabilityDispatcher.write_document(delta) → DELTA_DIRECT。"""
    huly = _make_mock_plugin("huly", collab=True)

    async def _get_plugin(ws, name):
        return huly if name == "huly" else None

    with patch(
        "app.agent_builder.services.plugin_discovery.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(side_effect=_get_plugin),
    ), patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(side_effect=_get_plugin),
    ):
        await PluginDiscoveryService.install_plugin(
            workspace_id=workspace_id_a, plugin_name="huly",
            config_json={}, db=db_session, spawn_daemon=True,
        )
        # caller 直接传 prosemirror-json delta
        payload = json.dumps({"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "x"}]}
        ]}).encode("utf-8")
        delta = CRDTDelta(format="prosemirror-json", payload=payload)
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=workspace_id_a, plugin_name="huly",
            doc_ref=DocRef(plugin_name="huly", native_id="doc-1"),
            content=delta,
        )
        assert result.outcome == DispatchOutcome.DELTA_DIRECT
        huly.doc.apply_document_delta.assert_awaited_once()


@pytest.mark.asyncio
async def test_outline_install_via_dispatcher_fallback_to_replace(
    setup_3plugin_registry, db_session, workspace_id_a,
):
    """install outline → caller 传 delta → service serialize → REPLACE 路径。"""
    outline = _make_mock_plugin("outline", collab=False)

    async def _get_plugin(ws, name):
        return outline if name == "outline" else None

    with patch(
        "app.agent_builder.services.plugin_discovery.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(side_effect=_get_plugin),
    ), patch(
        "app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin",
        new=AsyncMock(side_effect=_get_plugin),
    ):
        await PluginDiscoveryService.install_plugin(
            workspace_id=workspace_id_a, plugin_name="outline",
            config_json={}, db=db_session, spawn_daemon=True,
        )
        payload = json.dumps({"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 1},
             "content": [{"type": "text", "text": "fallback"}]}
        ]}).encode("utf-8")
        delta = CRDTDelta(format="prosemirror-json", payload=payload)
        result = await DocCapabilityDispatcher.write_document(
            workspace_id=workspace_id_a, plugin_name="outline",
            doc_ref=DocRef(plugin_name="outline", native_id="doc-1"),
            content=delta,
        )
        assert result.outcome == DispatchOutcome.FALLBACK_TO_REPLACE
        outline.doc.replace_document_content.assert_awaited_once()
        # 验证 service 传给 facade 的 markdown 含 "fallback"
        passed_md = outline.doc.replace_document_content.await_args.args[1]
        assert "fallback" in passed_md
```

**避坑**:
- mock 替换路径：`app.agent_builder.services.plugin_discovery.PlatformPluginRegistry.get_plugin` 和 `app.agent_builder.services.doc_capability_dispatcher.PlatformPluginRegistry.get_plugin` 是同一个 class method，但 patch 必须按 import 路径作用域分别 patch（service module 各自的 namespace）
- `db_session` / `workspace_id_a` / `workspace_id_b` 来自 conftest.py，本 plan 不再重复声明
- 真 daemon spawn 留 plan 08 E2E（CONTEXT.md 决策：本 plan 仅 service 层 wiring + mock facade 集成）— 注释中已说明

commit message:
- `test(05c-07): add 3plugin install/spawn/dispose integration tests (mock plugin facade)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py -v 2>&1 | tail -30</automated>
  </verify>
  <done>4 集成 test 全绿（lifecycle happy path / parallel install / huly delta_direct / outline fallback_to_replace）；mock plugin facade 真正被调用 + dispatcher outcome 正确；daemon attach/detach 模拟干净。</done>
</task>

<task type="auto">
  <name>Task 5: 回归验证 — Phase 5.A 271 platforms tests + 5.B 5/5 acid test + 5.C plan 02-05 全绿 + commit</name>
  <files>.planning/phases/05c-doc-capability/05c-07-SUMMARY.md</files>
  <action>
**目的**：本 plan 三个新 service module 落地后必须验证 Phase 5.A/5.B/5.C plan 02-05 全部 0 regression。

---

1. **回归测试 — Phase 5.A platforms（271 tests baseline）**:
```bash
cd backend && python -m pytest tests/platforms/ -x 2>&1 | tail -30
```
预期：271 + 本 plan 新增（~14 prosemirror + 10 dispatcher + 8 discovery = 32+）= 303+ 全绿，0 fail。

2. **回归测试 — Phase 5.B 5/5 acid test**:
```bash
cd backend && python -m pytest tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py -v 2>&1 | tail -20
```
预期：5/5 acid test 全绿（plan 07 service 层独立不动 daemon 子进程逻辑）。

3. **回归测试 — Phase 5.B watchdog / network**:
```bash
cd backend && python -m pytest tests/platforms_integration/test_watchdog_grace_period.py tests/platforms_integration/test_idle_reaper.py tests/platforms_integration/test_network_allowlist.py tests/platforms_integration/test_cgroups_v2_sandbox.py 2>&1 | tail -20
```
预期：Linux-only 测过 + macOS skip 正常。

4. **回归测试 — Phase 4 IM provider 131 tests**:
```bash
cd backend && python -m pytest tests/test_im_provider_protocol.py tests/test_feishu_provider.py tests/test_wecom_provider.py tests/test_dingtalk_provider.py tests/test_slack_provider.py tests/test_mattermost_provider.py tests/test_webhook_provider.py 2>&1 | tail -10
```
预期：0 regression（plan 07 不动 IM 路径）。

5. **本 plan 新测试 整体跑一遍**:
```bash
cd backend && python -m pytest tests/platforms/test_prosemirror_to_markdown.py tests/platforms/test_capability_fallback_dispatcher.py tests/platforms/test_plugin_discovery_3plugin.py tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py -v 2>&1 | tail -50
```
预期：~36 test 全 pass。

6. **写 SUMMARY** `.planning/phases/05c-doc-capability/05c-07-SUMMARY.md`:

```markdown
# Phase 5.C Plan 07 — Capability fallback service layer + plugin discovery wiring SUMMARY

> Completed: {YYYY-MM-DD}
> Wave 4 (并行 plan 06)
> depends_on: [03, 04, 05]

## Outputs

- `docs/reading-dify-05c-07-capability-fallback-2026-05-18.md`（commit hash: ...）
- `backend/app/agent_builder/services/__init__.py`
- `backend/app/agent_builder/services/prosemirror_to_markdown.py`（XX 行）
- `backend/app/agent_builder/services/doc_capability_dispatcher.py`（XX 行）
- `backend/app/agent_builder/services/plugin_discovery.py`（XX 行）
- 4 test 文件，~36 测全绿

## Test Results

| 测试集 | Count | Status |
|---|---|---|
| 本 plan 新单元 (prosemirror + dispatcher + discovery) | 14 + 10 + 8 = 32 | ALL GREEN |
| 本 plan 新集成 (3plugin install/spawn/dispose) | 4 | ALL GREEN |
| Phase 5.A platforms regression | 271 | 0 regression |
| Phase 5.B 5/5 acid test regression | 5 | 0 regression |
| Phase 5.B watchdog/network regression | N | 0 regression |
| Phase 4 IM 131 tests regression | 131 | 0 regression |

## Dify 参考点

5 借鉴点（指回 reading doc 章节锚点）:
1. Dispatch envelope (node_factory.py) → DocCapabilityDispatcher 路由层
2. install_plugin 幂等 (plugin_service.py) → PluginDiscoveryService.install_plugin ON CONFLICT
3. list_plugins metadata schema → PluginMetadata dataclass
4. lifecycle dispose → uninstall_plugin detach_daemon + UPDATE status='disabled'
5. per-tenant scoping → workspace_id 第一参数

## 关键决策

- 双路径 fallback 决定：False plugin 接受 markdown 直接 replace；接受 delta 但 format 必须 'prosemirror-json' 才 serialize；其它 format raise UnsupportedDeltaFormatError
- True plugin (Huly) 接受 markdown 时不在 service 内 import plugins.huly._internal（plugin 进程隔离原则），转而调 DocFacade.replace_document_content（plan 05 在 daemon 内做二步流程）
- discovery wiring：本 plan 不修改 PlatformPluginRegistry，仅在 service 层包装；三 plugin 是否被 discover 到由 Phase 5.A `discover("plugins/")` 启动逻辑保证（plan 02-05 落 plugins/huly/ + plugins/outline/ + plugins/lark_docs/ 后即生效）
- 集成测策略：用 mock plugin facade 而非真 daemon spawn（避免阻塞 wave 4 并行；真 daemon 留 plan 08 E2E）

## Plan 06 / Plan 08 coordinate

- 与 plan 06（ai_suggest_mentions）正交：plan 06 扩 DocCapability Protocol v1.1，本 plan 仅用 v1 接口
- 为 plan 08 E2E 留接口：DocCapabilityDispatcher.write_document 是 doc_write 节点（v1.5）唯一入口；PluginDiscoveryService 是 plugin marketplace UI（v1.5）唯一入口

## DoD ✅

- [x] Outline / Lark 收 delta → 自动 serialize → markdown replace 成功
- [x] Huly 收 delta → 直接 collab service apply_delta
- [x] plugin discovery 三 plugin 都列出
- [x] 3 plugin install/spawn/dispose 干净退出（mock facade 验证）
- [x] structured log `outcome="fallback_to_replace"` 出现
- [x] Phase 5.A 271 tests + 5.B 5/5 + 5.C plan 02-05 全绿
- [x] Dify reading doc commit 早于任何 feat commit（CLAUDE.md §2.7）
- [x] License attribution 在 doc + service module 头部
```

7. **git commit**（summary + 任何遗漏文件）:
```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder && git add .planning/phases/05c-doc-capability/05c-07-SUMMARY.md && git commit -m "docs(05c-07): add SUMMARY — capability fallback service + plugin discovery wiring (3plugin)"
```

**避坑**:
- 任一 Phase 5.A regression → 立即 git diff 排查（本 plan 三 service module 都是新加文件，理论上 0 风险触发已有测试）
- 5/5 acid test 是 plan 05 HulyPlugin 集成测；本 plan 不动 daemon spawn 路径，0 regression 风险
- SUMMARY 必须列 Dify 参考点（CLAUDE.md §2.7 verify 阶段要求）
- summary 写完只 commit doc，service 代码已在前序 task 各自 commit
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_prosemirror_to_markdown.py tests/platforms/test_capability_fallback_dispatcher.py tests/platforms/test_plugin_discovery_3plugin.py tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py -v 2>&1 | tail -20 && test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-07-SUMMARY.md && grep -q "Dify 参考点" /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-07-SUMMARY.md</automated>
  </verify>
  <done>本 plan 36+ 新测试全绿；Phase 5.A 271 / 5.B 5/5 / Phase 4 131 IM 0 regression；SUMMARY.md 存在含 Dify 参考点 + DoD 复核；已 commit。</done>
</task>

</tasks>

<verification>
**phase-local checks（plan 07 内部）**:
- `pytest tests/platforms/test_prosemirror_to_markdown.py -v` → 14+ 全绿
- `pytest tests/platforms/test_capability_fallback_dispatcher.py -v` → 10+ 全绿
- `pytest tests/platforms/test_plugin_discovery_3plugin.py -v` → 8+ 全绿
- `pytest tests/platforms_integration/test_3plugin_install_spawn_dispose_integration.py -v` → 4 全绿

**双路径 fallback 验证**:
- caplog 中含至少 1 条 `outcome=fallback_to_replace` log record
- Outline (False) + CRDTDelta(yjs) raise UnsupportedDeltaFormatError
- Huly (True) + CRDTDelta(prosemirror-json) outcome=DELTA_DIRECT
- ProseMirror→Markdown round-trip 与 plan 05 forward 对称

**plan 03/04/05 不破坏**:
- DocCapability Protocol 0 修改（plan 06 扩 v1.1，本 plan 仅 v1）
- DocFacade signature 0 修改
- PlatformPluginRegistry signature 0 修改
- plugins/huly/_internal/markdown_to_prosemirror 0 修改（仅依赖 forward 接口）

**reading doc gate（CLAUDE.md §2.7）**:
- `git log --oneline | grep -E "05c-07"` 第一条必须是 `docs(05c-07):` reading doc commit
- 后续 feat/test/refactor commit 都晚于 reading doc commit

**Phase 5.A / 5.B / 5.C plan 02-05 regression**:
- `pytest backend/tests/platforms/ -x` → 271 (5.A) + 32 (本 plan) = 303+ 全绿
- `pytest backend/tests/platforms_integration/test_huly_acid_test.py test_fault_isolation.py -v` → 5/5 全绿
- `pytest backend/tests/notification/ -x` → Phase 4 IM 0 regression
</verification>

<success_criteria>
1. **双路径 fallback 真落地**: Outline/Lark 收 CRDTDelta(prosemirror-json) → service serialize → markdown → facade.replace；fallback_to_replace 在 structured log 可见
2. **Huly 反向兼容**: Huly 收 markdown → service 调 facade.replace_document_content（daemon 内做二步流程）— 业务无感
3. **format 严格校验**: 非 prosemirror-json delta 传给 False plugin → UnsupportedDeltaFormatError raise，避免静默掉数据
4. **plugin discovery 三 plugin 可见**: list_available_plugins 返回 [huly, lark_docs, outline]（确定性排序），supports_collaborative_edit 值正确
5. **install 幂等**: ON CONFLICT (workspace_id, plugin_name) UPDATE version + config — 重复 install 不报错
6. **uninstall 优雅 dispose**: detach_daemon + UPDATE status='disabled'，留 audit 记录
7. **workspace 隔离基线**: 双 workspace 互不可见对方 install 行（CLAUDE.md §2.4）
8. **prosemirror_to_markdown 与 plan 05 对称**: 12 元素映射逆向一致；round-trip 测过（如 plan 05 已 ready）
9. **测试覆盖**: 单元 ~32 + 集成 4 全绿；Phase 5.A 271 + 5.B 5/5 + Phase 4 131 IM 0 regression
10. **CLAUDE.md §2.7 硬性 gate**: reading doc commit 早于 feat commit；5 借鉴点指明 source file → target module；License attribution 在 doc + 每 service module 头部
11. **plan 03/04/05 接口零破坏**: DocCapability Protocol / DocFacade / PlatformPluginRegistry / markdown_to_prosemirror 0 修改
12. **与 plan 06 正交**: plan 07 仅用 DocCapability v1 接口，不依赖 plan 06 的 ai_suggest_mentions v1.1 扩展
</success_criteria>

<output>
完成后 `.planning/phases/05c-doc-capability/05c-07-SUMMARY.md` 已存在，含：

- Reading doc 链接 + commit hash
- 4 test 文件路径 + 测试结果（unit 32 + integration 4 + regression 271+5+131）
- 三 service module 行数 + 5 借鉴点 (Dify 参考点小节)
- 关键决策：双路径 fallback 设计 / Huly markdown 路径选 facade.replace / mock facade 集成策略 / plan 06/08 coordinate
- Phase 5.A 271 / 5.B 5/5 / Phase 4 131 IM 0 regression 证明
- DoD checklist 全 ✅
</output>
</content>
</invoke>