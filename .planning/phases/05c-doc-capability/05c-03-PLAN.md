---
phase: 05c-doc-capability
plan: 03
type: execute
wave: 2
depends_on:
  - "01"
files_modified:
  - docs/reading-dify-05c-03-outline-plugin-2026-05-18.md
  - plugins/__init__.py
  - plugins/outline/__init__.py
  - plugins/outline/platform.yaml
  - plugins/outline/outline_plugin.py
  - plugins/outline/_internal/__init__.py
  - plugins/outline/_internal/outline_client.py
  - plugins/outline/prompts/ai_suggest_mentions_zh.md
  - backend/tests/platforms/test_outline_plugin.py
  - backend/tests/platforms_integration/test_outline_plugin_integration.py
  - backend/tests/platforms_integration/fixtures/mock_outline_server.py
  - backend/tests/platforms/fixtures/manifest_outline.yaml
  - backend/requirements.txt
autonomous: true
requirements:
  - 5C-SC-1
  - 5C-FW-04

must_haves:
  truths:
    - "Dify HTTP retry / tool credential reading doc 先于代码 commit（CLAUDE.md §2.7 硬性 gate）"
    - "OutlinePlugin daemon 可被 PlatformDaemonClient spawn（python -u -m plugins.outline.outline_plugin）"
    - "DocCapability.replace_document_content(markdown) 走 OutlineClient → POST /api/documents.update 真打到 mock outline server"
    - "DocCapability.create_document(title, markdown, owners=None) 走 POST /api/documents.create + 返回 DocRef(plugin_name='outline', native_id=outline_doc_id)"
    - "DocCapability.add_comment(doc_ref, body, mentions=None) 走 POST /api/comments.create + 返回 CommentRef(plugin_name='outline')"
    - "DocCapability.apply_document_delta() raise NotImplementedError('Outline 不支持 CRDT delta — 用 replace')"
    - "DocCapability.ai_suggest_mentions() raise NotImplementedError v1 占位（真实现在 plan 06）"
    - "supports_collaborative_edit = False 由 manifest 声明 + plugin facade 上报（让 service layer fallback 能感知）"
    - "supports_comments = True 由 manifest 声明"
    - "OutlineClient 走 AllowlistTransport（make_sandboxed_http_client）— 禁止直接 httpx.AsyncClient()"
    - "OutlineClient credentials 经 vault / encrypted_credentials_json 取 — 不裸 api_token / env 传"
    - "Outline 429 触发 tenacity AsyncRetrying：最多 2 次重试 + wait_exponential(1s/2s)（Pitfall 12 防超 daemon 30s timeout）"
    - "5.A 273 platforms regression 0 fail（PLATFORMS_BASE）"
    - "5.B 5/5 acid test regression 0 fail（HULY_ACID）"
  artifacts:
    - path: "docs/reading-dify-05c-03-outline-plugin-2026-05-18.md"
      provides: "Dify HTTP node retry / tool credential schema 阅读笔记（5 节标准 + 5 借鉴点 + Outline OpenAPI 对照）"
      min_lines: 80
      contains: "可借鉴的设计模式"
    - path: "plugins/outline/platform.yaml"
      provides: "OutlinePlugin manifest — capabilities:[doc] / runtime python plugins.outline.outline_plugin / sandbox.network allow outline.* / doc.supports_collaborative_edit=False / config_schema base_url+api_token"
      contains: "name: outline"
    - path: "plugins/outline/outline_plugin.py"
      provides: "Daemon entry — JSONRPC over stdio + METHODS dict + 5 doc handlers + ai_suggest_mentions stub"
      contains: "METHODS"
      exports: ["main", "METHODS"]
    - path: "plugins/outline/_internal/outline_client.py"
      provides: "httpx wrapper — AllowlistTransport + tenacity retry + documents.create/update / comments.create"
      contains: "class OutlineClient"
      exports: ["OutlineClient"]
    - path: "backend/tests/platforms/test_outline_plugin.py"
      provides: "Unit test ≥ 12 — handler marshalling + apply_document_delta NotImplementedError + 429 tenacity retry"
    - path: "backend/tests/platforms_integration/test_outline_plugin_integration.py"
      provides: "Integration test ≥ 5 — 真 daemon spawn + 真 httpx + mock outline server roundtrip"
    - path: "backend/tests/platforms_integration/fixtures/mock_outline_server.py"
      provides: "respx-based mock Outline API 监听 127.0.0.1:18088 — documents.create/update + comments.create + 429 触发开关"
    - path: "plugins/outline/prompts/ai_suggest_mentions_zh.md"
      provides: "Plan 06 LLM prompt 模板占位（v1 内容空 placeholder + 中文 schema）"
      min_lines: 10
  key_links:
    - from: "plugins/outline/outline_plugin.py"
      to: "plugins/outline/_internal/outline_client.py"
      via: "daemon handlers 实例化 OutlineClient 并调用 documents_create / documents_update / comments_create"
      pattern: "OutlineClient\\("
    - from: "plugins/outline/_internal/outline_client.py"
      to: "backend/app/agent_builder/platforms/sandbox/network.py"
      via: "make_sandboxed_http_client 注入 AllowlistTransport"
      pattern: "make_sandboxed_http_client"
    - from: "plugins/outline/outline_plugin.py"
      to: "backend/app/agent_builder/platforms/capabilities/doc.py"
      via: "JSONRPC method names 与 DocCapability.* method 完全对应（doc.create_document / doc.replace_document_content / doc.apply_document_delta / doc.add_comment / doc.get_document / doc.ai_suggest_mentions）"
      pattern: "doc\\.create_document"
    - from: "plugins/outline/platform.yaml"
      to: "backend/app/agent_builder/platforms/manifest.py"
      via: "PlatformManifest.doc.supports_collaborative_edit=False 被 DocFacade.supports_collaborative_edit property 读取 → service layer fallback 感知"
      pattern: "supports_collaborative_edit: false"
    - from: "backend/tests/platforms_integration/test_outline_plugin_integration.py"
      to: "backend/tests/platforms_integration/fixtures/mock_outline_server.py"
      via: "fixture 起 mock server on 127.0.0.1:18088 → daemon 通过 env OUTLINE_BASE_URL 知道 mock URL"
      pattern: "OUTLINE_BASE_URL"
---

<objective>
实现 **OutlinePlugin daemon** —— DocCapability **单 capability** 最简实现，作为 Phase 5.C 三个 plugin 中最直接的"参考样板"（也是 v1 真接入的第一个文档平台）。

Purpose: Outline 是协作文档平台中"传统 markdown 全量替换"模型的代表（不支持 CRDT）。本 plan 完整实现 5 个 DocCapability method 真打到 mock outline server（`127.0.0.1:18088`），验证 Phase 5.A DocCapability Protocol + Phase 5.B AllowlistTransport + 三层测试链路在"真 plugin 真 httpx 真 daemon"场景下的可用性。**OutlinePlugin 是 Phase 5.C 三个 plugin 中复杂度最低（单 capability、无 marko/prosemirror、无 docker network）但最完整端到端**的样板 —— 后续 LarkDocsPlugin (plan 04) / HulyPlugin (plan 05-07) 在此基础上叠加 multi-capability / CRDT delta / docker network attach 等复杂度。

Output:
- Dify HTTP node retry / tool credential schema reading doc（CLAUDE.md §2.7 硬性 gate）
- 完整 OutlinePlugin 模块（manifest / daemon entry / httpx client / prompt 占位）
- 单元测试 + 集成测试 + mock outline server fixture
- 注册到 `plugins/__init__.py` 让 PluginRegistry.discover 能扫到
- 0 regression Phase 5.A 273 platforms + Phase 5.B 5/5 acid test
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
@.planning/phases/05c-doc-capability/05c-01-PLAN.md
@CLAUDE.md
@backend/app/agent_builder/platforms/capabilities/doc.py
@backend/app/agent_builder/platforms/sandbox/network.py
@backend/app/agent_builder/platforms/capability_facades.py
@backend/app/agent_builder/platforms/manifest.py
@plugins/huly/huly_plugin.py
@plugins/huly/platform.yaml

<interfaces>
<!-- 本 plan 实现的核心契约（plan 07 service layer 会消费这些） -->

## 1. DocCapability Protocol（plan 实现的目标契约）

From `backend/app/agent_builder/platforms/capabilities/doc.py`（Phase 5.A 已定）:

```python
@runtime_checkable
class DocCapability(Protocol):
    name: str                                           # "outline"
    supports_collaborative_edit: bool                   # False (Outline 不支持 CRDT)
    supports_comments: bool                             # True

    async def create_document(
        self, *, title: str, markdown: str,
        owners: list[UserRef] | None = None,
    ) -> DocRef: ...

    async def replace_document_content(
        self, doc_ref: DocRef, markdown: str,
    ) -> None: ...

    async def apply_document_delta(             # → NotImplementedError("Outline 不支持 CRDT")
        self, doc_ref: DocRef, delta: CRDTDelta,
    ) -> None: ...

    async def add_comment(
        self, *, doc_ref: DocRef, body: str,
        mentions: list[UserRef] | None = None,
    ) -> CommentRef: ...

    async def get_document(
        self, doc_ref: DocRef,
    ) -> DocInfo | None: ...
```

值对象（dataclass frozen=True，daemon JSONRPC 序列化用 `asdict`）:
```python
@dataclass(frozen=True)
class DocRef:
    plugin_name: str        # "outline"
    native_id: str          # outline document id（UUID）
    extras: dict[str, str]  # {} 或 {"url": "https://outline/doc/..."}

@dataclass(frozen=True)
class DocInfo:
    doc_ref: DocRef
    title: str
    url: str | None = None
    content_markdown: str | None = None

@dataclass(frozen=True)
class CommentRef:
    plugin_name: str
    native_id: str
    parent_doc_ref: DocRef

@dataclass(frozen=True)
class UserRef:
    plugin_name: str
    native_id: str

@dataclass(frozen=True)
class CRDTDelta:
    format: str             # "yjs"/"automerge"/"json-patch"
    payload: bytes
```

## 2. AllowlistTransport（plan 必须走的网络安全契约）

From `backend/app/agent_builder/platforms/sandbox/network.py`（Phase 5.B 已定）:

```python
def make_sandboxed_http_client(
    allow_list: list[str],          # ["outline.example.com:443", ...]
    *, timeout: float = 10.0,
) -> httpx.AsyncClient:
    """plugin daemon 显式调此 factory 拿沙箱化 httpx.AsyncClient。

    用法（plugin daemon entrypoint 内）:
        async with make_sandboxed_http_client(allow_list) as client:
            r = await client.post("https://api.example.com/foo", json={...})
    """
    ...

class NetworkBlockedError(Exception):
    """非白名单 host:port 出站 → daemon dispatcher 转 JSONRPC -32000 错误。"""
    host: str
    port: int
    allowlist: list[str]
```

**强制规则**（CONTEXT.md §Critical constraints）:
- OutlineClient **必须**走 `make_sandboxed_http_client(allow_list, ...)`
- **禁止** 直接 `httpx.AsyncClient()` 或 `aiohttp.ClientSession()`
- `allow_list` 由 daemon 启动时通过 env `PLUGIN_NETWORK_ALLOW` 接收（与 huly_plugin.py 同模式）

## 3. JSONRPC method 命名（plugin daemon ↔ DocFacade 协议）

From `backend/app/agent_builder/platforms/capability_facades.py`（Phase 5.A 已定）:

DocFacade 调用对应 JSONRPC method:
| Facade method                | daemon JSONRPC method            |
|------------------------------|----------------------------------|
| `create_document(...)`       | `doc.create_document`            |
| `replace_document_content`   | `doc.replace_document_content`   |
| `apply_document_delta`       | `doc.apply_document_delta`       |
| `add_comment(...)`           | `doc.add_comment`                |
| `get_document(...)`          | `doc.get_document`               |
| `ai_suggest_mentions(...)`   | `doc.ai_suggest_mentions` (v1.1) |

params shape（DocFacade 已实现的序列化约定）:
- `create_document`: `{title: str, markdown: str, owners: list[dict]}`（asdict(UserRef)）
- `replace_document_content`: `{doc_ref: dict, markdown: str}`（asdict(DocRef)）
- `apply_document_delta`: `{doc_ref: dict, delta: {format, payload_b64}}`（payload base64 编码）
- `add_comment`: `{doc_ref: dict, body: str, mentions: list[dict]}`
- `get_document`: `{doc_ref: dict}`

返回 shape（result）:
- `create_document`: `{plugin_name: "outline", native_id: <doc_id>, extras: {url: ...}}`
- `replace_document_content`: `null`
- `apply_document_delta`: raise NotImplementedError → -32603
- `add_comment`: `{plugin_name: "outline", native_id: <comment_id>, parent_doc_ref: {...}}`
- `get_document`: `{doc_ref: {...}, title: str, url: str | null, content_markdown: str | null}` 或 `null`

## 4. Outline REST API 真实 schema（Outline OpenAPI spec3.yml 一手参考）

```python
# documents.create — POST /api/documents.create
# Auth: Bearer api_token
# Body:
{
    "title": "string",
    "text": "markdown_string",      # ← markdown 透传，Outline 原生接受
    "collectionId": "uuid",          # required
    "parentDocumentId": "uuid | null",
    "publish": true,                  # 默认 true，让创建后立即可见
}
# Response 200:
{
    "data": {
        "id": "uuid",
        "url": "/doc/slug-uuid",     # relative URL；客户端拼 base_url
        "title": "string",
        "text": "markdown",
        # ... 其他字段
    }
}

# documents.update — POST /api/documents.update
# Body:
{
    "id": "uuid",
    "text": "new_full_markdown",     # 全量替换（append=false）
    "title": "optional_new_title",
    "append": false,                  # 默认 false = 全量替换
}
# Response 200: { "data": { ... } }

# comments.create — POST /api/comments.create
# Body:
{
    "documentId": "uuid",
    "data": { "type": "doc", "content": [...] },   # ProseMirror JSON
    "parentCommentId": "optional uuid",
}
# Response 200: { "data": { "id": "uuid", ... } }
# NOTE: Outline comments 是 ProseMirror JSON 不是 markdown
# v1 简化：把 markdown 包成单 paragraph 的 ProseMirror JSON
#   {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"<body>"}]}]}

# documents.info — POST /api/documents.info（不是 GET，是 POST!）
# Body: { "id": "uuid" }
# Response 200: { "data": { id, title, text, urlId, url, ... } }
```

## 5. Outline 限速策略（Pitfall 4 + Pitfall 12）

- Outline 默认 `RATE_LIMITER_REQUESTS=1000` per minute per IP
- daemon 是单 IP / 多 workspace 共享 → 高并发触发 429
- 重试策略（**plan 06 tenacity 调优前的 v1 baseline**）:
  - tenacity AsyncRetrying
  - stop_after_attempt(3)（共 3 次：1 原 + 2 retry）
  - wait_exponential(multiplier=1, min=1, max=4) → 1s, 2s
  - retry_if_exception_type(httpx.HTTPStatusError) AND `exc.response.status_code in (429, 502, 503, 504)`
  - **总耗时上限 ~10s**（1 + 1 + 2 + 3*2 = 9-10s）< daemon invoke_timeout 30s 的 1/3（Pitfall 12 防超）

</interfaces>
</context>

<reference>
## CLAUDE.md §2.7 Reference-First — Dify 模块映射

我实现的是什么：**OutlinePlugin daemon — DocCapability 单 capability，httpx 直调 Outline REST API + tenacity 429 重试**。
Dify 有没有类似功能：有 — Dify 的 `api/core/workflow/nodes/http_request/` (HTTP 节点 retry / timeout / rate limit 模式) 与本 plan 高度同构；`api/core/tools/` (tool credential schema) 与 OutlinePlugin manifest config_schema 同构。

**必读 Dify 模块**（Task 0 读完写 reading doc）:
1. **后端**: `/Users/admin/ai/ref/dify/repo/api/core/workflow/nodes/http_request/` — 重点 `node.py` (HTTP node retry / 5xx 处理) + `entities.py` (RequestData schema)
2. **后端**: `/Users/admin/ai/ref/dify/repo/api/core/tools/` — 重点 `entities/tool_entities.py` (ToolParameter / ToolProviderCredentials schema)
3. （可选）**前端**: `/Users/admin/ai/ref/dify/repo/web/app/components/workflow/nodes/http/` — HTTP 节点 retry UI（与本 plan 后端无关，但理解最终 UX）

**借鉴重点**（reading doc §可借鉴的设计模式 必含 5 条）:
1. **Dify HTTP node retry on 5xx / 429**：retry 次数 + 退避策略（对照本 plan tenacity AsyncRetrying 2 次 + wait_exponential 1s/2s）
2. **Dify timeout 分层**：connect_timeout / read_timeout / total_timeout 分别配置 → 对照本 plan `httpx.Timeout(timeout=10.0)` 简化为单 total
3. **Dify ToolProviderCredentials schema**：每 tool 声明 credentials 字段类型 + UI form_type → 对照本 plan platform.yaml `config_schema.properties.api_token.format=password`
4. **Dify HTTP body content_type**：json / form / raw 区分 → 对照本 plan 全部 json（Outline 无 multipart 路径）
5. **Dify error envelope**：HTTP 4xx/5xx → node error 不是 raw exception → 对照本 plan daemon dispatcher 把 httpx exception 包成 JSONRPC -32000

**License**: Dify AGPL-3.0；OutlinePlugin Apache-2.0 + 100% 独立创作。**严禁拷贝**任何 Dify 源代码；仅借鉴**设计模式 / 字段命名思路 / retry 策略**。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify HTTP node retry + tool credential schema 阅读笔记（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05c-03-outline-plugin-2026-05-18.md</files>
  <action>
**STOP — 这是 Task 1-7 所有 commit 的前置 gate**。CLAUDE.md §2.7 强制要求：先 commit 此 reading doc 才允许写代码。

**Read 阶段**（仅 Read 不修改）：

1. `/Users/admin/ai/ref/dify/repo/api/core/workflow/nodes/http_request/node.py` — HTTP node retry / 429 / 5xx 处理
   - grep `retry|429|timeout|backoff` 上下文 20 行
2. `/Users/admin/ai/ref/dify/repo/api/core/workflow/nodes/http_request/entities.py` — RequestData / HttpResponse schema
3. `/Users/admin/ai/ref/dify/repo/api/core/tools/entities/tool_entities.py` — ToolProviderCredentials / form_type=password
   - grep `class ToolProviderCredentials|form_type|credentials_schema` 上下文 20 行

**Write 阶段** — 写到 `docs/reading-dify-05c-03-outline-plugin-2026-05-18.md`，**完全按 CLAUDE.md §2.7 模板**：

```markdown
# Dify 阅读笔记 — OutlinePlugin daemon HTTP retry + credential schema

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (commit ${LOCAL_HEAD}, /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> Outline OpenAPI 一手参考: https://github.com/outline/openapi/blob/main/spec3.yml
> Stars: Dify ~141k / Outline ~32k

## 项目概述（一句话）
Dify HTTP 节点 + Tool credential schema 是其与 OutlinePlugin（httpx + manifest config_schema）高度同构的两个参考点。

## 技术栈对照
| 维度 | Dify HTTP node | OutlinePlugin |
|---|---|---|
| HTTP client | httpx (synchronous) | httpx (async) |
| Retry | 自实现 exponential backoff | tenacity AsyncRetrying |
| Credentials | ToolProviderCredentials schema | manifest.config_schema JSON Schema |
| Timeout | connect/read 分层 | 单 total_timeout 简化 |
| Error envelope | NodeException | JSONRPC -32000 |

## 架构要点（简图）
Dify HTTP 节点链路:
  WorkflowEntry → HttpRequestNodeData → http_request_node.execute()
    → httpx.Client.request() with retry decorator
    → response → mapping_outputs → return Variable

OutlinePlugin 链路（参考 Dify 抽象）:
  PlatformDaemonClient.invoke("doc", "create_document", ...)
    → JSONRPC over stdio → daemon main() dispatch
    → METHODS["doc.create_document"](params)
    → OutlineClient(api_token).documents_create()
    → tenacity AsyncRetrying wrap httpx.post() → response.json()["data"]
    → return {plugin_name, native_id, extras} → JSONRPC success envelope

## 可借鉴的设计模式（5 条必含）
1. **HTTP retry on 5xx / 429**（Dify `http_request/node.py:...`）
   Dify 设计：retry 次数可配 + 5xx 与 429 区分对待 + exponential backoff
   → OutlinePlugin 用 tenacity AsyncRetrying + `retry_if_exception_type(httpx.HTTPStatusError) & status in (429, 502, 503, 504)` + wait_exponential(min=1, max=4)
2. **Timeout 分层**（Dify `http_request/entities.py:HttpRequestNodeTimeout`）
   Dify 设计：connect_timeout / read_timeout / max_connect_timeout 分别可配
   → OutlinePlugin 简化为单 `httpx.Timeout(10.0)` total；理由：plugin daemon 内部不暴露 HTTP timeout UI，简化用户配置
3. **Tool credentials schema**（Dify `tool_entities.py:ToolProviderCredentials`）
   Dify 设计：每 credential 字段声明 `form_type` (secret-input/text-input/select)、`required`、`label.zh_CN`
   → OutlinePlugin platform.yaml `config_schema.properties.api_token.format=password` + `required: [api_token, base_url]`
4. **HTTP body content-type**（Dify `http_request/entities.py:HttpRequestNodeBody.type`）
   Dify 设计：json / form-data / x-www-form-urlencoded / raw / binary 区分
   → OutlinePlugin 全部 json（Outline 6 endpoint 都接受 application/json；无 multipart 路径）
5. **Error envelope 翻译**（Dify NodeException + status_code）
   Dify 设计：HTTP error → NodeException (含 message + execution_metadata.error)，不是 raw httpx 抛出
   → OutlinePlugin daemon dispatcher (Pattern 1 from huly_plugin.py)：捕获 httpx.HTTPStatusError → -32000 业务错误；NotImplementedError → -32603 internal

## Outline OpenAPI 关键 endpoint 对照（一手参考）
- POST /api/documents.create — 接受 markdown 透传（text 字段直接 markdown）
- POST /api/documents.update — append=false 即全量替换
- POST /api/comments.create — data 是 ProseMirror JSON（不是 markdown）
- POST /api/documents.info — POST 不是 GET（与一般 REST 反直觉）
- 鉴权：Bearer api_token in Authorization header
- 限速：默认 1000 req/min/IP（self-host 可调）

## 与本项目的关系
本 plan 实现 OutlinePlugin daemon — 完全照 Dify HTTP 节点的 retry + credential schema 设计模式，但用 tenacity + manifest.yaml 替代 Dify 自实现的 retry / ToolProviderCredentials 类。Phase 5.C 04 (LarkDocsPlugin) + 05/06/07 (HulyPlugin) 会复用本 plan 验证过的 daemon pattern + AllowlistTransport 集成模式。

## License 与 attribution
- Dify AGPL-3.0 + Python 同步 HTTP node
- agent-builder Apache-2.0 + Python async OutlinePlugin
- 100% 独立创作；仅借鉴**设计模式 / retry 策略 / credential schema 思路**
- 严禁拷贝 Dify 源代码（含 retry decorator 实现细节 / NodeException 类名等）
```

**质量门**:
- 至少 80 行
- 5 个可借鉴的设计模式必须**每条**指明 Dify 文件路径 + OutlinePlugin 对应实现位置
- License 段必须含"100% 独立创作 / 严禁拷贝"
- **不要**贴 Dify 源代码片段（许可证）

commit message: `docs(05c-03): add Dify HTTP retry + tool credential reading doc`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-03-outline-plugin-2026-05-18.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-03-outline-plugin-2026-05-18.md | awk '{exit ($1 >= 80 ? 0 : 1)}' && grep -q "AGPL-3.0" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-03-outline-plugin-2026-05-18.md && grep -q "Apache-2.0" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-03-outline-plugin-2026-05-18.md && grep -q "可借鉴的设计模式" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-03-outline-plugin-2026-05-18.md && grep -q "100% 独立创作" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-03-outline-plugin-2026-05-18.md</automated>
  </verify>
  <done>Reading doc 存在 ≥ 80 行 + 含 AGPL/Apache attribution + 含"可借鉴的设计模式"段 + 含"100% 独立创作"声明 + 已 git commit（hash 早于所有其他 task commit）</done>
</task>

<task type="auto">
  <name>Task 1: OutlinePlugin manifest.yaml + 包结构 + 注册</name>
  <files>plugins/__init__.py,plugins/outline/__init__.py,plugins/outline/platform.yaml,plugins/outline/_internal/__init__.py,plugins/outline/prompts/ai_suggest_mentions_zh.md,backend/tests/platforms/fixtures/manifest_outline.yaml</files>
  <action>
Reading doc 已 commit ✓（CLAUDE.md §2.7 gate 通过）→ 开始写代码。

### 1. 创建空 `plugins/__init__.py` （顶层 plugins 包标记）

```python
"""Phase 5.C plugins root package — 容纳所有 platform plugin（outline / lark_docs / huly / ...）。

每个子目录是一个独立 plugin（含 platform.yaml manifest + daemon entry）。
PluginRegistry.discover('plugins/') 启动期扫描所有子目录注册可用 plugin。

License: 各 plugin 独立声明 license；本 __init__.py 仅命名空间标记，无逻辑。
"""
```

### 2. 创建 `plugins/outline/__init__.py`

```python
"""Outline platform plugin — Phase 5.C plan 03 (DocCapability only)。

仅声明 doc capability（Outline 不支持 IM / HR / Identity 协作角色）。

设计要点：
- supports_collaborative_edit = False（Outline 用全量 markdown 替换，不支持 CRDT delta）
- supports_comments = True
- AllowlistTransport 强制（httpx 出站走 make_sandboxed_http_client）
- tenacity 重试 429/5xx（Outline 默认 1000 req/min/IP）

License: 100% 独立创作（Apache-2.0），仅借鉴 Dify HTTP node retry + tool credential schema 设计模式（AGPL-3.0），不拷贝任何源代码。
参考阅读笔记：docs/reading-dify-05c-03-outline-plugin-2026-05-18.md
"""
```

### 3. 创建 `plugins/outline/_internal/__init__.py`

```python
"""OutlinePlugin internal modules — daemon 内部使用，外部不应 import。

- outline_client.py: httpx wrapper (AllowlistTransport + tenacity retry)
"""
```

### 4. 创建 `plugins/outline/platform.yaml` （**核心 manifest**）

```yaml
# Phase 5.C plan 03 — OutlinePlugin manifest
#
# 用途：
# - PluginRegistry.discover("plugins/") 启动期扫描注册
# - PlatformDaemonClient 通过 runtime.entry 启动 daemon 子进程
# - DocFacade.supports_collaborative_edit 读 doc.supports_collaborative_edit
#
# Reference: docs/reading-dify-05c-03-outline-plugin-2026-05-18.md §3 credential schema 借鉴

name: outline
version: 1.0.0
description: "Outline 协作文档平台 plugin —— DocCapability only（markdown 全量替换 + ProseMirror 评论）"
license: Apache-2.0
agent_builder_version: ">=1.0"

runtime:
  type: python
  entry: plugins.outline.outline_plugin
  python_version: "3.11"

capabilities:
  - doc

# Workspace 配置 schema（前端 5.C 自动渲染配置表单）
config_schema:
  type: object
  required:
    - base_url
    - api_token
    - default_collection_id
  properties:
    base_url:
      type: string
      format: uri
      description: "Outline 实例根 URL（如 https://outline.example.com，无尾随 /api）"
    api_token:
      type: string
      format: password
      description: "Outline 用户 API token（Outline 设置 → API token 创建）"
    default_collection_id:
      type: string
      format: uuid
      description: "默认创建文档放入的 collection UUID"
    cache_ttl_seconds:
      type: integer
      default: 3600
      minimum: 60
      description: "可选 — get_document content cache TTL（v1 暂未使用，留 v1.1）"

# Doc capability flags（DocFacade.supports_* 读这里）
doc:
  supports_collaborative_edit: false   # Outline 不支持 CRDT delta → apply_document_delta 抛 NotImplementedError
  supports_comments: true              # add_comment 实现走 ProseMirror JSON

# Phase 5.B 沙箱配置
sandbox:
  cpu_limit: "0.5"                     # 半核（OutlinePlugin 是 IO bound，CPU 占用低）
  memory: "256Mi"                      # 256MB（httpx + json 解析够用）
  network:
    # exact host:port 白名单（manifest validator 强制 ^[a-z0-9.-]+:\d+$）
    # 生产环境 workspace 安装时由 admin 覆盖为真实 Outline 实例 host:port
    # 此处放占位 — 集成测 fixture 通过 env PLUGIN_NETWORK_ALLOW 注入 127.0.0.1:18088
    - "outline.example.com:443"
  timeout_invoke: 30                   # daemon invoke timeout 30s（与 Phase 5.B 默认对齐）
  timeout_idle: 300                    # daemon idle reaper 5 分钟
  use_cgroups: false                   # macOS dev / Linux 默认 baseline；Plan 05b-04 cgroups 切换
  env_allowlist:
    # OutlinePlugin daemon 需要的 env 白名单（其他 env strip-all 防 secret 泄漏 — Pitfall 8）
    - "PLUGIN_NETWORK_ALLOW"           # Phase 5.B AllowlistTransport 注入入口
    - "OUTLINE_BASE_URL"               # 集成测覆盖 base_url（生产从 workspace config 读）
    - "OUTLINE_API_TOKEN"              # 集成测覆盖 api_token（生产从 vault 读）
```

### 5. 创建 fixture manifest `backend/tests/platforms/fixtures/manifest_outline.yaml`

复制 plugins/outline/platform.yaml 内容到此 fixture，让 test_outline_plugin.py 加载（避免 cwd 问题）：

```yaml
# Test fixture for OutlinePlugin manifest — Phase 5.C plan 03
# 内容与 plugins/outline/platform.yaml 一致（让 manifest schema + plugin spawn test 共用）
# 集成测引用此 fixture 做加载校验

name: outline
version: 1.0.0
description: "Outline 协作文档平台 plugin —— test fixture"
license: Apache-2.0
agent_builder_version: ">=1.0"

runtime:
  type: python
  entry: plugins.outline.outline_plugin
  python_version: "3.11"

capabilities:
  - doc

config_schema:
  type: object
  required:
    - base_url
    - api_token
    - default_collection_id
  properties:
    base_url:
      type: string
      format: uri
    api_token:
      type: string
      format: password
    default_collection_id:
      type: string
      format: uuid

doc:
  supports_collaborative_edit: false
  supports_comments: true

sandbox:
  cpu_limit: "0.5"
  memory: "256Mi"
  network:
    - "127.0.0.1:18088"               # test 用 mock outline server
  timeout_invoke: 5
  timeout_idle: 60
  use_cgroups: false
  env_allowlist:
    - "PLUGIN_NETWORK_ALLOW"
    - "OUTLINE_BASE_URL"
    - "OUTLINE_API_TOKEN"
```

### 6. 创建 `plugins/outline/prompts/ai_suggest_mentions_zh.md` （v1 placeholder）

```markdown
# OutlinePlugin AI Suggest Mentions Prompt (Chinese, v1 placeholder)

> Plan 06 真实现 ai_suggest_mentions 时使用此 prompt 模板。
> v1（plan 03）只占位 — daemon handler raise NotImplementedError。
> Reference: 05c-CONTEXT.md §Decision 7 ai_suggest_mentions LLM 钩子

## Schema

输入：
- markdown: str — 文档内容（截断至前 4000 字符避免 token 超限）
- context: dict — workspace_id / document_id / author_id 等元信息

输出：
- mentions: list[MentionSuggestion]
  - user_ref: UserRef
  - confidence: float 0.0-1.0
  - rationale: str（简短中文说明，≤ 50 字）

## 模板（v1 placeholder，plan 06 替换为真 LLM prompt）

```
你是协作文档 mention 推荐助手。根据以下文档内容，建议 @ 哪些用户审核或参与讨论。

文档内容：
{markdown}

可选用户列表（从 IdentityCapability.list_users 拉取）：
{users}

请返回 JSON 数组，每项含 user_id / confidence / rationale。
仅返回最相关的 ≤ 3 人。
```

## 失败 fallback

LLM 调用失败 / 解析失败 / 超时 → daemon handler 返回空 list + structured log（不阻塞节点）。
```

注：v1 此文件**仅占位**，daemon `ai_suggest_mentions` handler 直接 raise NotImplementedError（不读此模板）。Plan 06 真实现时再激活。

### 7. 校验 manifest

```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend
python -c "
from app.agent_builder.platforms.manifest import load_manifest
m = load_manifest('../plugins/outline/platform.yaml')
assert m.name == 'outline'
assert 'doc' in m.capabilities
assert m.doc.supports_collaborative_edit is False
assert m.doc.supports_comments is True
assert m.sandbox is not None
assert '127.0.0.1:18088' not in m.sandbox.network, '生产 manifest 不应含 test mock URL'
assert 'PLUGIN_NETWORK_ALLOW' in m.sandbox.env_allowlist
print('manifest OK:', m.name, m.version, m.capabilities)
"
```

commit messages（拆 3 个）:
- `feat(05c-03): add plugins/__init__.py + outline package skeleton`
- `feat(05c-03): add OutlinePlugin platform.yaml manifest + test fixture`
- `feat(05c-03): add ai_suggest_mentions_zh.md prompt placeholder (plan 06 真实现)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "from app.agent_builder.platforms.manifest import load_manifest; m = load_manifest('../plugins/outline/platform.yaml'); assert m.name == 'outline' and 'doc' in m.capabilities and m.doc.supports_collaborative_edit is False and m.doc.supports_comments is True and m.sandbox is not None and 'PLUGIN_NETWORK_ALLOW' in m.sandbox.env_allowlist; m2 = load_manifest('tests/platforms/fixtures/manifest_outline.yaml'); assert m2.name == 'outline' and '127.0.0.1:18088' in m2.sandbox.network; print('manifest schema OK')"</automated>
  </verify>
  <done>plugins/__init__.py + plugins/outline/__init__.py + plugins/outline/_internal/__init__.py 存在；plugins/outline/platform.yaml + 测试 fixture manifest_outline.yaml 解析成功并满足所有约束（capabilities=[doc] / supports_collaborative_edit=False / sandbox.env_allowlist 含 PLUGIN_NETWORK_ALLOW）；prompts/ai_suggest_mentions_zh.md ≥ 10 行</done>
</task>

<task type="auto">
  <name>Task 2: OutlineClient (httpx wrapper + AllowlistTransport + tenacity retry)</name>
  <files>plugins/outline/_internal/outline_client.py,backend/requirements.txt</files>
  <action>
### 1. 确认 tenacity 在 requirements.txt

```bash
grep -E "^tenacity" /Users/admin/ai/resume/interview/liuxin/agent-builder/backend/requirements.txt
# 预期：tenacity==8.2.3 或更高（Phase 3 已锁）
```

若未含则追加：`tenacity==8.2.3`（与 Phase 3.04 / 05c-RESEARCH §Don't Hand-Roll 锁定一致）。

### 2. 创建 `plugins/outline/_internal/outline_client.py`

```python
"""OutlineClient — httpx wrapper for Outline REST API (Phase 5.C plan 03)。

设计要点（05c-RESEARCH §Pattern 2 + Pitfall 4 + reading doc 借鉴点）:
- **强制走 AllowlistTransport**（CONTEXT.md §Critical constraints）—— 通过
  `make_sandboxed_http_client(allow_list, timeout)` 拿沙箱化 httpx.AsyncClient；
  禁止直接 httpx.AsyncClient() / aiohttp.ClientSession()
- **tenacity AsyncRetrying** wrap 所有 POST（Pitfall 4 / Pitfall 12）：
  - stop_after_attempt(3) = 1 原 + 2 retry
  - wait_exponential(multiplier=1, min=1, max=4) = 1s, 2s
  - retry_if_exception_type httpx.HTTPStatusError 且 status_code in (429, 502, 503, 504)
  - 总耗时 ≤ 10s（< daemon invoke_timeout 30s 的 1/3）
- **endpoint 列表**（v1 实现 5 个 + get_document 1 个）：
  - POST /api/documents.create
  - POST /api/documents.update (append=false 即全量替换)
  - POST /api/comments.create (data 是 ProseMirror JSON)
  - POST /api/documents.info (注意是 POST 不是 GET)
- credentials 从构造参数取（daemon main() 从 env / config 读后传入），**不裸 import os.environ**
- structured log 字段：method / url / latency_ms / status_code / outcome（Phase 7 Run Viewer 钩子）

License: 100% 独立创作（Apache-2.0），仅借鉴 Dify HTTP node retry 设计模式（AGPL-3.0）。
参考阅读笔记：docs/reading-dify-05c-03-outline-plugin-2026-05-18.md
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# AllowlistTransport — Phase 5.B 强制走的安全网络出口
from app.agent_builder.platforms.sandbox.network import make_sandboxed_http_client

_log = logging.getLogger("agent_builder.plugins.outline.client")

# Retry 触发条件：429 限速 + 5xx 服务端瞬时故障
_RETRYABLE_STATUS = {429, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    """tenacity retry_if_exception 谓词 — 仅对 429/5xx HTTPStatusError 重试。

    不重试：
    - 4xx 客户端错误（401 鉴权失败 / 404 doc 不存在 / 400 bad request）
    - httpx.ConnectError 等网络层错误（NetworkBlockedError 是其子类不能重试）
    - 任意非 httpx 异常
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


class OutlineClient:
    """httpx wrapper for Outline REST — daemon 内单例（main() 启动时构造）。

    用法（daemon entrypoint 内）::

        client = OutlineClient(
            base_url="https://outline.example.com",
            api_token="abc...",
            allow_list=["outline.example.com:443"],
            timeout=10.0,
        )
        doc = await client.documents_create(
            title="Hello", text="# Hello\\n\\nWorld",
            collection_id="uuid-...", parent_document_id=None, publish=True,
        )
        # doc == {"id": "uuid", "url": "/doc/...", "title": "Hello", "text": "...", ...}

    Args:
        base_url: Outline 根 URL（无尾随 /api），如 "https://outline.example.com"
        api_token: Outline API token (Bearer)
        allow_list: AllowlistTransport 白名单（["host:port", ...]）—— 必须含 base_url 的 host
        timeout: 单 HTTP 请求总超时（秒），默认 10s
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        allow_list: list[str],
        timeout: float = 10.0,
    ) -> None:
        self._api_base = base_url.rstrip("/") + "/api"
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self._allow_list = list(allow_list)
        self._timeout = timeout

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST {path} with json body — 内部统一 retry + log + raise_for_status。

        Path 形如 "/documents.create"（前导 / 必带，避免 path join 错）。

        Returns:
            response.json() 完整 dict（含 "data" 键 — 调用方按需取）
        Raises:
            httpx.HTTPStatusError: 4xx / 5xx 经 retry 后仍失败
            tenacity.RetryError: retry 累计 3 次仍失败（用 .last_attempt.exception() 取原因）
            NetworkBlockedError: AllowlistTransport 拦截（不在 retry 列表 — 安全 baseline）
        """
        url = f"{self._api_base}{path}"
        start = time.monotonic()
        status_code = -1

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    # AllowlistTransport — Phase 5.B 安全出口，不允许绕过
                    async with make_sandboxed_http_client(
                        self._allow_list, timeout=self._timeout
                    ) as http:
                        resp = await http.post(url, headers=self._headers, json=body)
                        status_code = resp.status_code
                        resp.raise_for_status()
                        return resp.json()
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            raise
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            outcome = (
                "success" if 200 <= status_code < 300
                else "rate_limited" if status_code == 429
                else "error"
            )
            _log.info(
                "outline.api.call method=POST path=%s status=%s latency_ms=%d outcome=%s",
                path, status_code, latency_ms, outcome,
            )

    # ── DocCapability 真实现 ───────────────────────────────────────────────────

    async def documents_create(
        self,
        *,
        title: str,
        text: str,
        collection_id: str,
        parent_document_id: str | None = None,
        publish: bool = True,
    ) -> dict[str, Any]:
        """POST /api/documents.create — 新建文档（markdown 透传到 text 字段）。

        Outline OpenAPI: documents.create
        Returns: response["data"] = {id, url, title, text, ...}
        """
        body = {
            "title": title,
            "text": text,
            "collectionId": collection_id,
            "parentDocumentId": parent_document_id,
            "publish": publish,
        }
        result = await self._post_json("/documents.create", body)
        return result["data"]

    async def documents_update(
        self,
        *,
        doc_id: str,
        text: str,
        title: str | None = None,
        append: bool = False,
    ) -> dict[str, Any]:
        """POST /api/documents.update — 全量替换 (append=False) 或追加 (append=True)。

        默认 append=False = 全量替换 markdown（replace_document_content 走这里）。
        """
        body = {
            "id": doc_id,
            "text": text,
            "title": title,
            "append": append,
        }
        result = await self._post_json("/documents.update", body)
        return result["data"]

    async def comments_create(
        self,
        *,
        document_id: str,
        data: dict[str, Any],
        parent_comment_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/comments.create — 评论 data 是 ProseMirror JSON (非 markdown)。

        v1 简化：daemon handler 把 markdown body 包成单 paragraph ProseMirror:
          {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":body}]}]}
        """
        body = {
            "documentId": document_id,
            "data": data,
            "parentCommentId": parent_comment_id,
        }
        result = await self._post_json("/comments.create", body)
        return result["data"]

    async def documents_info(self, *, doc_id: str) -> dict[str, Any] | None:
        """POST /api/documents.info — 查文档元信息 + content（注意是 POST 不是 GET）。

        Returns: response["data"] 或 None（doc 不存在 → 404 转 None）
        """
        body = {"id": doc_id}
        try:
            result = await self._post_json("/documents.info", body)
            return result.get("data")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise


__all__ = ["OutlineClient"]
```

### 3. 避坑（在 code 中已注释，此处复述）

- `make_sandboxed_http_client` 每次调用都新建 client — 这是简化方案；若高并发性能不达标，plan 06 可改为模块级单例 + lazy lock（与 huly_plugin._ensure_client 同模式）
- `NetworkBlockedError` 是 `Exception` 子类不是 `httpx.HTTPStatusError` — 不会被 _is_retryable 命中（正确，不应重试白名单拦截）
- tenacity `reraise=True` 让最后一次的 exception 直接抛（不包成 RetryError）—— daemon dispatcher 见到 httpx.HTTPStatusError 转 -32000 错误清晰
- `documents.info` 是 POST（Outline 设计反直觉 — OpenAPI spec3.yml 明确）
- `comments.create` data 字段是 ProseMirror JSON dict — daemon handler 负责把 markdown body 包成单 paragraph（v1 简化）

commit messages（拆 2 个）:
- `feat(05c-03): add OutlineClient httpx wrapper + AllowlistTransport + tenacity retry`
- `chore(05c-03): pin tenacity==8.2.3 in requirements.txt (if missing)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "import sys; sys.path.insert(0, '..'); from plugins.outline._internal.outline_client import OutlineClient; c = OutlineClient(base_url='https://example.com', api_token='x', allow_list=['example.com:443'], timeout=5.0); assert c._api_base == 'https://example.com/api'; assert 'Authorization' in c._headers and c._headers['Authorization'] == 'Bearer x'; assert c._allow_list == ['example.com:443']; assert c._timeout == 5.0; print('OutlineClient OK')" && grep -E "^tenacity" /Users/admin/ai/resume/interview/liuxin/agent-builder/backend/requirements.txt</automated>
  </verify>
  <done>OutlineClient 可 import + 构造正常 + _api_base / _headers / _allow_list / _timeout 字段符合预期；4 个方法签名（documents_create / documents_update / comments_create / documents_info）已定义；tenacity 在 requirements.txt 锁定</done>
</task>

<task type="auto">
  <name>Task 3: OutlinePlugin daemon entry (JSONRPC dispatch + 5 doc handlers + ai_suggest_mentions stub)</name>
  <files>plugins/outline/outline_plugin.py</files>
  <action>
### 创建 `plugins/outline/outline_plugin.py` （**daemon 主入口** — 子进程跑 `python -u -m plugins.outline.outline_plugin`）

参考 plugins/huly/huly_plugin.py 的 JSONRPC dispatch 主循环模式（已 Phase 5.A 验证），改造为 doc capability handlers：

```python
"""OutlinePlugin daemon entrypoint — JSONRPC over stdio (Phase 5.C plan 03)。

子进程跑 ``python -u -m plugins.outline.outline_plugin``：

- 主循环：从 stdin 行级读取 JSONRPC envelope
- 路由 method 名（"doc.<method>"）到对应 handler
- 结果走 stdout（行分隔 JSON envelope）

DocCapability 范围（v1 完整 6 method）:
- ``doc.create_document`` → POST /api/documents.create
- ``doc.replace_document_content`` → POST /api/documents.update (append=false)
- ``doc.apply_document_delta`` → raise NotImplementedError（Outline 不支持 CRDT）
- ``doc.add_comment`` → POST /api/comments.create（markdown 包成 ProseMirror）
- ``doc.get_document`` → POST /api/documents.info
- ``doc.ai_suggest_mentions`` → raise NotImplementedError（plan 06 真实现）

设计要点：
- 与 huly_plugin.py 同 daemon 主循环结构（JSONRPC 2.0 + stdin/stdout 行级 + stderr log）
- METHODS dict 集中路由 — 易扩展
- Error code 约定：
  - -32601: Method not found（METHODS dict 没有这个 method 名）
  - -32603: Internal error（含 NotImplementedError — Outline 不支持的 method）
  - -32000~-32099: 业务错误（HTTP 4xx/5xx / Outline 鉴权失败 / 频率限制经 retry 仍 fail）
- 启动时 lazy 构造 OutlineClient（首次调用时初始化，复用单例）—— 与 huly _ensure_client 同模式
- env 注入约定（manifest env_allowlist 已声明）：
  - ``PLUGIN_NETWORK_ALLOW``: AllowlistTransport 白名单（comma-separated host:port）
  - ``OUTLINE_BASE_URL``: Outline 实例根 URL（生产从 workspace config 读 + daemon_client 注入）
  - ``OUTLINE_API_TOKEN``: API token（生产从 vault 读 + daemon_client 注入）

License: 100% 独立创作；借鉴 plugins/huly/huly_plugin.py 同仓 main 循环模式（Apache-2.0 同项目）。
参考阅读笔记：docs/reading-dify-05c-03-outline-plugin-2026-05-18.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

# ── 配置 ────────────────────────────────────────────────────────────────────────

_log = logging.getLogger("agent_builder.plugins.outline.daemon")


def _parse_network_allow() -> list[str]:
    """从 env ``PLUGIN_NETWORK_ALLOW`` 解出 ``["host:port", ...]`` 白名单。

    主进程（Phase 5.B daemon_client）会从 manifest ``sandbox.network`` 转化为 ``,``
    分隔字符串注入子进程；本函数解析后传给 ``OutlineClient(allow_list=...)``。
    """
    raw = os.environ.get("PLUGIN_NETWORK_ALLOW", "")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


# ── Lazy OutlineClient 单例（daemon 进程内）─────────────────────────────────────

# 模块级 lazy 单例（与 huly_plugin._client 同模式）
_outline_client: Any = None  # OutlineClient | None — 用 Any 避免 import 顺序问题
_client_lock = asyncio.Lock()


async def _ensure_client() -> Any:
    """daemon 首次调用时构造 OutlineClient（lazy）。

    避免在模块顶层 import OutlineClient → 让 daemon 启动时即使 OUTLINE_API_TOKEN
    未设也不立即崩溃（仅在真调用 method 时才报错，易于调试）。
    """
    global _outline_client
    if _outline_client is not None:
        return _outline_client

    async with _client_lock:
        if _outline_client is not None:
            return _outline_client

        # lazy import — 子进程 PYTHONPATH 若未含 backend/ 则 import 会失败，但仅在真调用时触发
        from plugins.outline._internal.outline_client import OutlineClient

        base_url = os.environ.get("OUTLINE_BASE_URL")
        api_token = os.environ.get("OUTLINE_API_TOKEN")
        if not base_url or not api_token:
            raise RuntimeError(
                "OutlinePlugin daemon: OUTLINE_BASE_URL + OUTLINE_API_TOKEN env 必须设置 "
                "(by daemon_client from workspace config / vault)"
            )

        allow_list = _parse_network_allow()
        if not allow_list:
            raise RuntimeError(
                "OutlinePlugin daemon: PLUGIN_NETWORK_ALLOW env 未设置 — "
                "AllowlistTransport 拒所有出站（Phase 5.B 安全 baseline）"
            )

        _outline_client = OutlineClient(
            base_url=base_url,
            api_token=api_token,
            allow_list=allow_list,
            timeout=10.0,
        )
        _log.info("outline.daemon.client_ready base_url=%s allow_size=%d", base_url, len(allow_list))
        return _outline_client


# ── Capability handlers ──────────────────────────────────────────────────────


async def doc_create_document(params: dict[str, Any]) -> dict[str, Any]:
    """DocCapability.create_document(title, markdown, owners=None) 真实现。

    params 来自主进程 DocFacade.create_document：
    - title: str
    - markdown: str
    - owners: list[dict]  # asdict(UserRef) — v1 OutlinePlugin 不传 collaborators API（留 plan 06）
    """
    client = await _ensure_client()

    title = params["title"]
    text = params["markdown"]
    # default_collection_id 从 workspace config 读 → daemon_client 注入 env
    # v1 简化：用 env OUTLINE_DEFAULT_COLLECTION_ID（生产时与 OUTLINE_API_TOKEN 同路径）
    collection_id = os.environ.get("OUTLINE_DEFAULT_COLLECTION_ID", "")
    if not collection_id:
        raise RuntimeError(
            "OutlinePlugin: OUTLINE_DEFAULT_COLLECTION_ID env 未设置 "
            "(daemon_client 应从 workspace config.default_collection_id 注入)"
        )

    doc_data = await client.documents_create(
        title=title,
        text=text,
        collection_id=collection_id,
        parent_document_id=None,
        publish=True,
    )

    return {
        "plugin_name": "outline",
        "native_id": doc_data["id"],
        "extras": {
            "url": doc_data.get("url", ""),
        },
    }


async def doc_replace_document_content(params: dict[str, Any]) -> None:
    """DocCapability.replace_document_content(doc_ref, markdown) 真实现 — 全量替换。

    params:
    - doc_ref: dict  # asdict(DocRef) — 取 native_id 作 outline doc id
    - markdown: str
    """
    client = await _ensure_client()
    doc_id = params["doc_ref"]["native_id"]
    text = params["markdown"]
    await client.documents_update(doc_id=doc_id, text=text, append=False)
    return None


async def doc_apply_document_delta(params: dict[str, Any]) -> None:
    """DocCapability.apply_document_delta — Outline 不支持 CRDT delta。

    raise NotImplementedError → daemon dispatcher 转 JSONRPC -32603（与 manifest
    supports_collaborative_edit=False 一致；service layer fallback 应走
    replace_document_content）。
    """
    raise NotImplementedError(
        "Outline 不支持 CRDT delta — 调用方应检查 supports_collaborative_edit "
        "为 False 时走 replace_document_content"
    )


async def doc_add_comment(params: dict[str, Any]) -> dict[str, Any]:
    """DocCapability.add_comment(doc_ref, body, mentions=None) 真实现。

    Outline comments.create data 字段是 ProseMirror JSON（非 markdown）。
    v1 简化：把 markdown body 包成单 paragraph ProseMirror。
    v1 不支持 @ mention（lark_open_id / outline user_id 解析在 plan 06 + 5.D）。

    params:
    - doc_ref: dict  # asdict(DocRef)
    - body: str  # markdown
    - mentions: list[dict]  # asdict(UserRef) — v1 暂未使用
    """
    client = await _ensure_client()
    doc_id = params["doc_ref"]["native_id"]
    body = params["body"]

    # v1 简化：单 paragraph ProseMirror（plan 06 用 marko AST 转换更完整）
    prosemirror_data = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": body}],
            }
        ],
    }

    comment_data = await client.comments_create(
        document_id=doc_id,
        data=prosemirror_data,
        parent_comment_id=None,
    )

    return {
        "plugin_name": "outline",
        "native_id": comment_data["id"],
        # parent_doc_ref 透传回去让 facade 重建 CommentRef
        "parent_doc_ref": params["doc_ref"],
    }


async def doc_get_document(params: dict[str, Any]) -> dict[str, Any] | None:
    """DocCapability.get_document(doc_ref) 真实现。

    params: { doc_ref: dict }
    Returns: { doc_ref, title, url, content_markdown } 或 None（doc 不存在）
    """
    client = await _ensure_client()
    doc_id = params["doc_ref"]["native_id"]
    data = await client.documents_info(doc_id=doc_id)
    if data is None:
        return None
    return {
        "doc_ref": params["doc_ref"],
        "title": data.get("title", ""),
        "url": data.get("url"),
        "content_markdown": data.get("text"),
    }


async def doc_ai_suggest_mentions(params: dict[str, Any]) -> list[dict[str, Any]]:
    """DocCapability.ai_suggest_mentions — v1 占位（plan 06 真实现 LLM 调用）。

    raise NotImplementedError → daemon dispatcher 转 JSONRPC -32603。
    Plan 06 实现：读 prompts/ai_suggest_mentions_zh.md 模板 → 调主进程 LLM provider
    → 返回 list[MentionSuggestion]。
    """
    raise NotImplementedError(
        "ai_suggest_mentions v1 占位 — plan 06 真实现（LLM provider 路径 + prompt 模板）"
    )


# ── Method routing ───────────────────────────────────────────────────────────

# method 名 → handler 映射（与 DocFacade.* method JSONRPC 命名严格一一对应）
METHODS: dict[str, Any] = {
    "doc.create_document": doc_create_document,
    "doc.replace_document_content": doc_replace_document_content,
    "doc.apply_document_delta": doc_apply_document_delta,
    "doc.add_comment": doc_add_comment,
    "doc.get_document": doc_get_document,
    "doc.ai_suggest_mentions": doc_ai_suggest_mentions,
}


# ── JSONRPC envelope 构造 / dispatch ─────────────────────────────────────────


def _make_success(rid: Any, result: Any) -> dict[str, Any]:
    """JSONRPC 2.0 success envelope。"""
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _make_error(rid: Any, code: int, message: str) -> dict[str, Any]:
    """JSONRPC 2.0 error envelope。"""
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


async def _process_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """处理单个 JSONRPC envelope，返回 response envelope。

    路由：
    1. method 不在 METHODS → -32601 Method not found
    2. handler 抛 NotImplementedError → -32603 Internal error (含原 message)
    3. handler 抛其他异常（含 httpx.HTTPStatusError / RuntimeError / NetworkBlockedError）→ -32000 业务错误
    4. handler 正常返回 → success envelope（result 可以是 None / dict / list）
    """
    rid = envelope.get("id")
    method_name = envelope.get("method", "")
    params = envelope.get("params") or {}

    handler = METHODS.get(method_name)
    if handler is None:
        return _make_error(rid, -32601, f"Method not found: {method_name}")

    try:
        result = await handler(params)
        return _make_success(rid, result)
    except NotImplementedError as e:
        return _make_error(rid, -32603, str(e))
    except Exception as e:  # noqa: BLE001 — daemon 兜底所有异常
        # -32000 ~ -32099 为应用业务错误（HTTP 失败 / NetworkBlockedError / OUTLINE env 缺）
        return _make_error(rid, -32000, f"OutlinePlugin business error: {type(e).__name__}: {e!s}")


# ── Daemon main loop ─────────────────────────────────────────────────────────


async def main() -> None:
    """Daemon 主循环：从 stdin 读 JSONRPC 行，处理后写 stdout。

    协议：
    - 行级编码（每行一个完整 JSON envelope，utf-8）
    - readline 返回空 bytes → stdin EOF（主进程关闭 stdin）→ 退出主循环
    - 非法 JSON 行 → stderr log + skip（不能给 error response 因为不知道 id）

    实现细节（与 huly_plugin.main 同模式）：
    - 用 asyncio.StreamReader 包装 sys.stdin 实现 async readline
    - sys.stdout.buffer.write + flush 确保 response 立即送出（虽然 ``python -u`` 已 unbuffered）
    """
    loop = asyncio.get_event_loop()

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            # stdin EOF — 主进程关闭 stdin → 退出
            break

        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            sys.stderr.write(f"[outline_plugin] invalid JSON: {line!r}\n")
            sys.stderr.flush()
            continue

        response = await _process_envelope(envelope)
        out_line = (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
        sys.stdout.buffer.write(out_line)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    asyncio.run(main())
```

**避坑**:
- `_ensure_client` 用 lazy + asyncio.Lock 防 race（首次调用并发）—— 与 huly_plugin._ensure_client 同模式
- handler raise NotImplementedError 时**必须**让原 message 传出（用 `str(e)` 不要 repr）
- `_process_envelope` 兜底 catch Exception 必带 type name —— 调试时区分 RuntimeError / HTTPStatusError / NetworkBlockedError
- `json.dumps(..., ensure_ascii=False)` — 中文 body 必须 — 否则 mock outline server 收不到正确 UTF-8
- 不要在模块顶层 `from plugins.outline._internal.outline_client import OutlineClient` —— lazy import 让 daemon 启动 ↔ 实调 解耦
- 不要在 daemon 内 `import os; os.environ["OUTLINE_API_TOKEN"]` 直接当 fallback —— 必须由 daemon_client 显式注入

commit messages（拆 2 个）:
- `feat(05c-03): add OutlinePlugin daemon entry with JSONRPC dispatch + 6 doc handlers`
- `feat(05c-03): add lazy OutlineClient singleton + env-driven config injection`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder && python -c "import sys; sys.path.insert(0, 'backend'); sys.path.insert(0, '.'); from plugins.outline.outline_plugin import METHODS, _process_envelope, _ensure_client, _parse_network_allow; expected = {'doc.create_document', 'doc.replace_document_content', 'doc.apply_document_delta', 'doc.add_comment', 'doc.get_document', 'doc.ai_suggest_mentions'}; assert set(METHODS.keys()) == expected, f'METHODS missing: {expected - set(METHODS.keys())}'; print('OutlinePlugin daemon entry OK, METHODS:', sorted(METHODS.keys()))"</automated>
  </verify>
  <done>plugins/outline/outline_plugin.py 可 import；METHODS dict 含完整 6 个 doc.* method；_ensure_client / _parse_network_allow / _process_envelope 函数已定义；与 plugins/huly/huly_plugin.py 同主循环架构</done>
</task>

<task type="auto">
  <name>Task 4: 单元测试 - handler marshalling + apply_document_delta NotImplementedError + 429 retry</name>
  <files>backend/tests/platforms/test_outline_plugin.py</files>
  <action>
### 创建 `backend/tests/platforms/test_outline_plugin.py` （unit test ≥ 12 case）

测试范围（不真起子进程 / 不真发 HTTP — 仅用 `httpx.MockTransport` mock httpx 层 + 直接 await handler）：

```python
"""OutlinePlugin unit tests — Phase 5.C plan 03 (PLUG-FW-05c-03)。

测试范围（不真起子进程；用 respx 或 httpx.MockTransport mock httpx 层）：

1. METHODS dict 完整性 + 命名约定（doc.* 前缀）
2. doc_create_document handler marshalling — params → OutlineClient.documents_create → return shape
3. doc_replace_document_content handler — 调 documents_update(append=False)
4. doc_apply_document_delta — raise NotImplementedError + message 含 "Outline 不支持"
5. doc_add_comment — markdown body 转 ProseMirror 单 paragraph + 返回 CommentRef shape
6. doc_get_document — 200 返回 DocInfo dict / 404 返回 None
7. doc_ai_suggest_mentions — raise NotImplementedError + message 含 "v1 占位"
8. _process_envelope — 未知 method → -32601 / NotImplementedError → -32603 / HTTPStatusError → -32000
9. OutlineClient retry on 429 — tenacity 2 次重试后成功（mock 429 → 429 → 200）
10. OutlineClient retry on 5xx — tenacity 2 次重试后成功（mock 503 → 200）
11. OutlineClient retry 累计失败 — 3 次 429 后 raise httpx.HTTPStatusError
12. OutlineClient 4xx 不 retry — 401 直接 raise（不浪费 retry）
13. _parse_network_allow — env 空 / 单条 / 多条 comma-separated 解析

License: 100% 独立创作。
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import httpx
import pytest


# ── 1. METHODS dict 完整性 ─────────────────────────────────────────────────────


def test_methods_dict_complete():
    """METHODS dict 必须含 6 个 doc.* method 完整对齐 DocCapability Protocol。"""
    from plugins.outline.outline_plugin import METHODS

    expected = {
        "doc.create_document",
        "doc.replace_document_content",
        "doc.apply_document_delta",
        "doc.add_comment",
        "doc.get_document",
        "doc.ai_suggest_mentions",
    }
    assert set(METHODS.keys()) == expected, (
        f"METHODS dict 应严格匹配 DocCapability Protocol method 集合，"
        f"缺少: {expected - set(METHODS.keys())}，多余: {set(METHODS.keys()) - expected}"
    )


def test_methods_all_async():
    """每个 handler 必须是 async function (await 调用)。"""
    from plugins.outline.outline_plugin import METHODS

    for method_name, handler in METHODS.items():
        assert asyncio.iscoroutinefunction(handler), (
            f"{method_name} handler 必须是 async function"
        )


# ── 2-7. Handler marshalling ─────────────────────────────────────────────────


@pytest.fixture
def outline_env(monkeypatch):
    """注入 daemon 启动所需 env（模拟 daemon_client 注入）。"""
    monkeypatch.setenv("OUTLINE_BASE_URL", "https://outline.example.com")
    monkeypatch.setenv("OUTLINE_API_TOKEN", "test-token-abc")
    monkeypatch.setenv("OUTLINE_DEFAULT_COLLECTION_ID", "col-uuid-1234")
    monkeypatch.setenv("PLUGIN_NETWORK_ALLOW", "outline.example.com:443")


@pytest.fixture(autouse=True)
def reset_outline_client_singleton():
    """每 test reset _outline_client 单例（防 test 间 state 串污染）。"""
    import plugins.outline.outline_plugin as op

    op._outline_client = None
    yield
    op._outline_client = None


@pytest.mark.asyncio
async def test_doc_create_document_marshals_params_to_client(outline_env, monkeypatch):
    """doc_create_document 应把 params → OutlineClient.documents_create 调用 → 返回 shape 正确."""
    from plugins.outline.outline_plugin import doc_create_document

    captured = {}

    async def fake_documents_create(self, **kwargs):
        captured.update(kwargs)
        return {
            "id": "outline-doc-123",
            "url": "/doc/hello-123",
            "title": kwargs["title"],
            "text": kwargs["text"],
        }

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.OutlineClient.documents_create",
        fake_documents_create,
    )

    result = await doc_create_document({
        "title": "Hello",
        "markdown": "# Hello\n\nWorld",
        "owners": [],
    })

    assert captured["title"] == "Hello"
    assert captured["text"] == "# Hello\n\nWorld"
    assert captured["collection_id"] == "col-uuid-1234"
    assert captured["publish"] is True
    assert result == {
        "plugin_name": "outline",
        "native_id": "outline-doc-123",
        "extras": {"url": "/doc/hello-123"},
    }


@pytest.mark.asyncio
async def test_doc_create_document_raises_when_collection_env_missing(outline_env, monkeypatch):
    """OUTLINE_DEFAULT_COLLECTION_ID 缺 → daemon raise RuntimeError → dispatcher 包成 -32000."""
    from plugins.outline.outline_plugin import doc_create_document

    monkeypatch.delenv("OUTLINE_DEFAULT_COLLECTION_ID")
    with pytest.raises(RuntimeError, match="OUTLINE_DEFAULT_COLLECTION_ID"):
        await doc_create_document({"title": "T", "markdown": "m", "owners": []})


@pytest.mark.asyncio
async def test_doc_replace_document_content_calls_update_append_false(outline_env, monkeypatch):
    """doc_replace_document_content 调 documents_update(append=False) 全量替换."""
    from plugins.outline.outline_plugin import doc_replace_document_content

    captured = {}

    async def fake_documents_update(self, **kwargs):
        captured.update(kwargs)
        return {"id": kwargs["doc_id"], "text": kwargs["text"]}

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.OutlineClient.documents_update",
        fake_documents_update,
    )

    result = await doc_replace_document_content({
        "doc_ref": {"plugin_name": "outline", "native_id": "doc-xyz", "extras": {}},
        "markdown": "# Updated\n\nNew content",
    })

    assert captured["doc_id"] == "doc-xyz"
    assert captured["text"] == "# Updated\n\nNew content"
    assert captured["append"] is False
    assert result is None


@pytest.mark.asyncio
async def test_doc_apply_document_delta_raises_not_implemented(outline_env):
    """Outline 不支持 CRDT delta → NotImplementedError 含明确 message。"""
    from plugins.outline.outline_plugin import doc_apply_document_delta

    with pytest.raises(NotImplementedError, match="Outline 不支持 CRDT"):
        await doc_apply_document_delta({
            "doc_ref": {"plugin_name": "outline", "native_id": "d1", "extras": {}},
            "delta": {"format": "yjs", "payload_b64": "AA=="},
        })


@pytest.mark.asyncio
async def test_doc_add_comment_wraps_markdown_to_prosemirror(outline_env, monkeypatch):
    """doc_add_comment 把 markdown body 包成单 paragraph ProseMirror JSON."""
    from plugins.outline.outline_plugin import doc_add_comment

    captured = {}

    async def fake_comments_create(self, **kwargs):
        captured.update(kwargs)
        return {"id": "comment-456"}

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.OutlineClient.comments_create",
        fake_comments_create,
    )

    result = await doc_add_comment({
        "doc_ref": {"plugin_name": "outline", "native_id": "doc-abc", "extras": {}},
        "body": "Looks good!",
        "mentions": [],
    })

    assert captured["document_id"] == "doc-abc"
    assert captured["data"]["type"] == "doc"
    assert captured["data"]["content"][0]["type"] == "paragraph"
    assert captured["data"]["content"][0]["content"][0]["text"] == "Looks good!"
    assert result == {
        "plugin_name": "outline",
        "native_id": "comment-456",
        "parent_doc_ref": {"plugin_name": "outline", "native_id": "doc-abc", "extras": {}},
    }


@pytest.mark.asyncio
async def test_doc_get_document_returns_none_on_404(outline_env, monkeypatch):
    """doc_get_document doc 不存在时返回 None（不 raise）."""
    from plugins.outline.outline_plugin import doc_get_document

    async def fake_documents_info(self, **kwargs):
        return None  # OutlineClient.documents_info 已把 404 转 None

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.OutlineClient.documents_info",
        fake_documents_info,
    )

    result = await doc_get_document({"doc_ref": {"plugin_name": "outline", "native_id": "missing", "extras": {}}})
    assert result is None


@pytest.mark.asyncio
async def test_doc_get_document_returns_info_dict(outline_env, monkeypatch):
    """doc_get_document 200 返回 {doc_ref, title, url, content_markdown}."""
    from plugins.outline.outline_plugin import doc_get_document

    async def fake_documents_info(self, **kwargs):
        return {
            "id": "doc-abc",
            "title": "My Doc",
            "url": "/doc/my-doc",
            "text": "# Body",
        }

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.OutlineClient.documents_info",
        fake_documents_info,
    )

    result = await doc_get_document({"doc_ref": {"plugin_name": "outline", "native_id": "doc-abc", "extras": {}}})
    assert result == {
        "doc_ref": {"plugin_name": "outline", "native_id": "doc-abc", "extras": {}},
        "title": "My Doc",
        "url": "/doc/my-doc",
        "content_markdown": "# Body",
    }


@pytest.mark.asyncio
async def test_doc_ai_suggest_mentions_raises_not_implemented(outline_env):
    """ai_suggest_mentions v1 占位 → NotImplementedError 含 "v1 占位"."""
    from plugins.outline.outline_plugin import doc_ai_suggest_mentions

    with pytest.raises(NotImplementedError, match="v1 占位"):
        await doc_ai_suggest_mentions({"markdown": "x", "context": {}})


# ── 8. _process_envelope ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_envelope_unknown_method_returns_minus_32601():
    """未知 method → JSONRPC -32601 Method not found."""
    from plugins.outline.outline_plugin import _process_envelope

    resp = await _process_envelope({
        "jsonrpc": "2.0", "id": 1, "method": "doc.unknown", "params": {},
    })
    assert resp["error"]["code"] == -32601
    assert "Method not found" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_process_envelope_not_implemented_returns_minus_32603():
    """handler raise NotImplementedError → -32603 含原 message。"""
    from plugins.outline.outline_plugin import _process_envelope

    resp = await _process_envelope({
        "jsonrpc": "2.0", "id": 2, "method": "doc.apply_document_delta",
        "params": {"doc_ref": {"plugin_name": "outline", "native_id": "x", "extras": {}}, "delta": {"format": "yjs", "payload_b64": "AA=="}},
    })
    assert resp["error"]["code"] == -32603
    assert "Outline 不支持 CRDT" in resp["error"]["message"]


# ── 9-12. OutlineClient retry behavior ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_outline_client_retries_on_429_succeeds(monkeypatch):
    """429 → 429 → 200 — tenacity 2 次重试后成功（Pitfall 4 防护）."""
    from plugins.outline._internal.outline_client import OutlineClient

    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(429, json={"error": "Too Many Requests"})
        return httpx.Response(200, json={"data": {"id": "ok-123"}})

    # patch make_sandboxed_http_client 让其返回带 MockTransport 的 client
    def fake_make_client(allow_list, timeout=10.0):
        return httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), timeout=timeout)

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.make_sandboxed_http_client",
        fake_make_client,
    )

    client = OutlineClient(
        base_url="https://outline.example.com",
        api_token="t",
        allow_list=["outline.example.com:443"],
        timeout=5.0,
    )
    # tenacity wait 1+2=3s 真等会让 test 慢 — 用 monkeypatch.setattr 缩短
    # 简单方法：patch tenacity wait_exponential 直接返回 0 wait
    import tenacity
    monkeypatch.setattr(tenacity, "wait_exponential", lambda **kw: lambda rs: 0)

    # Re-import to pick up patched wait
    import importlib
    import plugins.outline._internal.outline_client as oc
    importlib.reload(oc)
    monkeypatch.setattr("plugins.outline._internal.outline_client.make_sandboxed_http_client", fake_make_client)

    client = oc.OutlineClient(
        base_url="https://outline.example.com", api_token="t",
        allow_list=["outline.example.com:443"], timeout=5.0,
    )
    result = await client.documents_create(
        title="T", text="m", collection_id="c", parent_document_id=None, publish=True,
    )
    assert result == {"id": "ok-123"}
    assert call_count["n"] == 3  # 1 原 + 2 retry


@pytest.mark.asyncio
async def test_outline_client_retries_on_503_succeeds(monkeypatch):
    """5xx 触发 retry — 503 → 200 一次重试后成功."""
    from plugins.outline._internal.outline_client import OutlineClient

    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, json={"error": "Service Unavailable"})
        return httpx.Response(200, json={"data": {"id": "ok-456"}})

    def fake_make_client(allow_list, timeout=10.0):
        return httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), timeout=timeout)

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.make_sandboxed_http_client",
        fake_make_client,
    )

    import tenacity
    monkeypatch.setattr(tenacity, "wait_exponential", lambda **kw: lambda rs: 0)
    import importlib
    import plugins.outline._internal.outline_client as oc
    importlib.reload(oc)
    monkeypatch.setattr("plugins.outline._internal.outline_client.make_sandboxed_http_client", fake_make_client)

    client = oc.OutlineClient(
        base_url="https://outline.example.com", api_token="t",
        allow_list=["outline.example.com:443"], timeout=5.0,
    )
    result = await client.documents_update(doc_id="d", text="t", append=False)
    assert result == {"id": "ok-456"}
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_outline_client_4xx_does_not_retry(monkeypatch):
    """401 / 404 不在 retry 列表 — 1 次后直接 raise（不浪费 retry）."""
    from plugins.outline._internal.outline_client import OutlineClient

    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, json={"error": "Unauthorized"})

    def fake_make_client(allow_list, timeout=10.0):
        return httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), timeout=timeout)

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.make_sandboxed_http_client",
        fake_make_client,
    )

    client = OutlineClient(
        base_url="https://outline.example.com", api_token="bad",
        allow_list=["outline.example.com:443"], timeout=5.0,
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.documents_create(
            title="T", text="m", collection_id="c", parent_document_id=None, publish=True,
        )
    assert exc_info.value.response.status_code == 401
    assert call_count["n"] == 1, "4xx 不应该触发 retry"


@pytest.mark.asyncio
async def test_outline_client_retry_exhausted_raises_last_error(monkeypatch):
    """3 次都 429 → reraise 最后一次的 httpx.HTTPStatusError."""
    from plugins.outline._internal.outline_client import OutlineClient

    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, json={"error": "Rate limited"})

    def fake_make_client(allow_list, timeout=10.0):
        return httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), timeout=timeout)

    monkeypatch.setattr(
        "plugins.outline._internal.outline_client.make_sandboxed_http_client",
        fake_make_client,
    )

    import tenacity
    monkeypatch.setattr(tenacity, "wait_exponential", lambda **kw: lambda rs: 0)
    import importlib
    import plugins.outline._internal.outline_client as oc
    importlib.reload(oc)
    monkeypatch.setattr("plugins.outline._internal.outline_client.make_sandboxed_http_client", fake_make_client)

    client = oc.OutlineClient(
        base_url="https://outline.example.com", api_token="t",
        allow_list=["outline.example.com:443"], timeout=5.0,
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.documents_create(
            title="T", text="m", collection_id="c", parent_document_id=None, publish=True,
        )
    assert exc_info.value.response.status_code == 429
    assert call_count["n"] == 3, "应该重试到上限"


# ── 13. _parse_network_allow ──────────────────────────────────────────────────


def test_parse_network_allow_empty(monkeypatch):
    monkeypatch.delenv("PLUGIN_NETWORK_ALLOW", raising=False)
    from plugins.outline.outline_plugin import _parse_network_allow

    assert _parse_network_allow() == []


def test_parse_network_allow_single(monkeypatch):
    monkeypatch.setenv("PLUGIN_NETWORK_ALLOW", "outline.example.com:443")
    from plugins.outline.outline_plugin import _parse_network_allow

    assert _parse_network_allow() == ["outline.example.com:443"]


def test_parse_network_allow_multiple_with_whitespace(monkeypatch):
    monkeypatch.setenv("PLUGIN_NETWORK_ALLOW", "a.com:443, b.com:80 , c.com:8080")
    from plugins.outline.outline_plugin import _parse_network_allow

    assert _parse_network_allow() == ["a.com:443", "b.com:80", "c.com:8080"]
```

**避坑**:
- `reset_outline_client_singleton` 必须 `autouse=True` 否则 test 间 _outline_client 单例污染
- mock retry test 用 `monkeypatch.setattr(tenacity, "wait_exponential", lambda **kw: lambda rs: 0)` 把 wait 缩为 0 防 test 慢 3s
- mock `make_sandboxed_http_client` 而不是 mock `httpx.AsyncClient` — 让 retry 逻辑真跑（不绕过 OutlineClient 内部代码）
- `documents.info` 不在 retry 测试中（4xx/5xx 路径覆盖已够）— 不要重复测

commit message: `test(05c-03): add OutlinePlugin unit tests (handlers + retry + dispatcher)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_outline_plugin.py -v 2>&1 | tail -25</automated>
  </verify>
  <done>tests/platforms/test_outline_plugin.py ≥ 13 test case 全 pass；含 retry 行为验证 (429/5xx retry + 4xx 不 retry + 累计失败 reraise)；handler marshalling + NotImplementedError 路径覆盖</done>
</task>

<task type="auto">
  <name>Task 5: Mock Outline server fixture (respx-based, 监听 127.0.0.1:18088)</name>
  <files>backend/tests/platforms_integration/fixtures/mock_outline_server.py</files>
  <action>
### 创建 `backend/tests/platforms_integration/fixtures/mock_outline_server.py`

用 `aiohttp.web`（与 mock_huly_server.py 同模式）— **不**用 respx（respx 是 in-process httpx mock，无法被 daemon 子进程的 httpx 触发）：

```python
"""Mock Outline API server — Phase 5.C plan 03 integration test 用 aiohttp stub。

监听 127.0.0.1:18088（test fixture 通过 free_port 也可分配，但本 fixture 默认 18088
与 manifest_outline.yaml sandbox.network 一致）模拟 Outline REST API:

- ``POST /api/documents.create`` — 接受 {title, text, collectionId, parentDocumentId, publish}
- ``POST /api/documents.update`` — 接受 {id, text, title, append}
- ``POST /api/documents.info`` — 接受 {id}
- ``POST /api/comments.create`` — 接受 {documentId, data, parentCommentId}

为什么真起 aiohttp server 而非 mock httpx：
- daemon 是独立子进程，无法在主进程 patch 它的 httpx (mock_huly_server.py 同理)
- 必须用真实 HTTP server 监听本地端口
- daemon 通过 OUTLINE_BASE_URL env var 知道 mock server URL

设计要点（与 mock_huly_server.py 同模式）：
- 每个 doc 生成唯一 id (``outline-doc-{uuid4().hex[:8]}``)
- 内存中保存 docs / comments dict，let documents.info 查回
- 支持 ``X-Mock-Force-429`` header 触发 429 测试（retry 行为验证）
- 不实现真实 Outline 鉴权 / DB / collection 业务逻辑

License: 独立创作；借鉴 mock_huly_server.py 同仓模式（Apache-2.0 同项目）。
"""

from __future__ import annotations

import uuid
from typing import Any

from aiohttp import web

# ── In-memory storage ────────────────────────────────────────────────────────

# 模拟 Outline storage — 每 fixture 实例独立（test 间 reset by re-spawning fixture）
_DOCS_STORE: dict[str, dict[str, Any]] = {}
_COMMENTS_STORE: dict[str, dict[str, Any]] = {}


def _reset_stores() -> None:
    """Reset stores between fixture uses (called by build_mock_app each call)."""
    _DOCS_STORE.clear()
    _COMMENTS_STORE.clear()


# ── handlers ─────────────────────────────────────────────────────────────────


async def documents_create_handler(request: web.Request) -> web.Response:
    """POST /api/documents.create — 接受 markdown 透传创建文档。

    强制 X-Mock-Force-429 header 时返回 429（用于 retry 测试）。
    """
    # 测试触发 429
    if request.headers.get("X-Mock-Force-429") == "1":
        return web.json_response(
            {"error": "Too Many Requests (mock force)"}, status=429
        )

    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:  # noqa: BLE001
        return web.json_response({"error": f"invalid JSON: {e}"}, status=400)

    # Auth check (轻量)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"error": "Unauthorized"}, status=401)

    if "title" not in body or "text" not in body or "collectionId" not in body:
        return web.json_response(
            {"error": "missing required field: title/text/collectionId"},
            status=400,
        )

    doc_id = f"outline-doc-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": doc_id,
        "url": f"/doc/{doc_id[:6]}-mock",
        "title": body["title"],
        "text": body["text"],
        "collectionId": body["collectionId"],
        "parentDocumentId": body.get("parentDocumentId"),
        "publish": body.get("publish", True),
    }
    _DOCS_STORE[doc_id] = doc
    return web.json_response({"data": doc})


async def documents_update_handler(request: web.Request) -> web.Response:
    """POST /api/documents.update — append=false 即全量替换。"""
    if request.headers.get("X-Mock-Force-429") == "1":
        return web.json_response({"error": "Too Many Requests"}, status=429)

    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:  # noqa: BLE001
        return web.json_response({"error": f"invalid JSON: {e}"}, status=400)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"error": "Unauthorized"}, status=401)

    doc_id = body.get("id")
    if not doc_id or doc_id not in _DOCS_STORE:
        return web.json_response({"error": "Document not found"}, status=404)

    doc = _DOCS_STORE[doc_id]
    if body.get("title") is not None:
        doc["title"] = body["title"]
    new_text = body.get("text", "")
    if body.get("append", False):
        doc["text"] = doc["text"] + "\n" + new_text
    else:
        doc["text"] = new_text
    return web.json_response({"data": doc})


async def documents_info_handler(request: web.Request) -> web.Response:
    """POST /api/documents.info — 注意是 POST 不是 GET。"""
    if request.headers.get("X-Mock-Force-429") == "1":
        return web.json_response({"error": "Too Many Requests"}, status=429)

    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:  # noqa: BLE001
        return web.json_response({"error": f"invalid JSON: {e}"}, status=400)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"error": "Unauthorized"}, status=401)

    doc_id = body.get("id")
    if not doc_id or doc_id not in _DOCS_STORE:
        return web.json_response({"error": "Document not found"}, status=404)

    return web.json_response({"data": _DOCS_STORE[doc_id]})


async def comments_create_handler(request: web.Request) -> web.Response:
    """POST /api/comments.create — data 字段是 ProseMirror JSON。"""
    if request.headers.get("X-Mock-Force-429") == "1":
        return web.json_response({"error": "Too Many Requests"}, status=429)

    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:  # noqa: BLE001
        return web.json_response({"error": f"invalid JSON: {e}"}, status=400)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"error": "Unauthorized"}, status=401)

    document_id = body.get("documentId")
    data = body.get("data")
    if not document_id or not isinstance(data, dict):
        return web.json_response(
            {"error": "missing required field: documentId or data"}, status=400
        )

    comment_id = f"comment-{uuid.uuid4().hex[:8]}"
    comment = {
        "id": comment_id,
        "documentId": document_id,
        "data": data,
        "parentCommentId": body.get("parentCommentId"),
    }
    _COMMENTS_STORE[comment_id] = comment
    return web.json_response({"data": comment})


# ── app builder ──────────────────────────────────────────────────────────────


def build_mock_app() -> web.Application:
    """构造 aiohttp Application 含 4 个 Outline API route。

    用法（test fixture）::

        from aiohttp import web

        _reset_stores()
        app = build_mock_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 18088)
        await site.start()
        try:
            yield "http://127.0.0.1:18088"
        finally:
            await runner.cleanup()

    Returns:
        aiohttp.web.Application — 4 路由完整覆盖 OutlineClient 调用面
    """
    _reset_stores()
    app = web.Application()
    app.router.add_post("/api/documents.create", documents_create_handler)
    app.router.add_post("/api/documents.update", documents_update_handler)
    app.router.add_post("/api/documents.info", documents_info_handler)
    app.router.add_post("/api/comments.create", comments_create_handler)
    return app


__all__ = ["build_mock_app", "_DOCS_STORE", "_COMMENTS_STORE"]
```

**避坑**:
- 与 mock_huly_server.py 同模式 — 用 aiohttp 真起 server 监听端口（**不**用 respx，因为 daemon 子进程的 httpx 不受主进程 mock 影响）
- `_reset_stores()` 在每次 `build_mock_app()` 时清空 — 集成 test fixture 复用 server 时也保证 doc 独立
- X-Mock-Force-429 header 触发 429 — 集成 test 验证 retry 行为时用
- 401 Unauthorized 触发条件简化：Authorization header 不以 Bearer 开头（test 验证 token 注入是否正确）
- Outline `documents.info` 注意是 **POST 不是 GET**（OpenAPI 反直觉）

commit message: `test(05c-03): add mock Outline server fixture (aiohttp on 127.0.0.1:18088)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "import sys; sys.path.insert(0, '.'); from tests.platforms_integration.fixtures.mock_outline_server import build_mock_app, _DOCS_STORE, _COMMENTS_STORE; app = build_mock_app(); routes = sorted(str(r.resource) for r in app.router.routes()); assert any('/api/documents.create' in r for r in routes); assert any('/api/documents.update' in r for r in routes); assert any('/api/documents.info' in r for r in routes); assert any('/api/comments.create' in r for r in routes); assert _DOCS_STORE == {} and _COMMENTS_STORE == {}; print('mock outline server OK, 4 routes:', len(routes))"</automated>
  </verify>
  <done>mock_outline_server.py 可 import；build_mock_app() 返回 aiohttp.Application 含 4 个 POST 路由（documents.create/update/info + comments.create）；_DOCS_STORE / _COMMENTS_STORE 内存字典正确暴露</done>
</task>

<task type="auto">
  <name>Task 6: 集成测试 - 真 daemon spawn + mock outline server roundtrip</name>
  <files>backend/tests/platforms_integration/test_outline_plugin_integration.py</files>
  <action>
### 创建 `backend/tests/platforms_integration/test_outline_plugin_integration.py`

**核心目标**（CONTEXT.md §Critical constraints + DoD）:
- **OutlinePlugin daemon 真 spawn**（不 mock daemon_client.invoke）
- **真 httpx** 经过 AllowlistTransport 真打到本地 mock outline server
- **DocCapability.replace_document_content 成功** + **DocCapability.create_document 返回 DocRef + 真 doc 存在 mock store**
- **429 retry** 真触发（X-Mock-Force-429 header）
- 与 huly_acid_test 同模式（防 mock 退化 — `elapsed > 0.2s` timing assert）

```python
"""OutlinePlugin integration tests — Phase 5.C plan 03 (5C-SC-1)。

测试链路（防 mock 退化关键）：
1. mock_outline_server fixture 起 aiohttp stub 监听 127.0.0.1:18088
2. PlatformDaemonClient 真起 ``python -u -m plugins.outline.outline_plugin`` 子进程
   (env OUTLINE_BASE_URL=http://127.0.0.1:18088, OUTLINE_API_TOKEN=mock-token,
    OUTLINE_DEFAULT_COLLECTION_ID=col-mock, PLUGIN_NETWORK_ALLOW=127.0.0.1:18088)
3. 主进程通过 JSONRPC stdio 发 doc.create_document → daemon 真 httpx POST mock server
4. mock server 返回 {data: {id: outline-doc-xxx, ...}} → daemon JSONRPC response →
   主进程拿 DocRef
5. 验证：mock_outline_server._DOCS_STORE 含真 doc + DocRef.native_id 匹配 store id

防 mock 客户端退化（Pitfall 9）：
- ``elapsed > 0.2s`` (200ms) timing assert
- 真 subprocess spawn + Python 启动 + JSONRPC roundtrip + httpx 网络层 ≥ 200ms

License: 独立创作；测试模式借鉴 test_huly_acid_test.py 同仓（Apache-2.0 同项目）。
"""
from __future__ import annotations

import asyncio
import socket
import time
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web

from app.agent_builder.platforms.capabilities.doc import (
    CRDTDelta,
    DocCapability,
    DocRef,
)
from app.agent_builder.platforms.capability_facades import DocFacade
from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.exceptions import PluginInvocationError
from app.agent_builder.platforms.manifest import load_manifest
from app.agent_builder.platforms.plugin import PlatformPlugin

from tests.platforms_integration.fixtures.mock_outline_server import (
    _DOCS_STORE,
    build_mock_app,
)

OUTLINE_MODULE = "plugins.outline.outline_plugin"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest_asyncio.fixture
async def mock_outline_server():
    """起 mock Outline server 监听 free port，yield URL。"""
    port = _find_free_port()
    app = build_mock_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        yield f"http://127.0.0.1:{port}", port
    finally:
        await runner.cleanup()


@pytest.fixture
def project_root() -> str:
    """项目根目录 — daemon spawn 时 cwd 必须设这里（让 plugins.outline.* 可 import）。"""
    return str(Path(__file__).resolve().parents[3])  # backend/tests/platforms_integration/test_*.py → 4 上


# ── Test 1: 真 daemon + create_document end-to-end ─────────────────────────────


@pytest.mark.asyncio
async def test_outline_plugin_create_document_real_subprocess_end_to_end(
    mock_outline_server, project_root
) -> None:
    """**Phase 5.C plan 03 核心 DoD**（防 mock 退化关键）：

    1. 真起 plugins.outline.outline_plugin 子进程（不 mock daemon_client.invoke）
    2. 主进程通过 JSONRPC stdio 发 doc.create_document
    3. daemon 内 OutlineClient 真 httpx POST mock outline server /api/documents.create
    4. mock server 返回 {data: {id: outline-doc-xxx, url: /doc/...}}
    5. daemon JSONRPC response → 主进程 DocFacade 拿 DocRef

    验证（全部必须通过）：
    - elapsed > 0.2s — 真起 subprocess（Pitfall 9 防护）
    - DocRef.plugin_name == "outline"
    - DocRef.native_id 以 "outline-doc-" 开头（mock server 生成格式）
    - DocRef.extras["url"] 非空
    - _DOCS_STORE 中实际有该 doc
    """
    mock_url, mock_port = mock_outline_server
    start = time.monotonic()

    daemon = PlatformDaemonClient(
        module_entry=OUTLINE_MODULE,
        env={
            "OUTLINE_BASE_URL": mock_url,
            "OUTLINE_API_TOKEN": "mock-token-abc",
            "OUTLINE_DEFAULT_COLLECTION_ID": "col-mock-1",
            "PLUGIN_NETWORK_ALLOW": f"127.0.0.1:{mock_port}",
        },
        invoke_timeout=10.0,
        cwd=project_root,
    )

    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "platforms"
        / "fixtures"
        / "manifest_outline.yaml"
    )
    manifest = load_manifest(manifest_path)
    plugin = PlatformPlugin(manifest=manifest, daemon=daemon)

    try:
        doc_cap: DocCapability | None = plugin.doc
        assert doc_cap is not None, "outline manifest 声明 'doc' capability，plugin.doc 不应为 None"
        assert isinstance(doc_cap, DocFacade), f"plugin.doc 应返回 DocFacade，实际 {type(doc_cap)}"
        assert doc_cap.supports_collaborative_edit is False, "Outline supports_collaborative_edit 必须 False"
        assert doc_cap.supports_comments is True, "Outline supports_comments 必须 True"

        doc_ref = await doc_cap.create_document(
            title="Plan 05c-03 Integration Test",
            markdown="# Hello Outline\n\nFrom OutlinePlugin daemon (真 subprocess)",
            owners=None,
        )

        elapsed = time.monotonic() - start
        assert elapsed > 0.2, (
            f"end-to-end 测试 < 200ms — 可能未真起 subprocess (Pitfall 9 防护)；elapsed={elapsed:.3f}s"
        )

        assert doc_ref.plugin_name == "outline"
        assert doc_ref.native_id.startswith("outline-doc-"), f"got {doc_ref.native_id!r}"
        assert doc_ref.extras.get("url"), f"DocRef.extras.url 必须非空: {doc_ref.extras}"
        assert doc_ref.native_id in _DOCS_STORE, (
            f"mock store 应含真 doc {doc_ref.native_id}，实际 keys: {list(_DOCS_STORE.keys())}"
        )
    finally:
        await daemon.close()


# ── Test 2: replace_document_content + 验证 mock store 真更新 ──────────────────


@pytest.mark.asyncio
async def test_outline_plugin_replace_document_content_real_roundtrip(
    mock_outline_server, project_root
) -> None:
    """create → replace_document_content → mock store 真被全量替换。"""
    mock_url, mock_port = mock_outline_server

    daemon = PlatformDaemonClient(
        module_entry=OUTLINE_MODULE,
        env={
            "OUTLINE_BASE_URL": mock_url,
            "OUTLINE_API_TOKEN": "tok",
            "OUTLINE_DEFAULT_COLLECTION_ID": "col1",
            "PLUGIN_NETWORK_ALLOW": f"127.0.0.1:{mock_port}",
        },
        invoke_timeout=10.0,
        cwd=project_root,
    )
    manifest_path = (
        Path(__file__).resolve().parents[1] / "platforms" / "fixtures" / "manifest_outline.yaml"
    )
    plugin = PlatformPlugin(manifest=load_manifest(manifest_path), daemon=daemon)

    try:
        doc_cap = plugin.doc
        doc_ref = await doc_cap.create_document(
            title="Initial", markdown="initial content", owners=None
        )
        assert doc_ref.native_id in _DOCS_STORE
        assert _DOCS_STORE[doc_ref.native_id]["text"] == "initial content"

        await doc_cap.replace_document_content(doc_ref, "REPLACED CONTENT")

        assert _DOCS_STORE[doc_ref.native_id]["text"] == "REPLACED CONTENT", (
            f"mock store 应被全量替换，实际: {_DOCS_STORE[doc_ref.native_id]['text']!r}"
        )
    finally:
        await daemon.close()


# ── Test 3: apply_document_delta NotImplementedError → -32603 ──────────────────


@pytest.mark.asyncio
async def test_outline_plugin_apply_document_delta_raises_through_daemon(
    mock_outline_server, project_root
) -> None:
    """Outline daemon 收到 doc.apply_document_delta → NotImplementedError → JSONRPC -32603 →
    DocFacade 转 PluginInvocationError（或类似）。"""
    mock_url, mock_port = mock_outline_server

    daemon = PlatformDaemonClient(
        module_entry=OUTLINE_MODULE,
        env={
            "OUTLINE_BASE_URL": mock_url,
            "OUTLINE_API_TOKEN": "tok",
            "OUTLINE_DEFAULT_COLLECTION_ID": "col1",
            "PLUGIN_NETWORK_ALLOW": f"127.0.0.1:{mock_port}",
        },
        invoke_timeout=10.0,
        cwd=project_root,
    )
    manifest_path = (
        Path(__file__).resolve().parents[1] / "platforms" / "fixtures" / "manifest_outline.yaml"
    )
    plugin = PlatformPlugin(manifest=load_manifest(manifest_path), daemon=daemon)

    try:
        doc_cap = plugin.doc
        fake_ref = DocRef(plugin_name="outline", native_id="fake-id", extras={})
        delta = CRDTDelta(format="yjs", payload=b"\x00\x01")

        with pytest.raises((PluginInvocationError, NotImplementedError, Exception)) as exc_info:
            await doc_cap.apply_document_delta(fake_ref, delta)
        # daemon -32603 应包含 "Outline 不支持 CRDT" 原 message
        assert "Outline" in str(exc_info.value) or "CRDT" in str(exc_info.value), (
            f"exception 应含 Outline / CRDT 提示，实际: {exc_info.value!r}"
        )
    finally:
        await daemon.close()


# ── Test 4: 429 retry 真触发 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outline_plugin_retries_on_429_through_real_daemon(
    mock_outline_server, project_root
) -> None:
    """X-Mock-Force-429 在 daemon 不可直接控制 — 改用 mock server 内部计数器实现"前两次 429 后正常".

    简化方案（v1 真集成 path）:
    本 test 验证 tenacity retry 在真 subprocess 内仍然工作 — 用 X-Mock-Force-429
    header 不现实（daemon 不会附带）。改为 patch mock server handler 让前两次返回 429:
    """
    mock_url, mock_port = mock_outline_server

    # 替换 documents.create handler 让前两次 429
    from tests.platforms_integration.fixtures import mock_outline_server as mos

    call_count = {"n": 0}
    original_handler = mos.documents_create_handler

    async def flaky_handler(request):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return web.json_response({"error": "Mock Rate Limited"}, status=429)
        return await original_handler(request)

    # monkey patch handler on running aiohttp app — 重新 setup 简单
    # 直接通过 ParentRoute 替换太复杂；用 daemon timeout 短 + 验证 elapsed 间接证明 retry
    # 简化：直接断言 elapsed > 2s（tenacity wait 1s + 2s + 1 success = 至少 3s）

    # NOTE: aiohttp 不支持动态替换 handler；改为新起 app
    runner_new = web.AppRunner(web.Application())
    runner_new._app.router.add_post("/api/documents.create", flaky_handler)
    runner_new._app.router.add_post("/api/documents.update", mos.documents_update_handler)
    runner_new._app.router.add_post("/api/documents.info", mos.documents_info_handler)
    runner_new._app.router.add_post("/api/comments.create", mos.comments_create_handler)

    flaky_port = _find_free_port()
    await runner_new.setup()
    site_new = web.TCPSite(runner_new, "127.0.0.1", flaky_port)
    await site_new.start()

    daemon = PlatformDaemonClient(
        module_entry=OUTLINE_MODULE,
        env={
            "OUTLINE_BASE_URL": f"http://127.0.0.1:{flaky_port}",
            "OUTLINE_API_TOKEN": "tok",
            "OUTLINE_DEFAULT_COLLECTION_ID": "col1",
            "PLUGIN_NETWORK_ALLOW": f"127.0.0.1:{flaky_port}",
        },
        invoke_timeout=20.0,  # 给 retry 留时间（最长 ~10s）
        cwd=project_root,
    )
    manifest_path = (
        Path(__file__).resolve().parents[1] / "platforms" / "fixtures" / "manifest_outline.yaml"
    )
    plugin = PlatformPlugin(manifest=load_manifest(manifest_path), daemon=daemon)

    try:
        start = time.monotonic()
        doc_cap = plugin.doc
        doc_ref = await doc_cap.create_document(title="Retry test", markdown="x", owners=None)
        elapsed = time.monotonic() - start

        assert call_count["n"] == 3, (
            f"应调 mock 3 次（2 次 429 + 1 次 200），实际 {call_count['n']} 次"
        )
        assert elapsed >= 2.5, (
            f"tenacity 重试 wait 1s + 2s 至少需 3s（实际宽松到 2.5s），elapsed={elapsed:.2f}s"
        )
        assert doc_ref.plugin_name == "outline"
    finally:
        await daemon.close()
        await runner_new.cleanup()


# ── Test 5: NetworkBlockedError — AllowlistTransport 拦截非白名单 host ─────────


@pytest.mark.asyncio
async def test_outline_plugin_blocks_non_allowlisted_host(
    mock_outline_server, project_root
) -> None:
    """daemon 配 PLUGIN_NETWORK_ALLOW=blocked.example.com:443 但 OUTLINE_BASE_URL 指向 mock →
    AllowlistTransport 拦截 → daemon JSONRPC -32000 → DocFacade 抛 PluginInvocationError。"""
    mock_url, mock_port = mock_outline_server

    daemon = PlatformDaemonClient(
        module_entry=OUTLINE_MODULE,
        env={
            "OUTLINE_BASE_URL": mock_url,                # 真 mock URL
            "OUTLINE_API_TOKEN": "tok",
            "OUTLINE_DEFAULT_COLLECTION_ID": "col1",
            "PLUGIN_NETWORK_ALLOW": "blocked.example.com:443",  # 白名单不含 mock
        },
        invoke_timeout=10.0,
        cwd=project_root,
    )
    manifest_path = (
        Path(__file__).resolve().parents[1] / "platforms" / "fixtures" / "manifest_outline.yaml"
    )
    plugin = PlatformPlugin(manifest=load_manifest(manifest_path), daemon=daemon)

    try:
        doc_cap = plugin.doc
        with pytest.raises((PluginInvocationError, Exception)) as exc_info:
            await doc_cap.create_document(title="X", markdown="x", owners=None)
        # daemon -32000 应含 NetworkBlockedError 提示
        assert "127.0.0.1" in str(exc_info.value) or "Network" in str(exc_info.value) or "allowlist" in str(exc_info.value).lower(), (
            f"exception 应含 host / NetworkBlocked / allowlist 提示，实际: {exc_info.value!r}"
        )
    finally:
        await daemon.close()
```

**避坑**:
- `project_root` 必须设到项目根（让 daemon 子进程能 `python -m plugins.outline.outline_plugin`）
- mock fixture 复用 mock_huly_server.py 的 free_port 模式 — aiohttp runner / TCPSite 标准
- timing assert `elapsed > 0.2s` 是真 subprocess 防护（Pitfall 9）
- Test 4 (429 retry) 用动态新建 aiohttp app 替换 handler 而不是 monkey patch — 简单可靠
- Test 5 (NetworkBlockedError) 用 PLUGIN_NETWORK_ALLOW 故意不含 mock URL 触发拦截
- assert exception message 用 `Exception` 兜底 — 因为 PluginInvocationError 可能在不同路径
- `_DOCS_STORE` test 间会污染但本 plan test 都 yield 新 server / 新 fixture — OK

commit messages（拆 2 个）:
- `test(05c-03): add OutlinePlugin integration tests (真 daemon + mock outline server)`
- `test(05c-03): add 429 retry + NetworkBlockedError 集成测试`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms_integration/test_outline_plugin_integration.py -v --tb=short 2>&1 | tail -40</automated>
  </verify>
  <done>tests/platforms_integration/test_outline_plugin_integration.py 5 个 integration test 全 pass；含真 subprocess spawn (elapsed > 0.2s) + 真 httpx + mock outline server roundtrip + 429 retry 真触发 + NetworkBlockedError 拦截</done>
</task>

<task type="auto">
  <name>Task 7: Plugin discovery registration smoke + 5.A/5.B regression 全绿</name>
  <files>backend/tests/platforms/test_outline_plugin.py</files>
  <action>
### 1. 在已建的 `test_outline_plugin.py` 末尾追加 1 个 smoke test 验证 manifest 可被 PluginRegistry 加载

```python
# ── 14. Plugin discovery registration smoke ────────────────────────────────────


def test_outline_manifest_loadable_via_pluginregistry_path():
    """manifest 可被 load_manifest() 加载且 capability_facades.DocFacade
    能正确 read supports_collaborative_edit/comments flags。"""
    from pathlib import Path

    from app.agent_builder.platforms.manifest import load_manifest

    # 加载真实 manifest（不是 test fixture）
    project_root = Path(__file__).resolve().parents[3]
    manifest_path = project_root / "plugins" / "outline" / "platform.yaml"
    manifest = load_manifest(manifest_path)

    assert manifest.name == "outline"
    assert "doc" in manifest.capabilities
    assert manifest.runtime.entry == "plugins.outline.outline_plugin"
    assert manifest.doc.supports_collaborative_edit is False
    assert manifest.doc.supports_comments is True
    # 校验 sandbox config（Phase 5.B AllowlistTransport 必须的 env_allowlist）
    assert manifest.sandbox is not None
    assert "PLUGIN_NETWORK_ALLOW" in manifest.sandbox.env_allowlist
    assert "OUTLINE_BASE_URL" in manifest.sandbox.env_allowlist
    assert "OUTLINE_API_TOKEN" in manifest.sandbox.env_allowlist
```

### 2. 跑 Phase 5.A platforms regression 全套（**不能 break**）

```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend
python -m pytest tests/platforms/ -v --tb=short -x 2>&1 | tail -30
# 预期：273 + 14 = 287+ 全 pass（plan 03 加 14 个 unit test）
```

### 3. 跑 Phase 5.B 5/5 acid test regression（**不能 break**）

```bash
python -m pytest tests/platforms_integration/test_huly_acid_test.py -v 2>&1 | tail -20
# 预期：5/5 全 pass
```

### 4. 跑本 plan 5 个 integration test 全过

```bash
python -m pytest tests/platforms_integration/test_outline_plugin_integration.py -v --tb=short 2>&1 | tail -30
# 预期：5/5 全 pass
```

### 5. 整体 platforms + platforms_integration regression

```bash
python -m pytest tests/platforms/ tests/platforms_integration/ -x 2>&1 | tail -10
# 预期：0 fail；warning 容忍（如 deprecation）
```

### 6. 校验 reading doc commit 早于代码 commit（CLAUDE.md §2.7 硬性 gate 复查）

```bash
git log --oneline tests/platforms/test_outline_plugin.py | tail -1   # 代码最早 commit
git log --oneline docs/reading-dify-05c-03-outline-plugin-2026-05-18.md | head -1  # reading doc commit
# 校验：reading doc commit 时间 ≤ 代码 commit 时间
```

commit message: `test(05c-03): add plugin discovery smoke + verify regression baseline`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_outline_plugin.py tests/platforms_integration/test_outline_plugin_integration.py tests/platforms_integration/test_huly_acid_test.py -v --tb=short 2>&1 | tail -30 && echo "--- Phase 5.A regression ---" && python -m pytest tests/platforms/ --tb=line 2>&1 | tail -5</automated>
  </verify>
  <done>
    - 本 plan unit test (≥ 14) + integration test (5) 全 pass
    - Phase 5.A platforms 273 测试 0 regression
    - Phase 5.B 5/5 acid test 0 regression
    - manifest 通过 load_manifest 校验 + sandbox.env_allowlist 含必需 env 名
    - reading doc commit hash 早于本 plan 任何 feat / test commit（CLAUDE.md §2.7 校验）
  </done>
</task>

</tasks>

<verification>
**Phase-local 测试矩阵（plan 03 验收）**:

| 维度 | 检查项 | 命令 / 预期 |
|---|---|---|
| **Reading doc gate** | reading doc 早于代码 commit（CLAUDE.md §2.7） | `git log --oneline docs/reading-dify-05c-03-outline-plugin-2026-05-18.md plugins/outline/` 时间顺序校验 |
| **Manifest schema** | manifest 通过 load_manifest 校验 | Task 1 verify 命令绿 |
| **OutlineClient 单元** | 13+ test 覆盖 marshalling + retry 行为 | `pytest tests/platforms/test_outline_plugin.py -v` 全绿 |
| **真子进程** | daemon spawn elapsed > 200ms（防 mock 退化） | Task 6 timing assert |
| **httpx + AllowlistTransport** | 真打 mock outline server + 走 AllowlistTransport | Task 6 端到端 DocRef.native_id ∈ _DOCS_STORE |
| **429 retry 真发** | 前两次 429 后 200 成功 + elapsed ≥ 2.5s | Task 6 flaky_handler 计数器 |
| **NetworkBlockedError 真触发** | PLUGIN_NETWORK_ALLOW 错配时 daemon -32000 → PluginInvocationError | Task 6 Test 5 |
| **NotImplementedError 双路径** | apply_document_delta + ai_suggest_mentions 都 raise + message 正确 | Task 4 + Task 6 Test 3 |
| **supports_collaborative_edit=False 上报** | DocFacade.supports_collaborative_edit 读 manifest doc.supports_collaborative_edit | Task 6 Test 1 断言 |

**Phase 5.A / 5.B regression（不能 break）**:
- `pytest tests/platforms/ -x` 273 测试 0 fail
- `pytest tests/platforms_integration/test_huly_acid_test.py` 5/5 全绿
- `pytest tests/platforms_integration/test_idle_reaper.py tests/platforms_integration/test_network_allowlist.py tests/platforms_integration/test_watchdog_grace_period.py tests/platforms_integration/test_cgroups_v2_sandbox.py tests/platforms_integration/test_fault_isolation.py` 全绿
</verification>

<success_criteria>
1. **Reading doc gate** ✓ — `docs/reading-dify-05c-03-outline-plugin-2026-05-18.md` ≥ 80 行 + 5 借鉴点 + AGPL/Apache attribution + commit 早于代码
2. **Manifest 完整** ✓ — `plugins/outline/platform.yaml` 通过 load_manifest 校验，capabilities=[doc] / supports_collaborative_edit=False / sandbox.network + env_allowlist 完整
3. **OutlineClient 接口完整** ✓ — `documents_create / documents_update / comments_create / documents_info` 4 method 实现 + AllowlistTransport 强制 + tenacity 429/5xx 重试
4. **OutlinePlugin daemon 6 method handler 完整** ✓ — `doc.create_document / replace_document_content / apply_document_delta(NotImplemented) / add_comment / get_document / ai_suggest_mentions(NotImplemented)`
5. **真 subprocess + httpx + mock server roundtrip** ✓ — integration test elapsed > 0.2s + DocRef.native_id ∈ mock _DOCS_STORE
6. **429 retry 真触发** ✓ — integration test 验证 3 次调用 + elapsed ≥ 2.5s（tenacity wait 1+2s）
7. **NetworkBlockedError 真触发** ✓ — integration test 验证 PLUGIN_NETWORK_ALLOW 错配时 daemon 抛 -32000
8. **三层测试覆盖** ✓ — Unit (≥ 14) + Integration (5) + E2E 留 plan 08
9. **Phase 5.A 273 platforms regression** ✓ — 0 fail
10. **Phase 5.B 5/5 acid test regression** ✓ — 0 fail
11. **plan 04 / 05 可并行**：本 plan 不修改 backend/app/agent_builder/platforms/ 任何已有文件（仅新增 plugins/outline/ + 测试 + reading doc），与 plan 04 (lark) / plan 05 (huly internal) 文件无冲突
</success_criteria>

<output>
完成后创建 `.planning/phases/05c-doc-capability/05c-03-SUMMARY.md`，至少含：

- **Dify 参考点** 小节 — 5 借鉴点 + 指回 reading doc 章节锚点（CLAUDE.md §2.7 验收要求）
- **OutlinePlugin 模块清单** — 8 个新文件 + commit hash 对照
- **三层测试覆盖** — unit / integration / E2E 各自的 case 数 + 通过率
- **Phase 5.A / 5.B regression 验证截图** — pytest 输出数字
- **plan 04/05/06/07 接入点** — 本 plan 提供给后续 plan 的 contracts:
  - JSONRPC method 命名（doc.* 6 method）
  - OutlineClient httpx pattern（AllowlistTransport + tenacity retry）
  - 双 NotImplementedError 路径（apply_document_delta + ai_suggest_mentions）
  - daemon spawn pattern（与 huly_plugin 同模式 lazy _ensure_client）
- **Pitfall 4 (Outline 429) + Pitfall 12 (tenacity timeout 叠加) 验证记录** — integration test elapsed 数据
- **License attribution 记录** — 所有新文件含 "100% 独立创作 + Apache-2.0" 注释
</output>
</content>