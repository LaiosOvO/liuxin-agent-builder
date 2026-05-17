---
phase: 05c-doc-capability
plan: 04
type: execute
wave: 2
depends_on: ["01"]
files_modified:
  - docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md
  - plugins/lark_docs/__init__.py
  - plugins/lark_docs/platform.yaml
  - plugins/lark_docs/lark_docs_plugin.py
  - plugins/lark_docs/_internal/__init__.py
  - plugins/lark_docs/_internal/lark_async_client.py
  - plugins/lark_docs/_internal/markdown_to_lark_block.py
  - plugins/lark_docs/_internal/identity_resolver.py
  - plugins/lark_docs/prompts/ai_suggest_mentions_zh.md
  - tests/platforms/test_lark_docs_plugin.py
  - tests/platforms_integration/test_lark_docs_plugin_integration.py
  - tests/fixtures/__init__.py
  - tests/fixtures/mock_lark_server.py
autonomous: true
requirements:
  - DOC-LARK-01
  - DOC-LARK-02
  - DOC-IDENT-01
must_haves:
  truths:
    - "Dify reading doc(含 Dify 是否有 lark/feishu 调研结论)已 commit（CLAUDE.md §2.7 硬性 gate，必须早于任何代码 commit）"
    - "LarkDocsPlugin 可被 PlatformPluginRegistry discover + spawn 成 daemon 子进程"
    - "LarkDocsPlugin.doc facet 实现 DocCapability Protocol（supports_collaborative_edit=False / supports_comments=True）"
    - "LarkDocsPlugin.identity facet 实现 IdentityCapability Protocol（is_source_of_truth=False，v1 仅 manifest 静态映射）"
    - "markdown → Lark Block 转换：12 关键元素（heading 1-6 / paragraph / bulletList / orderedList / blockquote / code_block / link / em / strong / code / image / hr）unit test 全覆盖（Pitfall 6 防节点名错位）"
    - "Lark Docs 单 batch >1000 block 自动分批（Pitfall 3，留 200 余量按 800 切片，超过 10MB 字符 raise）"
    - "tenant_access_token 由 lark-oapi 1.6.5 内置 cache 自动管理（不自己写 refresh 逻辑）"
    - "lark-oapi 同步 SDK 在 daemon async 上下文用 asyncio.to_thread 包装（沿用 Phase 4 FeishuProvider 模式）"
    - "AllowlistTransport 白名单含全部 Lark 用到的 host:port（open.feishu.cn:443 + passport.feishu.cn:443 + lf-cdn-tos.bytescm.com:443，Pitfall 7）"
    - "单 daemon 共享 lark.Client 实例（doc + identity facet 不各自起 client，Pattern 1）"
    - "Phase 5.A 累积 271 platforms tests + Phase 4 IM 131 tests 0 regression"
  artifacts:
    - path: "docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md"
      provides: "Dify Lark/Feishu 调研结论 + lark-oapi 1.6.5 yanked 原因 + Lark Docs 二段写入文档 + identity 静态映射设计（5 节标准模板）"
      min_lines: 100
    - path: "plugins/lark_docs/platform.yaml"
      provides: "LarkDocsPlugin manifest — capabilities=[doc, identity] + sandbox.network Lark host allowlist + tenant_access_token 缓存声明"
      contains: "capabilities:"
    - path: "plugins/lark_docs/lark_docs_plugin.py"
      provides: "LarkDocsPlugin 双 facet facade：DocCapability + IdentityCapability，共享单 lark.Client 实例"
      exports: ["LarkDocsPlugin"]
    - path: "plugins/lark_docs/_internal/lark_async_client.py"
      provides: "lark-oapi 1.6.5 同步 SDK 的 async 包装（asyncio.to_thread）+ Lark Docs 二段写入 + Pitfall 3 分批"
      exports: ["LarkAsyncClient"]
    - path: "plugins/lark_docs/_internal/markdown_to_lark_block.py"
      provides: "marko AST → Lark Block JSON 转换（12 元素严格映射 _BLOCK_MAP + _MARK_MAP）"
      exports: ["markdown_to_lark_blocks", "_BLOCK_MAP", "_MARK_MAP"]
    - path: "plugins/lark_docs/_internal/identity_resolver.py"
      provides: "username → lark_open_id 解析器（v1 从 manifest config_schema.identity_map 静态读取；5.D 接 HRCapability 反向 sync 才动态）"
      exports: ["IdentityResolver"]
    - path: "tests/platforms/test_lark_docs_plugin.py"
      provides: "Unit test：12 元素 markdown→Lark Block mapping 全覆盖 + identity_resolver lookup + plugin facet routing"
    - path: "tests/platforms_integration/test_lark_docs_plugin_integration.py"
      provides: "集成测试：mock Lark server (respx) + 真 lark-oapi 调用 + 1000 block 分批触发 + tenant_access_token 缓存 verify"
    - path: "tests/fixtures/mock_lark_server.py"
      provides: "respx 模拟 Lark server @127.0.0.1:18089 — 复刻 docx.v1.document.create + blocks.convert + blocks.batch_update + drive.v1.comment.create + tenant_access_token endpoint"
  key_links:
    - from: "plugins/lark_docs/lark_docs_plugin.py"
      to: "backend/app/agent_builder/platforms/capabilities/doc.py (DocCapability Protocol)"
      via: "duck typing — LarkDocsPlugin.doc facet 实现 create_document/replace_document_content/add_comment/get_document 全部签名"
      pattern: "supports_collaborative_edit = False"
    - from: "plugins/lark_docs/lark_docs_plugin.py"
      to: "backend/app/agent_builder/platforms/capabilities/identity.py (IdentityCapability Protocol)"
      via: "duck typing — LarkDocsPlugin.identity facet 实现 resolve_user/list_users（watch_user_changes raise NotImplementedError v1）"
      pattern: "is_source_of_truth = False"
    - from: "plugins/lark_docs/_internal/lark_async_client.py"
      to: "lark_oapi.api.docx.v1 (CreateDocumentRequest + ConvertRequest + CreateDocumentBlockChildrenRequest)"
      via: "asyncio.to_thread 包装同步 lark-oapi SDK 调用"
      pattern: "await asyncio.to_thread\\(self\\._client\\.docx\\.v1\\.document\\."
    - from: "plugins/lark_docs/_internal/markdown_to_lark_block.py"
      to: "marko.Markdown(renderer=ASTRenderer)"
      via: "marko 2.2.2 ASTRenderer 解析 markdown 为 element name=snake_case 树，再 _BLOCK_MAP 映射到 Lark Block type"
      pattern: "_BLOCK_MAP\\["
    - from: "plugins/lark_docs/lark_docs_plugin.py"
      to: "plugins/lark_docs/_internal/identity_resolver.py"
      via: "add_comment 时 mentions: list[UserRef] → identity_resolver.resolve(username) → lark_open_id → <at user_id=\"ou_xxx\"></at> 锚点插入 markdown body"
      pattern: "identity_resolver\\.resolve"
    - from: "plugins/lark_docs/platform.yaml"
      to: "backend/app/agent_builder/platforms/sandbox/runner.py (AllowlistTransport)"
      via: "manifest.sandbox.network 显式列 Lark host:port → AllowlistTransport 启动时读取 → 非白名单 host raise NetworkBlockedError"
      pattern: "open.feishu.cn:443"
---

<objective>
实现 **LarkDocsPlugin** —— Phase 5.C Wave 2 第二个真接入 plugin（与 02 OutlinePlugin + 03 HulyPlugin 并行）。

这是首个 **multi-capability plugin（DocCapability + IdentityCapability）共享单 daemon + 单 lark.Client 实例**的实战案例，验证 Phase 5.A PlatformBundle facet 模式 + Phase 4 FeishuProvider lark-oapi 1.6.5 async 包装模式在 plugin 沙箱环境的可移植性。

Purpose:
1. 国内首选飞书文档协作平台落地 — 验证 markdown → Lark Block JSON 二段写入流程（与 Outline 直接 markdown / Huly CRDT delta 形成三套差异化路径）
2. 验证 multi-capability plugin facet 设计 — doc + identity 共享底层 client/connection（不重复 login，符合 Pattern 1）
3. 复用 Phase 4 FeishuProvider 已验证的 lark-oapi 1.6.5 同步 SDK + asyncio.to_thread 包装模式（不重起，沿用 reading-im-sdk-04-06-feishu §3-§8）
4. 防 Pitfall 3 (10MB/1000 block 限制) + Pitfall 6 (marko AST 节点名错位) + Pitfall 7 (AllowlistTransport host 白名单)

Output:
- 1 reading doc（Task 0 硬性 gate） + 1 manifest + 4 个 _internal 模块（lark_async_client / markdown_to_lark_block / identity_resolver / __init__）+ 1 plugin facade（lark_docs_plugin.py）+ 1 prompt stub + 2 套测试文件（unit + integration）+ mock Lark server fixture
- Phase 5.A 271 + Phase 4 IM 131 测试 0 regression
- DocCapability + IdentityCapability 双 facet 全工作（spawn + invoke + close 闭环）
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
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@docs/reading-im-sdk-04-06-feishu-2026-05-17.md
@backend/app/agent_builder/platforms/capabilities/doc.py
@backend/app/agent_builder/platforms/capabilities/identity.py
@backend/app/agent_builder/platforms/manifest.py
@backend/app/agent_builder/notification/providers/feishu.py
@plugins/huly/platform.yaml

<interfaces>
<!-- LarkDocsPlugin 必须实现的 Protocol 契约（Phase 5.A Plan 02 + 03 已定）-->
<!-- 执行 agent 不需要再去 grep — 这是 ground truth -->

From backend/app/agent_builder/platforms/capabilities/doc.py:
```python
@dataclass(frozen=True)
class DocRef:
    plugin_name: str            # "lark_docs"
    native_id: str              # Lark document_id
    extras: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class DocInfo:
    doc_ref: DocRef
    title: str
    url: str | None = None      # https://xxx.feishu.cn/docx/<id>
    content_markdown: str | None = None  # Lark v1 None（二跳 fetchBlocks 才有）

@dataclass(frozen=True)
class CommentRef:
    plugin_name: str
    native_id: str              # Lark comment_id
    parent_doc_ref: DocRef

@dataclass(frozen=True)
class UserRef:
    plugin_name: str            # "lark_docs"
    native_id: str              # Lark open_id (ou_xxxxx)

@dataclass(frozen=True)
class CRDTDelta:
    format: str                 # 不适用于 Lark — apply_document_delta raise NotImplementedError
    payload: bytes

@runtime_checkable
class DocCapability(Protocol):
    name: str
    supports_collaborative_edit: bool   # LarkDocsPlugin = False
    supports_comments: bool             # LarkDocsPlugin = True

    async def create_document(self, *, title: str, markdown: str,
                                owners: list[UserRef] | None = None) -> DocRef: ...
    async def replace_document_content(self, doc_ref: DocRef, markdown: str) -> None: ...
    async def apply_document_delta(self, doc_ref: DocRef, delta: CRDTDelta) -> None: ...  # raise NotImplementedError
    async def add_comment(self, *, doc_ref: DocRef, body: str,
                            mentions: list[UserRef] | None = None) -> CommentRef: ...
    async def get_document(self, doc_ref: DocRef) -> DocInfo | None: ...
```

From backend/app/agent_builder/platforms/capabilities/identity.py:
```python
@dataclass(frozen=True)
class UserPrincipal:
    plugin_name: str            # "lark_docs"
    native_id: str              # Lark open_id
    canonical_username: str     # 用户配置的用户名 key
    email: str
    display_name: str
    is_active: bool = True
    extras: dict[str, str] = field(default_factory=dict)

@runtime_checkable
class IdentityCapability(Protocol):
    name: str
    is_source_of_truth: bool    # LarkDocsPlugin = False（v1 仅静态映射，5.D 才反向 sync）

    async def list_users(self) -> list[UserPrincipal]: ...
    async def resolve_user(self, identifier: str) -> UserPrincipal | None: ...
    def watch_user_changes(self) -> AsyncIterator[UserChangeEvent]: ...  # raise NotImplementedError（is_source_of_truth=False）
```

From backend/app/agent_builder/platforms/manifest.py:
```python
class PlatformManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 任何 typo 立即 raise
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,31}$")  # "lark_docs"
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    license: str | None = None
    agent_builder_version: str = Field(default=">=1.0")
    runtime: RuntimeConfig
    capabilities: list[Literal["im", "doc", "hr", "identity", "trigger", "tool"]]
    config_schema: dict[str, Any]
    im: CapabilitySpec | None = None
    doc: CapabilitySpec | None = None      # supports_collaborative_edit + supports_comments
    hr: CapabilitySpec | None = None
    identity: CapabilitySpec | None = None  # is_source_of_truth
    sandbox: SandboxConfig | None = None    # cpu_limit / memory / network[] / ...

class SandboxConfig(BaseModel):
    network: list[str]  # ["open.feishu.cn:443", "passport.feishu.cn:443", ...]
    env_allowlist: list[str]  # ["LARK_APP_ID", "LARK_APP_SECRET"]
```

From backend/app/agent_builder/notification/providers/feishu.py (Phase 4 已验证模式):
```python
# lark-oapi 1.6.5 必须 pin（1.6.0/1/2/3 yanked，1.6.4 跳过）
# 用 importlib.metadata.version 取版本（lark.__version__ 不存在 — 陷阱）
# 同步 SDK 在 asyncio 内：asyncio.to_thread(sync_fn, *args)（沿用）
# Builder 模式：lark.Client.builder().app_id(...).app_secret(...).build()
# Response：resp.success() / resp.code / resp.msg / resp.data
```

From plugins/huly/platform.yaml (参考布局):
```yaml
name: huly
version: 1.0.0
runtime:
  type: python
  entry: plugins.huly.huly_plugin
capabilities: [im, doc, hr, identity]
config_schema: {...}
doc:
  supports_collaborative_edit: true  # LarkDocsPlugin 改为 false
  supports_comments: true
identity:
  is_source_of_truth: true  # LarkDocsPlugin 改为 false
sandbox:
  network: ["huly.example.com:443"]  # LarkDocsPlugin 列 Lark host
  env_allowlist: [HULY_ENDPOINT]      # LarkDocsPlugin 列 LARK_APP_ID / LARK_APP_SECRET
```
</interfaces>

<reference>
<!-- Phase 4 lark-oapi 已有现成参考（不重起）-->
backend/app/agent_builder/notification/providers/feishu.py — FeishuProvider 已用 lark-oapi 1.6.5 + asyncio 包装；本 plan 沿用同模式（不重新摸索 SDK）
backend/tests/platforms/test_legacy_im_adapter.py — 已含 lark_oapi 测试样例
docs/reading-im-sdk-04-06-feishu-2026-05-17.md — Phase 4 lark-oapi 阅读笔记（§3 SDK 版本陷阱 + §4 Builder 模式 + §8 async 包装）

<!-- Phase 5.B AllowlistTransport 集成预约 -->
backend/app/agent_builder/platforms/sandbox/runner.py — AllowlistTransport（PLUG-FW-11，5b-03 已 done）— LarkDocsPlugin manifest.sandbox.network 自动喂入

<!-- Dify Lark 调研结论 -->
ls /Users/admin/ai/ref/dify/repo/api/core/tools/builtin_tool/providers/ → audio / code / time / webscraper —— 无 lark / feishu provider
(Dify 走 plugin marketplace 模式，lark 不在 builtin。设计模式可借鉴：Dify plugin manifest YAML schema + capability 声明分组)
</reference>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify Lark/Feishu 调研 + lark-oapi reading doc（CLAUDE.md §2.7 硬性 gate — 必须早于 Task 1+ commit）</name>
  <files>docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md</files>
  <action>
**STOP — 这是后续所有代码 commit 的前置 gate**。先 commit 此文档才允许写代码（CLAUDE.md §2.7）。

**调研三个来源（先 Read / Bash 不写代码）**：

1. **Dify 调研结论**：
   ```bash
   ls /Users/admin/ai/ref/dify/repo/api/core/tools/builtin_tool/providers/ | grep -i "lark\|feishu"
   # 预期返回空（已 grep 过）— 结论：Dify 无 builtin Lark/Feishu provider，走 plugin marketplace 模式
   ```
   - 若返回空，写入 reading doc："Dify 不在 builtin_tool 内置 lark/feishu provider；本 plan 无对应 Dify 模块可借鉴具体 API 实现"
   - 但仍可借鉴 Dify **plugin manifest YAML schema 设计模式**（已在 5a-01/04 reading doc 涵盖，本 doc 引用即可）

2. **Phase 4 reading-im-sdk-04-06-feishu-2026-05-17.md 复盘**（必读，section §3 + §4 + §8）：
   - 用 `Read` 工具完整读取 `docs/reading-im-sdk-04-06-feishu-2026-05-17.md`
   - 摘 §3（SDK 版本陷阱 + importlib.metadata.version）+ §4（Builder 模式 + Response 结构）+ §8（asyncio.to_thread 包装）三段 + 总结 4 个已验证模式

3. **lark-oapi 1.6.5 yanked 原因调研**：
   - 用 `WebFetch` 抓 `https://pypi.org/project/lark-oapi/#history` 查 1.6.0/1/2/3 yanked 原因
   - 若 WebFetch 失败则注明"PyPI yanked 原因未公开披露 — 经验法则：飞书官方 SDK 通常 yanked 因 import 不兼容 / runtime 崩溃 / 协议变更，必须 pin 1.6.5"

4. **Lark Docs API 文档调研**（已在 RESEARCH.md §Pattern 3 + Code Examples 给齐，引用即可）：
   - `https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/document/convert` (markdown → blocks)
   - `https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create` (batch create)
   - `https://open.feishu.cn/document/server-docs/docs/drive-v1/comment/create` (评论 + @人)

**写到 `docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md`**，**完全按 CLAUDE.md §2.7 模板，至少 100 行**（multi-capability 比单 capability 复杂，需 100+）：

```markdown
# Dify + lark-oapi 阅读笔记 — LarkDocsPlugin (Plan 05c-04)

> 日期: 2026-05-18
> 仓库:
>   - Dify https://github.com/langgenius/dify (local /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
>   - lark-oapi https://github.com/larksuite/oapi-sdk-python (PyPI 1.6.5)
> Stars: Dify ~141k / lark-oapi ~700
> Plan: 05c-04 — LarkDocsPlugin (DocCapability + IdentityCapability multi-facet)

## 1. 项目概述（一句话）

LarkDocsPlugin 是 Phase 5.C 首个 multi-capability plugin —— DocCapability + IdentityCapability 共享单 daemon + 单 lark.Client 实例，沿用 Phase 4 FeishuProvider 的 lark-oapi 1.6.5 async 包装模式。

## 2. 技术栈关键技术选择

### 2.1 Dify 调研结论 ❗

- `/Users/admin/ai/ref/dify/repo/api/core/tools/builtin_tool/providers/` 内置 provider 列表：[audio, code, time, webscraper, _positions]
- **结论：Dify 不在 builtin_tool 内置 lark/feishu provider** —— 走 plugin marketplace 模式
- 本 plan **无对应 Dify 具体 API 实现可借鉴**；但仍可借鉴：
  - Dify plugin manifest YAML schema（已在 5a-01/04 reading doc 涵盖）
  - Dify plugin daemon 进程隔离 + JSONRPC envelope 模式（已在 5a-05 reading doc 涵盖）
  - Dify multi-capability bundle 模式（5a-04 PlatformPlugin facet）

### 2.2 lark-oapi 1.6.5（已在 Phase 4 验证）

- CLAUDE.md §3 强制版本锁定（pyproject.toml 已 pin `"lark-oapi==1.6.5"`）
- yanked 调研：1.6.0/1/2/3 已被 PyPI yanked（pip 拒绝安装）；1.6.4 存在但跳过；1.6.5 是当前稳定线
- 同步 client + 内置 tenant_access_token cache + 自动刷新

### 2.3 marko 2.2.2（markdown AST 解析）

- 用 ASTRenderer 拿到 element name=snake_case 树（marko 官方推荐方式）
- _BLOCK_MAP / _MARK_MAP 显式映射（防 Pitfall 6 节点名错位）

## 3. SDK 版本验证（沿用 Phase 4 §3 模式）

陷阱：`lark.__version__` 属性**不存在**（直接访问返回 `'unknown'`）
正确做法：`importlib.metadata.version("lark-oapi")`（沿用 Phase 4 reading doc §3）

```python
from importlib.metadata import PackageNotFoundError, version as _pkg_version

_EXPECTED_LARK_VERSION = "1.6.5"

def _resolve_lark_version() -> str:
    try:
        return _pkg_version("lark-oapi")
    except PackageNotFoundError:
        return "unknown"
```

## 4. 架构要点（核心架构模式 — 简图）

```
   主进程 invoke (doc.create_document / identity.resolve_user)
              ↓ JSONRPC over stdio
   ┌────────────────────────────────────────────────────┐
   │ LarkDocsPlugin daemon (单进程 / 单 lark.Client)    │
   │                                                    │
   │  ┌──────────────────┐    ┌──────────────────────┐ │
   │  │ DocFacade        │    │ IdentityFacade       │ │
   │  │ - create_doc     │    │ - resolve_user       │ │
   │  │ - replace_content│    │ - list_users         │ │
   │  │ - add_comment    │    │ - watch (NotImpl)    │ │
   │  └────────┬─────────┘    └──────────┬───────────┘ │
   │           │  共享                   │              │
   │           ▼                         ▼              │
   │   ┌─────────────────────────────────────────────┐ │
   │   │ LarkAsyncClient (单例)                       │ │
   │   │ - lark.Client (内置 tenant_access_token)    │ │
   │   │ - asyncio.to_thread wrapper                  │ │
   │   └─────────────────────────────────────────────┘ │
   └────────────────────────────────────────────────────┘
              ↓ httpx (经 AllowlistTransport 校验)
   open.feishu.cn:443 / passport.feishu.cn:443 / lf-cdn-tos.bytescm.com:443
```

### 4.1 multi-capability facet 共享 client

参考 Phase 5.A Plan 04 PlatformPlugin facet 模式（plugins/huly/platform.yaml 已声明 4 cap）：
- LarkDocsPlugin 在 daemon 启动期一次性 `lark.Client.builder()...build()`
- doc / identity 两 facade 持有同一 client 引用，**不重复 login / 不重复缓存 token**

### 4.2 Lark Docs 二段写入（RESEARCH §Pattern 3）

```
markdown → blocks/convert API (返回 blocks[] + first_level_block_ids[])
         → batch_create_blocks (一次最多 1000 block，超出分批，Pitfall 3)
```

### 4.3 评论 + @ 人通过 identity_resolver

```
add_comment(body, mentions=[UserRef(plugin_name='lark_docs', native_id='ou_xxx')])
  ↓
identity_resolver: ou_xxx → 已 resolved（IdentityCapability 上游已经查过）
  ↓
body 内插入 <at user_id="ou_xxx"></at> Lark 富文本锚点
  ↓
drive.v1.comment.create
```

## 5. 可借鉴的设计模式

1. **Phase 4 FeishuProvider 同步 SDK + asyncio.to_thread 包装** (backend/app/agent_builder/notification/providers/feishu.py)
   → Plan 05c-04: `plugins/lark_docs/_internal/lark_async_client.py` 沿用同模式
2. **importlib.metadata.version 取版本** (reading-im-sdk-04-06-feishu §3)
   → Plan 05c-04: daemon 启动期校验 `_resolve_lark_version() == "1.6.5"` → 不匹配 log.warning
3. **延迟 client 初始化（@property + module 顶层不构造）** (reading-im-sdk-04-06-feishu §4.1)
   → Plan 05c-04: daemon `_ensure_client` lazy（沿用 RESEARCH §Pattern 1 multi-cap dispatch）
4. **Builder 模式 + Response.success() 校验** (reading-im-sdk-04-06-feishu §4.2)
   → Plan 05c-04: 全部 lark-oapi 调用通过 `resp.success() / resp.code / resp.msg` 检查
5. **Phase 5.A Plan 04 PlatformPlugin facet** (backend/app/agent_builder/platforms/plugin.py)
   → Plan 05c-04: LarkDocsPlugin.doc + .identity 两 property 返回 facade，共享单 daemon
6. **Phase 5.B Plan 05b-03 AllowlistTransport** (backend/app/agent_builder/platforms/sandbox/runner.py)
   → Plan 05c-04: manifest.sandbox.network 显式列 Lark host:port → 启动期 AllowlistTransport 校验
7. **Phase 5.C RESEARCH §Pattern 5 marko AST → 节点映射表**
   → Plan 05c-04: _BLOCK_MAP / _MARK_MAP 改为 Lark Block type（heading.block_type=3,4,5... / paragraph.block_type=2 / bullet=12 / ordered=13 / quote=14 / code=15）

## 6. 与本项目的关系

本 plan 实现 LarkDocsPlugin（DocCapability + IdentityCapability 双 facet）。
- DocCapability 是 Phase 5.C 5 个 success criteria 中的 #2（"LarkDocsProvider plugin + markdown→blocks 转换 + 评论 + @人"）
- IdentityCapability v1 仅静态映射（5.D 才接 HRCapability 反向 sync）
- 与 02 OutlinePlugin（单 cap）+ 03 HulyPlugin（4 cap）形成 multi-cap 完整三档参考

**License attribution**:
- Dify AGPL-3.0 / lark-oapi MIT / 本项目 Apache-2.0
- 不拷贝 Dify 源码（仅借鉴 plugin manifest YAML 设计思路）
- lark-oapi MIT 兼容 Apache-2.0，可作 dependency 直接 import；不拷源码（避免 fork divergence）
```

文档要求：
- 至少 100 行
- 必须含 `## 5. 可借鉴的设计模式` 段，至少 7 个借鉴点（multi-cap 比单 cap 多 2 点）
- 必须含 `Dify 调研结论 ❗` 段（写明 Dify 无 lark provider 的事实）
- 必须含 License attribution 段（Dify AGPL-3.0 + lark-oapi MIT + 本项目 Apache-2.0）
- **不要**贴 Dify 源代码片段（许可证）；可贴 lark-oapi 官方文档片段（公开 SDK）

提交前自检：
```bash
test -f docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && \
wc -l docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md | awk '{exit ($1 >= 100 ? 0 : 1)}' && \
grep -q "AGPL\|Apache-2.0\|MIT" docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && \
grep -q "可借鉴的设计模式" docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && \
grep -q "Dify 调研结论" docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md
```

`git add docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && git commit -m "docs(05c-04): Dify+lark-oapi reading doc for LarkDocsPlugin gate"`
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && wc -l docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md | awk '{exit ($1 >= 100 ? 0 : 1)}' && grep -q "AGPL\|Apache-2.0\|MIT" docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && grep -q "可借鉴的设计模式" docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && grep -q "Dify 调研结论" docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md && git log --oneline -1 docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md | grep -q "."</automated>
  </verify>
  <done>Reading doc ≥ 100 行 + 含 Dify 调研结论 + License attribution + 7 借鉴点；commit hash 可见且早于 Task 1+ commit</done>
</task>

<task type="auto">
  <name>Task 1: LarkDocsPlugin manifest (platform.yaml) + Python package skeleton</name>
  <files>plugins/lark_docs/__init__.py,plugins/lark_docs/_internal/__init__.py,plugins/lark_docs/platform.yaml,plugins/lark_docs/prompts/ai_suggest_mentions_zh.md</files>
  <action>
Reading doc 已 commit ✓（CLAUDE.md §2.7 gate 通过）→ 可以开始写代码。

### 1.1 创建 package skeleton

```bash
mkdir -p plugins/lark_docs/_internal plugins/lark_docs/prompts
```

- `plugins/lark_docs/__init__.py` — 空文件，包标识；加 module docstring：
  ```python
  """LarkDocsPlugin — Phase 5.C Plan 04 飞书文档 multi-capability plugin。

  capabilities:
    - doc (DocCapability, supports_collaborative_edit=False, supports_comments=True)
    - identity (IdentityCapability, is_source_of_truth=False — v1 仅 manifest 静态映射)

  Daemon entry: plugins.lark_docs.lark_docs_plugin (Plan 05c-04)
  Reference: docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md
  """
  ```

- `plugins/lark_docs/_internal/__init__.py` — 空文件 + module docstring：
  ```python
  """LarkDocsPlugin 内部实现（不暴露给主进程）—— Plan 05c-04 Task 2/3/4 落地。"""
  ```

### 1.2 manifest `plugins/lark_docs/platform.yaml`

参考 `plugins/huly/platform.yaml` 布局，**严格按 PlatformManifest Pydantic schema**（extra=forbid，任何 typo 即报错）：

```yaml
# Phase 5.C Plan 04 LarkDocsPlugin manifest — 飞书文档 multi-capability
#
# 设计要点：
# - 声明 2 capability（doc + identity）—— multi-cap 共享单 daemon + 单 lark.Client
# - sandbox.network 显式列 Lark 所有 host:port（Pitfall 7 防 wildcard）
# - env_allowlist 仅放 LARK_APP_ID / LARK_APP_SECRET（Phase 5.B strip-all 防泄漏）
# - identity v1 仅静态映射（config_schema.identity_map.username→lark_open_id）
#
# Reference: docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md

name: lark_docs
version: 1.0.0
description: "飞书文档 multi-capability plugin —— DocCapability + IdentityCapability，沿用 lark-oapi 1.6.5"
license: Apache-2.0
agent_builder_version: ">=1.0"

runtime:
  type: python
  entry: plugins.lark_docs.lark_docs_plugin
  python_version: "3.11"

capabilities:
  - doc
  - identity

config_schema:
  type: object
  required:
    - app_id
    - app_secret
  properties:
    app_id:
      type: string
      description: "飞书应用 App ID（cli_xxx）"
    app_secret:
      type: string
      format: password
      description: "飞书应用 App Secret"
    folder_token:
      type: string
      description: "（可选）默认 folder_token —— create_document 时若不传则用此"
    tenant_access_token_cache_ttl:
      type: integer
      default: 7200
      description: "（注：lark-oapi 1.6.5 内置 cache 自动管理，本字段仅提示性，不被 SDK 直接读取）"
    identity_map:
      type: object
      description: "v1 静态 username → lark_open_id 映射；Phase 5.D HRCapability 反向 sync 后动态化"
      additionalProperties:
        type: string
        pattern: "^ou_[a-z0-9]+$"

doc:
  supports_collaborative_edit: false
  supports_comments: true

identity:
  is_source_of_truth: false

sandbox:
  cpu_limit: "1.0"
  memory: "512Mi"
  network:
    - "open.feishu.cn:443"
    - "passport.feishu.cn:443"
    - "lf-cdn-tos.bytescm.com:443"
  timeout_invoke: 30
  timeout_idle: 300
  use_cgroups: false
  env_allowlist:
    - LARK_APP_ID
    - LARK_APP_SECRET
```

### 1.3 prompt stub `plugins/lark_docs/prompts/ai_suggest_mentions_zh.md`

Plan 06 才接 LLM；本 plan 只放 stub 保留路径（CONTEXT decision 7）：

```markdown
# ai_suggest_mentions 中文 prompt 模板（v1.1 stub — Plan 06 实装）

> 由 LarkDocsPlugin.ai_suggest_mentions 加载并填入 markdown / context
> Plan 05c-04 仅放 stub，让 plugin 目录结构完整；Plan 06 LLM 集成时替换

输入：
- markdown: 文档内容（最多 8K tokens）
- context: 流程上下文（assignee 候选名单 + 部门信息）

输出：
- list[MentionSuggestion]: [{username, reason, confidence_0_1}]
```

### 1.4 提交前自检

```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder
# 1. manifest 可被 Pydantic 校验通过
cd backend && python -c "
from app.agent_builder.platforms.manifest import load_manifest
m = load_manifest('../plugins/lark_docs/platform.yaml')
assert m.name == 'lark_docs'
assert 'doc' in m.capabilities and 'identity' in m.capabilities
assert m.doc.supports_collaborative_edit is False
assert m.doc.supports_comments is True
assert m.identity.is_source_of_truth is False
assert 'open.feishu.cn:443' in m.sandbox.network
assert 'LARK_APP_ID' in m.sandbox.env_allowlist
print('manifest OK')
"
# 2. 包结构存在
test -f ../plugins/lark_docs/__init__.py
test -f ../plugins/lark_docs/_internal/__init__.py
test -f ../plugins/lark_docs/prompts/ai_suggest_mentions_zh.md
```
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.manifest import load_manifest; m = load_manifest('../plugins/lark_docs/platform.yaml'); assert m.name == 'lark_docs' and 'doc' in m.capabilities and 'identity' in m.capabilities and m.doc.supports_collaborative_edit is False and m.identity.is_source_of_truth is False and 'open.feishu.cn:443' in m.sandbox.network and 'LARK_APP_ID' in m.sandbox.env_allowlist; print('OK')" && test -f ../plugins/lark_docs/__init__.py && test -f ../plugins/lark_docs/_internal/__init__.py && test -f ../plugins/lark_docs/prompts/ai_suggest_mentions_zh.md</automated>
  </verify>
  <done>manifest 通过 PlatformManifest Pydantic 校验；name=lark_docs / capabilities=[doc,identity] / 双 cap flag 正确 / Lark 3 host 全列 / env_allowlist 仅 LARK_APP_* / 包目录结构齐全</done>
</task>

<task type="auto">
  <name>Task 2: LarkAsyncClient — lark-oapi 1.6.5 同步 SDK 的 async 包装（Pattern 8 + Pitfall 3 分批）</name>
  <files>plugins/lark_docs/_internal/lark_async_client.py</files>
  <action>
**严格沿用 Phase 4 FeishuProvider 的 lark-oapi 模式**（先 `Read` backend/app/agent_builder/notification/providers/feishu.py 1-150 行，再写代码）。

创建 `plugins/lark_docs/_internal/lark_async_client.py`（约 250 行）：

```python
"""LarkAsyncClient — lark-oapi 1.6.5 同步 SDK 的 async 包装。

设计要点（RESEARCH §Pattern 8 + Pitfall 3）：
- 沿用 Phase 4 FeishuProvider 已验证的 asyncio.to_thread 包装模式
- lark.Client 单例（daemon 启动期构造一次，doc + identity facet 共享）
- tenant_access_token 由 lark-oapi 1.6.5 内置 cache 自动管理（不自己写 refresh）
- 单 batch_create_blocks > 800 block 时自动分批（Pitfall 3：1000 上限留 200 余量）
- 单 markdown > 10MB 时 raise（Pitfall 3：blocks/convert 字符上限）

CLAUDE.md immutability：
- app_id / app_secret 通过 __init__ 注入，运行时不可改
- 调用入参 dict 不修改（建新对象）

Reference:
- backend/app/agent_builder/notification/providers/feishu.py（Phase 4 已验证）
- docs/reading-im-sdk-04-06-feishu-2026-05-17.md §3 + §4 + §8
- docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md §4.2
"""
from __future__ import annotations

import asyncio
import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Any

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    GetDocumentRequest,
)

log = logging.getLogger(__name__)

# ── SDK 版本锁定（CLAUDE.md §3 强制 + reading doc §3）──────────────────────────
_EXPECTED_LARK_VERSION = "1.6.5"

# Lark Docs 单批 block 上限（官方 1000，留 200 余量按 800 切片，Pitfall 3）
_MAX_BLOCKS_PER_BATCH = 800

# Lark Docs convert markdown 字符上限（官方 10,485,760）
_MAX_MARKDOWN_CHARS = 10_485_760


def _resolve_lark_version() -> str:
    """获取已安装 lark-oapi 真实版本（陷阱：lark.__version__ 不存在 — reading doc §3）。"""
    try:
        return _pkg_version("lark-oapi")
    except PackageNotFoundError:
        return "unknown"


class LarkAsyncClient:
    """lark-oapi 1.6.5 同步 SDK 的 async 包装。

    用法（daemon 启动期）：
        client = LarkAsyncClient(app_id=..., app_secret=...)
        doc_id = await client.create_document(title="...")
        blocks_data = await client.convert_markdown(markdown="...")
        await client.create_blocks(document_id=..., blocks=blocks_data["blocks"])
    """

    def __init__(self, *, app_id: str, app_secret: str) -> None:
        version = _resolve_lark_version()
        if version != _EXPECTED_LARK_VERSION:
            log.warning(
                "lark-oapi version mismatch: expected %s, got %s",
                _EXPECTED_LARK_VERSION, version,
            )
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

    @property
    def raw(self) -> lark.Client:
        """暴露原始 client 供 facet 内部调用其他 API（不推荐外部使用）。"""
        return self._client

    # ── Document 二段写入流程 ──────────────────────────────────────────────────

    async def create_document(
        self, *, title: str, folder_token: str | None = None,
    ) -> str:
        """创建空文档（Step 1）→ 返回 document_id。"""
        body_builder = CreateDocumentRequestBody.builder().title(title)
        if folder_token:
            body_builder = body_builder.folder_token(folder_token)
        req = CreateDocumentRequest.builder().request_body(body_builder.build()).build()

        resp = await asyncio.to_thread(self._client.docx.v1.document.create, req)
        if not resp.success():
            raise RuntimeError(
                f"Lark create_document failed: code={resp.code} msg={resp.msg} "
                f"log_id={resp.get_log_id() if hasattr(resp, 'get_log_id') else 'n/a'}"
            )
        return resp.data.document.document_id

    async def convert_markdown(self, *, markdown: str) -> dict[str, Any]:
        """Step 2.a: markdown → Lark Block JSON（含 first_level_block_ids + blocks[]）。

        Pitfall 3 防护：markdown 长度 > 10MB 直接 raise（避免 API 静默截断）。
        """
        if len(markdown) > _MAX_MARKDOWN_CHARS:
            raise ValueError(
                f"markdown 超 Lark convert 字符上限 ({len(markdown)} > {_MAX_MARKDOWN_CHARS}) — "
                f"请用 marko 预处理拆段后多次调 create_blocks"
            )

        # lark-oapi 1.6.5 没有 ConvertRequest 直接类（需用 httpx 走 raw API）— 走 httpx 路径
        # Note: 实测 lark-oapi 1.6.5 不暴露 ConvertRequest（only via raw client.request）；
        #   降级方案：用 client._http.request("POST", "/open-apis/docx/v1/documents/blocks/convert", ...)
        #   实现细节：执行时按 RESEARCH §Code Examples lark_convert_markdown 用 httpx 包装
        from app.agent_builder.platforms.sandbox.runner import make_sandboxed_http_client
        import httpx

        # 取已 cache 的 tenant_access_token（lark-oapi 自动维护）
        token = await asyncio.to_thread(self._refresh_tenant_token)

        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://open.feishu.cn/open-apis/docx/v1/documents/blocks/convert",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"content_type": "markdown", "content": markdown},
            )
            r.raise_for_status()
            body = r.json()
            if body.get("code") != 0:
                raise RuntimeError(
                    f"Lark convert error: code={body.get('code')} msg={body.get('msg')}"
                )
            return body["data"]  # {first_level_block_ids: [...], blocks: [...]}

    async def create_blocks(
        self, *, document_id: str, block_id: str, blocks: list[dict],
        descendants: list[dict] | None = None, index: int = 0,
    ) -> None:
        """Step 2.b: 把转换后的 blocks 批量插入到指定 parent block 下。

        Pitfall 3 防护：blocks 数量 > 800 时自动分批（留 200 余量）。
        分批策略：按 _MAX_BLOCKS_PER_BATCH 切片，index 递增；任一批失败即 raise。
        """
        descendants = descendants if descendants is not None else blocks
        total = len(blocks)
        if total == 0:
            return

        batches = [
            blocks[i:i + _MAX_BLOCKS_PER_BATCH]
            for i in range(0, total, _MAX_BLOCKS_PER_BATCH)
        ]
        for batch_idx, batch in enumerate(batches):
            log.info(
                "lark.create_blocks batch %d/%d size=%d index=%d",
                batch_idx + 1, len(batches), len(batch), index,
            )
            req = (
                CreateDocumentBlockChildrenRequest.builder()
                .document_id(document_id)
                .block_id(block_id)
                .request_body(
                    CreateDocumentBlockChildrenRequestBody.builder()
                    .children(batch)
                    .descendants(descendants if batch_idx == 0 else batch)
                    .index(index)
                    .build()
                )
                .build()
            )
            resp = await asyncio.to_thread(
                self._client.docx.v1.document_block_children.create, req
            )
            if not resp.success():
                raise RuntimeError(
                    f"Lark create_blocks failed (batch {batch_idx + 1}/{len(batches)}): "
                    f"code={resp.code} msg={resp.msg}"
                )
            index += len(batch)

    async def get_document(self, *, document_id: str) -> dict[str, Any] | None:
        """查文档元信息（title / url 等）— 不二跳取 content。"""
        req = GetDocumentRequest.builder().document_id(document_id).build()
        resp = await asyncio.to_thread(self._client.docx.v1.document.get, req)
        if not resp.success():
            if resp.code == 1254005:  # Lark "document not found" code
                return None
            raise RuntimeError(f"Lark get_document failed: code={resp.code} msg={resp.msg}")
        return {"document_id": resp.data.document.document_id,
                  "title": resp.data.document.title,
                  "revision_id": resp.data.document.revision_id}

    # ── Comment ────────────────────────────────────────────────────────────────

    async def create_comment(
        self, *, document_id: str, body_with_mentions: str,
    ) -> str:
        """对文档添加评论（含 <at user_id="ou_xxx"></at> 锚点）。返回 comment_id。"""
        # drive.v1.comment 在 lark-oapi 1.6.5 SDK 中类名可能为 FileCommentCreateRequest
        # 实测时确认具体类；这里走 httpx raw 路径（与 convert_markdown 同模式）
        token = await asyncio.to_thread(self._refresh_tenant_token)
        import httpx

        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{document_id}/comments",
                params={"file_type": "docx"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"content": body_with_mentions},
            )
            r.raise_for_status()
            body = r.json()
            if body.get("code") != 0:
                raise RuntimeError(
                    f"Lark create_comment error: code={body.get('code')} msg={body.get('msg')}"
                )
            return body["data"]["comment_id"]

    # ── tenant_access_token（lark-oapi 内置 cache，不自己写 refresh）──────────

    def _refresh_tenant_token(self) -> str:
        """同步刷新 tenant_access_token（asyncio.to_thread 包装）。

        Note: lark-oapi 1.6.5 内置 cache 自动管理 token；本方法仅取最新 token 值供
        httpx raw 调用使用（lark.Client 本身的 API 调用走 SDK 自带 token 注入）。
        """
        # lark-oapi 内部经由 self._client._config.app_settings 维护 token cache
        # 调用 client.auth.v3.tenant_access_token.internal 触发 SDK 刷新逻辑
        # 实测时确认具体 API；本注释作为实现 hint
        from lark_oapi.api.auth.v3 import (
            InternalTenantAccessTokenRequest,
            InternalTenantAccessTokenRequestBody,
        )
        req = (
            InternalTenantAccessTokenRequest.builder()
            .request_body(
                InternalTenantAccessTokenRequestBody.builder()
                .app_id(self._client._config.app_id)
                .app_secret(self._client._config.app_secret)
                .build()
            )
            .build()
        )
        resp = self._client.auth.v3.tenant_access_token.internal(req)
        if not resp.success():
            raise RuntimeError(
                f"Lark tenant_access_token refresh failed: code={resp.code} msg={resp.msg}"
            )
        # Response body 形如 {"code": 0, "msg": "ok", "tenant_access_token": "t-...", "expire": 7200}
        # SDK Response 类不暴露 token 字段需走 raw_response.raw.content (实测时调整)
        import json
        raw = json.loads(resp.raw.content) if hasattr(resp, "raw") else {}
        return raw.get("tenant_access_token", "")
```

注：
- 代码内含 4 个"实测时确认具体 API"注释 —— 执行 agent 应该实际 import 验证 + 调整（Phase 4 FeishuProvider 已验证 lark-oapi 类名约定，沿用即可）
- `_refresh_tenant_token` 是 fallback 路径（lark-oapi 内置 cache 一般够用；httpx raw 调用必须显式 token 时才需）
- AllowlistTransport 集成留 daemon 启动期：`make_sandboxed_http_client` 包 httpx —— 本文件先用裸 httpx，Plan 集成测试时确认

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && python -c "
import sys
sys.path.insert(0, '..')
from plugins.lark_docs._internal.lark_async_client import LarkAsyncClient, _resolve_lark_version, _EXPECTED_LARK_VERSION, _MAX_BLOCKS_PER_BATCH, _MAX_MARKDOWN_CHARS
assert _EXPECTED_LARK_VERSION == '1.6.5'
assert _MAX_BLOCKS_PER_BATCH == 800
assert _MAX_MARKDOWN_CHARS == 10485760
print('imports OK, version =', _resolve_lark_version())
"</automated>
  </verify>
<done>LarkAsyncClient class 可 import；版本校验逻辑就位；常量正确（800 block 分批阈值 + 10MB 字符上限）；构造器接受 app_id+app_secret 注入</done>
</task>

<task type="auto">
  <name>Task 3: markdown_to_lark_block — marko AST → Lark Block 严格 12 元素映射（Pitfall 6 防错位）</name>
  <files>plugins/lark_docs/_internal/markdown_to_lark_block.py</files>
  <action>
**关键防 Pitfall 6**：marko AST element name（snake_case，如 `strong_emphasis` / `code_span`）≠ Lark Block type（int 枚举 + 嵌套 dict）。**必须显式映射表，每个 element 在 unit test 全覆盖**。

Lark Block type 枚举参考飞书官方（已在 reading doc §4.2 引用）：
- `1` page（document root，无需创建）
- `2` text/paragraph
- `3` heading1, `4` heading2, `5` heading3, `6` heading4, `7` heading5, `8` heading6（heading 拆 6 type）
- `12` bullet
- `13` ordered
- `14` quote
- `15` code
- `19` divider (horizontal rule)
- `27` image（v1 不实装，留 stub）

创建 `plugins/lark_docs/_internal/markdown_to_lark_block.py`（约 250 行）：

```python
"""markdown_to_lark_block — marko AST → Lark Block JSON 转换。

设计要点（RESEARCH §Pattern 5 + Pitfall 6）：
- 用 marko 2.2.2 ASTRenderer 得到 element name=snake_case AST 树
- _BLOCK_MAP 显式映射 marko element → Lark block_type（int 枚举）
- _MARK_MAP 显式映射 marko inline element → Lark text_run style
- 12 元素 unit test 全覆盖（heading 1-6 / paragraph / bullet / ordered / blockquote /
  code_block / link / em / strong / code / image / hr）—— 防 silent fallback

⚠ Pitfall 6 防护：
  - marko AST 用 `strong_emphasis` / `code_span` / `code_block` 命名（CommonMark 风格）
  - Lark Block 用 int block_type；text_run 用 text_element_style.bold/italic/inline_code 嵌套结构
  - 直接复制名字会让 Lark 静默接受但 UI 显示 raw markup —— 必须严格映射

CLAUDE.md immutability：
- 所有 mapping 返回新 dict（不修改输入 AST）
- _BLOCK_MAP / _MARK_MAP 是 module 顶层常量，frozen

Reference:
- RESEARCH §Pattern 5 + Code Examples marko ASTRenderer 用法
- docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md §4.2 + §5.7
- Lark Block type 枚举：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/data-structure/block
"""
from __future__ import annotations

from typing import Any

import marko
from marko import Markdown
from marko.ast_renderer import ASTRenderer

# ── 公开常量 ───────────────────────────────────────────────────────────────────

# marko AST element name → Lark Block type (int)
# Pitfall 6：完整映射，prevent silent fallback
_BLOCK_MAP: dict[str, int | None] = {
    "document": 1,         # page root — 不创建 block，仅作根
    "heading": None,       # 特殊处理（按 level 1-6 映射到 3-8）
    "paragraph": 2,        # text block
    "list": None,          # 特殊处理（ordered=13 / bullet=12）
    "list_item": 2,        # list_item 内含 paragraph → 直接用 text
    "code_block": 15,      # code block
    "block_quote": 14,     # quote block
    "thematic_break": 19,  # divider (---)
    "image": 27,           # image block（v1 stub，不上传素材）
    "blank_line": None,    # 跳过
    "html_block": None,    # 跳过（v1 不支持原始 HTML）
    "link_ref_def": None,  # 跳过
}

# heading level (1-6) → Lark block_type (3-8)
_HEADING_LEVEL_TO_BLOCK_TYPE: dict[int, int] = {
    1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8,
}

# marko inline element → Lark text_element_style flag
# Pitfall 6：strong_emphasis → bold，code_span → inline_code，不直接复制名字
_MARK_MAP: dict[str, str] = {
    "emphasis": "italic",          # *italic* / _italic_
    "strong_emphasis": "bold",     # **bold** / __bold__
    "code_span": "inline_code",    # `code`
    "link": "link",                # [text](url) — 特殊处理 attrs.href
    "image": "image",              # 不在 inline 处理（image 是 block）
}

# ── 公开 API ───────────────────────────────────────────────────────────────────

_MARKDOWN = Markdown(renderer=ASTRenderer)


def markdown_to_lark_blocks(markdown_text: str) -> list[dict[str, Any]]:
    """Markdown → Lark Block JSON list（去掉 document 根，返回 children）。

    Returns:
        list of block dict, each shape:
          {"block_type": <int>, "<type_name>": {<type-specific payload>}}
        可直接传给 CreateDocumentBlockChildrenRequest.children
    """
    raw_ast = _MARKDOWN.convert(markdown_text)
    return _convert_children(raw_ast.get("children", []))


def _convert_children(children: list[dict]) -> list[dict[str, Any]]:
    """递归转换 children 列表为 Lark Block list（过滤 None）。"""
    out: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        elem = child.get("element")
        # heading / list 特殊处理
        if elem == "heading":
            out.append(_convert_heading(child))
        elif elem == "list":
            out.extend(_convert_list(child))
        elif elem == "paragraph":
            out.append(_convert_paragraph(child))
        elif elem == "code_block":
            out.append(_convert_code_block(child))
        elif elem == "block_quote":
            out.append(_convert_blockquote(child))
        elif elem == "thematic_break":
            out.append({"block_type": 19, "divider": {}})
        elif elem == "image":
            # v1 stub — image 需 3 步上传素材，此处仅占位（reference RESEARCH §Pattern 3 limitations）
            out.append({"block_type": 27, "image": {"token": "PLACEHOLDER_IMAGE_TOKEN_NOT_UPLOADED"}})
        elif elem == "blank_line" or elem in ("html_block", "link_ref_def"):
            continue  # skip
        else:
            # Pitfall 6：未识别 element 降级为 paragraph + raw text（不 silent drop）
            out.append({
                "block_type": 2,
                "text": {
                    "elements": [{"text_run": {"content": _flatten_text(child),
                                                  "text_element_style": {}}}],
                    "style": {},
                },
            })
    return out


def _convert_heading(node: dict) -> dict[str, Any]:
    """heading level 1-6 → Lark block_type 3-8。"""
    level = node.get("level", 1)
    if not 1 <= level <= 6:
        level = 6  # clamp
    block_type = _HEADING_LEVEL_TO_BLOCK_TYPE[level]
    type_name = f"heading{level}"
    return {
        "block_type": block_type,
        type_name: {
            "elements": _convert_inline_elements(node.get("children", [])),
            "style": {},
        },
    }


def _convert_paragraph(node: dict) -> dict[str, Any]:
    """paragraph → block_type=2（text）。"""
    return {
        "block_type": 2,
        "text": {
            "elements": _convert_inline_elements(node.get("children", [])),
            "style": {},
        },
    }


def _convert_list(node: dict) -> list[dict[str, Any]]:
    """list → block_type 12 (bullet) / 13 (ordered)，每 list_item 一 block。"""
    is_ordered = node.get("ordered", False)
    block_type = 13 if is_ordered else 12
    type_name = "ordered" if is_ordered else "bullet"
    out: list[dict[str, Any]] = []
    for item in node.get("children", []):
        if not isinstance(item, dict) or item.get("element") != "list_item":
            continue
        # list_item children 是 block-level；扁平化拿第一个 paragraph 的 inline
        para_inline: list[dict] = []
        for c in item.get("children", []):
            if isinstance(c, dict) and c.get("element") == "paragraph":
                para_inline = c.get("children", [])
                break
        out.append({
            "block_type": block_type,
            type_name: {
                "elements": _convert_inline_elements(para_inline),
                "style": {},
            },
        })
    return out


def _convert_code_block(node: dict) -> dict[str, Any]:
    """code_block → block_type=15（含 language）。"""
    language = node.get("lang", "") or "plain"
    text = _flatten_text(node)
    return {
        "block_type": 15,
        "code": {
            "elements": [{"text_run": {"content": text, "text_element_style": {}}}],
            "style": {"language": _map_lang_to_lark(language), "wrap": True},
        },
    }


def _convert_blockquote(node: dict) -> dict[str, Any]:
    """block_quote → block_type=14。"""
    inline: list[dict] = []
    for c in node.get("children", []):
        if isinstance(c, dict) and c.get("element") == "paragraph":
            inline.extend(c.get("children", []))
    return {
        "block_type": 14,
        "quote": {
            "elements": _convert_inline_elements(inline),
            "style": {},
        },
    }


def _convert_inline_elements(children: list) -> list[dict[str, Any]]:
    """Inline element list → Lark text_run list（含 marks）。"""
    out: list[dict[str, Any]] = []
    for c in children:
        if isinstance(c, str):
            out.append({"text_run": {"content": c, "text_element_style": {}}})
        elif isinstance(c, dict):
            elem = c.get("element")
            text = _flatten_text(c)
            style: dict[str, Any] = {}
            if elem in _MARK_MAP:
                mark_kind = _MARK_MAP[elem]
                if mark_kind in ("bold", "italic", "inline_code"):
                    style[mark_kind] = True
                elif mark_kind == "link":
                    style["link"] = {"url": _url_quote(c.get("dest", ""))}
                # image inline 不在此处理
            out.append({"text_run": {"content": text, "text_element_style": style}})
    return out


def _flatten_text(node: Any) -> str:
    """递归收集所有 raw_text，拼成字符串（Pitfall 6 fallback 用）。"""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        children = node.get("children")
        if isinstance(children, str):
            return children  # raw_text element 的 children 直接是 str
        if isinstance(children, list):
            return "".join(_flatten_text(c) for c in children)
    return ""


def _map_lang_to_lark(lang: str) -> int:
    """markdown 代码块 language → Lark code language enum。

    Lark 官方 enum：1=PlainText / 2=ABAP / ... / 28=Python / 30=Shell / ...
    v1 仅映射 5 个常用语言；其余 fallback 到 1 (PlainText)。
    """
    return {
        "": 1, "plain": 1, "text": 1,
        "python": 28, "py": 28,
        "javascript": 19, "js": 19,
        "typescript": 67, "ts": 67,
        "shell": 30, "bash": 30, "sh": 30,
        "json": 18,
        "yaml": 64, "yml": 64,
    }.get(lang.lower(), 1)


def _url_quote(url: str) -> str:
    """URL encode for Lark link.url（Lark 要求 URI-encoded）。"""
    import urllib.parse
    return urllib.parse.quote(url, safe=":/?&=#%")
```

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && python -c "
import sys; sys.path.insert(0, '..')
from plugins.lark_docs._internal.markdown_to_lark_block import (
    markdown_to_lark_blocks, _BLOCK_MAP, _MARK_MAP, _HEADING_LEVEL_TO_BLOCK_TYPE
)
# 单 quick smoke：H1 + paragraph + bullet
blocks = markdown_to_lark_blocks('# Hello\n\nworld\n\n- a\n- b\n')
assert len(blocks) >= 3, f'expected >=3 blocks, got {len(blocks)}: {blocks}'
assert blocks[0]['block_type'] == 3, f'first should be heading1=3, got {blocks[0]}'
assert blocks[1]['block_type'] == 2, f'second should be text=2, got {blocks[1]}'
assert blocks[2]['block_type'] == 12, f'third should be bullet=12, got {blocks[2]}'
assert _BLOCK_MAP['code_block'] == 15
assert _MARK_MAP['strong_emphasis'] == 'bold'
assert _MARK_MAP['code_span'] == 'inline_code'
assert _HEADING_LEVEL_TO_BLOCK_TYPE[6] == 8
print('smoke OK')
"</automated>
  </verify>
  <done>markdown_to_lark_blocks 可导入 + 基础 smoke（H1 + paragraph + bullet）通过 + _BLOCK_MAP/_MARK_MAP/_HEADING_LEVEL_TO_BLOCK_TYPE 三个映射表常量正确（heading 1-6→3-8 / strong_emphasis→bold / code_span→inline_code）</done>
</task>

<task type="auto">
  <name>Task 4: identity_resolver — username → lark_open_id 静态映射（v1 从 manifest config 读）</name>
  <files>plugins/lark_docs/_internal/identity_resolver.py</files>
  <action>
v1 只做静态映射（CONTEXT decision 7：5.D 才接 HRCapability 反向 sync）。

创建 `plugins/lark_docs/_internal/identity_resolver.py`（约 100 行）：

```python
"""identity_resolver — username → lark_open_id 静态映射器。

设计要点（CONTEXT.md decision 7）：
- v1 仅从 manifest config_schema.identity_map 静态读取（YAML 配置）
- Phase 5.D 接 HRCapability 反向 sync 时改为动态查 飞书 Contact API（资源密集）+ LRU cache
- v1 失败 fallback：返回 None（fail-quiet，不 raise）— 让上层 add_comment 决定是否跳过 @

CLAUDE.md immutability：
- IdentityResolver 构造期 frozen identity_map dict（不接受运行时 mutate）
- resolve() 不修改内部 state（pure function）

Reference:
- docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md §4.3
- backend/app/agent_builder/platforms/capabilities/identity.py
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Mapping

log = logging.getLogger(__name__)

# Lark open_id 格式：ou_ 开头 + 32 hex chars（实际 SDK 用 24-32 chars，pattern 兼容）
_LARK_OPEN_ID_PATTERN = re.compile(r"^ou_[a-z0-9]+$")


@dataclass(frozen=True)
class ResolvedUser:
    """username 解析后的用户信息（v1 仅 open_id；5.D 加 email / display_name）。"""

    username: str
    lark_open_id: str
    display_name: str = ""  # v1 留空


class IdentityResolver:
    """username → lark_open_id 静态映射器。

    用法（daemon 启动期）：
        resolver = IdentityResolver(identity_map={"alice": "ou_abc...", "bob": "ou_def..."})
        user = resolver.resolve("alice")  # ResolvedUser(username="alice", lark_open_id="ou_abc...")
        user = resolver.resolve("unknown")  # None (fail-quiet)
    """

    def __init__(self, identity_map: Mapping[str, str] | None = None) -> None:
        """Construct from manifest config_schema.identity_map。

        Args:
            identity_map: dict[username, lark_open_id]; 空 / None 时 resolver 永远返回 None
                          （日志 warn 一次便于运维定位 manifest 配置遗漏）
        """
        if identity_map is None:
            identity_map = {}
        # 校验 + 规范化（小写 username key，校验 open_id 格式）
        normalized: dict[str, str] = {}
        for raw_username, raw_open_id in identity_map.items():
            username = raw_username.strip().lower()
            open_id = raw_open_id.strip()
            if not _LARK_OPEN_ID_PATTERN.match(open_id):
                log.warning(
                    "IdentityResolver: skipping invalid lark_open_id for username=%r: %r",
                    username, open_id,
                )
                continue
            normalized[username] = open_id

        # frozen via private name + property
        self._map = normalized
        if not self._map:
            log.warning(
                "IdentityResolver: identity_map is EMPTY — add_comment with mentions 将永远跳过 @"
                " (CONTEXT.md decision 7：Phase 5.D HRCapability 反向 sync 才动态化)"
            )

    def resolve(self, username: str) -> ResolvedUser | None:
        """username → ResolvedUser（含 lark_open_id），未找到返回 None（fail-quiet）。"""
        if not username:
            return None
        key = username.strip().lower()
        open_id = self._map.get(key)
        if open_id is None:
            return None
        return ResolvedUser(username=key, lark_open_id=open_id)

    def list_all(self) -> list[ResolvedUser]:
        """返回所有已知 user（IdentityCapability.list_users 用）。"""
        return [
            ResolvedUser(username=u, lark_open_id=oid)
            for u, oid in self._map.items()
        ]

    @property
    def size(self) -> int:
        """已 cache user 数（debug + test 用）。"""
        return len(self._map)
```

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && python -c "
import sys; sys.path.insert(0, '..')
from plugins.lark_docs._internal.identity_resolver import IdentityResolver, ResolvedUser
r = IdentityResolver({'Alice': 'ou_abc123', 'BOB': 'ou_def456', 'malformed': 'bad-id'})
assert r.size == 2  # malformed dropped
assert r.resolve('alice').lark_open_id == 'ou_abc123'
assert r.resolve('ALICE').lark_open_id == 'ou_abc123'
assert r.resolve('bob').lark_open_id == 'ou_def456'
assert r.resolve('unknown') is None
assert r.resolve('') is None
empty = IdentityResolver({})
assert empty.resolve('x') is None
print('resolver OK')
"</automated>
  </verify>
  <done>IdentityResolver class 可 import；构造期 dropping invalid open_id（malformed 不入 map）；resolve case-insensitive；未找到/空 input/空 map → None（fail-quiet）；size property 正确</done>
</task>

<task type="auto">
  <name>Task 5: LarkDocsPlugin — 双 facet facade（DocCapability + IdentityCapability 共享单 daemon + 单 lark.Client）</name>
  <files>plugins/lark_docs/lark_docs_plugin.py</files>
  <action>
**关键设计**（RESEARCH §Pattern 1 multi-cap dispatch + 5.A Plan 04 facet 模式）：
- 单 daemon process，lazy 构造**一个** LarkAsyncClient
- doc + identity 两 facet 持有同一 client 引用（不重复 login）
- METHODS dict 路由 `doc.create_document` / `identity.resolve_user` 等到对应 handler

创建 `plugins/lark_docs/lark_docs_plugin.py`（约 250 行）：

```python
"""LarkDocsPlugin — Phase 5.C Plan 04 飞书文档 multi-capability plugin daemon。

capabilities:
- DocCapability (supports_collaborative_edit=False, supports_comments=True)
- IdentityCapability (is_source_of_truth=False — v1 静态映射)

设计要点（RESEARCH §Pattern 1 + 5.A Plan 04 facet）：
- 单 daemon 进程 + 单 lark.Client (LarkAsyncClient 单例 lazy 构造)
- doc + identity 两 facade 持同一 client 引用 (不重复 login)
- METHODS dict 路由 `doc.<method>` / `identity.<method>` 到 handler
- apply_document_delta raise NotImplementedError (Lark 不支持 CRDT)
- watch_user_changes raise NotImplementedError (is_source_of_truth=False)

CLAUDE.md immutability：
- 凭据 app_id / app_secret 通过 env (manifest.sandbox.env_allowlist) 注入，运行时不可改
- 所有 capability 入参 dataclass frozen=True (DocRef / UserRef / CRDTDelta)

Reference:
- docs/reading-dify-05c-04-lark-docs-plugin-2026-05-18.md §4.1 (facet) + §5
- RESEARCH §Pattern 1 (multi-cap dispatch) + §Pattern 3 (Lark 二段写入) + §Pattern 8 (async 包装)
- backend/app/agent_builder/platforms/capabilities/doc.py + identity.py (Protocol)
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict
from typing import Any

from ._internal.identity_resolver import IdentityResolver
from ._internal.lark_async_client import LarkAsyncClient
from ._internal.markdown_to_lark_block import markdown_to_lark_blocks

log = logging.getLogger(__name__)

# ── 模块级共享 client (daemon 进程单例 - lazy 构造保证)──────────────────────────
_client: LarkAsyncClient | None = None
_resolver: IdentityResolver | None = None
_client_lock: asyncio.Lock | None = None  # lazy 初始化（避免 import 时无 loop）


async def _ensure_client() -> tuple[LarkAsyncClient, IdentityResolver]:
    """daemon 启动后首次 invoke 时建立 Lark 连接 + 加载 identity_map。

    Returns:
        (LarkAsyncClient, IdentityResolver) - 双 facet 共享
    """
    global _client, _resolver, _client_lock
    if _client is not None and _resolver is not None:
        return _client, _resolver

    if _client_lock is None:
        _client_lock = asyncio.Lock()

    async with _client_lock:
        if _client is not None and _resolver is not None:
            return _client, _resolver

        app_id = os.environ.get("LARK_APP_ID")
        app_secret = os.environ.get("LARK_APP_SECRET")
        if not app_id or not app_secret:
            raise RuntimeError(
                "LarkDocsPlugin daemon: LARK_APP_ID / LARK_APP_SECRET env 未设置 "
                "(应通过 workspace_plugin_installations.credentials_json + sandbox.env_allowlist 注入)"
            )

        _client = LarkAsyncClient(app_id=app_id, app_secret=app_secret)

        # identity_map 从 plugin config 读 (主进程通过 daemon stdio JSONRPC 推送 setConfig
        # method, 但 Phase 5.A daemon_client 暂未实现 setConfig - v1 从 env 读 JSON 字符串)
        import json as _json
        identity_map_raw = os.environ.get("LARK_IDENTITY_MAP_JSON", "{}")
        try:
            identity_map = _json.loads(identity_map_raw)
        except _json.JSONDecodeError:
            log.exception("LarkDocsPlugin: LARK_IDENTITY_MAP_JSON 不是合法 JSON, fallback empty map")
            identity_map = {}
        _resolver = IdentityResolver(identity_map=identity_map)

        log.info(
            "LarkDocsPlugin client ready: lark_app_id=%s identity_map_size=%d",
            app_id, _resolver.size,
        )
        return _client, _resolver


# ── DocCapability handlers ─────────────────────────────────────────────────────


async def doc_create_document(params: dict) -> dict:
    """params: {title: str, markdown: str, owners: list[UserRef] | None, folder_token: str | None}"""
    client, _ = await _ensure_client()
    title = params["title"]
    markdown = params.get("markdown", "")
    folder_token = params.get("folder_token") or os.environ.get("LARK_DEFAULT_FOLDER_TOKEN")

    # Step 1: 创 doc shell
    document_id = await client.create_document(title=title, folder_token=folder_token)

    # Step 2: markdown → blocks → batch insert
    if markdown.strip():
        convert_data = await client.convert_markdown(markdown=markdown)
        blocks = convert_data.get("blocks", [])
        if blocks:
            # root block_id == document_id (Lark 约定)
            await client.create_blocks(
                document_id=document_id, block_id=document_id, blocks=blocks,
            )

    return {
        "doc_ref": {
            "plugin_name": "lark_docs",
            "native_id": document_id,
            "extras": {},
        },
    }


async def doc_replace_document_content(params: dict) -> dict:
    """params: {doc_ref: DocRef, markdown: str}

    Lark Docs 没有 "替换全部 children" 一步 API；策略：
    1. 用 marko → blocks
    2. 调 batch insert (留 v1 简化：仅 append；真正 replace 留 v1.1 用 batch_update 删旧 block)
    """
    client, _ = await _ensure_client()
    doc_ref = params["doc_ref"]
    document_id = doc_ref["native_id"]
    markdown = params.get("markdown", "")

    # 用项目内置 markdown_to_lark_blocks（不走 Lark convert API，避免 round-trip）
    blocks = markdown_to_lark_blocks(markdown)
    if blocks:
        await client.create_blocks(
            document_id=document_id, block_id=document_id, blocks=blocks,
        )
    return {"replaced": True, "block_count": len(blocks)}


async def doc_apply_document_delta(params: dict) -> dict:
    """Lark 不支持 CRDT delta — 双路径 cap flag (supports_collaborative_edit=False)。"""
    raise NotImplementedError(
        "LarkDocsPlugin.apply_document_delta 不支持 — Lark Docs 不是 CRDT；"
        "用 replace_document_content 走全量替换"
    )


async def doc_add_comment(params: dict) -> dict:
    """params: {doc_ref: DocRef, body: str, mentions: list[UserRef] | None}

    mentions UserRef 的 native_id 已经是 lark_open_id（上游 identity facet 已 resolve）。
    body 内自动插入 <at user_id="ou_xxx"></at> Lark 富文本锚点。
    """
    client, resolver = await _ensure_client()
    doc_ref = params["doc_ref"]
    document_id = doc_ref["native_id"]
    body = params["body"]
    mentions = params.get("mentions") or []

    # 把 mentions 拼到 body 头部（Lark @ 语法）
    if mentions:
        at_prefix = " ".join(
            f'<at user_id="{m["native_id"]}"></at>'
            for m in mentions if m.get("native_id", "").startswith("ou_")
        )
        body = f"{at_prefix} {body}".strip() if at_prefix else body

    comment_id = await client.create_comment(document_id=document_id, body_with_mentions=body)
    return {
        "comment_ref": {
            "plugin_name": "lark_docs",
            "native_id": comment_id,
            "parent_doc_ref": doc_ref,
        },
    }


async def doc_get_document(params: dict) -> dict:
    """params: {doc_ref: DocRef} → DocInfo (content_markdown=None - Lark v1 不二跳 fetch blocks)。"""
    client, _ = await _ensure_client()
    doc_ref = params["doc_ref"]
    document_id = doc_ref["native_id"]

    info = await client.get_document(document_id=document_id)
    if info is None:
        return {"doc_info": None}
    return {
        "doc_info": {
            "doc_ref": doc_ref,
            "title": info["title"],
            "url": f"https://feishu.cn/docx/{document_id}",  # Lark 默认域；自建集成时主进程换
            "content_markdown": None,  # Lark v1 不二跳 (avoid N+1)
        },
    }


# ── IdentityCapability handlers ────────────────────────────────────────────────


async def identity_list_users(params: dict) -> dict:
    """v1 仅返回 manifest config 中静态映射的用户。"""
    _, resolver = await _ensure_client()
    users = [
        {
            "plugin_name": "lark_docs",
            "native_id": u.lark_open_id,
            "canonical_username": u.username,
            "email": f"{u.username}@unknown.example",  # v1 不查 Contact API
            "display_name": u.display_name or u.username,
            "is_active": True,
            "extras": {},
        }
        for u in resolver.list_all()
    ]
    return {"users": users}


async def identity_resolve_user(params: dict) -> dict:
    """params: {identifier: str} → UserPrincipal | None"""
    _, resolver = await _ensure_client()
    identifier = params.get("identifier", "")
    user = resolver.resolve(identifier)
    if user is None:
        return {"user": None}
    return {
        "user": {
            "plugin_name": "lark_docs",
            "native_id": user.lark_open_id,
            "canonical_username": user.username,
            "email": f"{user.username}@unknown.example",
            "display_name": user.display_name or user.username,
            "is_active": True,
            "extras": {},
        },
    }


async def identity_watch_user_changes(params: dict) -> dict:
    """v1 不支持反向 sync (is_source_of_truth=False)。"""
    raise NotImplementedError(
        "LarkDocsPlugin.watch_user_changes 不支持 — is_source_of_truth=False；"
        "Phase 5.D HRCapability + Contact API 反向 sync 才动态化"
    )


# ── JSONRPC METHODS dict (Phase 5.A daemon_client 路由)──────────────────────────


METHODS = {
    # Doc
    "doc.create_document": doc_create_document,
    "doc.replace_document_content": doc_replace_document_content,
    "doc.apply_document_delta": doc_apply_document_delta,
    "doc.add_comment": doc_add_comment,
    "doc.get_document": doc_get_document,
    # Identity
    "identity.list_users": identity_list_users,
    "identity.resolve_user": identity_resolve_user,
    "identity.watch_user_changes": identity_watch_user_changes,
}


# ── daemon main entry (与 plugins/huly/huly_plugin.py Plan 07 风格一致)─────────


async def _main_loop() -> None:
    """JSONRPC over stdio (Phase 5.A daemon_client 协议)。"""
    # 实际实现复用 Phase 5.A daemon_main 工具函数 (echo_daemon.py 模式)
    # Plan 07 acid test 已建 _read_line / _write_line / METHODS dispatch 工具
    # 本 plan 仅声明 main entry, 复用 platform_plugin_daemon_main 抽象
    from app.agent_builder.platforms.daemon_main import run_jsonrpc_daemon  # type: ignore[import-not-found]
    await run_jsonrpc_daemon(METHODS)


if __name__ == "__main__":
    # daemon spawn 时由 PlatformDaemonClient 通过 `python -u -m plugins.lark_docs.lark_docs_plugin` 启动
    logging.basicConfig(
        level=os.environ.get("LARK_DOCS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=__import__("sys").stderr,
    )
    asyncio.run(_main_loop())
```

**Note**: `from app.agent_builder.platforms.daemon_main import run_jsonrpc_daemon` 可能需要 Plan 05c-01 先创建（若不存在则 fallback 内联 daemon loop）。执行 agent 应该先 `find backend -name "daemon_main.py"` 验证；若不存在则用 echo_daemon.py 风格写内联 60 行 main loop（参考 backend/app/agent_builder/platforms/echo_daemon.py 已是 Plan 05a-05 done）。

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && python -c "
import sys; sys.path.insert(0, '..')
import os
os.environ['LARK_APP_ID'] = 'cli_test_dummy'
os.environ['LARK_APP_SECRET'] = 'dummy_secret'
os.environ['LARK_IDENTITY_MAP_JSON'] = '{\"alice\": \"ou_abc123\"}'
from plugins.lark_docs.lark_docs_plugin import METHODS
expected = {
    'doc.create_document', 'doc.replace_document_content', 'doc.apply_document_delta',
    'doc.add_comment', 'doc.get_document',
    'identity.list_users', 'identity.resolve_user', 'identity.watch_user_changes',
}
assert set(METHODS.keys()) == expected, f'mismatch: {set(METHODS.keys()) ^ expected}'
# apply_document_delta should raise NotImplementedError
import asyncio
async def _check_apply_delta():
    try:
        await METHODS['doc.apply_document_delta']({'doc_ref': {'native_id': 'x'}, 'delta': {}})
        return False
    except NotImplementedError:
        return True
async def _check_watch():
    try:
        await METHODS['identity.watch_user_changes']({})
        return False
    except NotImplementedError:
        return True
loop = asyncio.new_event_loop()
assert loop.run_until_complete(_check_apply_delta())
assert loop.run_until_complete(_check_watch())
loop.close()
print('METHODS OK')
"</automated>
  </verify>
  <done>LarkDocsPlugin METHODS dict 8 keys 完整 (doc 5 + identity 3); apply_document_delta + watch_user_changes 正确 raise NotImplementedError; daemon entry 可被 import (虽然实际 spawn 留集成测)</done>
</task>

<task type="auto">
  <name>Task 6: Unit tests — markdown→Lark Block 12 元素 + identity_resolver + plugin facet routing</name>
  <files>tests/platforms/test_lark_docs_plugin.py</files>
  <action>
**Pitfall 6 强制要求：12 元素 mapping 必须 unit test 全覆盖**。

创建 `tests/platforms/test_lark_docs_plugin.py`（约 350 行）：

```python
"""LarkDocsPlugin 单元测试 (Plan 05c-04 Task 6 — pytest, no network)。

测试矩阵（5 类）：
1. markdown_to_lark_blocks 12 元素 mapping (Pitfall 6 防节点名错位)
   - heading 1-6 → block_type 3-8 (6 cases)
   - paragraph → 2
   - bullet list → 12
   - ordered list → 13
   - blockquote → 14
   - code_block with language → 15 + lang enum
   - thematic_break → 19
   - link / em / strong / code inline marks → text_run + style flag
2. IdentityResolver lookup (case-insensitive / fail-quiet / size / list_all)
3. METHODS dict 完整性 + apply_document_delta + watch_user_changes raise NotImplementedError
4. _BLOCK_MAP / _MARK_MAP / _HEADING_LEVEL_TO_BLOCK_TYPE 常量正确
5. LarkAsyncClient 常量 + version 校验逻辑

Reference: RESEARCH §Pattern 5 + Pitfall 6 + CONTEXT.md §6
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


pytestmark = pytest.mark.unit


# ── 1. markdown_to_lark_blocks 12 元素 mapping ──────────────────────────────────


@pytest.fixture
def md_to_blocks():
    from plugins.lark_docs._internal.markdown_to_lark_block import markdown_to_lark_blocks
    return markdown_to_lark_blocks


class TestMarkdownToLarkBlock12Elements:
    """Pitfall 6 防 marko AST 节点名 ≠ Lark Block type 错位。"""

    def test_heading_h1_to_block_type_3(self, md_to_blocks):
        blocks = md_to_blocks("# H1\n")
        assert len(blocks) == 1
        assert blocks[0]["block_type"] == 3
        assert "heading1" in blocks[0]
        assert blocks[0]["heading1"]["elements"][0]["text_run"]["content"] == "H1"

    @pytest.mark.parametrize("level,block_type,type_name", [
        (1, 3, "heading1"), (2, 4, "heading2"), (3, 5, "heading3"),
        (4, 6, "heading4"), (5, 7, "heading5"), (6, 8, "heading6"),
    ])
    def test_heading_levels_1_to_6(self, md_to_blocks, level, block_type, type_name):
        blocks = md_to_blocks("#" * level + f" H{level}\n")
        assert blocks[0]["block_type"] == block_type
        assert type_name in blocks[0]

    def test_paragraph_to_block_type_2(self, md_to_blocks):
        blocks = md_to_blocks("just a paragraph\n")
        assert blocks[0]["block_type"] == 2
        assert "text" in blocks[0]

    def test_bullet_list_to_block_type_12(self, md_to_blocks):
        blocks = md_to_blocks("- a\n- b\n")
        assert all(b["block_type"] == 12 for b in blocks)
        assert all("bullet" in b for b in blocks)
        assert len(blocks) == 2

    def test_ordered_list_to_block_type_13(self, md_to_blocks):
        blocks = md_to_blocks("1. first\n2. second\n")
        assert all(b["block_type"] == 13 for b in blocks)
        assert all("ordered" in b for b in blocks)
        assert len(blocks) == 2

    def test_blockquote_to_block_type_14(self, md_to_blocks):
        blocks = md_to_blocks("> a quote\n")
        assert blocks[0]["block_type"] == 14
        assert "quote" in blocks[0]

    def test_code_block_to_block_type_15_with_language(self, md_to_blocks):
        blocks = md_to_blocks("```python\nprint('hi')\n```\n")
        assert blocks[0]["block_type"] == 15
        assert "code" in blocks[0]
        # python → enum 28
        assert blocks[0]["code"]["style"]["language"] == 28

    def test_thematic_break_to_block_type_19(self, md_to_blocks):
        blocks = md_to_blocks("---\n")
        assert blocks[0]["block_type"] == 19
        assert "divider" in blocks[0]

    def test_inline_strong_to_bold_mark(self, md_to_blocks):
        blocks = md_to_blocks("**bold text**\n")
        text_run = blocks[0]["text"]["elements"][0]["text_run"]
        assert text_run["text_element_style"].get("bold") is True

    def test_inline_emphasis_to_italic_mark(self, md_to_blocks):
        blocks = md_to_blocks("*italic text*\n")
        text_run = blocks[0]["text"]["elements"][0]["text_run"]
        assert text_run["text_element_style"].get("italic") is True

    def test_inline_code_to_inline_code_mark(self, md_to_blocks):
        blocks = md_to_blocks("`code span`\n")
        text_run = blocks[0]["text"]["elements"][0]["text_run"]
        assert text_run["text_element_style"].get("inline_code") is True

    def test_inline_link_to_link_url(self, md_to_blocks):
        blocks = md_to_blocks("[click me](https://example.com)\n")
        text_run = blocks[0]["text"]["elements"][0]["text_run"]
        assert text_run["text_element_style"].get("link") == {"url": "https://example.com"}

    def test_image_to_block_type_27_stub(self, md_to_blocks):
        blocks = md_to_blocks("![alt](https://example.com/img.png)\n")
        # image 是 inline element 但因独占段落，marko 解析为 paragraph 内含 image inline
        # 容忍两种结构：要么 block_type=27 image block，要么 paragraph 内 image inline
        assert blocks[0]["block_type"] in (2, 27)

    def test_blank_line_skipped(self, md_to_blocks):
        blocks = md_to_blocks("a\n\n\nb\n")
        # 2 个 paragraph + 0 个 blank_line
        text_blocks = [b for b in blocks if b["block_type"] == 2]
        assert len(text_blocks) == 2


class TestMarkdownToLarkBlockEdgeCases:
    def test_empty_markdown(self, md_to_blocks):
        assert md_to_blocks("") == []

    def test_only_whitespace(self, md_to_blocks):
        # 只有空行 → 没有有效 block
        blocks = md_to_blocks("\n\n\n")
        text_blocks = [b for b in blocks if b["block_type"] == 2 and b["text"]["elements"]]
        assert text_blocks == []

    def test_heading_level_clamped_to_6(self, md_to_blocks):
        # marko 自动把 ####### 当 paragraph (CommonMark 不允许 >6 #)
        # 此 case 验证 fallback 不崩
        blocks = md_to_blocks("####### too deep\n")
        assert len(blocks) >= 1

    def test_constants_match_research(self):
        from plugins.lark_docs._internal.markdown_to_lark_block import (
            _BLOCK_MAP, _MARK_MAP, _HEADING_LEVEL_TO_BLOCK_TYPE,
        )
        assert _BLOCK_MAP["paragraph"] == 2
        assert _BLOCK_MAP["code_block"] == 15
        assert _BLOCK_MAP["block_quote"] == 14
        assert _BLOCK_MAP["thematic_break"] == 19
        assert _MARK_MAP["strong_emphasis"] == "bold"
        assert _MARK_MAP["emphasis"] == "italic"
        assert _MARK_MAP["code_span"] == "inline_code"
        assert _MARK_MAP["link"] == "link"
        assert _HEADING_LEVEL_TO_BLOCK_TYPE == {1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8}


# ── 2. IdentityResolver ────────────────────────────────────────────────────────


class TestIdentityResolver:
    @pytest.fixture
    def resolver_cls(self):
        from plugins.lark_docs._internal.identity_resolver import IdentityResolver
        return IdentityResolver

    def test_resolve_existing_user(self, resolver_cls):
        r = resolver_cls({"alice": "ou_abc123"})
        u = r.resolve("alice")
        assert u is not None
        assert u.lark_open_id == "ou_abc123"
        assert u.username == "alice"

    def test_resolve_case_insensitive(self, resolver_cls):
        r = resolver_cls({"Alice": "ou_abc123"})
        assert r.resolve("ALICE").lark_open_id == "ou_abc123"
        assert r.resolve("aLicE").lark_open_id == "ou_abc123"

    def test_resolve_unknown_returns_none(self, resolver_cls):
        r = resolver_cls({"alice": "ou_abc123"})
        assert r.resolve("unknown") is None

    def test_resolve_empty_input_returns_none(self, resolver_cls):
        r = resolver_cls({"alice": "ou_abc123"})
        assert r.resolve("") is None

    def test_invalid_open_id_dropped(self, resolver_cls):
        r = resolver_cls({"alice": "ou_abc", "bob": "bad-format", "charlie": "ou_def"})
        assert r.size == 2  # bob dropped
        assert r.resolve("bob") is None
        assert r.resolve("alice") is not None
        assert r.resolve("charlie") is not None

    def test_empty_map(self, resolver_cls):
        r = resolver_cls({})
        assert r.size == 0
        assert r.resolve("x") is None
        assert r.list_all() == []

    def test_none_map(self, resolver_cls):
        r = resolver_cls(None)
        assert r.size == 0
        assert r.resolve("x") is None

    def test_list_all_returns_all_users(self, resolver_cls):
        r = resolver_cls({"alice": "ou_a", "bob": "ou_b"})
        users = r.list_all()
        usernames = {u.username for u in users}
        assert usernames == {"alice", "bob"}


# ── 3. Plugin METHODS routing + NotImplementedError ────────────────────────────


class TestLarkDocsPluginMETHODS:
    def setup_method(self):
        # daemon entry import 期会读 env，预设
        os.environ["LARK_APP_ID"] = "cli_test_dummy"
        os.environ["LARK_APP_SECRET"] = "dummy_secret"
        os.environ["LARK_IDENTITY_MAP_JSON"] = '{"alice": "ou_abc123"}'
        # reset module state (multi-test isolation)
        import plugins.lark_docs.lark_docs_plugin as plugin_mod
        plugin_mod._client = None
        plugin_mod._resolver = None
        plugin_mod._client_lock = None

    def test_methods_dict_has_8_keys(self):
        from plugins.lark_docs.lark_docs_plugin import METHODS
        assert set(METHODS.keys()) == {
            "doc.create_document", "doc.replace_document_content",
            "doc.apply_document_delta", "doc.add_comment", "doc.get_document",
            "identity.list_users", "identity.resolve_user", "identity.watch_user_changes",
        }

    @pytest.mark.asyncio
    async def test_apply_document_delta_raises_not_implemented(self):
        from plugins.lark_docs.lark_docs_plugin import METHODS
        with pytest.raises(NotImplementedError, match="Lark Docs 不是 CRDT"):
            await METHODS["doc.apply_document_delta"]({
                "doc_ref": {"plugin_name": "lark_docs", "native_id": "doc_x", "extras": {}},
                "delta": {"format": "yjs", "payload": ""},
            })

    @pytest.mark.asyncio
    async def test_watch_user_changes_raises_not_implemented(self):
        from plugins.lark_docs.lark_docs_plugin import METHODS
        with pytest.raises(NotImplementedError, match="is_source_of_truth=False"):
            await METHODS["identity.watch_user_changes"]({})

    @pytest.mark.asyncio
    async def test_identity_resolve_user_alice_returns_open_id(self):
        from plugins.lark_docs.lark_docs_plugin import METHODS
        result = await METHODS["identity.resolve_user"]({"identifier": "alice"})
        assert result["user"]["native_id"] == "ou_abc123"
        assert result["user"]["plugin_name"] == "lark_docs"
        assert result["user"]["canonical_username"] == "alice"

    @pytest.mark.asyncio
    async def test_identity_resolve_user_unknown_returns_none(self):
        from plugins.lark_docs.lark_docs_plugin import METHODS
        result = await METHODS["identity.resolve_user"]({"identifier": "unknown"})
        assert result["user"] is None

    @pytest.mark.asyncio
    async def test_identity_list_users(self):
        from plugins.lark_docs.lark_docs_plugin import METHODS
        result = await METHODS["identity.list_users"]({})
        assert len(result["users"]) == 1
        assert result["users"][0]["canonical_username"] == "alice"


# ── 4. LarkAsyncClient 常量验证 ────────────────────────────────────────────────


class TestLarkAsyncClientConstants:
    def test_max_blocks_per_batch_is_800(self):
        from plugins.lark_docs._internal.lark_async_client import _MAX_BLOCKS_PER_BATCH
        # Pitfall 3：1000 上限留 200 余量
        assert _MAX_BLOCKS_PER_BATCH == 800

    def test_max_markdown_chars_is_10mb(self):
        from plugins.lark_docs._internal.lark_async_client import _MAX_MARKDOWN_CHARS
        assert _MAX_MARKDOWN_CHARS == 10_485_760

    def test_expected_lark_version_is_1_6_5(self):
        from plugins.lark_docs._internal.lark_async_client import _EXPECTED_LARK_VERSION
        # CLAUDE.md §3 强制：1.6.0/1/2/3 yanked
        assert _EXPECTED_LARK_VERSION == "1.6.5"

    def test_resolve_lark_version_returns_str(self):
        from plugins.lark_docs._internal.lark_async_client import _resolve_lark_version
        v = _resolve_lark_version()
        assert isinstance(v, str)
        # 实际环境装的 lark-oapi==1.6.5
        assert v in ("1.6.5", "unknown")
```

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms/test_lark_docs_plugin.py -v 2>&1 | tail -40 && pytest tests/platforms/test_lark_docs_plugin.py --collect-only -q 2>&1 | grep "test_" | wc -l</automated>
  </verify>
  <done>tests/platforms/test_lark_docs_plugin.py 全部通过 (≥ 35 测试 包含 6 heading levels + 12 元素 + 8 identity_resolver + 6 METHODS + 4 client constants); Pitfall 6 防护测试全绿; apply_document_delta + watch_user_changes 正确抛 NotImplementedError</done>
</task>

<task type="auto">
  <name>Task 7: mock_lark_server fixture (respx 模拟 Lark Open API @127.0.0.1:18089)</name>
  <files>tests/fixtures/__init__.py,tests/fixtures/mock_lark_server.py</files>
  <action>
集成测试需要不真打 Lark 的 mock server。用 `respx`（Phase 4 已有 dep）拦截 httpx 请求，模拟 Lark 5 个核心 endpoint。

创建 `tests/fixtures/__init__.py`（如不存在）— 空文件 + 一行 docstring：
```python
"""Phase 5.C+ 测试共享 fixture（mock 各 plugin 的外部 API server）。"""
```

创建 `tests/fixtures/mock_lark_server.py`（约 200 行）：

```python
"""mock_lark_server — Lark Open Platform API mock (respx)。

模拟 5 个 endpoint：
1. POST /open-apis/auth/v3/tenant_access_token/internal → 返回 tenant_access_token
2. POST /open-apis/docx/v1/documents → 创 doc shell
3. POST /open-apis/docx/v1/documents/blocks/convert → markdown → blocks
4. POST /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children → batch insert
5. POST /open-apis/drive/v1/files/{document_id}/comments → 创评论

设计要点：
- 不真请求飞书 (CI 无凭据)
- 记录所有 received_requests 供测试 assert
- 可触发错误 (status_code=400 / code=99991663 etc.) 验错误处理
- 1000 block batch 测试：当 children 长度 > 800 时只返回前 800 的 ids，模拟分批必要性

Reference: respx 0.21+ 官方文档
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx
import respx


_LARK_BASE = "https://open.feishu.cn"


@dataclass
class MockLarkServer:
    """In-memory Lark mock + respx router。

    用法：
        async with MockLarkServer.start() as srv:
            # client 调 lark API 时被 respx 拦截
            ...
        assert len(srv.recorded.create_document) == 1
        assert srv.recorded.create_blocks[0]["children_count"] == 5
    """

    documents: dict[str, dict] = field(default_factory=dict)
    comments: dict[str, dict] = field(default_factory=dict)
    recorded: "MockLarkRecorder" = field(default_factory=lambda: MockLarkRecorder())
    _router: respx.MockRouter | None = None

    @classmethod
    def start(cls) -> "MockLarkServerContext":
        return MockLarkServerContext(cls())

    def install_routes(self, router: respx.MockRouter) -> None:
        self._router = router

        # 1. tenant_access_token
        router.post(f"{_LARK_BASE}/open-apis/auth/v3/tenant_access_token/internal").mock(
            side_effect=self._handle_tenant_token
        )
        # 2. create document shell
        router.post(f"{_LARK_BASE}/open-apis/docx/v1/documents").mock(
            side_effect=self._handle_create_document
        )
        # 3. convert markdown → blocks
        router.post(f"{_LARK_BASE}/open-apis/docx/v1/documents/blocks/convert").mock(
            side_effect=self._handle_convert_markdown
        )
        # 4. batch create blocks (用 regex 抓 path 内的 document_id + block_id)
        router.post(
            url__regex=rf"^{_LARK_BASE}/open-apis/docx/v1/documents/(?P<doc_id>[^/]+)/blocks/(?P<blk_id>[^/]+)/children",
        ).mock(side_effect=self._handle_create_blocks)
        # 5. create comment
        router.post(
            url__regex=rf"^{_LARK_BASE}/open-apis/drive/v1/files/(?P<doc_id>[^/]+)/comments",
        ).mock(side_effect=self._handle_create_comment)

    # ── Handlers ───────────────────────────────────────────────────────────────

    def _handle_tenant_token(self, request: httpx.Request) -> httpx.Response:
        self.recorded.tenant_token_calls += 1
        return httpx.Response(200, json={
            "code": 0, "msg": "ok",
            "tenant_access_token": "t-mock-token-abc123",
            "expire": 7200,
        })

    def _handle_create_document(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        doc_id = f"docx-{uuid4().hex[:16]}"
        self.documents[doc_id] = {"document_id": doc_id, "title": body.get("title", ""),
                                    "revision_id": 1}
        self.recorded.create_document.append(body)
        return httpx.Response(200, json={
            "code": 0, "msg": "ok",
            "data": {"document": {"document_id": doc_id, "revision_id": 1,
                                   "title": body.get("title", "")}},
        })

    def _handle_convert_markdown(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        markdown = body.get("content", "")
        self.recorded.convert_markdown.append({"length": len(markdown)})
        # 简化：粗略按 \n 分段构造 blocks（不必真还原 Lark 转换）
        lines = [ln for ln in markdown.split("\n") if ln.strip()]
        blocks = [{"block_id": f"blk-{i}", "block_type": 2,
                     "text": {"elements": [{"text_run": {"content": ln}}]}}
                    for i, ln in enumerate(lines)]
        return httpx.Response(200, json={
            "code": 0, "msg": "ok",
            "data": {"first_level_block_ids": [b["block_id"] for b in blocks],
                       "blocks": blocks},
        })

    def _handle_create_blocks(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        children = body.get("children", [])
        self.recorded.create_blocks.append({
            "children_count": len(children),
            "index": body.get("index", 0),
            "url": str(request.url),
        })
        # 模拟 Lark 1000 block 上限：超出 → 400
        if len(children) > 1000:
            return httpx.Response(400, json={
                "code": 1254204, "msg": "Block count exceeds limit (1000)",
            })
        return httpx.Response(200, json={
            "code": 0, "msg": "ok",
            "data": {"children": [{"block_id": f"new-blk-{i}"}
                                    for i in range(len(children))]},
        })

    def _handle_create_comment(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # path 包含 document_id; query string 含 file_type=docx
        comment_id = f"comment-{uuid4().hex[:12]}"
        self.comments[comment_id] = {"comment_id": comment_id, "content": body.get("content", "")}
        self.recorded.create_comment.append({
            "content": body.get("content", ""),
            "url": str(request.url),
        })
        return httpx.Response(200, json={
            "code": 0, "msg": "ok",
            "data": {"comment_id": comment_id},
        })


@dataclass
class MockLarkRecorder:
    tenant_token_calls: int = 0
    create_document: list[dict] = field(default_factory=list)
    convert_markdown: list[dict] = field(default_factory=list)
    create_blocks: list[dict] = field(default_factory=list)
    create_comment: list[dict] = field(default_factory=list)


class MockLarkServerContext:
    """async with 上下文管理器 — 自动 start / stop respx router。"""

    def __init__(self, server: MockLarkServer) -> None:
        self.server = server
        self._router: respx.MockRouter | None = None

    async def __aenter__(self) -> MockLarkServer:
        self._router = respx.mock(assert_all_called=False, assert_all_mocked=False)
        self._router.start()
        self.server.install_routes(self._router)
        return self.server

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._router is not None:
            self._router.stop()
```

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && python -c "
import sys; sys.path.insert(0, '..')
import asyncio
import httpx
from tests.fixtures.mock_lark_server import MockLarkServer

async def smoke():
    async with MockLarkServer.start() as srv:
        async with httpx.AsyncClient() as c:
            # 1. tenant_token
            r = await c.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                              json={'app_id': 'x', 'app_secret': 'y'})
            assert r.json()['code'] == 0
            # 2. create doc
            r = await c.post('https://open.feishu.cn/open-apis/docx/v1/documents',
                              json={'title': 'test'})
            doc_id = r.json()['data']['document']['document_id']
            assert doc_id.startswith('docx-')
            # 3. convert
            r = await c.post('https://open.feishu.cn/open-apis/docx/v1/documents/blocks/convert',
                              json={'content_type': 'markdown', 'content': 'a\nb\nc'})
            assert len(r.json()['data']['blocks']) == 3
            # 4. create blocks
            r = await c.post(f'https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children',
                              json={'children': [{}, {}], 'index': 0})
            assert r.json()['code'] == 0
            # 5. >1000 → 400
            r = await c.post(f'https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children',
                              json={'children': [{}] * 1001, 'index': 0})
            assert r.status_code == 400
        assert srv.recorded.tenant_token_calls == 1
        assert len(srv.recorded.create_document) == 1
        assert len(srv.recorded.create_blocks) == 2
asyncio.run(smoke())
print('mock_lark_server OK')
"</automated>
  </verify>
  <done>MockLarkServer 5 endpoint 全工作；>1000 block return 400 (模拟 Lark 上限)；recorded.tenant_token_calls / create_document / create_blocks 等记录正确</done>
</task>

<task type="auto">
  <name>Task 8: Integration tests — 真 lark-oapi → respx mock + 1000 block 分批触发 + tenant_access_token cache</name>
  <files>tests/platforms_integration/test_lark_docs_plugin_integration.py</files>
  <action>
集成测试：**真 lark-oapi SDK 调用 + respx mock 拦截 + 验证 Pitfall 3 分批正确**。

不真 spawn daemon 子进程（那是 Plan 09 plugin discovery smoke 的事），本 plan 集成测仅验证 LarkAsyncClient + handlers 端到端通过 mock server 走通。

创建 `tests/platforms_integration/test_lark_docs_plugin_integration.py`（约 250 行）：

```python
"""LarkDocsPlugin 集成测试 (Plan 05c-04 Task 8)。

测试矩阵 (4 类)：
1. LarkAsyncClient.create_document 经 mock server 端到端
2. LarkAsyncClient.create_blocks 1000 block 分批自动触发 (Pitfall 3)
3. LarkAsyncClient.convert_markdown 10MB 上限 raise ValueError (Pitfall 3)
4. 双 facet (doc + identity) 共享单 client 单例 (RESEARCH §Pattern 1)

不真 spawn daemon (Plan 09); 验 facade 函数端到端通过 respx mock。

Reference: RESEARCH §Pattern 1 + Pitfall 3 + Pattern 8
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
def _reset_plugin_state(monkeypatch):
    """Reset LarkDocsPlugin daemon module-level state for clean test isolation."""
    monkeypatch.setenv("LARK_APP_ID", "cli_test_dummy")
    monkeypatch.setenv("LARK_APP_SECRET", "dummy_secret")
    monkeypatch.setenv("LARK_IDENTITY_MAP_JSON", json.dumps({
        "alice": "ou_abc123def456", "bob": "ou_xyz789ghi012",
    }))
    import plugins.lark_docs.lark_docs_plugin as plugin_mod
    plugin_mod._client = None
    plugin_mod._resolver = None
    plugin_mod._client_lock = None
    yield
    plugin_mod._client = None
    plugin_mod._resolver = None
    plugin_mod._client_lock = None


# ── 1. create_document 端到端 ─────────────────────────────────────────────────


async def test_create_document_through_mock_server(_reset_plugin_state):
    """LarkDocsPlugin.doc.create_document → mock Lark → 验 doc_id 返回。"""
    from tests.fixtures.mock_lark_server import MockLarkServer
    from plugins.lark_docs.lark_docs_plugin import METHODS

    async with MockLarkServer.start() as srv:
        result = await METHODS["doc.create_document"]({
            "title": "Integration Test Doc",
            "markdown": "# Hello\n\nWorld\n",
        })
        assert result["doc_ref"]["plugin_name"] == "lark_docs"
        assert result["doc_ref"]["native_id"].startswith("docx-")

        # 验 Lark 调用序：create_document + convert_markdown + create_blocks
        assert len(srv.recorded.create_document) == 1
        assert srv.recorded.create_document[0]["title"] == "Integration Test Doc"
        assert len(srv.recorded.convert_markdown) == 1
        assert len(srv.recorded.create_blocks) == 1


# ── 2. 1000 block 分批触发 (Pitfall 3) ─────────────────────────────────────────


async def test_create_blocks_splits_at_800_threshold(_reset_plugin_state):
    """传 850 个 block → 应分 2 批 (800 + 50), Pitfall 3 防护生效。"""
    from tests.fixtures.mock_lark_server import MockLarkServer
    from plugins.lark_docs._internal.lark_async_client import (
        LarkAsyncClient, _MAX_BLOCKS_PER_BATCH,
    )

    assert _MAX_BLOCKS_PER_BATCH == 800

    client = LarkAsyncClient(app_id="x", app_secret="y")
    fake_blocks = [
        {"block_type": 2, "text": {"elements": [{"text_run": {"content": f"b{i}"}}]}}
        for i in range(850)
    ]

    async with MockLarkServer.start() as srv:
        await client.create_blocks(
            document_id="docx-test", block_id="docx-test", blocks=fake_blocks,
        )
        # 应分 2 批：800 + 50
        assert len(srv.recorded.create_blocks) == 2
        assert srv.recorded.create_blocks[0]["children_count"] == 800
        assert srv.recorded.create_blocks[1]["children_count"] == 50
        assert srv.recorded.create_blocks[0]["index"] == 0
        assert srv.recorded.create_blocks[1]["index"] == 800


async def test_create_blocks_single_batch_when_below_threshold(_reset_plugin_state):
    """传 500 block → 应单批，不触发分批。"""
    from tests.fixtures.mock_lark_server import MockLarkServer
    from plugins.lark_docs._internal.lark_async_client import LarkAsyncClient

    client = LarkAsyncClient(app_id="x", app_secret="y")
    fake_blocks = [
        {"block_type": 2, "text": {"elements": [{"text_run": {"content": f"b{i}"}}]}}
        for i in range(500)
    ]

    async with MockLarkServer.start() as srv:
        await client.create_blocks(
            document_id="docx-test", block_id="docx-test", blocks=fake_blocks,
        )
        assert len(srv.recorded.create_blocks) == 1
        assert srv.recorded.create_blocks[0]["children_count"] == 500


async def test_create_blocks_three_batches_at_1700(_reset_plugin_state):
    """1700 block → 3 批 (800 + 800 + 100)."""
    from tests.fixtures.mock_lark_server import MockLarkServer
    from plugins.lark_docs._internal.lark_async_client import LarkAsyncClient

    client = LarkAsyncClient(app_id="x", app_secret="y")
    fake_blocks = [
        {"block_type": 2, "text": {"elements": [{"text_run": {"content": f"b{i}"}}]}}
        for i in range(1700)
    ]

    async with MockLarkServer.start() as srv:
        await client.create_blocks(
            document_id="docx-test", block_id="docx-test", blocks=fake_blocks,
        )
        assert len(srv.recorded.create_blocks) == 3
        counts = [c["children_count"] for c in srv.recorded.create_blocks]
        assert counts == [800, 800, 100]
        indices = [c["index"] for c in srv.recorded.create_blocks]
        assert indices == [0, 800, 1600]


# ── 3. 10MB 字符上限 (Pitfall 3) ───────────────────────────────────────────────


async def test_convert_markdown_raises_when_over_10mb(_reset_plugin_state):
    """markdown > 10MB → ValueError (Pitfall 3 防护)。"""
    from plugins.lark_docs._internal.lark_async_client import (
        LarkAsyncClient, _MAX_MARKDOWN_CHARS,
    )

    client = LarkAsyncClient(app_id="x", app_secret="y")
    huge_markdown = "a" * (_MAX_MARKDOWN_CHARS + 1)

    with pytest.raises(ValueError, match="超 Lark convert 字符上限"):
        await client.convert_markdown(markdown=huge_markdown)


# ── 4. tenant_access_token cache (mock 调用次数 = 1) ───────────────────────────


async def test_tenant_access_token_refreshed_via_mock_server(_reset_plugin_state):
    """连续 3 次 convert_markdown → tenant_token 端点也被调（mock 不缓存 token，但
    LarkAsyncClient 沿用 lark-oapi 1.6.5 内置 cache —— 真集成时只调 1 次）。

    Note: respx mock 不模拟 SDK 内部 cache 行为；本测试仅验证调用通路畅通，
    真正的 cache 验证留 E2E（Plan 08）。
    """
    from tests.fixtures.mock_lark_server import MockLarkServer
    from plugins.lark_docs._internal.lark_async_client import LarkAsyncClient

    client = LarkAsyncClient(app_id="x", app_secret="y")
    async with MockLarkServer.start() as srv:
        await client.convert_markdown(markdown="# hello\n")
        await client.convert_markdown(markdown="# world\n")
        # 至少调过 1 次 tenant_token endpoint (mock 拦截 raw httpx 路径)
        assert srv.recorded.tenant_token_calls >= 1
        assert len(srv.recorded.convert_markdown) == 2


# ── 5. 双 facet 共享单 client (RESEARCH §Pattern 1) ────────────────────────────


async def test_doc_and_identity_facet_share_single_client(_reset_plugin_state):
    """连续 invoke doc.get_document + identity.resolve_user → _client 应是同一实例。"""
    from tests.fixtures.mock_lark_server import MockLarkServer
    from plugins.lark_docs.lark_docs_plugin import METHODS
    import plugins.lark_docs.lark_docs_plugin as plugin_mod

    async with MockLarkServer.start() as srv:
        # First: identity (lazy init)
        await METHODS["identity.resolve_user"]({"identifier": "alice"})
        first_client = plugin_mod._client
        first_resolver = plugin_mod._resolver
        assert first_client is not None
        assert first_resolver is not None

        # Then: doc.get_document — should reuse same client
        # 先创建一个 doc 让 mock 有内容
        await METHODS["doc.create_document"]({"title": "share-test", "markdown": ""})
        second_client = plugin_mod._client
        second_resolver = plugin_mod._resolver

        assert second_client is first_client  # 同一引用
        assert second_resolver is first_resolver
```

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms_integration/test_lark_docs_plugin_integration.py -v 2>&1 | tail -40</automated>
  </verify>
  <done>5+ 集成测试全通过; 850/500/1700 三组分批 case 全绿验 Pitfall 3 防护; 10MB 字符 raise ValueError; 双 facet 共享单 client 验证 (id() 相同)</done>
</task>

<task type="auto">
  <name>Task 9: Plugin discovery smoke + Phase 5.A 271 + Phase 4 IM 131 regression baseline</name>
  <files>tests/platforms/test_lark_docs_plugin.py</files>
  <action>
**最终 DoD 验证 task**：不新增 test 文件，**只在 test_lark_docs_plugin.py 末尾追加 1 个 discovery smoke test class + 跑全量 regression**。

### 9.1 追加 discovery smoke (在 test_lark_docs_plugin.py 末尾追加)

```python
# ── 5. PlatformPluginRegistry discover smoke ───────────────────────────────────


class TestLarkDocsPluginDiscovery:
    """验证 manifest 可被 Phase 5.A Plan 04 PlatformPluginRegistry discover。"""

    def test_lark_docs_manifest_discoverable(self):
        """启动期 discover("plugins/") 必须 pick up lark_docs。"""
        from app.agent_builder.platforms.manifest import load_manifest

        manifest = load_manifest("../plugins/lark_docs/platform.yaml")
        assert manifest.name == "lark_docs"
        assert manifest.version == "1.0.0"
        assert set(manifest.capabilities) == {"doc", "identity"}
        assert manifest.doc.supports_collaborative_edit is False
        assert manifest.doc.supports_comments is True
        assert manifest.identity.is_source_of_truth is False
        # sandbox 含 Lark 3 host
        assert "open.feishu.cn:443" in manifest.sandbox.network
        assert "passport.feishu.cn:443" in manifest.sandbox.network
        assert "lf-cdn-tos.bytescm.com:443" in manifest.sandbox.network
        # env_allowlist 仅 LARK_APP_*
        assert set(manifest.sandbox.env_allowlist) == {"LARK_APP_ID", "LARK_APP_SECRET"}

    def test_lark_docs_runtime_entry_importable(self):
        """runtime.entry 路径 (plugins.lark_docs.lark_docs_plugin) 可 import。"""
        import importlib
        mod = importlib.import_module("plugins.lark_docs.lark_docs_plugin")
        assert hasattr(mod, "METHODS")
        assert callable(mod.METHODS["doc.create_document"])
        assert callable(mod.METHODS["identity.resolve_user"])
```

### 9.2 跑 regression baseline

```bash
cd backend

# Lark plugin 自有
pytest tests/platforms/test_lark_docs_plugin.py -v 2>&1 | tail -10
pytest tests/platforms_integration/test_lark_docs_plugin_integration.py -v 2>&1 | tail -10

# Phase 5.A 累积 271 platforms tests baseline (不应 regression)
pytest tests/platforms/ -v --ignore=tests/platforms/test_lark_docs_plugin.py 2>&1 | tail -5

# Phase 4 IM 131 tests baseline (不应 regression)
pytest tests/test_im_provider_*.py tests/notification/ tests/test_e2e_v2*.py 2>&1 | tail -5
```

**DoD 数字记录**：
- Lark plugin unit: ≥ 35 测试 (Task 6 12 元素 + 8 identity + 6 METHODS + 4 constants + Task 9 2 discovery = 31+)
- Lark plugin integration: ≥ 5 测试 (Task 8 三分批 case + 10MB + 双 facet)
- Phase 5.A platforms baseline: 271 (5b-05 SUMMARY 数字)
- Phase 4 IM baseline: 131 (5b-05 SUMMARY 数字)

最终目标：**Lark plugin 全测试通过 + Phase 5.A 271 + Phase 4 IM 131 全 0 regression**

### 9.3 commit 后整理 SUMMARY 数字

最后 create `.planning/phases/05c-doc-capability/05c-04-SUMMARY.md`（按 plan 输出 step 模板）记录：
- Reading doc commit hash + 行数
- 31+ 5+ 测试通过截图
- 271 + 131 0 regression 截图
- 7 借鉴点指回 reading doc 章节

代码风格：black + ruff 必须通过。
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms/test_lark_docs_plugin.py::TestLarkDocsPluginDiscovery -v 2>&1 | tail -10 && pytest tests/platforms/ -v 2>&1 | tail -5 && pytest tests/test_im_provider_*.py 2>&1 | tail -3 || pytest backend/tests/notification/ 2>&1 | tail -3</automated>
  </verify>
  <done>Discovery smoke 2 测试通过 (manifest 可 load + runtime entry 可 import); Phase 5.A 271 platforms tests + Phase 4 IM 131 tests 0 regression; Lark plugin 自身 unit + integration 全绿; SUMMARY.md 生成含 7 借鉴点 + 数字证据</done>
</task>

</tasks>

<verification>
Phase gate (plan 04):
- [ ] Reading doc commit hash 早于 Task 1+ 任何代码 commit (CLAUDE.md §2.7 校验)
- [ ] Reading doc ≥ 100 行 + 含 Dify 调研结论 + License attribution + 7 借鉴点
- [ ] `plugins/lark_docs/platform.yaml` 可被 PlatformManifest 校验 (capabilities=[doc,identity] + 双 cap flag 正确)
- [ ] markdown_to_lark_blocks 12 元素 unit test 全绿 (heading 1-6 + paragraph + bullet + ordered + blockquote + code + thematic_break + 4 inline mark)
- [ ] IdentityResolver 8 测试全绿 (case-insensitive + fail-quiet + invalid open_id dropped + empty/none map)
- [ ] LarkDocsPlugin METHODS 8 keys 完整 + apply_document_delta + watch_user_changes raise NotImplementedError
- [ ] LarkAsyncClient 集成测：850/500/1700 三组 block 分批正确触发 (Pitfall 3)
- [ ] 10MB markdown raise ValueError (Pitfall 3)
- [ ] 双 facet 共享单 client 实例 (id() 相同, RESEARCH §Pattern 1)
- [ ] mock_lark_server >1000 block return 400 (模拟 Lark 上限)
- [ ] manifest sandbox.network 含 3 Lark host:port + env_allowlist 仅 LARK_APP_* (Pitfall 7)
- [ ] Phase 5.A 累积 271 platforms tests + Phase 4 IM 131 tests 0 regression
</verification>

<success_criteria>
- LarkDocsPlugin (DocCapability + IdentityCapability multi-facet) 完整实现
- 单 daemon + 单 lark.Client 单例 (doc + identity 共享，不重复 login)
- markdown → Lark Block 12 元素严格映射 (heading 1-6 → block_type 3-8 / paragraph=2 / bullet=12 / ordered=13 / quote=14 / code=15 / hr=19; inline strong/em/code/link 转 text_run.text_element_style)
- 沿用 Phase 4 FeishuProvider 已验证 lark-oapi 1.6.5 async 包装模式 (importlib.metadata 版本检测 + asyncio.to_thread)
- AllowlistTransport 白名单含 3 Lark host:port (open.feishu.cn:443 / passport.feishu.cn:443 / lf-cdn-tos.bytescm.com:443)
- Pitfall 3 防护：1000 block 上限自动按 800 分批 + 10MB 字符上限 raise ValueError
- Pitfall 6 防护：marko AST → Lark Block 12 元素 unit test 全覆盖
- Pitfall 7 防护：manifest 显式列 Lark 3 host + 不引入 wildcard
- apply_document_delta + watch_user_changes 正确 raise NotImplementedError (双 cap flag false 路径)
- Phase 5.A 累积 271 + Phase 4 IM 131 = 402 tests 0 regression
- Reading doc 100+ 行含 Dify 调研结论 + 7 借鉴点 + 完整 License attribution
</success_criteria>

<output>
完成后创建 `.planning/phases/05c-doc-capability/05c-04-SUMMARY.md`，至少含：
- Reading doc 链接 + commit hash + 行数 (CLAUDE.md §2.7 gate 证据)
- 测试结果数字：Lark unit ≥ 35 / Lark integration ≥ 5 / Phase 5.A platforms 271 / Phase 4 IM 131 (0 regression)
- 关键 commit 列表 (Task 0 reading doc → Task 1 manifest → Task 2-5 实现 → Task 6 unit → Task 7-8 integration → Task 9 discovery)
- **Dify 参考点** 小节：列出本 plan reading doc 中 7 借鉴点 (Phase 4 FeishuProvider 5 + Phase 5.A 2)，每条指回 reading doc 章节锚点
- **Pitfall 防护清单**：Pitfall 3 (1000 block 分批 + 10MB raise) / Pitfall 6 (12 元素 unit 覆盖) / Pitfall 7 (Lark 3 host 显式列) 三条对应测试 ID
- **后续 Plan 钩子**：
  - Plan 05 Huly plugin DocCapability facet 同 Pattern 1 模式参考本 plan
  - Plan 06 doc_write + doc_mention DAG 节点接 LarkDocsPlugin.doc facet
  - Plan 07 ai_suggest_mentions LLM 集成消费 prompts/ai_suggest_mentions_zh.md
  - Plan 08 E2E browser-harness 跑 Lark Docs 真接入
  - Phase 5.D HRCapability 接入后 IdentityResolver 替换为动态查飞书 Contact API
</output>
