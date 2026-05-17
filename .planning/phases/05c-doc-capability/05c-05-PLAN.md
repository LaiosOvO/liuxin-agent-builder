---
phase: 05c-doc-capability
plan: 05
type: execute
wave: 3
depends_on: ["02"]
files_modified:
  - docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md
  - plugins/huly/__init__.py
  - plugins/huly/manifest.yaml
  - plugins/huly/huly_plugin.py
  - plugins/huly/_internal/__init__.py
  - plugins/huly/_internal/markdown_to_prosemirror.py
  - plugins/huly/_internal/collab_client.py
  - plugins/huly/_internal/identity_lru.py
  - plugins/huly/_internal/per_user_channel.py
  - plugins/huly/prompts/ai_suggest_mentions_zh.md
  - backend/tests/platforms/test_huly_plugin_doc.py
  - backend/tests/platforms/test_huly_plugin_im.py
  - backend/tests/platforms/test_huly_plugin_identity.py
  - backend/tests/platforms/test_huly_plugin_tracker_stub.py
  - backend/tests/platforms/test_huly_plugin_concurrent_lock.py
  - backend/tests/platforms/test_huly_plugin_license_attribution.py
  - backend/tests/platforms_integration/mock_huly_server.py
  - backend/tests/platforms_integration/test_huly_plugin_4cap_integration.py
  - backend/tests/platforms_integration/test_huly_acid_test.py
autonomous: true
requirements:
  - DOC-05
  - DOC-06
  - IM-06
  - IDENT-01
  - PLUG-MULTI-01
must_haves:
  truths:
    - "HulyPlugin daemon spawn 一次 + 4 facet (doc/im/identity/tracker) 全注册可调"
    - "DocCapability 二步流程封装在 daemon 内：create shell → collab createContent → update_doc(content=blobRef) 主进程无需感知 collab service"
    - "IMCapability send_card with RecipientSpec kind='dm_user' 自动走 per-user Channel (dm-{username}) 而非 chunter:DirectMessage"
    - "IdentityCapability.resolve_user 走 SocialIdentity → Employee mixin LRU cache（TTL 默认 3600s manifest 可覆盖）"
    - "TrackerCapability stub 接口存在但调用 raise NotImplementedError（v1.1 接入）"
    - "Phase 5.A acid test 5/5 替换原 mock stub 为真 HulyPlugin daemon 后仍全绿"
    - "Phase 5.A 271 platforms + Phase 5.B 5/5 acid + 131 IM 0 regression"
    - "4 facet 并发调用受 asyncio.Lock 保护 ws 写入（Pitfall 10）— 3 并发 mock 任一 invoke ≤ 100ms"
    - "marko AST → ProseMirror JSON 12 元素映射完整 + ListItem 强制 wrap paragraph（Pitfall 11）"
    - "所有 plugins/huly/_internal/*.py 含 'Inspired by hr/offboarding-flow design — not derived source' attribution（Pitfall 8）"
  artifacts:
    - path: "plugins/huly/manifest.yaml"
      provides: "升级版 manifest — capability_facets=[doc,im,identity,tracker] + sandbox.docker_networks + config cache_ttl_seconds + identity.is_source_of_truth=true"
      contains: "capability_facets"
    - path: "plugins/huly/huly_plugin.py"
      provides: "HulyPlugin daemon facade — 4 dispatcher (doc.* / im.* / identity.* / tracker.*) + eager connect_huly + 共享 _client + asyncio.Lock 包 ws 写"
      exports: ["main", "METHODS"]
      min_lines: 280
    - path: "plugins/huly/_internal/markdown_to_prosemirror.py"
      provides: "marko AST → ProseMirror JSON 12 元素映射（heading/paragraph/list[ordered+bullet]/listItem/blockquote/code_block/horizontalRule + em/strong/code/link marks）"
      exports: ["markdown_to_prosemirror"]
      min_lines: 150
    - path: "plugins/huly/_internal/collab_client.py"
      provides: "HulyCollabClient — /rpc/{encoded_doc_id} createContent → blob ref；urlEncoded(ws|class|id|attr) 段构造；ws_token Bearer"
      exports: ["HulyCollabClient"]
      min_lines: 80
    - path: "plugins/huly/_internal/identity_lru.py"
      provides: "TTLCache(maxsize=10000, ttl=3600) + double-check lock 防 race + 跨 workspace_uuid 隔离 cache key + invalidate_cache(username, workspace_uuid)"
      exports: ["resolve_person_uuid", "invalidate_cache", "configure_cache"]
      min_lines: 90
    - path: "plugins/huly/_internal/per_user_channel.py"
      provides: "chunter:Channel dm-{username} ensure-or-create + members=[bot, target_uuid] + LRU channel_id 缓存"
      exports: ["ensure_user_channel"]
      min_lines: 70
    - path: "plugins/huly/prompts/ai_suggest_mentions_zh.md"
      provides: "v1.1 留 prompt 模板（v1 daemon 直接返回 []，但模板就位）"
      min_lines: 20
    - path: "backend/tests/platforms/test_huly_plugin_doc.py"
      provides: "DocCapability unit — 二步流程封装测（mock create_doc + mock HulyCollabClient + mock update_doc）+ markdown_to_prosemirror 12 元素覆盖 + ListItem paragraph wrap 验证"
      min_lines: 180
    - path: "backend/tests/platforms/test_huly_plugin_im.py"
      provides: "IMCapability unit — send_card with kind='dm_user' 自动 ensure_user_channel + add_collection 路由 + 不走 chunter:DirectMessage 断言"
      min_lines: 100
    - path: "backend/tests/platforms/test_huly_plugin_identity.py"
      provides: "IdentityCapability unit — LRU cache hit/miss/expire + workspace_uuid 隔离 + invalidate + double-check lock"
      min_lines: 100
    - path: "backend/tests/platforms/test_huly_plugin_tracker_stub.py"
      provides: "TrackerCapability stub — facet 注册存在 + 调用 raise NotImplementedError"
      min_lines: 30
    - path: "backend/tests/platforms/test_huly_plugin_concurrent_lock.py"
      provides: "Pitfall 10 防御 — 3 并发 daemon invoke 任一 ≤ 100ms（mock fast Huly） + asyncio.Lock 串行 ws 写"
      min_lines: 60
    - path: "backend/tests/platforms/test_huly_plugin_license_attribution.py"
      provides: "Pitfall 8 防御 — grep 所有 plugins/huly/_internal/*.py 必含 'Inspired by hr/offboarding-flow design'"
      min_lines: 30
    - path: "backend/tests/platforms_integration/mock_huly_server.py"
      provides: "升级 5.A mock — 加 REST find_one (SocialIdentity / Employee mixin / Channel) + Tx create_doc/add_collection/update_doc + collab WS RPC createContent 端点"
      min_lines: 200
    - path: "backend/tests/platforms_integration/test_huly_plugin_4cap_integration.py"
      provides: "真 daemon spawn + mock huly REST + WS server + 4 capability 顺序调用 + 单 daemon 1 client 复用验证 + 4 facet 全注册 Registry smoke"
      min_lines: 200
    - path: "backend/tests/platforms_integration/test_huly_acid_test.py"
      provides: "替换 5.A stub im.send_card 路径为真 HulyPlugin per-user Channel 路径；5/5 acid test 0 regression"
      min_lines: 80
  key_links:
    - from: "plugins/huly/huly_plugin.py"
      to: "plugins/huly/_internal/collab_client.py"
      via: "doc.create_document → HulyCollabClient.create_content → blob_ref → update_doc(content=blob_ref)"
      pattern: "HulyCollabClient.*create_content"
    - from: "plugins/huly/huly_plugin.py"
      to: "plugins/huly/_internal/per_user_channel.py"
      via: "im.send_card RecipientSpec kind='dm_user' → ensure_user_channel(username) → add_collection(ChatMessage, channel_id, ...)"
      pattern: "ensure_user_channel"
    - from: "plugins/huly/huly_plugin.py"
      to: "plugins/huly/_internal/identity_lru.py"
      via: "identity.resolve_user / im.send_card 内 username → resolve_person_uuid (LRU cache hit/miss)"
      pattern: "resolve_person_uuid"
    - from: "plugins/huly/huly_plugin.py"
      to: "plugins/huly/_internal/markdown_to_prosemirror.py"
      via: "doc.replace_document_content markdown 入参 → markdown_to_prosemirror(text) → ProseMirror JSON → collab createContent"
      pattern: "markdown_to_prosemirror"
    - from: "plugins/huly/manifest.yaml"
      to: "backend/app/agent_builder/platforms/sandbox/runner.py"
      via: "sandbox.docker_networks=['huly_huly_net'] → daemon spawn 后 docker network connect（plan 01 已扩 SandboxRunner.spawn_with_limits 接受 docker_networks 参数）"
      pattern: "docker_networks"
    - from: "backend/tests/platforms_integration/test_huly_acid_test.py"
      to: "plugins/huly/huly_plugin.py"
      via: "5.A 原 stub im.send_card → 真 ensure_user_channel + add_collection 路径替换"
      pattern: "huly-msg-|chunter:Channel"
    - from: "backend/tests/platforms/test_huly_plugin_concurrent_lock.py"
      to: "plugins/huly/huly_plugin.py"
      via: "3 并发 ws 写 → asyncio.Lock 串行化 → 任一 ≤ 100ms"
      pattern: "asyncio.gather|asyncio.Lock"
---

<objective>
本 phase 最大 plan（4 capability bundle，~45min）：实现 HulyPlugin = PlatformBundle（DocCapability + IMCapability + IdentityCapability + TrackerCapability stub）— 单 daemon 进程 + 单 HulyPlatformClient + 单 WS 连接 4 facet 共享，替换 Phase 5.A acid test 的 stub im.send_card 为真 per-user Channel 路径。

Purpose: 这是 Phase 5.C 的"集大成"—— 把 hr/offboarding-flow B-full-channel 1454 行 Python 的设计教训（DM 静默 reject / Document.content 非 raw markdown / PersonUuid 解析慢路径 / collab service blob ref）全部翻译为生产级 PlatformBundle。完成此 plan 后 Phase 5.A acid test 5/5 + Phase 5.B 5/5 + Phase 5.C 4 facet 集成测全绿 → Phase 5.D HR + 反向 sync 可基于本 plan 的 IdentityCapability + LRU cache 直接扩展。

Output:
- 1 reading doc (Task 0 hard gate — Dify multi-tool provider + hr huly_doc_provider/huly_im_provider 参考)
- HulyPlugin daemon entry (4 dispatcher + eager connect + asyncio.Lock 包 ws 写)
- 4 internal modules (markdown_to_prosemirror / collab_client / identity_lru / per_user_channel)
- manifest.yaml 升级 (4 facet + docker_networks + cache config + identity.is_source_of_truth=true)
- 1 prompt 模板 stub (plan 06 用)
- 6 unit tests (4 capability + concurrent lock + license attribution)
- 1 integration test (4 capability end-to-end with mock REST + WS)
- 升级 mock_huly_server.py 加 collab WS + REST find_one + Tx endpoints
- 替换 test_huly_acid_test.py 5/5 测试（stub → 真 HulyPlugin 路径）
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/05c-doc-capability/05c-CONTEXT.md
@.planning/phases/05c-doc-capability/05c-RESEARCH.md
@CLAUDE.md
@plugins/huly/huly_plugin.py
@plugins/huly/platform.yaml
@backend/app/agent_builder/platforms/capabilities/doc.py
@backend/app/agent_builder/platforms/capabilities/im.py
@backend/app/agent_builder/platforms/capabilities/identity.py
@backend/app/agent_builder/platforms/sandbox/runner.py
@backend/tests/platforms_integration/mock_huly_server.py
@backend/tests/platforms_integration/test_huly_acid_test.py

<interfaces>
From Phase 5.A (capabilities 已定型):

```python
# DocCapability key methods (backend/app/agent_builder/platforms/capabilities/doc.py)
async def create_document(*, title: str, markdown: str | None, collection_id: str | None,
                            initial_delta: CRDTDelta | None = None) -> DocInfo: ...
async def replace_document_content(doc_ref: DocRef, markdown: str) -> None: ...
async def apply_document_delta(doc_ref: DocRef, delta: CRDTDelta) -> None: ...  # supports_collaborative_edit=True 走此
async def add_comment(doc_ref: DocRef, body_markdown: str, mentions: list[UserRef]) -> CommentRef: ...
async def get_document(doc_ref: DocRef) -> DocInfo: ...

@dataclass(frozen=True)
class DocRef:
    plugin_name: str
    native_id: str
    extras: dict[str, str] = field(default_factory=dict)


# IMCapability key methods (backend/app/agent_builder/platforms/capabilities/im.py)
async def send_card(*, recipient: RecipientSpec, card: NormalizedCard, idempotency_key: str) -> MessageRef: ...

@dataclass(frozen=True)
class RecipientSpec:
    kind: Literal["channel", "dm_user", "thread"]
    workspace_id: str | None
    channel_id: str | None
    user_id: str | None
    thread_id: str | None


# IdentityCapability key methods (backend/app/agent_builder/platforms/capabilities/identity.py)
async def resolve_user(identifier: str) -> UserPrincipal | None: ...
async def list_users(workspace_id: str | None = None) -> list[UserPrincipal]: ...
async def watch_user_changes() -> AsyncIterator[UserChangeEvent]: ...  # is_source_of_truth=True 才实
```

From Plan 02 (本 phase _internal/ 港口模块):
- `plugins/huly/_internal/rest_client.py` — `HulyRESTClient` (login + selectWorkspace + tx + find-all + ensure-person)
- `plugins/huly/_internal/tx_factory.py` — `TxCreateDoc / TxCollectionCUD / TxUpdateDoc / TxRemoveDoc`
- `plugins/huly/_internal/tx_operations.py` — `create_doc / add_collection / update_doc / remove_doc` high-level API
- `plugins/huly/_internal/platform_client.py` — `HulyPlatformClient.rest / .ops / .bot_account / .workspace_uuid / .workspace_token`
- `plugins/huly/_internal/constants.py` — `DOCUMENT_CLASS_DOCUMENT / CHUNTER_CLASS_CHANNEL / CHUNTER_CLASS_CHAT_MESSAGE / CORE_SPACE_SPACE / DEMO_EMAIL_DOMAIN / DOCUMENT_IDS_NO_PARENT`
- `connect_huly(accounts_url, admin_email, admin_password, workspace_url, timeout) → HulyPlatformClient`

From Plan 01 (manifest schema 已扩):
- `sandbox.docker_networks: list[str]` (default `[]`)
- `SandboxRunner.spawn_with_limits(..., docker_networks: list[str] | None = None)` (PosixResourceSandbox no-op + warning, CgroupsV2Sandbox 真 attach)
- manifest `config.cache_ttl_seconds: int` (default 3600)

From Phase 5.A:
- `PlatformDaemonClient.invoke(capability, method, **kwargs) → Any` (timeout 30s, JSONRPC stdio)
- `PlatformPluginRegistry.discover(plugins_dir) → list[PlatformPlugin]`
- `PlatformPlugin.doc / .im / .identity / .tracker` @property facade
- `tests/platforms_integration/mock_huly_server.py` 已建 aiohttp stub（本 plan 升级）
- `tests/platforms_integration/test_huly_acid_test.py` 已建 5 test（本 plan 替换 mock stub 为真路径）

From hr/offboarding-flow B-full-channel（仅借鉴设计，不复制源码 — AGPL 防御）：
- 二步流程: ops.create_doc(content="") → collab_client.create_content → ops.update_doc(content=blob_ref)
- per-user Channel: chunter:Channel name=`dm-{username}` members=[bot, target_uuid]
- LRU cache key: `f"{workspace_uuid}:{username}"` (跨 ws 隔离)
- Pitfall 2: `chunter:DirectMessage` 静默 reject — 永不尝试
- Pitfall 1: Document.content 是 collab blob ref，不是 markdown 字符串
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: 阅读文档（CLAUDE.md §2.7 硬性 gate — 必先 commit reading doc 才能写代码）</name>
  <files>docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md</files>
  <action>
读以下材料（不复制源码，仅借鉴设计/数据结构/边界考虑）：

**Dify 必读（multi-tool provider + plugin facet 模式）**：
1. `/Users/admin/ai/ref/dify/repo/api/core/tools/provider/` — 抽样 1-2 个 multi-tool provider 实现 (e.g. `builtin_tool_provider.py` 或 `wechat_offiaccount/`)，理解 Dify 怎么把多 tool 组织成一个 provider
2. `grep -r "facet\|capabilities\b" /Users/admin/ai/ref/dify/repo/api/core/plugin/` — 看 Dify 是否有 PlatformBundle 概念（预期：Dify 用 plugin.declare(capabilities=[...]) 一次性声明，本 phase 借鉴此模式）
3. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py` — PluginDeclaration / PluginCategories (tool/model/agent 等) 是否对应 capability_facets
4. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_invoke_service.py` — 多 capability dispatch 模式（method 名 routing）

**hr 必读（B-full-channel 实战教训 — 仅借鉴设计，不复制 Python 源码）**：
5. `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly_doc_provider.py` (304 行) — 重点：`create_document` 的二步流程（line 82-117 当前文件版本，但本 plan 接的是 §4.3 升级版含 collab service RPC）
6. `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly_im_provider.py` (247 行) — 重点：`_ensure_user_channel` (line 203-247) + `_resolve_account` (line 182-201) + DM 降级注释 (line 4-7)
7. `/Users/admin/ai/resume/interview/liuxin/hr/docs/huly-integration-architecture-2026-05-18.md` §4.3 collab service RPC + §4.5 markup JSON 例 + §5.2 DM 静默 reject + §5.5 LRU cache

**prosemirror 0.6.1 一手 reference**：
8. PyPI prosemirror 0.6.1 文档（`prosemirror.schema_basic` / `prosemirror.schema_list`）— 节点 schema 规则（ListItem 必须含 paragraph 子节点 → Pitfall 11）
9. CommonMark spec 与 marko AST element 命名差异（marko `strong_emphasis` vs ProseMirror `strong`）

**写到 `docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md`，5 节标准模板（最少 120 行 — 最大 plan，4 capability + 多教训点）**：

```markdown
# Dify + hr/offboarding-flow 阅读笔记 — HulyPlugin 4-capability Bundle

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local /Users/admin/ai/ref/dify/repo/) + hr/offboarding-flow (LOCAL ONLY, NOT REDISTRIBUTED, Apache-2.0)
> Stars: ~141k (Dify)

## 项目概述
（HulyPlugin = 单 daemon + 4 capability facet 共享 HulyPlatformClient + 共享 WS 连接，是 Phase 5.A acid test 的真实生产升级）

## 技术栈
（Python 3.11+ asyncio + aiohttp/httpx + cachetools.TTLCache + marko 2.2.2 + prosemirror 0.6.1）

## 架构要点
（含 4 capability dispatch 图：JSONRPC stdio → METHODS dict → _ensure_client → 4 capability handler）

## 可借鉴的设计模式（≥ 10 借鉴点 — 最大 plan 必充实）
1. Dify multi-tool provider 一 declare 多 tool（参考 `<dify path>`）→ 5.C HulyPlugin manifest `capability_facets: [doc,im,identity,tracker]` 一次声明
2. Dify PluginDeclaration capabilities[] 模式 → 5.C `manifest.capability_facets` 字段（区别于 Phase 5.A `capabilities[]` 单层）
3. hr `_ensure_user_channel` per-user Channel 命名 `dm-{username}` → 5.C 严格沿用（Pitfall 2 防御）
4. hr `_resolve_account` 2 跳查询（SocialIdentity → Employee mixin → personUuid）→ 5.C identity_lru.py 完整复制路径（含 `email:{user}@demo.local` social key 格式）
5. hr `_connect_lock + double-check` 防 race → 5.C daemon `_client_lock` 同模式（lazy connect + double check）
6. hr Document.content 不写 markdown 走 collab service RPC（§4.3 教训）→ 5.C doc.create_document 强制走二步流程（Pitfall 1 防御）
7. Huly collab service `/rpc/{encoded_doc_id}` URL 段编码（`workspace_uuid|class|id|attr` urlEncoded）→ 5.C collab_client.py `_encode_doc_id`
8. ProseMirror markup 字符串约定（hr §4.5 JSON 例）→ 5.C markdown_to_prosemirror.py 12 元素映射
9. cachetools TTLCache LRU + asyncio.Lock 防 race → 5.C identity_lru.py 用同模式 + 跨 workspace 隔离 cache key
10. Dify plugin entry `__main__` 写 `asyncio.run(main())` → 5.C huly_plugin.py 同样模式（5.A 已建主循环，本 plan 扩 METHODS）

## 与本项目的关系
（每借鉴点指向本 plan 的具体 task / 文件 / 行）

## License 声明
- Dify AGPL-3.0 → 严格不拷源码（重写 Python 实现 + 5.C 独立创作）
- hr 项目当前 license 未明确（Pitfall 8）→ 所有 `plugins/huly/_internal/*.py` 头部必加 `# Inspired by hr/offboarding-flow design (commit 2ae8bf8) — not derived source; re-implemented under Apache-2.0`
- agent-builder 本身 Apache-2.0 一致
```

写完后 git commit（本 plan 第一个 commit），消息 `docs(05c-05): Dify multi-tool provider + hr huly_doc/huly_im reading doc`。后续任何 code commit 必须在此 commit 之后。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md && wc -l docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md | awk '{exit ($1 >= 120 ? 0 : 1)}' && grep -q "AGPL\|attribution\|Inspired by" docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md && grep -qE "借鉴点 (10|[1-9][0-9])" docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md && git log --oneline -1 docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md | grep -q "05c-05"</automated>
  </verify>
  <done>Reading doc ≥ 120 行 + 10 借鉴点 + Dify + hr 两源都写 + License attribution + 已 commit（在任何代码 commit 之前）</done>
</task>

<task type="auto">
  <name>Task 1: manifest.yaml 升级 — 4 capability_facets + docker_networks + cache_ttl + is_source_of_truth</name>
  <files>plugins/huly/manifest.yaml,plugins/huly/__init__.py</files>
  <action>
1. **重命名 `plugins/huly/platform.yaml` → `plugins/huly/manifest.yaml`**（Phase 5.A 与 5.B 已统一 manifest.yaml 命名 — 本 plan 把 Huly 也对齐；若 5.A 用 platform.yaml 是历史遗留，本 plan 不破坏 5.A registry discover 兼容性 → 同时保留两个文件做软迁移，platform.yaml 内容改为 `# DEPRECATED → see manifest.yaml`）。**若 Phase 5.A discover() 已加 manifest.yaml 优先支持**则直接重命名；否则保留 platform.yaml 作为 5.A 兼容入口，新增 manifest.yaml 作为 5.C 真版本。**先 grep `registry.discover` 看 5.A 实际接受哪个文件名**：

```bash
grep -n "manifest\.yaml\|platform\.yaml" backend/app/agent_builder/platforms/registry.py
```

按结果决定（reading doc 中记录选哪条）。

2. **新 `plugins/huly/manifest.yaml` 内容**：

```yaml
# HulyPlugin manifest — Phase 5.C 4-capability bundle 升级版
#
# 升级要点（vs Phase 5.A platform.yaml）：
# - capability_facets（新字段）— 显式声明 4 facet 共享 daemon
# - sandbox.docker_networks（新字段，plan 01 引入）— Huly daemon 必 attach huly_huly_net
# - config.cache_ttl_seconds — IdentityCapability LRU cache TTL（默认 3600）
# - identity.is_source_of_truth=true — Phase 5.D 反向 sync 用
# - doc.supports_collaborative_edit=true — 走 apply_document_delta 主路径

name: huly
version: 1.1.0  # bump from 1.0.0 (5.A stub)
description: "Huly platform plugin — DocCapability + IMCapability + IdentityCapability + TrackerCapability(stub)"
license: Apache-2.0  # 5.C 重写后改为 Apache-2.0（5.A 原 EPL-2.0 是错误标记）
agent_builder_version: ">=1.0"

runtime:
  type: python
  entry: plugins.huly.huly_plugin
  python_version: "3.11"

# Phase 5.C 新增 — multi-capability bundle 显式声明
capability_facets:
  - doc
  - im
  - identity
  - tracker

# 兼容 5.A capabilities 字段（registry 旧路径仍可读）
capabilities:
  - im
  - doc
  - identity
  - tracker

config_schema:
  type: object
  required:
    - huly_url
    - huly_workspace
    - huly_admin_email
    - huly_admin_password
  properties:
    huly_url:
      type: string
      format: uri
      description: "Huly server base URL (e.g. http://192.168.2.44:8087)"
    huly_workspace:
      type: string
      description: "Huly workspace url-name (e.g. laios)"
    huly_admin_email:
      type: string
      format: email
    huly_admin_password:
      type: string
      format: password
    huly_collab_url:
      type: string
      description: "Huly collaborator service URL inside docker network (e.g. http://collaborator:3078)"
      default: "http://collaborator:3078"
    cache_ttl_seconds:
      type: integer
      minimum: 60
      maximum: 86400
      default: 3600
      description: "PersonUuid LRU cache TTL"
    user_email_domain:
      type: string
      default: "demo.local"
      description: "SocialIdentity email domain（hr 教训 §5.5）"

im:
  supports_native_buttons: false
  supports_card_update: true
  supports_threads: true

doc:
  supports_collaborative_edit: true  # 5.C 走 apply_document_delta 主路径
  supports_comments: true

identity:
  is_source_of_truth: true  # Phase 5.D 反向 sync 入口

tracker:
  enabled: false  # stub — v1.1 接入

sandbox:
  cpu_limit: "1.0"
  memory: "512Mi"
  # Phase 5.C 新增（plan 01 引入字段）—— Huly daemon attach huly_huly_net 才能调 collaborator:3078
  docker_networks:
    - "huly_huly_net"
  network:
    # HTTP allowlist（Phase 5.B AllowlistTransport 用）—— 配 Huly REST + collab
    - "192.168.2.44:8087"
    - "collaborator:3078"
  timeout_invoke: 30
  timeout_idle: 300
  use_cgroups: false
  env_allowlist:
    - HULY_ACCOUNTS_URL
    - HULY_ADMIN_EMAIL
    - HULY_ADMIN_PASSWORD
    - HULY_WORKSPACE
    - HULY_COLLAB_URL
    - HULY_HTTP_TIMEOUT
    - PLUGIN_NETWORK_ALLOW
    - HULY_CACHE_TTL_SECONDS
    - HULY_USER_EMAIL_DOMAIN
```

3. **更新 `plugins/huly/__init__.py`** — 加 plugin metadata 入口（若已存在仅追加）：

```python
"""HulyPlugin — Phase 5.C 4-capability bundle (doc + im + identity + tracker stub).

License: Apache-2.0. Inspired by hr/offboarding-flow B-full-channel design — not derived source.
"""

__all__ = ["main"]


def main():
    """Phase 5.C daemon entry — re-export huly_plugin.main for module discovery."""
    from .huly_plugin import main as _main
    return _main()
```

注：本 task 不创建 `plugins/huly/_internal/__init__.py`（plan 02 已建）；如果 plan 02 仍未交付 → 本 plan Task 1 顺手补一个空 `__init__.py` 保证 import 可达：

```python
# plugins/huly/_internal/__init__.py
"""Internal-only modules — port from hr/offboarding-flow B-full-channel design.

License: All files Apache-2.0. Inspired by hr/offboarding-flow design — not derived source.
"""
```
  </action>
  <verify>
    <automated>test -f plugins/huly/manifest.yaml && python -c "import yaml; m=yaml.safe_load(open('plugins/huly/manifest.yaml')); assert set(m['capability_facets']) == {'doc','im','identity','tracker'}, 'capability_facets wrong'; assert 'huly_huly_net' in m['sandbox']['docker_networks'], 'docker_networks missing'; assert m['identity']['is_source_of_truth'] is True; assert m['doc']['supports_collaborative_edit'] is True; print('manifest OK')"</automated>
  </verify>
  <done>manifest.yaml 含 4 capability_facets + sandbox.docker_networks=[huly_huly_net] + identity.is_source_of_truth=true + doc.supports_collaborative_edit=true + cache_ttl_seconds schema 字段；__init__.py 含 license attribution</done>
</task>

<task type="auto">
  <name>Task 2: _internal/markdown_to_prosemirror.py — marko AST → ProseMirror JSON 12 元素映射</name>
  <files>plugins/huly/_internal/markdown_to_prosemirror.py,backend/tests/platforms/test_huly_plugin_doc.py</files>
  <action>
**实现完全按 RESEARCH §Pattern 5（line 563-716）+ Pitfall 11 (ListItem 必须含 paragraph) + Pitfall 6 (节点名映射) 严格映射 12 元素：**

```python
"""marko AST → ProseMirror JSON 转换器 — Huly markup 二步流程支持。

License: Apache-2.0. Inspired by hr/offboarding-flow design (huly-integration-architecture
§4.5 markup JSON 例) — not derived source; re-implemented under Apache-2.0.

12 元素映射（block × 8 + inline marks × 4）：
- Block: document/heading(level)/paragraph/list[ordered+bullet]/listItem/blockquote/
         code_block(lang)/horizontalRule
- Inline marks: em / strong / code / link(href)

防护：
- Pitfall 11: ListItem.content[0] 必须是 paragraph block（marko inline 强制 wrap）
- Pitfall 6: marko `strong_emphasis` → ProseMirror `strong` 显式映射（不依赖名字一致）
- blank_line → 跳过（return None，调用方 filter）
- 未识别 element → fallback paragraph + raw text（不 raise，保守降级）
"""

from __future__ import annotations
from typing import Any
import marko
from marko.ast_renderer import ASTRenderer
from marko import Markdown


_MARKDOWN = Markdown(renderer=ASTRenderer)

# marko AST `element` → ProseMirror mark `type`
_MARK_MAP: dict[str, str] = {
    "emphasis": "em",
    "strong_emphasis": "strong",
    "code_span": "code",
}
# link 特殊处理（attrs.href）— 不入 _MARK_MAP


def markdown_to_prosemirror(markdown_text: str) -> dict[str, Any]:
    """Markdown → Huly markup（ProseMirror JSON dict）。

    Args:
        markdown_text: CommonMark v0.31.2 markdown 字符串

    Returns:
        {"type": "doc", "content": [...]} — 可直接 json.dumps(ensure_ascii=False) 给 collab createContent
    """
    if not markdown_text:
        return {"type": "doc", "content": []}
    raw_ast = _MARKDOWN.convert(markdown_text)
    converted = _convert_node(raw_ast)
    return converted if converted is not None else {"type": "doc", "content": []}


def _convert_node(node: dict | str | None) -> dict | None:
    """递归 marko AST element → ProseMirror block node。"""
    if not isinstance(node, dict):
        return None
    name = node.get("element")

    if name == "document":
        return {
            "type": "doc",
            "content": [c for c in (_convert_node(child) for child in node.get("children", []))
                          if c is not None],
        }

    if name == "heading":
        return {
            "type": "heading",
            "attrs": {"level": max(1, min(6, int(node.get("level", 1))))},
            "content": _convert_inline(node.get("children", [])),
        }

    if name == "paragraph":
        return {
            "type": "paragraph",
            "content": _convert_inline(node.get("children", [])),
        }

    if name == "list":
        is_ordered = bool(node.get("ordered", False))
        return {
            "type": "orderedList" if is_ordered else "bulletList",
            "content": [c for c in (_convert_node(child) for child in node.get("children", []))
                          if c is not None],
        }

    if name == "list_item":
        # Pitfall 11 防御：ListItem.content[0] 必须是 paragraph（marko inline 强制 wrap）
        children = node.get("children", [])
        if children and isinstance(children[0], dict) and children[0].get("element") not in (
            "paragraph", "list", "blank_line"
        ):
            # marko 已把 inline 自动包 paragraph，但若直接 raw_text 出现 → 强制 wrap
            wrapped_inline = _convert_inline(children)
            return {
                "type": "listItem",
                "content": [{"type": "paragraph", "content": wrapped_inline}],
            }
        return {
            "type": "listItem",
            "content": [c for c in (_convert_node(child) for child in children)
                          if c is not None],
        }

    if name == "block_quote":
        return {
            "type": "blockquote",
            "content": [c for c in (_convert_node(child) for child in node.get("children", []))
                          if c is not None],
        }

    if name == "code_block" or name == "fenced_code":
        lang = node.get("lang", "") or node.get("language", "")
        # code_block.content 是 raw text 单一字符串（不递归 marks）
        raw_text = "".join(_flatten_text(node))
        return {
            "type": "code_block",
            "attrs": {"language": lang},
            "content": [{"type": "text", "text": raw_text}] if raw_text else [],
        }

    if name == "thematic_break":
        return {"type": "horizontalRule"}

    if name == "blank_line":
        return None  # 跳过

    # fallback — 未识别 element 退化为 paragraph + raw text
    inline = _convert_inline(node.get("children", []))
    return {"type": "paragraph", "content": inline} if inline else None


def _convert_inline(children: list) -> list[dict]:
    """Inline element list → ProseMirror text nodes (with marks)。"""
    out: list[dict] = []
    for c in children:
        if isinstance(c, str):
            if c:
                out.append({"type": "text", "text": c})
            continue
        if not isinstance(c, dict):
            continue
        elem = c.get("element")
        if elem == "raw_text":
            txt = c.get("children", "")
            if isinstance(txt, str) and txt:
                out.append({"type": "text", "text": txt})
            continue
        if elem == "link":
            # link 内可能含 inline marks — 递归内层 + 套 link mark
            inner = _convert_inline(c.get("children", []))
            for n in inner:
                marks = n.get("marks", [])
                marks.append({"type": "link", "attrs": {"href": c.get("dest", "")}})
                n["marks"] = marks
            out.extend(inner)
            continue
        if elem in _MARK_MAP:
            # em / strong / code 等含子 inline — flatten text + add mark
            text = "".join(_flatten_text(c))
            if text:
                out.append({
                    "type": "text",
                    "text": text,
                    "marks": [{"type": _MARK_MAP[elem]}],
                })
            continue
        # 未识别 inline element → flatten 当 raw text
        text = "".join(_flatten_text(c))
        if text:
            out.append({"type": "text", "text": text})
    return out


def _flatten_text(node: dict | str | None) -> list[str]:
    """递归收集所有 raw_text 字符串。"""
    if isinstance(node, str):
        return [node]
    if not isinstance(node, dict):
        return []
    children = node.get("children", [])
    if isinstance(children, str):
        return [children]
    out: list[str] = []
    if isinstance(children, list):
        for c in children:
            out.extend(_flatten_text(c))
    return out
```

≥ 150 行（含 docstring）。

**Unit tests (本 task 同时写 doc 测试主体)** — 写 `backend/tests/platforms/test_huly_plugin_doc.py` markdown_to_prosemirror 部分（doc handler 测试 task 6 写）：

```python
"""DocCapability unit tests — markdown_to_prosemirror + 二步流程封装测试。"""
import pytest
from plugins.huly._internal.markdown_to_prosemirror import markdown_to_prosemirror


class TestMarkdownToProseMirror:
    def test_heading_level_1_to_6(self):
        for level in range(1, 7):
            pm = markdown_to_prosemirror("#" * level + " Hello")
            assert pm["type"] == "doc"
            assert pm["content"][0]["type"] == "heading"
            assert pm["content"][0]["attrs"]["level"] == level

    def test_paragraph_with_marks(self):
        md = "Hello *em* **strong** `code` [link](https://example.com)."
        pm = markdown_to_prosemirror(md)
        para = pm["content"][0]
        assert para["type"] == "paragraph"
        marks_by_text = {n["text"]: n.get("marks", []) for n in para["content"]}
        assert any(m["type"] == "em" for m in marks_by_text.get("em", []))
        assert any(m["type"] == "strong" for m in marks_by_text.get("strong", []))
        assert any(m["type"] == "code" for m in marks_by_text.get("code", []))
        assert any(m["type"] == "link" and m["attrs"]["href"] == "https://example.com"
                     for m in marks_by_text.get("link", []))

    def test_bullet_list_items_have_paragraph_wrap(self):
        """Pitfall 11 防御 — ListItem.content[0] 必须是 paragraph。"""
        pm = markdown_to_prosemirror("- a\n- b\n- c")
        bl = pm["content"][0]
        assert bl["type"] == "bulletList"
        for li in bl["content"]:
            assert li["type"] == "listItem"
            assert li["content"][0]["type"] == "paragraph", \
                f"ListItem 内层必须 paragraph，实际是 {li['content'][0]['type']}"

    def test_ordered_list_distinct_from_bullet(self):
        pm = markdown_to_prosemirror("1. one\n2. two")
        assert pm["content"][0]["type"] == "orderedList"

    def test_code_block_with_language(self):
        pm = markdown_to_prosemirror("```python\nprint('hi')\n```")
        cb = pm["content"][0]
        assert cb["type"] == "code_block"
        assert cb["attrs"]["language"] == "python"
        assert "print" in cb["content"][0]["text"]

    def test_blockquote(self):
        pm = markdown_to_prosemirror("> quoted")
        assert pm["content"][0]["type"] == "blockquote"

    def test_horizontal_rule(self):
        pm = markdown_to_prosemirror("---")
        assert pm["content"][0]["type"] == "horizontalRule"

    def test_empty_markdown_returns_empty_doc(self):
        pm = markdown_to_prosemirror("")
        assert pm == {"type": "doc", "content": []}

    def test_blank_lines_skipped(self):
        pm = markdown_to_prosemirror("para1\n\n\npara2")
        para_count = sum(1 for n in pm["content"] if n["type"] == "paragraph")
        assert para_count == 2

    def test_strong_emphasis_maps_to_strong_not_strong_emphasis(self):
        """Pitfall 6 防御 — marko strong_emphasis → ProseMirror strong（不一致名字）。"""
        pm = markdown_to_prosemirror("**bold**")
        marks = pm["content"][0]["content"][0]["marks"]
        assert all(m["type"] != "strong_emphasis" for m in marks)
        assert any(m["type"] == "strong" for m in marks)

    def test_link_inline_with_em_inside(self):
        """[*em link*](url) — em mark + link mark 共存。"""
        pm = markdown_to_prosemirror("[*em link*](https://x.com)")
        node = pm["content"][0]["content"][0]
        mark_types = {m["type"] for m in node["marks"]}
        assert "link" in mark_types

    def test_full_doc_round_trip_to_huly_collab(self):
        """RESEARCH §Pattern 5 整文档测 — heading + para + bullet list + code 完整。"""
        md = "# Title\n\nParagraph **bold** here.\n\n- a\n- b\n\n```js\nconsole.log(1)\n```"
        pm = markdown_to_prosemirror(md)
        assert pm["type"] == "doc"
        assert len(pm["content"]) == 4
        assert pm["content"][0]["type"] == "heading"
        assert pm["content"][1]["type"] == "paragraph"
        assert pm["content"][2]["type"] == "bulletList"
        assert pm["content"][3]["type"] == "code_block"
```

12 元素全覆盖（heading × 6 levels 单测合并 + paragraph + ordered + bullet + listItem + blockquote + code_block + horizontalRule + em + strong + code + link = 12+）。
  </action>
  <verify>
    <automated>test -f plugins/huly/_internal/markdown_to_prosemirror.py && wc -l plugins/huly/_internal/markdown_to_prosemirror.py | awk '{exit ($1 >= 150 ? 0 : 1)}' && grep -q "Inspired by hr/offboarding-flow" plugins/huly/_internal/markdown_to_prosemirror.py && cd backend && uv run pytest tests/platforms/test_huly_plugin_doc.py::TestMarkdownToProseMirror -x -q 2>&1 | tail -5</automated>
  </verify>
  <done>markdown_to_prosemirror.py ≥ 150 行 + 12 元素映射 + ListItem paragraph wrap (Pitfall 11) + strong_emphasis→strong (Pitfall 6) + license attribution；unit tests TestMarkdownToProseMirror class 全绿（≥ 12 test cases）</done>
</task>

<task type="auto">
  <name>Task 3: _internal/collab_client.py — HulyCollabClient /rpc createContent</name>
  <files>plugins/huly/_internal/collab_client.py</files>
  <action>
**完全按 RESEARCH §Pattern 9 + §Code Example "Huly collab service createContent"（line 877-1002 + 1351-1383）实现，覆盖 RPC 段编码 + ws_token Bearer + 错误诊断：**

```python
"""HulyCollabClient — Huly collaborator service `/rpc/{encoded_doc_id}` 客户端。

License: Apache-2.0. Inspired by hr/offboarding-flow B-full-channel design
(huly-integration-architecture §4.3) — not derived source; re-implemented under Apache-2.0.

设计要点：
- collab service URL `http://collaborator:3078` 在 docker network `huly_huly_net` 内可达
- /rpc/{encoded_doc_id} POST：method=createContent + payload.content[attr]=markup_str
- encoded_doc_id = urlEncoded("{ws_uuid}|{class}|{id}|{attr}")
- 必须 Bearer {ws_token}（HulyPlatformClient.workspace_token，selectWorkspace 后产出）
- 失败模式诊断：HTTP 4xx/5xx → raise + RESEARCH Warning signs（"Unexpected token '<'" = nginx 未配 collab proxy）

防护：
- Pitfall 10: 不在模块顶层持有 httpx.AsyncClient（每次新开 + with 自动 close）；caller 负责并发
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

import httpx


class HulyCollabClient:
    """Huly collaborator service /rpc 客户端 — 仅 createContent 方法（v1 范围）。"""

    def __init__(self, *, collab_url: str, ws_token: str, timeout: float = 10.0):
        """Args:
            collab_url: 形如 "http://collaborator:3078"（docker network 内可达 — 必先 attach huly_huly_net）
            ws_token: HulyPlatformClient.workspace_token（selectWorkspace 后产出）
            timeout: 单次 HTTP 调用超时（秒）— 不超过 daemon invoke timeout 30s
        """
        if not collab_url:
            raise ValueError("HulyCollabClient.collab_url 不能为空 — 必须显式传 manifest 配置的 huly_collab_url")
        if not ws_token:
            raise ValueError("HulyCollabClient.ws_token 不能为空 — HulyPlatformClient.workspace_token 必须先就绪")
        self._collab_url = collab_url.rstrip("/")
        self._ws_token = ws_token
        self._timeout = timeout

    @staticmethod
    def encode_doc_id(*, workspace_uuid: str, object_class: str,
                       object_id: str, object_attr: str) -> str:
        """文档级 RPC URL 段：urlEncoded("{ws}|{class}|{id}|{attr}")。

        Huly collab service 用此 URL 段唯一定位文档+字段（attr 通常是 "content"）。
        """
        return urllib.parse.quote(
            f"{workspace_uuid}|{object_class}|{object_id}|{object_attr}",
            safe="",
        )

    async def create_content(
        self, *,
        workspace_uuid: str,
        object_class: str,
        object_id: str,
        object_attr: str,
        prosemirror_doc: dict,
    ) -> str:
        """POST /rpc/{encoded_doc_id} method=createContent → blob ref (str)。

        Args:
            workspace_uuid: HulyPlatformClient.workspace_uuid
            object_class: "document:class:Document" 等
            object_id: 之前 ops.create_doc 返回的 doc_id（content 字段暂为空字符串）
            object_attr: 通常 "content"
            prosemirror_doc: markdown_to_prosemirror() 返回的 dict

        Returns:
            blob_ref 字符串（e.g. "{docId}-content-{timestamp}"）— 调用方 ops.update_doc 写回 content 字段

        Raises:
            RuntimeError: HTTP 非 200 / 响应含 error / 响应解析失败
        """
        encoded = self.encode_doc_id(
            workspace_uuid=workspace_uuid, object_class=object_class,
            object_id=object_id, object_attr=object_attr,
        )
        markup = json.dumps(prosemirror_doc, ensure_ascii=False)
        body = {
            "method": "createContent",
            "payload": {"content": {object_attr: markup}},
        }
        url = f"{self._collab_url}/rpc/{encoded}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._ws_token}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as e:
                raise RuntimeError(
                    f"collab.createContent network error: {e} "
                    f"(检查 docker network 是否 attach huly_huly_net + collaborator:3078 是否可达)"
                ) from e

        if resp.status_code != 200:
            # 诊断 RESEARCH Warning signs:
            # "Unexpected token '<'" = nginx 未配 /_collaborator/ proxy 或调用方走错 URL
            preview = resp.text[:200] if resp.text else "<empty>"
            raise RuntimeError(
                f"collab.createContent HTTP {resp.status_code}: {preview} "
                f"(url={url})"
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"collab.createContent non-JSON response: {resp.text[:200]} (parse error: {e})"
            ) from e

        if "error" in data:
            raise RuntimeError(f"collab.createContent server error: {data['error']}")

        # 响应 schema: {"content": {<attr>: "<blob_ref>"}}
        content = data.get("content") or {}
        blob_ref = content.get(object_attr)
        if not blob_ref or not isinstance(blob_ref, str):
            raise RuntimeError(
                f"collab.createContent missing content[{object_attr}] in response: {data}"
            )
        return blob_ref
```

≥ 80 行。
  </action>
  <verify>
    <automated>test -f plugins/huly/_internal/collab_client.py && wc -l plugins/huly/_internal/collab_client.py | awk '{exit ($1 >= 80 ? 0 : 1)}' && grep -q "Inspired by hr/offboarding-flow" plugins/huly/_internal/collab_client.py && grep -q "encode_doc_id" plugins/huly/_internal/collab_client.py && grep -q "Bearer" plugins/huly/_internal/collab_client.py</automated>
  </verify>
  <done>collab_client.py ≥ 80 行 + encode_doc_id staticmethod + create_content async + Bearer ws_token + 3 raise 诊断（HTTP error / non-200 / non-JSON / server error） + license attribution</done>
</task>

<task type="auto">
  <name>Task 4: _internal/identity_lru.py — PersonUuid LRU cache + workspace 隔离</name>
  <files>plugins/huly/_internal/identity_lru.py</files>
  <action>
**完全按 RESEARCH §Pattern 6（line 723-792）+ Pitfall 5（cache key 跨 workspace 隔离）实现：**

```python
"""PersonUuid LRU cache — username → personUuid 2 跳查询缓存。

License: Apache-2.0. Inspired by hr/offboarding-flow huly_im_provider._resolve_account
+ huly-integration-architecture §5.5 cache 教训 — not derived source.

设计要点：
- TTLCache(maxsize=10000, ttl=3600) 默认；manifest config.cache_ttl_seconds 启动时一次性覆盖
- 跨 workspace_uuid 隔离 cache key（防 multi-workspace mismatch — RESEARCH Pitfall 5）
- double-check lock 防 cache miss 并发同名 → 多次查询 race
- "__not_found__" sentinel value 缓存 negative result（短 TTL 内避免反复查 not-found user）
- invalidate_cache 可按 username / workspace_uuid 选择性清

配置时机：
- daemon 启动时调 configure_cache(maxsize, ttl) 一次（manifest 读 cache_ttl_seconds）
- TTLCache 不支持运行时改 TTL —— 必须重新创建 cache 实例
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from cachetools import TTLCache

if TYPE_CHECKING:
    from .platform_client import HulyPlatformClient

_log = logging.getLogger(__name__)

# Sentinel 防 not-found user 反复查
_NOT_FOUND = "__not_found__"

# daemon 进程级单例（lazy-init by configure_cache）
_uuid_cache: TTLCache | None = None
_cache_lock = asyncio.Lock()


def configure_cache(*, maxsize: int = 10000, ttl_seconds: int = 3600) -> None:
    """daemon 启动时调用一次 — 用 manifest cache_ttl_seconds 覆盖默认值。

    TTLCache 不支持运行时改 TTL（实例不可变），故由本函数控制重建。
    """
    global _uuid_cache
    _uuid_cache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
    _log.info("identity LRU cache configured: maxsize=%d ttl=%ds", maxsize, ttl_seconds)


def _ensure_cache() -> TTLCache:
    """Lazy init — 第一次访问时若 configure_cache 未调用则用默认值。"""
    global _uuid_cache
    if _uuid_cache is None:
        configure_cache()
    return _uuid_cache  # type: ignore[return-value]


async def resolve_person_uuid(
    pc: "HulyPlatformClient",
    username: str,
    *,
    user_email_domain: str = "demo.local",
) -> Optional[str]:
    """username → personUuid (LRU cache hit / 2 跳 miss path)。

    Path (miss):
        SocialIdentity key=email:{username}@{user_email_domain} → attachedTo (PersonId)
        → Employee mixin _id=PersonId → personUuid

    Cache key: f"{workspace_uuid}:{username}" — 跨 workspace 隔离防 multi-ws mismatch
    Cache value: personUuid (str) | "__not_found__" (str) for negative cache
    """
    cache = _ensure_cache()
    ws_uuid = pc.rest.workspace_uuid
    cache_key = f"{ws_uuid}:{username}"

    cached = cache.get(cache_key)
    if cached is not None:
        return None if cached == _NOT_FOUND else cached

    async with _cache_lock:
        # double-check 防 race（两个 coroutine 同时 miss）
        cached = cache.get(cache_key)
        if cached is not None:
            return None if cached == _NOT_FOUND else cached

        social_key = f"email:{username}@{user_email_domain}"
        try:
            si = await pc.rest.find_one("contact:class:SocialIdentity", {"key": social_key})
        except Exception as e:
            _log.warning("identity.find_one SocialIdentity 失败 (username=%s): %s", username, e)
            return None  # 不缓存网络错误（下次重试）

        if not si or not si.get("attachedTo"):
            cache[cache_key] = _NOT_FOUND
            return None

        try:
            emp = await pc.rest.find_one("contact:mixin:Employee", {"_id": si["attachedTo"]})
        except Exception as e:
            _log.warning("identity.find_one Employee 失败 (username=%s, attachedTo=%s): %s",
                          username, si["attachedTo"], e)
            return None

        if not emp or not emp.get("personUuid"):
            cache[cache_key] = _NOT_FOUND
            return None

        uuid_val = str(emp["personUuid"])
        cache[cache_key] = uuid_val
        return uuid_val


def invalidate_cache(*, username: str | None = None,
                       workspace_uuid: str | None = None) -> int:
    """显式 invalidate — Phase 5.D Identity watch_user_changes 反向 sync 钩子用。

    Args:
        username: 限定 username（None = 不限）
        workspace_uuid: 限定 workspace（None = 不限）

    Returns:
        被清理的 key 数量
    """
    cache = _ensure_cache()
    if username is None and workspace_uuid is None:
        n = len(cache)
        cache.clear()
        return n
    keys_to_clear = [
        k for k in list(cache.keys())
        if (username is None or k.endswith(f":{username}"))
            and (workspace_uuid is None or k.startswith(f"{workspace_uuid}:"))
    ]
    for k in keys_to_clear:
        cache.pop(k, None)
    return len(keys_to_clear)


def cache_stats() -> dict:
    """调试用 — 返回 cache 当前大小 / maxsize / ttl。"""
    cache = _ensure_cache()
    return {
        "size": len(cache),
        "maxsize": cache.maxsize,
        "ttl": cache.ttl,
    }
```

≥ 90 行。
  </action>
  <verify>
    <automated>test -f plugins/huly/_internal/identity_lru.py && wc -l plugins/huly/_internal/identity_lru.py | awk '{exit ($1 >= 90 ? 0 : 1)}' && grep -q "Inspired by hr/offboarding-flow" plugins/huly/_internal/identity_lru.py && python -c "from plugins.huly._internal.identity_lru import configure_cache, cache_stats, invalidate_cache; configure_cache(maxsize=100, ttl_seconds=60); s=cache_stats(); assert s['maxsize']==100 and s['ttl']==60; assert invalidate_cache()==0; print('LRU ok')"
    <automated>test -f plugins/huly/_internal/identity_lru.py && wc -l plugins/huly/_internal/identity_lru.py | awk '{exit ($1 >= 90 ? 0 : 1)}' && grep -q "Inspired by hr/offboarding-flow" plugins/huly/_internal/identity_lru.py && python -c "from plugins.huly._internal.identity_lru import configure_cache, cache_stats, invalidate_cache; configure_cache(maxsize=100, ttl_seconds=60); s=cache_stats(); assert s['maxsize']==100 and s['ttl']==60; assert invalidate_cache()==0; print('LRU ok')"</automated>
  </verify>
  <done>identity_lru.py >= 90 行 + TTLCache + configure_cache + resolve_person_uuid + invalidate_cache + double-check lock + workspace_uuid 隔离 cache key + license attribution；smoke import 通过</done>
</task>

<task type="auto">
  <name>Task 5: _internal/per_user_channel.py — chunter:Channel dm-{username} ensure-or-create (IM 绕开方案)</name>
  <files>plugins/huly/_internal/per_user_channel.py</files>
  <action>
**完全按 hr huly_im_provider.py `_ensure_user_channel` (line 203-247) 的设计借鉴 + Pitfall 2 防御（永不尝试 chunter:DirectMessage）。代码骨架（≥ 70 行）：**

```python
"""Per-user Channel 模式 — Huly DM 静默 reject 绕开方案。

License: Apache-2.0. Inspired by hr/offboarding-flow huly_im_provider._ensure_user_channel
(huly-integration-architecture §5.2 DM 静默 reject 教训) — not derived source.

设计要点（Pitfall 2 防御）：
- 永不创 chunter:DirectMessage（server ACL 同步 race 导致 ChatMessage 静默 drop）
- 改创 chunter:Channel name=`dm-{username}` members=[bot_account, target_uuid]
- channel_id LRU 缓存（按 username 键，跨 ws_uuid 隔离）避免反复 find_one + create_doc
- target_uuid 解析失败时仍创 channel（仅 bot 是 member，warning log）— 同 hr line 219-224

幂等：
- find_one Channel by name → 已存在直接复用 channel_id
- create_doc 路径只在缓存 + DB 都 miss 时走
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from cachetools import TTLCache

if TYPE_CHECKING:
    from .platform_client import HulyPlatformClient

_log = logging.getLogger(__name__)

# daemon 进程级 channel_id 缓存（key: f"{ws_uuid}:{username}"，value: channel_id）
_channel_cache: TTLCache = TTLCache(maxsize=10000, ttl=3600)
_channel_lock = asyncio.Lock()


async def ensure_user_channel(
    pc: "HulyPlatformClient",
    username: str,
    *,
    channel_prefix: str = "dm-",
) -> str:
    """确保 user 的 per-user chunter:Channel 存在；返回 channel_id。

    Args:
        pc: HulyPlatformClient（已 connect + selectWorkspace）
        username: 业务侧 username
        channel_prefix: 频道名前缀（默认 "dm-"，可由 manifest 覆盖）

    Returns:
        channel_id (str) — 用于 ops.add_collection ChatMessage 入参 attachedTo
    """
    from .identity_lru import resolve_person_uuid  # lazy import 防循环
    from .constants import CHUNTER_CLASS_CHANNEL, CORE_SPACE_SPACE

    cache_key = f"{pc.rest.workspace_uuid}:{username}"

    cached = _channel_cache.get(cache_key)
    if cached:
        return cached

    async with _channel_lock:
        cached = _channel_cache.get(cache_key)
        if cached:
            return cached

        channel_name = f"{channel_prefix}{username}"
        # 1. find_one Channel by name
        try:
            existing = await pc.rest.find_one(CHUNTER_CLASS_CHANNEL, {"name": channel_name})
        except Exception as e:
            _log.warning("ensure_user_channel.find_one 失败 (%s): %s", channel_name, e)
            existing = None

        if existing is not None:
            channel_id = str(existing.get("_id"))
            _channel_cache[cache_key] = channel_id
            return channel_id

        # 2. 不存在 → create_doc
        target_uuid = await resolve_person_uuid(pc, username)
        bot_uuid = pc.bot_account
        members = [bot_uuid]
        if target_uuid:
            members.append(target_uuid)
        else:
            _log.warning(
                "ensure_user_channel: username=%s 无对应 Huly 账号；"
                "channel 仅 bot member（消息仍可发但用户看不到）", username,
            )

        try:
            channel_id = await pc.ops.create_doc(
                CHUNTER_CLASS_CHANNEL, CORE_SPACE_SPACE,
                {"name": channel_name, "description": f"Agent Builder DM — {username}",
                 "topic": "", "private": True, "archived": False,
                 "members": members, "autoJoin": False},
            )
        except Exception as e:
            raise RuntimeError(f"ensure_user_channel: create Channel({channel_name}) 失败: {e}") from e

        _log.info("per_user_channel created: %s id=%s members=%d", channel_name,
                   (channel_id or "?")[:8], len(members))
        _channel_cache[cache_key] = channel_id
        return channel_id


def invalidate_channel_cache(*, username: str | None = None,
                                workspace_uuid: str | None = None) -> int:
    """显式 invalidate — Phase 5.D 反向 sync 钩子 / 测试用。"""
    if username is None and workspace_uuid is None:
        n = len(_channel_cache); _channel_cache.clear(); return n
    keys = [k for k in list(_channel_cache.keys())
              if (username is None or k.endswith(f":{username}"))
                 and (workspace_uuid is None or k.startswith(f"{workspace_uuid}:"))]
    for k in keys: _channel_cache.pop(k, None)
    return len(keys)
```

**关键防御**：本模块永不出现字符串 `chunter:DirectMessage` —— Pitfall 2 + license attribution test (Task 8) 会 grep 验证。
  </action>
  <verify>
    <automated>test -f plugins/huly/_internal/per_user_channel.py && wc -l plugins/huly/_internal/per_user_channel.py | awk '{exit ($1 >= 70 ? 0 : 1)}' && grep -q "Inspired by hr/offboarding-flow" plugins/huly/_internal/per_user_channel.py && grep -q "ensure_user_channel" plugins/huly/_internal/per_user_channel.py && ! grep -q "chunter:DirectMessage" plugins/huly/_internal/per_user_channel.py</automated>
  </verify>
  <done>per_user_channel.py >= 70 行 + ensure_user_channel + invalidate_channel_cache + 永不出现 chunter:DirectMessage 字符串（Pitfall 2）+ license attribution + cache + warning fallback (target_uuid 找不到时仅 bot member)</done>
</task>

<task type="auto">
  <name>Task 6: huly_plugin.py — 4 capability dispatcher facade + eager connect + asyncio.Lock 包 ws 写</name>
  <files>plugins/huly/huly_plugin.py,plugins/huly/prompts/ai_suggest_mentions_zh.md</files>
  <action>
**这是 plan 的核心 task — 把 5.A stub huly_plugin.py 升级为 4-capability 完整 facade。基于 RESEARCH §Pattern 1 + §Pattern 9 + Pitfall 10（eager connect 防 lazy lock 死锁）。**

完整实现见 RESEARCH §Pattern 1 (line 252-319) 与 §Pattern 9 (line 877-1002)。骨架包含：

1. **模块级共享 client + ws 写锁**：
```python
_client: HulyPlatformClient | None = None
_client_lock = asyncio.Lock()
_ws_write_lock = asyncio.Lock()  # 4 facet 并发 ws 写串行化（Pitfall 10）
```

2. **eager connect**（daemon main() 启动时主动调）：
```python
async def _ensure_client_eager() -> HulyPlatformClient:
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is not None:
            return _client
        _client = await connect_huly(
            accounts_url=os.environ["HULY_ACCOUNTS_URL"],
            admin_email=os.environ["HULY_ADMIN_EMAIL"],
            admin_password=os.environ["HULY_ADMIN_PASSWORD"],
            workspace_url=os.environ["HULY_WORKSPACE"],
            timeout=float(os.environ.get("HULY_HTTP_TIMEOUT", "15.0")),
        )
        return _client
```

3. **doc.* 6 handler**（二步流程封装在 daemon 内）：
- `doc_create_document` — Step 1 create shell (content="") → Step 2 markdown → ProseMirror → Step 3 collab createContent → blob_ref → Step 4 update_doc(content=blob_ref)，全程 `async with _ws_write_lock:` 包 ws 写
- `doc_replace_document_content` — 同二步流程子集
- `doc_apply_document_delta` — v1 视 delta 为 ProseMirror dict 直接走 collab createContent
- `doc_get_document` — find_one + 返回元数据
- `doc_add_comment` — v1 raise NotImplementedError（v1.1 接入）
- `doc_ai_suggest_mentions` — v1 返回 []（plan 06 接 LLM provider）

4. **im.* 3 handler**（per-user Channel 路径）：
- `im_send_card` — recipient.kind='dm_user' 自动调 `ensure_user_channel(username)` → `ops.add_collection(ChatMessage, channel_id, ...)`；kind='channel' 直接用 channel_id；kind='thread' 降级 channel_id
- `im_update_card` — v1.1 待接入
- `im_send_text` — 内部转 send_card({title:"", body_markdown:text})

5. **identity.* 2 handler**（LRU cache）：
- `identity_resolve_user` — `resolve_person_uuid(pc, identifier, user_email_domain=_USER_EMAIL_DOMAIN)` → UserPrincipal dict
- `identity_list_users` — `pc.rest.find_all("contact:class:Person", {})`

6. **tracker.* 2 stub handler**：
- `tracker_create_issue` / `tracker_update_issue` — raise NotImplementedError("v1.1 待接入")

7. **METHODS dispatch table**（13 method 全注册）

8. **JSONRPC main loop**（沿用 5.A 设计 — 5.B daemon_client.invoke 兼容）：
- `_handle(line)` 接受 envelope → dispatch METHODS → 返回 response bytes
- `main()` 启动序：basicConfig log → configure_cache(ttl from HULY_CACHE_TTL_SECONDS) → eager connect → asyncio StreamReader stdin loop
- NotImplementedError → JSONRPC -32601；其他异常 → -32603

≥ 280 行。

**同时创建 `plugins/huly/prompts/ai_suggest_mentions_zh.md`** (≥ 20 行 stub for plan 06)：
- 输入 (markdown + context)
- 输出 (JSON list of {user_ref, confidence, rationale})
- Prompt 模板（v1 daemon 返回 [] —— 模板留 plan 06 LLM 接入用）

**完整代码请见 RESEARCH §Pattern 1 + §Pattern 9 + 本 plan reading doc 借鉴点 #1, #6, #7, #10。**
  </action>
  <verify>
    <automated>test -f plugins/huly/huly_plugin.py && wc -l plugins/huly/huly_plugin.py | awk '{exit ($1 >= 280 ? 0 : 1)}' && python -c "import ast; t=ast.parse(open('plugins/huly/huly_plugin.py').read()); methods=[n for n in ast.walk(t) if isinstance(n, ast.AsyncFunctionDef) and n.name.startswith(('doc_','im_','identity_','tracker_'))]; assert len(methods) >= 12, f'expected >= 12 capability handlers, got {len(methods)}'; print(f'{len(methods)} capability handlers OK')" && test -f plugins/huly/prompts/ai_suggest_mentions_zh.md && grep -q "_ws_write_lock" plugins/huly/huly_plugin.py && grep -q "ensure_user_channel" plugins/huly/huly_plugin.py && grep -q "HulyCollabClient" plugins/huly/huly_plugin.py</automated>
  </verify>
  <done>huly_plugin.py >= 280 行 + 12+ capability handlers（doc x 6 + im x 3 + identity x 2 + tracker x 2）+ METHODS dict 全 13 method + eager connect (Pitfall 10 防御) + _ws_write_lock 包所有 ws 写 + ai_suggest_mentions_zh.md stub 已创建</done>
</task>

<task type="auto">
  <name>Task 7: 替换 5.A acid test stub — test_huly_acid_test.py 走真 HulyPlugin per-user Channel 路径 + mock_huly_server 升级</name>
  <files>backend/tests/platforms_integration/test_huly_acid_test.py,backend/tests/platforms_integration/mock_huly_server.py</files>
  <action>
**第一步：mock_huly_server.py 升级（94 行 → ≥ 200 行）。** 在现有 aiohttp web 上加 5 个新 endpoints：

1. `POST /api/v1/login/email` — login_handler 返回 mock account token
2. `POST /api/v1/workspace/select` — select_workspace_handler 返回 {endpoint, token, workspace_uuid}
3. `POST /api/v1/find-one` — find_one_handler，按 class + query 派发：
   - `contact:class:SocialIdentity` key=email:{user}@demo.local → 返回 {attachedTo: pid-{user}}
   - `contact:mixin:Employee` _id=pid-{user} → 返回 {personUuid: puuid-{user}}
   - `chunter:class:Channel` name=dm-{user} → 返回缓存或 None
4. `POST /api/v1/tx` — tx_handler，按 TxType 派发：
   - TxCreateDoc objectClass=chunter:class:Channel → 缓存到 `_seed_channels[name]`，返回 {_id: ch-{hex8}}
   - TxCreateDoc objectClass=document:class:Document → 缓存到 `_seed_docs[id]`，返回 {_id: doc-{hex8}}
   - TxCollectionCUD → 简单 {ok: true}
   - TxUpdateDoc → 更新 `_seed_docs[doc_id]`，返回 {ok: true}
5. `POST /rpc/{encoded}` — collab_rpc_handler：
   - 解析 encoded urlEncoded("ws|class|id|attr") → 4 parts
   - 仅支持 method=createContent
   - 返回 `{content: {<attr>: "{id}-{attr}-{ts}"}}` blob_ref（按 hr §4.3 格式）

模块级 seed：`_seed_users = {"alice": {personUuid, personId}, "bob": {...}}` + `_seed_channels: dict` + `_seed_docs: dict`。

**保留** 5.A 原 `/api/v1/chunter/messages` handler 作 backward compat（旧 stub 路径仍可调，但 5.C 真路径不再走它）。

**第二步：test_huly_acid_test.py 替换 stub 测试为真路径**。保留 5/5 test 但每个 daemon spawn env 升级：

```python
env = {
    "HULY_ACCOUNTS_URL": mock_huly_server,
    "HULY_ADMIN_EMAIL": "admin@demo.local",
    "HULY_ADMIN_PASSWORD": "admin",
    "HULY_WORKSPACE": "mock-ws",
    "HULY_COLLAB_URL": mock_huly_server,  # 同 server 暴露 /rpc/...
    "HULY_CACHE_TTL_SECONDS": "300",
    "PYTHONPATH": project_root,
}
```

**Test 1（acid send_card 替换）**：
```python
result = await daemon.invoke("im", "send_card",
    recipient={"kind": "dm_user", "user_id": "alice"},
    card={"title": "Test", "body_markdown": "Hello alice"},
    idempotency_key="acid-001",
)
elapsed = time.monotonic() - t0
assert elapsed > 0.2, "必须真 subprocess + JSONRPC roundtrip"
assert result["plugin_name"] == "huly"
assert result["native_id"].startswith("huly-msg-")
assert result["extras"]["channel_id"].startswith("ch-")  # per-user Channel 路径
assert result["extras"]["kind"] == "dm_user"
```

**关键不变项（5/5 必绿）**：
- 真 subprocess spawn (`elapsed > 0.2`)
- JSONRPC stdio roundtrip
- 5/5 测试场景全过升级版 mock server
- fault isolation: SIGKILL daemon → 下次 invoke < 2s raise PluginDaemonExitedError
- repeated call: idempotency_key 不同 → 两次成功且 native_id 不同
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/platforms_integration/test_huly_acid_test.py -x -q 2>&1 | tail -10 && wc -l tests/platforms_integration/mock_huly_server.py | awk '{exit ($1 >= 200 ? 0 : 1)}' && grep -q "collab_rpc_handler\|/rpc/" tests/platforms_integration/mock_huly_server.py && grep -q "find_one_handler" tests/platforms_integration/mock_huly_server.py</automated>
  </verify>
  <done>mock_huly_server.py >= 200 行 + login/select_workspace/find_one/tx/collab_rpc 5 endpoints；test_huly_acid_test.py 5/5 全绿（替换后走真 HulyPlugin per-user Channel + collab createContent 路径）；真 subprocess >200ms + fault isolation <2s 不变</done>
</task>

<task type="auto">
  <name>Task 8: Unit tests — 4 capability + concurrent lock + license attribution（6 测试文件）</name>
  <files>backend/tests/platforms/test_huly_plugin_doc.py,backend/tests/platforms/test_huly_plugin_im.py,backend/tests/platforms/test_huly_plugin_identity.py,backend/tests/platforms/test_huly_plugin_tracker_stub.py,backend/tests/platforms/test_huly_plugin_concurrent_lock.py,backend/tests/platforms/test_huly_plugin_license_attribution.py</files>
  <action>
**6 个 unit test 文件**（Task 2 已写部分 doc test）：

### 8.1 `test_huly_plugin_doc.py`（继续 Task 2 写的 TestMarkdownToProseMirror 后追加）

```python
class TestDocCreateDocumentTwoPhaseFlow:
    """二步流程封装测 — mock create_doc + HulyCollabClient + update_doc。"""

    @pytest.fixture
    def fake_pc(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        pc = MagicMock()
        pc.rest.workspace_uuid = "ws-uuid-001"
        pc.rest.workspace_token = "ws-token-xxx"
        pc.ops.create_doc = AsyncMock(return_value="doc-abc12345")
        pc.ops.update_doc = AsyncMock(return_value=None)
        return pc

    @pytest.mark.asyncio
    async def test_create_document_calls_create_doc_then_collab_then_update_doc(self, fake_pc, monkeypatch):
        """Step 1: create_doc(content="") → Step 2: collab createContent → Step 3: update_doc(content=blob)."""
        from unittest.mock import AsyncMock
        import plugins.huly.huly_plugin as hp
        monkeypatch.setattr(hp, "_client", fake_pc)
        # mock HulyCollabClient.create_content 返回固定 blob
        monkeypatch.setattr(hp, "HulyCollabClient", lambda **kw: type("X", (), {
            "create_content": AsyncMock(return_value="doc-abc12345-content-1700000000000")
        })())

        result = await hp.doc_create_document({
            "title": "T", "markdown": "# H1", "collection_id": "ts-001",
        })

        assert fake_pc.ops.create_doc.called
        # Step 1: 第一次 create_doc 入参 content=""（临时占位）
        attrs = fake_pc.ops.create_doc.call_args[0][2]
        assert attrs["content"] == "", "Step 1: doc shell content 必须是空字符串"
        # Step 3: update_doc 入参 content=blob_ref
        update_attrs = fake_pc.ops.update_doc.call_args[0][3]
        assert update_attrs["content"].endswith("-content-1700000000000")
        assert result["plugin_name"] == "huly"
        assert result["native_id"] == "doc-abc12345"
        assert result["extras"]["collab_blob_ref"].endswith("-content-1700000000000")
```

### 8.2 `test_huly_plugin_im.py`（≥ 100 行）

```python
class TestIMSendCardPerUserChannel:
    """send_card with kind='dm_user' → per-user Channel 路径（Pitfall 2 防御）。"""

    @pytest.mark.asyncio
    async def test_dm_user_routes_to_ensure_user_channel_not_direct_message(self, monkeypatch):
        from unittest.mock import AsyncMock
        import plugins.huly.huly_plugin as hp
        fake_pc = type("X", (), {"rest": type("R",(),{"workspace_uuid":"ws-1"})(),
                                   "ops": type("O",(),{"add_collection": AsyncMock()})(),
                                   "bot_account": "bot-uuid"})()
        monkeypatch.setattr(hp, "_client", fake_pc)
        monkeypatch.setattr(hp, "ensure_user_channel", AsyncMock(return_value="ch-abc"))

        result = await hp.im_send_card({
            "recipient": {"kind": "dm_user", "user_id": "alice"},
            "card": {"title": "T", "body_markdown": "hi"},
            "idempotency_key": "k1",
        })

        # 必须调 ensure_user_channel(alice) - per-user Channel 路径
        hp.ensure_user_channel.assert_awaited_once_with(fake_pc, "alice")
        # 必须 add_collection ChatMessage 到 channel_id="ch-abc"
        call_args = fake_pc.ops.add_collection.call_args[0]
        assert call_args[1] == "ch-abc"  # attachedTo = channel_id
        assert result["extras"]["channel_id"] == "ch-abc"
        assert result["extras"]["kind"] == "dm_user"

    @pytest.mark.asyncio
    async def test_dm_user_missing_user_id_raises_value_error(self, monkeypatch):
        import plugins.huly.huly_plugin as hp
        with pytest.raises(ValueError, match="user_id"):
            await hp.im_send_card({
                "recipient": {"kind": "dm_user"},  # 缺 user_id
                "card": {"title": "T", "body_markdown": "x"}, "idempotency_key": "k",
            })

    @pytest.mark.asyncio
    async def test_channel_kind_uses_channel_id_directly(self, monkeypatch):
        # kind='channel' 不调 ensure_user_channel，直接用 channel_id
        ...

    @pytest.mark.asyncio
    async def test_unsupported_recipient_kind_raises(self, monkeypatch):
        # kind='broadcast' → ValueError
        ...
```

### 8.3 `test_huly_plugin_identity.py`（≥ 100 行）

```python
class TestIdentityLRUCache:
    """resolve_person_uuid + LRU cache + double-check lock + workspace 隔离。"""

    def setup_method(self):
        from plugins.huly._internal.identity_lru import configure_cache, invalidate_cache
        configure_cache(maxsize=100, ttl_seconds=60)
        invalidate_cache()  # 清空

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_redundant_find_one(self, monkeypatch):
        from unittest.mock import AsyncMock
        from plugins.huly._internal.identity_lru import resolve_person_uuid
        fake_pc = type("X", (), {"rest": type("R",(),{
            "workspace_uuid":"ws-1",
            "find_one": AsyncMock(side_effect=[
                {"attachedTo": "pid-a"},  # SocialIdentity
                {"personUuid": "puuid-a"},  # Employee mixin
            ]),
        })()})()

        # 第一次 miss → 2 次 find_one
        u1 = await resolve_person_uuid(fake_pc, "alice")
        assert u1 == "puuid-a"
        assert fake_pc.rest.find_one.call_count == 2

        # 第二次 hit → 0 次 find_one
        u2 = await resolve_person_uuid(fake_pc, "alice")
        assert u2 == "puuid-a"
        assert fake_pc.rest.find_one.call_count == 2  # 不增

    @pytest.mark.asyncio
    async def test_workspace_uuid_isolation(self, monkeypatch):
        # ws-1 / ws-2 同名 alice → 不串扰
        ...

    @pytest.mark.asyncio
    async def test_not_found_user_cached_with_sentinel(self, monkeypatch):
        # alice 在 ws 不存在 → cached as __not_found__，二次 hit 不查 DB
        ...

    @pytest.mark.asyncio
    async def test_invalidate_cache_by_username(self):
        # invalidate_cache(username="alice") → ws-1:alice 清除，ws-1:bob 保留
        ...

    @pytest.mark.asyncio
    async def test_double_check_lock_prevents_concurrent_miss_storm(self, monkeypatch):
        # 10 并发同名 alice → find_one 仅调用 2 次（一次 SocialIdentity + 一次 Employee）
        ...
```

### 8.4 `test_huly_plugin_tracker_stub.py`（≥ 30 行）

```python
class TestTrackerStub:
    @pytest.mark.asyncio
    async def test_create_issue_raises_not_implemented(self):
        import plugins.huly.huly_plugin as hp
        with pytest.raises(NotImplementedError, match="v1.1"):
            await hp.tracker_create_issue({"title": "x"})

    @pytest.mark.asyncio
    async def test_update_issue_raises_not_implemented(self):
        import plugins.huly.huly_plugin as hp
        with pytest.raises(NotImplementedError):
            await hp.tracker_update_issue({"issue_id": "x"})

    def test_methods_dispatch_has_tracker_entries(self):
        import plugins.huly.huly_plugin as hp
        assert "tracker.create_issue" in hp.METHODS
        assert "tracker.update_issue" in hp.METHODS
```

### 8.5 `test_huly_plugin_concurrent_lock.py`（≥ 60 行 — Pitfall 10 防御）

```python
class TestConcurrentWsWriteLock:
    @pytest.mark.asyncio
    async def test_3_concurrent_invokes_serialized_by_ws_lock_no_deadlock(self, monkeypatch):
        import asyncio, time
        from unittest.mock import AsyncMock
        import plugins.huly.huly_plugin as hp

        call_log = []
        async def fake_create_doc(*a, **kw):
            call_log.append(("create_doc", time.monotonic()))
            await asyncio.sleep(0.05)  # 模拟 50ms ws 写
            return "doc-mock"

        fake_pc = type("X", (), {
            "rest": type("R",(),{"workspace_uuid":"ws-1","workspace_token":"tok"})(),
            "ops": type("O",(),{"create_doc": fake_create_doc, "update_doc": AsyncMock()})(),
        })()
        monkeypatch.setattr(hp, "_client", fake_pc)
        # mock collab service 不阻塞 lock（lock 只包 ws 写）
        monkeypatch.setattr(hp, "HulyCollabClient", lambda **kw: type("X",(),{
            "create_content": AsyncMock(return_value="blob-ref"),
        })())

        # 3 并发 doc.create_document → 受 _ws_write_lock 串行（每次 ~50ms）
        t0 = time.monotonic()
        results = await asyncio.gather(
            hp.doc_create_document({"title":"a","markdown":"x","collection_id":"ts"}),
            hp.doc_create_document({"title":"b","markdown":"y","collection_id":"ts"}),
            hp.doc_create_document({"title":"c","markdown":"z","collection_id":"ts"}),
        )
        elapsed = time.monotonic() - t0

        # 全成功（无 deadlock）
        assert len(results) == 3
        # 每个 invoke 路径含 2 次 ws 写（Step 1 create_doc + Step 4 update_doc）= 6 次 ws 调用
        # ws_lock 串行 → 6 × 50ms = ~300ms（允许 200-500ms 区间）
        assert 0.2 < elapsed < 1.0, f"3 并发应串行 (~300ms)，实际 {elapsed*1000:.0f}ms"
```

### 8.6 `test_huly_plugin_license_attribution.py`（≥ 30 行 — Pitfall 8 防御）

```python
import pathlib
import pytest

INTERNAL_DIR = pathlib.Path(__file__).parents[3] / "plugins" / "huly" / "_internal"

@pytest.mark.parametrize("path", list(INTERNAL_DIR.glob("*.py")))
def test_all_internal_files_have_inspired_by_attribution(path):
    """Pitfall 8 防御 — 所有 plugins/huly/_internal/*.py 必含 hr 借鉴 attribution。"""
    if path.name == "__init__.py":
        # __init__.py 已有 module-level docstring 含 license
        text = path.read_text(encoding="utf-8")
        assert "Inspired by hr/offboarding-flow" in text or "License: All files Apache-2.0" in text
        return
    text = path.read_text(encoding="utf-8")
    assert "Inspired by hr/offboarding-flow" in text, \
        f"{path.name} 缺 'Inspired by hr/offboarding-flow' attribution（Pitfall 8 防御）"
    assert "Apache-2.0" in text, f"{path.name} 缺 'Apache-2.0' license 声明"

def test_no_chunter_direct_message_in_per_user_channel():
    """Pitfall 2 防御 — per_user_channel.py 永不出现 chunter:DirectMessage 字符串。"""
    src = (INTERNAL_DIR / "per_user_channel.py").read_text()
    assert "chunter:DirectMessage" not in src

def test_no_chunter_direct_message_in_huly_plugin():
    """Pitfall 2 防御 — huly_plugin.py 主文件也永不出现 chunter:DirectMessage。"""
    plugin_file = pathlib.Path(__file__).parents[3] / "plugins" / "huly" / "huly_plugin.py"
    src = plugin_file.read_text()
    assert "chunter:DirectMessage" not in src, "huly_plugin.py 不允许尝试 chunter:DirectMessage（Pitfall 2）"
```

**总测试矩阵**（6 文件覆盖 RESEARCH §Pattern 12 4 维度）：
- 共享 client lifecycle：concurrent_lock 验证 1 daemon 1 client + 4 facet 共享
- per-capability method：doc / im / identity / tracker 各自单测
- fault isolation：tracker stub raise + concurrent_lock 验证 deadlock 不发生
- license + AGPL 防御：license_attribution test
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/platforms/test_huly_plugin_doc.py tests/platforms/test_huly_plugin_im.py tests/platforms/test_huly_plugin_identity.py tests/platforms/test_huly_plugin_tracker_stub.py tests/platforms/test_huly_plugin_concurrent_lock.py tests/platforms/test_huly_plugin_license_attribution.py -x -q 2>&1 | tail -15</automated>
  </verify>
  <done>6 unit test 文件全绿；Pitfall 8 (license attribution) + Pitfall 2 (no chunter:DirectMessage) + Pitfall 10 (concurrent lock no deadlock + 3 并发 ~300ms 串行) + Pitfall 11 (ListItem paragraph wrap) 全 4 个 P0/P1 防御 test 通过</done>
</task>

<task type="auto">
  <name>Task 9: Integration test — 真 daemon spawn + 4 capability 全调用 + mock REST + WS server</name>
  <files>backend/tests/platforms_integration/test_huly_plugin_4cap_integration.py</files>
  <action>
**End-to-end 集成测：真 PlatformDaemonClient spawn `plugins.huly.huly_plugin` 子进程 + mock_huly_server (升级版含 collab WS endpoint) + 4 capability 顺序调用 + 验证单 daemon 复用 1 client：**

```python
"""HulyPlugin 4-capability integration test — 真 daemon + mock server。"""
import asyncio, time, os
import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient


HULY_MODULE = "plugins.huly.huly_plugin"


@pytest.fixture
async def huly_daemon(mock_huly_server, project_root):
    env = {
        "HULY_ACCOUNTS_URL": mock_huly_server,
        "HULY_ADMIN_EMAIL": "admin@demo.local",
        "HULY_ADMIN_PASSWORD": "admin",
        "HULY_WORKSPACE": "mock-ws",
        "HULY_COLLAB_URL": mock_huly_server,
        "HULY_CACHE_TTL_SECONDS": "300",
        "PYTHONPATH": project_root,
    }
    d = PlatformDaemonClient(HULY_MODULE, env=env)
    await d.start()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_doc_create_document_end_to_end_two_phase_flow(huly_daemon):
    """doc.create_document → daemon 内二步流程（create shell + collab createContent + update_doc）→ DocInfo。"""
    result = await huly_daemon.invoke("doc", "create_document",
        title="E2E Test Doc", markdown="# Hello\n\n- a\n- b", collection_id="ts-001")
    assert result["plugin_name"] == "huly"
    assert result["native_id"].startswith("doc-")
    # 二步流程验证 — extras 含 collab_blob_ref
    assert result["extras"]["collab_blob_ref"]
    assert "-content-" in result["extras"]["collab_blob_ref"]


@pytest.mark.asyncio
async def test_im_send_card_dm_user_routes_to_per_user_channel(huly_daemon):
    """im.send_card kind='dm_user' user_id=alice → ensure_user_channel + add_collection。"""
    result = await huly_daemon.invoke("im", "send_card",
        recipient={"kind": "dm_user", "user_id": "alice"},
        card={"title": "Notify", "body_markdown": "Hi alice"},
        idempotency_key="int-001")
    assert result["plugin_name"] == "huly"
    assert result["native_id"].startswith("huly-msg-")
    assert result["extras"]["channel_id"].startswith("ch-")
    assert result["extras"]["kind"] == "dm_user"


@pytest.mark.asyncio
async def test_identity_resolve_user_uses_lru_cache(huly_daemon):
    """identity.resolve_user alice 调 2 次：第二次走 cache（latency 显著下降）。"""
    t0 = time.monotonic()
    u1 = await huly_daemon.invoke("identity", "resolve_user", identifier="alice")
    miss_ms = (time.monotonic() - t0) * 1000

    t1 = time.monotonic()
    u2 = await huly_daemon.invoke("identity", "resolve_user", identifier="alice")
    hit_ms = (time.monotonic() - t1) * 1000

    assert u1 == u2
    assert u1["native_id"] == "puuid-alice"
    # cache hit 通常 < miss / 5（mock server roundtrip 已较快，但 cache 更快）
    # 至少不能比 miss 慢
    assert hit_ms <= miss_ms * 1.2, f"cache hit ({hit_ms:.0f}ms) 比 miss ({miss_ms:.0f}ms) 慢 — cache 未生效?"


@pytest.mark.asyncio
async def test_tracker_create_issue_returns_jsonrpc_method_not_implemented(huly_daemon):
    """tracker stub — invoke 返回 JSONRPC error code -32601 (NotImplementedError)。"""
    from app.agent_builder.platforms.exceptions import PluginInvocationError
    with pytest.raises(PluginInvocationError) as exc:
        await huly_daemon.invoke("tracker", "create_issue", title="x")
    assert "v1.1" in str(exc.value) or "NotImplemented" in str(exc.value)


@pytest.mark.asyncio
async def test_4_capabilities_share_single_daemon_one_client(huly_daemon, mock_huly_server_stats):
    """关键 — 4 capability 顺序调用，daemon 只 login + selectWorkspace 1 次。"""
    # 调 4 个 capability（不同 method）— eager connect 已发生于 main()
    await huly_daemon.invoke("doc", "get_document", doc_id="doc-test-001")  # 触发 find_one
    await huly_daemon.invoke("im", "send_card",
        recipient={"kind":"dm_user","user_id":"alice"},
        card={"title":"T","body_markdown":"x"}, idempotency_key="k2")
    await huly_daemon.invoke("identity", "resolve_user", identifier="bob")
    # tracker raise — OK
    
    # mock_huly_server_stats 是 fixture，记录 login_handler / select_workspace_handler 调用次数
    assert mock_huly_server_stats["login_count"] == 1, "4 capability 应共享 1 个 login"
    assert mock_huly_server_stats["select_workspace_count"] == 1


@pytest.mark.asyncio
async def test_registry_discover_huly_returns_4_facet_plugin(project_root):
    """Registry.discover() 扫到 huly manifest → 4 capability_facets 全注册。"""
    from app.agent_builder.platforms.registry import PlatformPluginRegistry
    reg = PlatformPluginRegistry()
    plugins = reg.discover(os.path.join(project_root, "plugins"))
    huly = next((p for p in plugins if p.manifest.name == "huly"), None)
    assert huly is not None
    # 4 facet 全注册 - 检查 manifest 字段
    facets = getattr(huly.manifest, "capability_facets", None) or huly.manifest.capabilities
    assert set(facets) == {"doc", "im", "identity", "tracker"}
    # facet properties 可访问（不真调，仅 attribute check）
    assert hasattr(huly, "doc") or hasattr(huly, "im")


@pytest.mark.asyncio
async def test_docker_networks_mock_skip_when_no_docker(project_root):
    """sandbox.docker_networks=['huly_huly_net'] 在 PosixResourceSandbox 应 no-op（macOS / 无 docker dev）。"""
    # plan 01 SandboxRunner.spawn_with_limits 加 docker_networks 参数
    # 验证 PosixResourceSandbox 收到非空 docker_networks 仅 warning log，不 raise
    from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox
    s = PosixResourceSandbox()
    # spawn echo cmd + docker_networks=['x'] → 应 no-op，无异常
    proc = await s.spawn_with_limits(
        ["python", "-c", "print('ok')"], cpu_seconds=5, memory_bytes=10*1024*1024,
        docker_networks=["test-net"],
    )
    await proc.wait()
    assert proc.returncode == 0
```

**fixture upgrades**（同 task 改 `backend/tests/platforms_integration/conftest.py`，若 fixture 已在 5.A 建则在原基础上加 mock_huly_server_stats）：

```python
@pytest.fixture
async def mock_huly_server_stats():
    """共享 dict 让 mock server handlers 累计调用次数。"""
    return {"login_count": 0, "select_workspace_count": 0}
```

mock_huly_server.py 的 login_handler / select_workspace_handler 在 increment 这个 dict（Task 7 升级时一并加）。

**关键 DoD**：≥ 200 行，7 个 test 覆盖 4 capability + Registry discover + 单 daemon 1 client 复用 + docker_networks no-op。
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/platforms_integration/test_huly_plugin_4cap_integration.py -x -q 2>&1 | tail -15 && wc -l tests/platforms_integration/test_huly_plugin_4cap_integration.py | awk '{exit ($1 >= 200 ? 0 : 1)}'</automated>
  </verify>
  <done>integration test >= 200 行 + 7 test 全绿：doc.create (二步流程) + im.send_card (per-user Channel) + identity.resolve (LRU cache) + tracker stub (NotImplemented) + 4 capability 共享 1 daemon 1 client + Registry discover 4 facet + docker_networks no-op</done>
</task>

<task type="auto">
  <name>Task 10: 全量回归 + Phase 5.A acid test + Phase 5.B 集成测试 0 regression</name>
  <files>backend/tests/platforms_integration/test_huly_acid_test.py</files>
  <action>
**最终回归验证 — 不写新代码，仅跑全量测试套件确认 0 regression：**

```bash
cd backend && uv run pytest tests/platforms/ tests/platforms_integration/ -x -q --tb=short 2>&1 | tail -30
```

**期望输出**：
- Phase 5.A 271 platforms tests: PASS
- Phase 5.A acid test 5/5: PASS (替换 stub 后路径走真 HulyPlugin per-user Channel)
- Phase 5.B 131 IM regression: PASS (5.B legacy adapter 不变)
- Phase 5.C 新增 6 unit + 1 integration: PASS

**如有 regression**：
1. 5.A platforms test fail → 检查 manifest.yaml 兼容性 (capabilities 字段保留 + capability_facets 新增 — 不互斥)
2. 5.A acid test fail → 检查 mock_huly_server 升级是否破坏原 `/api/v1/chunter/messages` endpoint backward compat
3. 5.B legacy adapter fail → 不应受影响 (LegacyIMProviderAdapter 不调 HulyPlugin daemon)

**手动断言（必加入 acid test 文件作 sanity check）**：

```python
# tests/platforms_integration/test_huly_acid_test.py 末尾加：

@pytest.mark.asyncio
async def test_phase5c_full_regression_acid_5_of_5_still_pass():
    """smoke test — 确认 5/5 acid test 都执行了（pytest 单次 -k filter 收集）。"""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/platforms_integration/test_huly_acid_test.py",
         "-q", "--collect-only", "--no-header"],
        capture_output=True, text=True,
    )
    # 期望至少 5 个 test collected
    assert result.stdout.count("::test_") >= 5, f"acid test 应 >= 5 个，实际 {result.stdout}"
```

**关键 DoD（必绿才允许 plan 标完成）**：
- backend/tests/platforms/ 全绿（含 5.A 原 200+ tests + 5.C 新加 6 unit tests）
- backend/tests/platforms_integration/test_huly_acid_test.py 5/5 PASS（已替换 stub 路径）
- backend/tests/platforms_integration/test_huly_plugin_4cap_integration.py 7/7 PASS
- backend/tests/platforms/test_legacy_im_adapter.py 5.B 131 tests 全绿（regression 防御）
- Phase 5.A acid test fault_isolation < 2s 不变（manifest.yaml 升级不破坏 PlatformDaemonClient lifecycle）
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/platforms/ tests/platforms_integration/ -q --tb=line 2>&1 | tail -20 | grep -E "passed|failed" | head -3</automated>
  </verify>
  <done>全量回归 0 regression：Phase 5.A 271 platforms + 5/5 acid（含替换后真路径）+ Phase 5.B 131 IM + Phase 5.C 6 unit + 7 integration 全绿；test_phase5c_full_regression_acid_5_of_5_still_pass smoke 通过</done>
</task>

</tasks>

<verification>
## Phase-Level Verification

**1. 全量测试套件全绿**（CLAUDE.md §2.2 三层测试）：
```bash
cd backend && uv run pytest tests/platforms/ tests/platforms_integration/ -q
# 期望: ≥ 410 passed (271 platforms 原 + 131 IM regression + 6 5.C unit + 7 5.C integration + 5 acid)
```

**2. Phase 5.A acid test 5/5 替换后仍绿**：
```bash
cd backend && uv run pytest tests/platforms_integration/test_huly_acid_test.py -v
# 期望: 5 passed in 5-15s（含真 subprocess 时间 + JSONRPC roundtrip）
```

**3. license attribution + Pitfall 2/8 防御静态扫**：
```bash
# Pitfall 8: 所有 _internal/*.py 含 attribution
grep -L "Inspired by hr/offboarding-flow" plugins/huly/_internal/*.py | wc -l
# 期望: 0（每文件都有）

# Pitfall 2: per_user_channel + huly_plugin 永不出现 chunter:DirectMessage
grep -l "chunter:DirectMessage" plugins/huly/per_user_channel.py plugins/huly/huly_plugin.py 2>/dev/null | wc -l
# 期望: 0
```

**4. manifest.yaml schema 合规**：
```bash
python -c "import yaml; m=yaml.safe_load(open('plugins/huly/manifest.yaml')); \
  assert set(m['capability_facets']) == {'doc','im','identity','tracker'}; \
  assert 'huly_huly_net' in m['sandbox']['docker_networks']; \
  assert m['identity']['is_source_of_truth'] is True; \
  assert m['doc']['supports_collaborative_edit'] is True"
```

**5. Reading doc 先于代码 commit（CLAUDE.md §2.7 硬性 gate）**：
```bash
git log --reverse --oneline -- 'plugins/huly/**' 'backend/tests/platforms*/test_huly*' \
  | head -2 | awk 'NR==1{print "first_code: " $1} NR==2{exit}'
git log --reverse --oneline -- docs/reading-dify-05c-05-huly-plugin-4cap-2026-05-18.md \
  | head -1 | awk '{print "reading_doc: " $1}'
# 期望: reading_doc commit 日期 早于 first_code commit 日期
```

**6. 文档语言 + 中文 commit 风格（CLAUDE.md §4.2-4.3）**：
- 所有新 .md 文档中文为主
- commit message 中文（feat:/fix:/docs: 前缀英文保留）
</verification>

<success_criteria>
- [x] 1 reading doc 写完 + ≥ 120 行 + 10 借鉴点 + 已 commit（Task 0 硬性 gate）
- [x] manifest.yaml 升级（4 capability_facets + docker_networks + cache_ttl + is_source_of_truth + supports_collaborative_edit）
- [x] huly_plugin.py daemon ≥ 280 行 + 13 method (doc×6 + im×3 + identity×2 + tracker×2) + eager connect + _ws_write_lock
- [x] 4 个 _internal/ 模块 (markdown_to_prosemirror ≥150 / collab_client ≥80 / identity_lru ≥90 / per_user_channel ≥70) + license attribution
- [x] prompts/ai_suggest_mentions_zh.md stub 就位（plan 06 用）
- [x] 6 unit test 文件（doc / im / identity / tracker stub / concurrent_lock / license_attribution）全绿
- [x] 1 integration test (test_huly_plugin_4cap_integration.py ≥ 200 行) 7 test 全绿
- [x] mock_huly_server.py 升级 ≥ 200 行（+ login/select_workspace/find_one/tx/collab_rpc 5 endpoints + backward compat）
- [x] test_huly_acid_test.py 5/5 替换后仍绿（真 HulyPlugin per-user Channel 路径 + fault isolation < 2s）
- [x] Phase 5.A 271 platforms + Phase 5.B 131 IM 0 regression
- [x] Pitfall 1/2/8/10/11 全 P0/P1 防御 test 通过：
  - P1 (Document.content blob ref): doc_create_document 二步流程测验证 Step 1 content=""
  - P2 (DM 静默 reject): grep chunter:DirectMessage = 0 + ensure_user_channel 路径测
  - P8 (AGPL attribution): license_attribution test
  - P10 (concurrent lock no deadlock): 3 并发 ~300ms 串行测
  - P11 (ListItem paragraph wrap): test_bullet_list_items_have_paragraph_wrap
- [x] 二步流程封装在 daemon 内（主进程不感知 collab service URL — 仅传 markdown 或 delta）
- [x] per-user Channel 命名规范 `dm-{username}` 严格遵守（unit test 断言）
- [x] LRU TTL manifest 可覆盖（HULY_CACHE_TTL_SECONDS env 注入 daemon main()）
- [x] AGPL 防御：不复制 hr 源码（每 _internal 文件 attribution 注释 + license test）
- [x] autonomous: true（4 capability bundle 自动验证 — 无 checkpoint）
</success_criteria>

<output>
After completion, create `.planning/phases/05c-doc-capability/05c-05-SUMMARY.md` containing:

1. **Plan facts**: phase / plan / wave / depends_on / actual_minutes / commits 数量
2. **Files created/modified**: 19 个 files (1 reading doc + 1 init + 1 manifest + 1 main + 4 internal + 1 prompt + 6 unit tests + 1 integration test + 2 fixture/acid updates)
3. **Capability matrix**: doc / im / identity / tracker 各 capability 的 method 列表 + 实现方式（real / stub / NotImplemented）
4. **二步流程实测数据**: Task 9 integration test 实测 doc.create_document end-to-end latency（mock server）
5. **Pitfall 防御实测**：
   - Pitfall 1 (Document.content): doc_create_document Step 1 content="" 断言 PASS
   - Pitfall 2 (DM 静默 reject): grep chunter:DirectMessage = 0
   - Pitfall 8 (AGPL): license_attribution test 全文件 PASS
   - Pitfall 10 (concurrent lock): 3 并发 ~300ms 串行 PASS
   - Pitfall 11 (ListItem paragraph wrap): test_bullet_list_items_have_paragraph_wrap PASS
6. **回归数据**：Phase 5.A 271 + 5.B 131 + 5.C 6 unit + 7 integration + 5 acid = 全数 + 期望 vs 实际
7. **Dify 参考点**：指回 reading doc 借鉴点列表（10+）
8. **hr B-full-channel 借鉴点**：指回 reading doc + 标注本 plan 哪些设计借自 hr
9. **License audit**：所有 _internal/*.py 文件 attribution check 输出
10. **Phase 5.D 接口预留点**：identity_lru.invalidate_cache + manifest identity.is_source_of_truth=true + tracker stub（v1.1 接入位置）
11. **Phase 5.C 收官路径**：本 plan 后 Phase 5.C 还剩 plan 06 (ai_suggest_mentions LLM 接入) + plan 07/08 (E2E browser-harness 三 plugin 全跑)
</output>
