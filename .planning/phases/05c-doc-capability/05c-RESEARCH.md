# Phase 5.C: DocCapability 真接入 - Research

**Researched:** 2026-05-18
**Domain:** 协作文档平台对接（Outline / Lark Docs / Huly）+ multi-capability plugin bundle + docker network attach + ai_suggest_mentions LLM 钩子
**Confidence:** HIGH（Huly hr port 模板 + Outline OpenAPI + Lark 官方文档全验证；marko/prosemirror Python 库版本现验）

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Decision 1 — 3 个 plugin 实现优先级 + 范围**:

- **OutlinePlugin (P0 最简)**：DocCapability only（单一 capability）；`replace_document_content(markdown)` 直接走 Outline `POST /api/documents.update`；`apply_document_delta` 抛 `NotImplementedError`；`supports_collaborative_edit = False`；凭据：`api_token` only
- **LarkDocsPlugin (P0 国内首选)**：DocCapability + IdentityCapability (multi-capability)；markdown → Lark Block 转换（`marko` AST + 严格映射）；评论 + @ 人通过 lark_open_id（IdentityCapability 提供）；`supports_collaborative_edit = False`；凭据：`app_id + app_secret + tenant_access_token` 缓存
- **HulyPlugin (P0 一体化 acid test 升级)**：**4-capability bundle** (DocCapability + IMCapability + IdentityCapability + (TrackerCapability stub))；共享 `HulyPlatformClient` (单 daemon 进程 + 单 WS 连接)；DocCapability 走 **二步流程**（create shell → collab service RPC → update content ref）；`supports_collaborative_edit = True` → `apply_document_delta(ProseMirrorJSON)`；IMCapability 走 **per-user Channel 模式** (DM 静默 reject hr 实战教训 §5.2)；IdentityCapability 走 SocialIdentity → Employee mixin 链 + LRU cache；凭据：`huly_url + huly_workspace + huly_admin_email + huly_admin_password`

**Decision 2 — hr B-full-channel 1454 行 Python port 策略**:

| hr 文件 | port 到 agent-builder | 改造 |
|--------|---------------------|------|
| `huly/rest_client.py` (286) | `plugins/huly/_internal/rest_client.py` | 添加 httpx AllowlistTransport（5.B Wave 2） |
| `huly/tx_factory.py` (220) | `plugins/huly/_internal/tx_factory.py` | 零改 |
| `huly/tx_operations.py` (182) | `plugins/huly/_internal/tx_operations.py` | 零改 |
| `huly/platform_client.py` (76) | `plugins/huly/_internal/platform_client.py` | lifecycle: 用 PlatformPlugin daemon `__init__` |
| `huly/constants.py` (72) | `plugins/huly/_internal/constants.py` | 零改 |
| `huly_doc_provider.py` (304) | DocCapability impl in `huly_plugin.py` | 接 Capability facade method 签名 |
| `huly_im_provider.py` (247) | IMCapability impl in `huly_plugin.py` | 同上 |
| **总计 1454 行** | **plugins/huly/** | ~70% 零改 port + ~30% 改 capability 签名 |

**Decision 3 — 网络白名单 + docker network attach (hr 教训 §4.4)**:

- `SandboxRunner.spawn_with_limits()` 接受 `docker_networks: list[str]`
- manifest `sandbox.docker_networks: ["huly_huly_net"]` (新字段)
- daemon spawn 时 `docker network connect <network> <container_id>` (PosixResourceSandbox no-op，CgroupsV2Sandbox 才做)
- 测试：mock huly server 监听 `127.0.0.1:18087`，跳过真实 docker network

**Decision 4 — DocCapability replace_content vs apply_delta 双路径策略**:

- **OutlinePlugin / LarkDocsPlugin** (`supports_collaborative_edit=False`)：仅实现 `replace_document_content(markdown)` 全量替换；`apply_document_delta` raise `NotImplementedError`；Service layer fallback：用户传 delta 时检测 `supports_collaborative_edit` 自动序列化为 markdown 走 replace
- **HulyPlugin** (`supports_collaborative_edit=True`)：主路径 `apply_document_delta(ProseMirrorJSON)` 走 collab service RPC；`replace_document_content(markdown)` 做 `marko` parse → ProseMirror JSON → apply_delta（hr 二步流程）；**二步流程优先封装在 plugin daemon 内**，主进程仅传 markdown 或 delta，无需感知 collab service

**Decision 5 — IMCapability per-user Channel 模式（hr 教训 §5.2）**:

- HulyPlugin IMCapability.send_card 默认 RecipientSpec `kind="dm_user"` → 自动 fallback per-user `chunter:Channel` 命名 `dm-{username}`
- 不尝试 `chunter:DirectMessage`（server 静默 reject）
- 接口对外仍是 `kind="dm_user"`，业务无感

**Decision 6 — PersonUuid 解析缓存 (hr §5.5)**:

- HulyPlugin daemon 内置 `_resolve_account_cache: LRU(maxsize=10000)`
- 输入 username → SocialIdentity (key=`email:{user}@demo.local`) → Employee mixin → personUuid
- TTL: 1h（manifest config 可覆盖）
- 缓存 miss → 实时查 + 写缓存

**Decision 7 — ai_suggest_mentions LLM 钩子 (ADR-001 §3.2 v1.1 留接口)**:

- `DocCapability.ai_suggest_mentions(markdown, context) -> list[MentionSuggestion]` v1 仅在 OutlinePlugin / LarkDocsPlugin 实现（HulyPlugin v1.1 留 NotImplementedError）
- 用 agent-builder 已有 LLM provider (GLM / OpenAI)
- prompt 模板路径：`plugins/<name>/prompts/ai_suggest_mentions_zh.md` (plugin 自带)
- 失败 fallback：返回空 list + structured log

**Decision 8 — AGPL-3.0 license 防御 (Phase 5.A 已设)**:

- **不拷贝** hr/offboarding-flow 源码（hr 自己也是研究稿，未必清晰 license）
- **借鉴**：架构模式 / Tx 链路设计 / collab service RPC 调用方式 / 二步流程 / per-user Channel 绕开方案
- 重写实现，不复制 — 各文件加 `# Inspired by hr/offboarding-flow design, not derived source`

**Decision 9 — Capability test 三层（CLAUDE.md §2.2）**:

- **Unit**: DocCapability Protocol contract + 每 plugin facade marshalling
- **Integration**: 真 plugin daemon spawn + mock Outline/Lark/Huly server (aiohttp/httpx mock)
- **E2E**: browser-harness CDP 直连用户 Chrome —— 跑通"DAG → doc_write 节点 → 真 Outline/Lark/Huly 文档" 一条端到端（v1.5 节点接入时跑）

**Decision 10 — PlatformBundle facet 模式 (ADR-001 §5)**:

- HulyPlugin 是首个 multi-capability plugin (4 facet 共享 daemon)
- `HulyPlugin.doc / .im / .identity / .tracker` 都返回 facade 包装同一个 `HulyPlatformClient`
- Plugin 初始化时一次性 `login + selectWorkspace` 拿 ws_token，4 facet 复用
- 这是 Phase 5.A acid test 5/5 mock 模式的**真实生产升级**

### Claude's Discretion

- marko AST 转 ProseMirror JSON 的具体 mapping rule (hr 教训 §4.5 给了 JSON 例子但不全) — 本研究 §Pattern 5 给出
- daemon spawn 时 docker network attach 失败时的降级策略（推荐 **raise + structured log**，不静默）— 本研究 §Pattern 4 提议接口
- AllowlistTransport 是否支持 wildcard host (Phase 5.B 已规约 exact match — Phase 5.C 不扩) — 本研究 Pitfall 7 不放宽
- 缓存 invalidation 时机（推荐 plugin manifest 可声明 `cache_ttl_seconds`，默认 3600）— 本研究 §Pattern 6 落实
- structured log 字段 schema：plugin_name + workspace_id + capability + method + latency_ms + outcome (Phase 7 Run Viewer 钩子) — 本研究 §Pattern 7 锁定

### Deferred Ideas (OUT OF SCOPE)

- DAG 节点 `doc_write` / `doc_mention` 配置面板（v1.5 — 本 phase 仅 Capability + plugin，节点接入留下个 phase）
- Lark Docs CRDT delta（飞书 Block 改造为 collaborative — v2）
- Huly Tracker IssueCapability 完整接入（spike 已通过 — v1.1 加 Protocol）
- multi-platform doc 同步（Outline ↔ Lark mirror — v2）
- ai_suggest_mentions Dify Workflow 路径（dify-integration 文档 §4.4 方案 B — v2 双路）
- AllowlistTransport wildcard host (`*.feishu.cn`) — v2（Phase 5.B 锁定 exact match）
</user_constraints>

---

<phase_requirements>
## Phase Requirements

Phase 5.C 没有显式 ROADMAP 中的 requirement ID（DOC-* 阶段定义，会在 plan-phase 期由 planner 落到 REQUIREMENTS.md）。当前 ROADMAP `Phase 5.C Success Criteria` 直接作为可追溯锚点：

| 锚点 ID | Success Criterion (ROADMAP) | Research 支持 |
|----|-------------|-----------------|
| 5C-SC-1 | OutlineProvider plugin manifest + 全 6 method 实现 + 集成测试 (实跑 Outline self-hosted .44) | §Standard Stack Outline OpenAPI + §Pattern 1 Plugin daemon + §Architecture Plugin folder layout |
| 5C-SC-2 | LarkDocsProvider plugin + markdown→blocks 转换 + 评论 + @人 | §Standard Stack Lark openapi + §Pattern 2 marko AST + §Pattern 5 ProseMirror mapping（不适用 Lark / 仅 Huly）+ §Pattern 8 lark-oapi 调用 |
| 5C-SC-3 | HulyPlugin DocCapability facet 真接入 + Y.js CRDT delta apply 工作 | §Standard Stack Huly REST + §Pattern 5 ProseMirror markup + §Pattern 9 二步流程 + Pitfall 1 docker network |
| 5C-SC-4 | DAG 节点 `doc_write` / `doc_mention` 集成 + AI suggest mentions LLM 钩子 (**deferred 到 v1.5 — 本 phase 仅 Capability + plugin + ai_suggest_mentions 接口**) | §Pattern 10 ai_suggest_mentions prompt 模板路径 + LLM provider 路径复用 |
| 5C-SC-5 | E2E with browser-harness：DAG 跑完 → Outline 出文档 → 协作人收 @ 提醒 | §Pattern 11 E2E browser-harness 三 plugin |

另外锚点（ADR-001 DoD 派生）：

| 锚点 ID | 说明 | Research 支持 |
|---|---|---|
| 5C-FW-01 | SandboxRunner `docker_networks` 字段 + manifest `sandbox.docker_networks` 扩展 + Phase 5.B PosixResourceSandbox/CgroupsV2Sandbox 集成 | §Pattern 4 daemon spawn 时 docker connect |
| 5C-FW-02 | hr B-full-channel 1454 行 Python port —— 70% 零改 + 30% capability 签名改造 | §Standard Stack `_internal/` 模块表 |
| 5C-FW-03 | Multi-capability plugin 测试 — 1 daemon 4 facet 共享 + 集成 + crash 隔离 | §Pattern 12 multi-capability test 4 维度 |
| 5C-FW-04 | License attribution — 不拷 hr 源码，借鉴 + 每文件 `# Inspired by` 注释 | §Sources 末段 + Pitfall 8 |
</phase_requirements>

---

## Summary

Phase 5.C 把 Phase 5.A DocCapability Protocol（Mock 设计）真接到 **Outline / Lark Docs / Huly 三平台**，其中 Huly 升级为 Phase 5.A acid test 5/5 stub 的**真实生产版**。

**核心难点不在 Outline（直接 markdown 全量替换）和 Lark（lark-oapi 1.6.5 现成 SDK + 官方 `/docx/v1/documents/blocks/convert` API）**，而在 **Huly 二步流程**：Huly Document 的 `content` 字段不是 raw markdown，而是 **collab service 的 blob reference**（格式 `{docId}-content-{timestamp}`）。简单字符串写入会被 server 接受但 UI 不渲染。必须走 `POST /rpc/{urlEncoded(workspaceUuid|class|objectId|attr)}` createContent / updateContent → 拿 blob ref → 二跳 update_doc。

**hr B-full-channel 1454 行 Python 是直接 port 模板**（不重头摸索）— rest_client.py 286 行 + tx_factory.py 220 行 + tx_operations.py 182 行 + platform_client.py 76 行 + constants.py 72 行（**总计 836 行内部 module 几乎零改 port**），huly_doc_provider.py 304 行 + huly_im_provider.py 247 行（**总计 551 行需改造为 Capability facade**）。**~70% 零改 + ~30% 改 capability 签名**比从 0 设计快 3x。

**网络白名单 + docker network attach** (hr §4.4 教训) 是 Phase 5.B AllowlistTransport 的**第二层补充**：Phase 5.B 只验证了 application-level (httpx 出站) 白名单；Huly daemon **额外需要 attach `huly_huly_net` docker network** 才能 DNS 解析 `collaborator:3078`。这是 Phase 5.C 必须扩展 SandboxRunner 的原因。

**Primary recommendation:** 5 wave 拓扑（详见末段 Phase Topology）：
1. **Wave 1 串行**：SandboxRunner `docker_networks` 字段 + manifest `sandbox.docker_networks` 扩展（5.B 强化，所有 plugin 共用）
2. **Wave 2 并行 x3**：OutlinePlugin (P0 最简) / LarkDocsPlugin (markdown→blocks 中等) / Huly internal port (rest_client + tx_factory + tx_operations 零改 port)
3. **Wave 3**：HulyPlugin 4-cap bundle 集成（用 Wave 2 internal modules + per-user Channel + LRU cache）
4. **Wave 4 并行 x2**：ai_suggest_mentions LLM 钩子（DocCapability v1.1 扩展）+ 三 plugin ai_suggest 实现
5. **Wave 5**：E2E browser-harness CDP（DAG 模拟跑通 → 真 Outline + Lark + Huly 出文档）

---

## Standard Stack

### Core 平台 SDK

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **httpx** | **0.28+ (5.B 锁定)** | Outline REST + Huly REST + Lark fallback HTTP | Phase 5.B AllowlistTransport 已基于 httpx Transport API；项目锁定 |
| **lark-oapi** | **1.6.5** (Phase 4.06 已锁) | Lark Docs API SDK | 官方 SDK；含 docx.v1.documents.blocks.convert / batch_update / create；版本与 Feishu provider 共用避免重复依赖 |
| **aiohttp** | **3.9+** | Huly mock server + daemon HTTP 出站（Phase 5.A 已用） | Phase 5.A acid test 已 aiohttp；daemon 内可继续使用 |
| **marko** | **2.2.2** | Markdown → AST (用于 Huly ProseMirror JSON 转换) | 高扩展性 CommonMark v0.31.2；自带 ASTRenderer 渲染为 JSON；扩展 4 ext (footnote/toc/pangu/codehilite)；BSD-3-Clause 兼容 Apache-2.0 |
| **prosemirror** | **0.6.1** | ProseMirror schema + transform Python (Huly markup 构造) | fellowapp/prosemirror-py 端口；prosemirror-model 1.25.4 + prosemirror-schema-basic 1.2.4 + prosemirror-schema-list 1.5.1；BSD-3-Clause |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **cachetools** | **5.3+** | LRU cache for HulyPlugin PersonUuid 解析 (hr §5.5) | TTLCache(maxsize=10000, ttl=3600) — daemon 内单例 |
| **tenacity** | 8.2+ (Phase 3 已锁) | Outline / Lark HTTP 重试 (429 / 5xx) | Outline rate limiter `1000 req/min/IP` 友好退避 |
| **docker** | 7.1+ (Python SDK) | docker_networks 字段实现 (CgroupsV2Sandbox path only) | `client.networks.get(name).connect(container)` — 测试 mock |
| **pydantic** | **2.13+** (Phase 5.A 已锁) | manifest sandbox.docker_networks list[str] schema | Field(default_factory=list) — 与 network 字段同模式 |

### 三个 Plugin 各自的依赖矩阵

| Plugin | Markdown lib | API SDK | Auth Cache | Special Module |
|---|---|---|---|---|
| OutlinePlugin | (透传 markdown，无需 parse) | httpx 直调 `/api/documents.*` | api_token (no refresh) | comments.create (markdown body + @user_id mention) |
| LarkDocsPlugin | `marko` (透传 markdown 给 blocks/convert API) | `lark-oapi==1.6.5` | tenant_access_token 自动 refresh (lark-oapi 内置 / TTL ~6900s) | docx.v1.documents.blocks.convert + docx.v1.document_block.batch_update |
| HulyPlugin | `marko` AST → `prosemirror` JSON | httpx 自实现 REST (hr port) | workspace_token (login + selectWorkspace) — daemon `_ensure_client` lock | collab service `/rpc/{encoded_doc_id}` POST createContent + Tx system |

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Decision |
|------------|-----------|----------|----------|
| `marko` | `mistletoe` | mistletoe 性能略好 + 同样 AST 渲染 | **`marko` 选定** — 扩展系统更友好；项目其他地方暂未引入 marko 也无负担 |
| `prosemirror` Python | 手写 JSON dict 构造 | 手写省一个依赖 | **`prosemirror` 选定** — schema 校验 + transform 系统保证生成的 JSON 不会被 Huly server 静默 reject；hr §4.5 给的 JSON 例子不全，靠 schema 兜底 |
| `lark-oapi` 1.6.5 | 直接 httpx 调 `open.feishu.cn` REST | 省一个 SDK 依赖 | **`lark-oapi` 选定** — Phase 4.06 已锁同版本 (NOTI-02)；avoid duplicate token-refresh 逻辑 + 已验证 1.6.0-1.6.3 yanked 锁 1.6.5 |
| OutlinePlugin 用 `outline-wiki-api` PyPI | 直接 httpx | PyPI 包 v0.3.3 仅 Python 3.12+ + 文档简陋 + 自带 search 但其他方法未文档化 | **直接 httpx 选定** — 6 个 endpoint 不复杂；不引入隐藏依赖 |
| Huly Y.js binary delta | Huly markup 字符串 (ProseMirror JSON.stringify) | Y.js binary 二进制更紧凑 + 真正 CRDT | **Huly markup 字符串选定** (hr §4.3) — `createContent` API 接受 markup 字符串；Phase 5.C 不上 Y.js binary（避免引入 ypy-websocket 依赖 + Huly 二步流程是为 markup 设计）。v2 升级 Y.js 留 IssueCapability |

**Installation** (Phase 5.C 新增到 backend/requirements.txt)：

```bash
# 新增（Phase 5.B 之上）
marko==2.2.2
prosemirror==0.6.1
cachetools==5.3.3

# 既有（Phase 4 / 5.A / 5.B 已锁，不动）
# httpx==0.28.1
# lark-oapi==1.6.5
# aiohttp==3.9.5
# tenacity==8.2.3
# pydantic==2.13.4
```

---

## Architecture Patterns

### Recommended Project Structure

```
plugins/
├── outline/                           # P0 最简 — DocCapability only
│   ├── platform.yaml                  # capabilities: [doc]
│   ├── outline_plugin.py              # daemon entry，主循环 + JSONRPC dispatch
│   ├── _internal/
│   │   ├── __init__.py
│   │   ├── client.py                  # Outline httpx client (10 endpoint封装)
│   │   └── markdown_render.py         # markdown 透传（Outline 原生接受）
│   └── prompts/
│       └── ai_suggest_mentions_zh.md  # ai_suggest_mentions LLM 模板
├── lark_docs/                         # P0 multi-capability (Doc + Identity)
│   ├── platform.yaml                  # capabilities: [doc, identity]
│   ├── lark_docs_plugin.py            # daemon entry
│   ├── _internal/
│   │   ├── __init__.py
│   │   ├── client.py                  # lark-oapi wrapper + token cache 复用
│   │   ├── docx_writer.py             # blocks.convert → batch_create_blocks 二段
│   │   └── identity_resolver.py       # username → lark_open_id
│   └── prompts/
│       └── ai_suggest_mentions_zh.md
└── huly/                              # P0 4-capability bundle
    ├── platform.yaml                  # capabilities: [doc, im, identity, tracker(stub)]
    ├── huly_plugin.py                 # daemon entry — 4 cap dispatch + 共享 HulyPlatformClient
    ├── _internal/                     # ~836 行 hr port
    │   ├── __init__.py
    │   ├── constants.py               # 零改 port (hr/huly/constants.py 72 行)
    │   ├── rest_client.py             # 零改 + httpx AllowlistTransport (hr/huly/rest_client.py 286 行 + 5.B 改造)
    │   ├── tx_factory.py              # 零改 port (hr/huly/tx_factory.py 220 行)
    │   ├── tx_operations.py           # 零改 port (hr/huly/tx_operations.py 182 行)
    │   ├── platform_client.py         # lifecycle 改造 (hr/huly/platform_client.py 76 行)
    │   ├── collab_client.py           # 新增 — /rpc/{encoded_doc_id} 协议 (hr §4.3-4.5)
    │   ├── markdown_to_prosemirror.py # 新增 — marko AST → ProseMirror JSON mapping (§Pattern 5)
    │   └── identity_resolver.py       # SocialIdentity → Employee mixin LRU cache (hr §5.5)
    └── prompts/
        └── ai_suggest_mentions_zh.md  # NotImplementedError v1.1 留接口
```

**为什么 `_internal/` 子包**:
- 主进程通过 `plugins.huly.huly_plugin` 模块入口启动 daemon
- daemon 内部使用 `plugins.huly._internal.*` (双下划线前缀 = 私有，类似 Python convention)
- 测试不直接 import `_internal/*`（除非 unit 测 module 本身）— 上层 IDE / mypy 自动正向

### Pattern 1: Plugin daemon Multi-Capability Dispatch

**What:** 一个 daemon process 同时服务多 capability 调用，共享底层 client/connection

**When to use:** 任何 multi-capability plugin（HulyPlugin / LarkDocsPlugin）

**Example:**

```python
# Source: 基于 plugins/huly/huly_plugin.py 现有结构演进（5.A acid test 已建主循环）
# Reference: docs/plans/2026-05-17-platform-plugin-framework-ADR.md §5

# plugins/huly/huly_plugin.py
from __future__ import annotations
import os
import asyncio
from ._internal.platform_client import HulyPlatformClient, connect_huly

# 模块级共享 client (daemon 进程内单例 — 由 lazy connect 保证)
_client: HulyPlatformClient | None = None
_client_lock = asyncio.Lock()


async def _ensure_client() -> HulyPlatformClient:
    """Phase 5.C 新增 — daemon 启动后首次调用时建立 Huly 连接。"""
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


# 4 capability handlers
async def doc_create_document(params): ...
async def doc_apply_document_delta(params): ...
async def im_send_card(params): ...
async def identity_resolve_user(params): ...

# METHODS dict —— 4 capability × N method
METHODS = {
    "doc.create_document": doc_create_document,
    "doc.apply_document_delta": doc_apply_document_delta,
    "doc.replace_document_content": doc_replace_document_content,
    "doc.add_comment": doc_add_comment,
    "doc.get_document": doc_get_document,
    "im.send_card": im_send_card,
    "im.update_card": im_update_card,
    "im.send_text": im_send_text,
    "identity.list_users": identity_list_users,
    "identity.resolve_user": identity_resolve_user,
    # Tracker stub v1
    "tracker.create_issue": _not_implemented,
}
```

**Anti-Patterns to Avoid:**
- **每 capability 一个 daemon**：浪费进程 + 重复 login + 4 个 ws_token 同步问题
- **client 同时被主进程和 daemon 持有**：5.B 沙箱模型要求 daemon 独立进程；client 只能在 daemon 内
- **lock 在模块顶层 `asyncio.Lock()` 时初始化**：daemon 可能未启动 event loop，会 RuntimeError。应在 `_ensure_client` 内 lazy 初始化或用 `asyncio.get_event_loop().create_task` 包装

### Pattern 2: Outline 单 capability 极简实现

**What:** OutlinePlugin = httpx + Outline REST，Markdown 透传

**When to use:** 任何只支持 markdown / 不支持 CRDT 的传统平台（Outline / Lark / WeCom）

**Example:**

```python
# Source: 设计稿，参考 hr/backend/src/offboarding_flow/outline.py (无 dify 借鉴需要)
# Outline OpenAPI spec: https://github.com/outline/openapi/blob/main/spec3.yml

# plugins/outline/_internal/client.py
import httpx
from typing import Any


class OutlineClient:
    def __init__(self, base_url: str, api_token: str, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/") + "/api"
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    async def documents_create(self, *, title: str, text: str,
                                collection_id: str, parent_document_id: str | None = None,
                                publish: bool = True) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as c:
            r = await c.post(f"{self._base_url}/documents.create", json={
                "title": title,
                "text": text,
                "collectionId": collection_id,
                "parentDocumentId": parent_document_id,
                "publish": publish,
            })
            r.raise_for_status()
            return r.json()["data"]

    async def documents_update(self, *, doc_id: str, text: str,
                                title: str | None = None, append: bool = False) -> None:
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as c:
            r = await c.post(f"{self._base_url}/documents.update", json={
                "id": doc_id, "text": text, "title": title, "append": append,
            })
            r.raise_for_status()

    async def comments_create(self, *, document_id: str, data: dict,
                               parent_comment_id: str | None = None) -> dict[str, Any]:
        """Outline comment data 是 ProseMirror JSON（非 markdown）— 上层需转换。"""
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as c:
            r = await c.post(f"{self._base_url}/comments.create", json={
                "documentId": document_id,
                "data": data,
                "parentCommentId": parent_comment_id,
            })
            r.raise_for_status()
            return r.json()["data"]
```

### Pattern 3: Lark Docs 二段写入流程

**What:** Lark Docs 通过 `blocks/convert` (markdown → block JSON) → `batch_create_blocks` (插入) 二段流程

**When to use:** LarkDocsPlugin.create_document / replace_document_content / append

**Example:**

```python
# Source: 基于 Lark Open Platform 官方文档
# https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/document/convert
# Auth: tenant_access_token (lark-oapi 内置 refresh)

import lark_oapi as lark
from lark_oapi.api.docx.v1 import *


class LarkDocsClient:
    def __init__(self, app_id: str, app_secret: str):
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

    async def create_document_from_markdown(self, *, title: str, markdown: str,
                                              folder_token: str | None = None) -> str:
        # Step 1: 创 doc shell
        req = CreateDocumentRequest.builder().request_body(
            CreateDocumentRequestBody.builder().title(title).folder_token(folder_token).build()
        ).build()
        resp = await asyncio.to_thread(self._client.docx.v1.document.create, req)
        if not resp.success():
            raise RuntimeError(f"Lark create document failed: {resp.code} {resp.msg}")
        document_id = resp.data.document.document_id

        # Step 2: markdown → blocks（不限制 10MB 字符；批 1000 block 限制）
        convert_req = ConvertRequest.builder().request_body(
            ConvertRequestBody.builder()
                .content_type("markdown")
                .content(markdown)
                .build()
        ).build()
        convert_resp = await asyncio.to_thread(
            self._client.docx.v1.document.convert, convert_req
        )
        if not convert_resp.success():
            raise RuntimeError(f"Lark convert markdown failed: {convert_resp.code}")
        blocks = convert_resp.data.blocks
        first_level_block_ids = convert_resp.data.first_level_block_ids

        # Step 3: batch insert blocks into root page block (block_id == document_id)
        # 注：Phase 5.C v1 暂不处理 >1000 block 的拆批；marko parse 后强校验长度
        # NOTE: API: docx.v1.document_block.create + descendant blocks
        # (实际调用是 `create` endpoint with descendants[] 一次性传入)
        create_blocks_req = (
            CreateDocumentBlockChildrenRequest.builder()
            .document_id(document_id)
            .block_id(document_id)
            .request_body(
                CreateDocumentBlockChildrenRequestBody.builder()
                .children(blocks)
                .descendants(blocks)
                .index(0)
                .build()
            )
            .build()
        )
        # ... 调用 + 错误处理

        return document_id

    async def add_comment_with_mention(self, *, document_id: str,
                                         body_markdown: str, mentions: list[str]) -> str:
        """
        Lark Docs @ 用户用 lark_open_id 在 markdown 内插入 @-mention syntax
        body_markdown 内含 <at user_id="ou_xxxxx"></at> 锚点（Lark 富文本 mention 语法）
        """
        # 通过 lark-oapi drive.v1.comment.create
        ...
```

**Key Limitations** (来自 Feishu Open Platform 文档):
- 单 convert 请求最大 **10,485,760 字符**
- 单次 create_blocks 最大 **1000 block**（超出需分批）
- `merge_info` 字段必须从 table block 移除（read-only）
- 图片需 3 步：convert → create blocks → 单独上传素材填 image_id

### Pattern 4: docker_networks 字段扩展 SandboxRunner

**What:** Phase 5.B SandboxRunner 加 `docker_networks: list[str]` 参数，在 daemon spawn 后调 `docker network connect`

**When to use:** Huly daemon（必须 attach `huly_huly_net` 才能调 `collaborator:3078`），其他 plugin 默认空

**Example:**

```python
# Source: 设计稿，扩展 backend/app/agent_builder/platforms/sandbox/runner.py
# Phase 5.B 现状：spawn_with_limits(cmd, cpu_seconds, memory_bytes, env, cwd)
# Phase 5.C 新增：docker_networks: list[str] = field(default_factory=list)

@runtime_checkable
class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        docker_networks: list[str] | None = None,  # 新增 — Phase 5.C
    ) -> asyncio.subprocess.Process: ...


class PosixResourceSandbox:
    """macOS dev / Linux baseline — docker_networks no-op (本地进程不在 container)。"""

    async def spawn_with_limits(self, cmd, *, cpu_seconds, memory_bytes,
                                  env=None, cwd=None, docker_networks=None):
        if docker_networks:
            _log.info("sandbox.docker_networks ignored on PosixResourceSandbox "
                      "(daemon runs as host process, not container)")
        # ... 5.B 原实现不变
        return proc


class CgroupsV2Sandbox:
    """Linux 生产 — daemon 是 systemd-run scope，加 docker network attach 仅在 daemon 是 container 时生效。"""

    async def spawn_with_limits(self, cmd, *, cpu_seconds, memory_bytes,
                                  env=None, cwd=None, docker_networks=None):
        proc = await self._spawn_base(...)  # 5.B 现有逻辑

        if docker_networks:
            # 仅 Linux + docker daemon 可用时
            try:
                import docker
                client = docker.from_env()
                container_id = self._resolve_container_for_pid(proc.pid)
                if container_id is None:
                    _log.warning(
                        "sandbox.docker_networks=%s but daemon pid=%d not in any container — skipping",
                        docker_networks, proc.pid
                    )
                    return proc
                for net_name in docker_networks:
                    net = client.networks.get(net_name)
                    net.connect(container_id)
                    _log.info("docker network connected: %s -> container=%s", net_name, container_id[:12])
            except Exception as e:
                # 决策（Claude's Discretion）：raise + structured log，不静默
                _log.exception("docker.network.connect failed: %s", e)
                proc.terminate()
                await proc.wait()
                raise RuntimeError(
                    f"Failed to attach docker networks {docker_networks!r}: {e}"
                ) from e

        return proc

    def _resolve_container_for_pid(self, pid: int) -> str | None:
        """读 /proc/<pid>/cgroup → 找 docker container id (Linux only)."""
        try:
            with open(f"/proc/{pid}/cgroup") as f:
                for line in f:
                    if "docker" in line:
                        # 形如 12:devices:/docker/abc123def... — 取末段
                        return line.strip().rsplit("/", 1)[-1]
        except (FileNotFoundError, PermissionError):
            return None
        return None
```

**关键设计**:
- `docker_networks` 在 PosixResourceSandbox 是 no-op + warning（macOS / Linux 非容器化场景安全）
- CgroupsV2Sandbox 失败时 **raise + terminate daemon**（Decision 推荐）—— 不许"silently no network"导致 Huly 调用一直 ConnectionError 看起来像超时
- 测试 mock 路径：注入 MockDockerClient（不真起 docker）

### Pattern 5: marko AST → ProseMirror JSON (Huly markup)

**What:** Markdown → marko AST → ProseMirror JSON dict → JSON.stringify 给 Huly collab service

**When to use:** HulyPlugin.replace_document_content / apply_document_delta（marko parse markdown）

**Example:**

```python
# Source: 设计稿，结合 marko AST renderer 模式 + Huly markup 字符串约定 (hr §4.5)
# hr §4.5 给的 markup 例：
# {
#   "type": "doc",
#   "content": [
#     {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "..."}]},
#     {"type": "bulletList", "content": [{"type": "listItem", "content": [...]}]}
#   ]
# }
# Reference: prosemirror-schema-basic + prosemirror-schema-list (Python port 0.6.1)

import marko
from marko.ast_renderer import ASTRenderer
from marko import Markdown
from typing import Any


_MARKDOWN = Markdown(renderer=ASTRenderer)


# Marko AST element_name (snake_case) → ProseMirror node type 映射
_MARK_MAP = {
    "emphasis": "em",
    "strong_emphasis": "strong",
    "code_span": "code",
    "link": "link",  # 特殊处理 attrs.href
}

_BLOCK_MAP = {
    "document": "doc",
    "heading": "heading",  # attrs.level 1-6
    "paragraph": "paragraph",
    "blank_line": None,  # 跳过
    "code_block": "code_block",  # attrs.language
    "list": "bulletList",  # ordered 时 → orderedList
    "list_item": "listItem",
    "block_quote": "blockquote",
    "thematic_break": "horizontalRule",
}


def markdown_to_prosemirror(markdown_text: str) -> dict[str, Any]:
    """Markdown → Huly markup 格式 (ProseMirror JSON)。

    Returns:
        dict — 顶层为 {"type": "doc", "content": [...]}
               可直接 json.dumps(ensure_ascii=False) 传给 Huly /rpc createContent
    """
    raw_ast = _MARKDOWN.convert(markdown_text)
    # marko ASTRenderer 返回完整 AST dict（element name 已 snake_case）
    return _convert_node(raw_ast)


def _convert_node(node: dict) -> dict:
    """递归 marko AST element → ProseMirror JSON。

    Marko AST 示例 (heading):
      {"element": "heading", "level": 2, "children": [{"element": "raw_text", "children": "Hello"}]}
    转 ProseMirror:
      {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Hello"}]}
    """
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
            "attrs": {"level": node.get("level", 1)},
            "content": _convert_inline(node.get("children", [])),
        }
    if name == "paragraph":
        return {
            "type": "paragraph",
            "content": _convert_inline(node.get("children", [])),
        }
    if name == "list":
        is_ordered = node.get("ordered", False)
        return {
            "type": "orderedList" if is_ordered else "bulletList",
            "content": [_convert_node(c) for c in node.get("children", []) if c],
        }
    if name == "list_item":
        # marko list_item children 是 block-level (paragraph / nested list)
        return {
            "type": "listItem",
            "content": [_convert_node(c) for c in node.get("children", []) if c is not None],
        }
    if name == "code_block":
        return {
            "type": "code_block",
            "attrs": {"language": node.get("lang", "")},
            "content": _convert_inline(node.get("children", [])),
        }
    if name == "blank_line":
        return None  # 跳过
    # fallback —— 未识别 element 退化为 paragraph + raw text
    return {"type": "paragraph", "content": _convert_inline(node.get("children", []))}


def _convert_inline(children: list) -> list:
    """Inline element list → ProseMirror text nodes (with marks)."""
    out = []
    for c in children:
        if isinstance(c, str):
            out.append({"type": "text", "text": c})
        elif isinstance(c, dict):
            elem = c.get("element")
            text = "".join(s for s in _flatten_text(c) if s)
            marks = _extract_marks(c)
            node = {"type": "text", "text": text}
            if marks:
                node["marks"] = marks
            out.append(node)
    return out


def _flatten_text(node: dict) -> list[str]:
    """递归收集所有 raw_text。"""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        out = []
        for c in node.get("children", []):
            out.extend(_flatten_text(c))
        return out
    return []


def _extract_marks(node: dict) -> list[dict]:
    """从 marko inline element 提取 ProseMirror marks (em / strong / code / link)."""
    name = node.get("element")
    if name == "emphasis":
        return [{"type": "em"}]
    if name == "strong_emphasis":
        return [{"type": "strong"}]
    if name == "code_span":
        return [{"type": "code"}]
    if name == "link":
        return [{"type": "link", "attrs": {"href": node.get("dest", "")}}]
    return []
```

**Validation Tests** (unit):
- markdown "# H1\n\n- a\n- b" → ProseMirror JSON with heading.level=1 + bulletList[listItem[paragraph[text=a]], ...]
- inline emphasis / strong / code / link 各自的 mark
- 空行 / 注释 / fenced code 边界

### Pattern 6: PersonUuid LRU Cache (hr §5.5)

**What:** `username → SocialIdentity → Employee mixin → personUuid` 解析路径每次都查 Huly REST 2-3 次，必须缓存

**When to use:** HulyPlugin.identity.resolve_user / 任何需要 personUuid 的调用

**Example:**

```python
# Source: 设计稿，扩展 hr/huly_im_provider.py:_resolve_account
# cachetools TTLCache 适合 LRU + TTL 组合

from cachetools import TTLCache
import asyncio

# daemon 进程级单例
_uuid_cache: TTLCache[str, str] = TTLCache(maxsize=10000, ttl=3600)  # 1h TTL
_cache_lock = asyncio.Lock()


async def resolve_person_uuid(pc: HulyPlatformClient, username: str) -> str | None:
    """username → personUuid (LRU cache + TTL)。

    cache key: f"{workspace_uuid}:{username}" (跨 workspace 隔离 Pitfall 5)
    cache value: personUuid (str) or sentinel for "not found"
    """
    ws_uuid = pc.rest.workspace_uuid
    cache_key = f"{ws_uuid}:{username}"
    cached = _uuid_cache.get(cache_key)
    if cached is not None:
        return None if cached == "__not_found__" else cached

    # miss path — 2 跳查询
    async with _cache_lock:
        # double check 防 race
        cached = _uuid_cache.get(cache_key)
        if cached is not None:
            return None if cached == "__not_found__" else cached

        social_key = f"email:{username}@demo.local"
        si = await pc.rest.find_one("contact:class:SocialIdentity", {"key": social_key})
        if not si or not si.get("attachedTo"):
            _uuid_cache[cache_key] = "__not_found__"
            return None

        emp = await pc.rest.find_one("contact:mixin:Employee", {"_id": si["attachedTo"]})
        if not emp or not emp.get("personUuid"):
            _uuid_cache[cache_key] = "__not_found__"
            return None

        uuid_val = str(emp["personUuid"])
        _uuid_cache[cache_key] = uuid_val
        return uuid_val


def invalidate_cache(username: str | None = None, workspace_uuid: str | None = None) -> int:
    """显式 invalidate — Phase 5.D Identity sync 钩子用。"""
    if username is None and workspace_uuid is None:
        n = len(_uuid_cache)
        _uuid_cache.clear()
        return n
    keys = [k for k in _uuid_cache
              if (username is None or k.endswith(f":{username}"))
                and (workspace_uuid is None or k.startswith(f"{workspace_uuid}:"))]
    for k in keys:
        _uuid_cache.pop(k, None)
    return len(keys)
```

**Decision (Claude's Discretion):** TTL 默认 3600（可由 manifest `config.cache_ttl_seconds` 覆盖；TTLCache 不支持运行时改 TTL，需 daemon 启动时一次性读 manifest 配）。

### Pattern 7: Structured Logging Schema for Phase 7 Run Viewer

**What:** 每个 capability call 产生统一 structured log（plugin_name / workspace_id / capability / method / latency_ms / outcome）

**When to use:** 所有 capability facade 调用，Phase 5.B daemon_client.invoke 已埋点，本 phase 在 plugin daemon 内补全

**Example:**

```python
# Source: 设计稿，扩展 Phase 5.B PlatformDaemonClient.invoke 已有的 structured log
# CLAUDE.md decision: plugin_name + workspace_id + capability + method + latency_ms + outcome

import logging
import time
import contextvars

_log = logging.getLogger("agent_builder.platform_plugin")

# workspace_id 通过 contextvars 注入（FastAPI middleware 设置 → 各层透传）
current_workspace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_workspace_id", default=None
)


def log_capability_call(*, plugin_name: str, capability: str, method: str,
                          latency_ms: int, outcome: str, **extras):
    """Phase 7 Run Viewer 钩子 — structured field log。

    outcome: "success" | "error" | "timeout" | "blocked" (NetworkBlockedError)
    extras: 附加调试字段（如 idempotency_key、doc_id 前 8 字符、recipient_kind）
    """
    _log.info(
        "platform.plugin.invoke",
        extra={
            "plugin_name": plugin_name,
            "workspace_id": current_workspace_id.get(),
            "capability": capability,
            "method": method,
            "latency_ms": latency_ms,
            "outcome": outcome,
            **{k: v for k, v in extras.items() if v is not None},
        },
    )
```

### Pattern 8: lark-oapi 1.6.5 Async 包装

**What:** lark-oapi SDK 是同步 API（与 Phase 4.06 FeishuProvider 一致），daemon async 调用需 `asyncio.to_thread`

**When to use:** LarkDocsPlugin 所有 lark-oapi 调用

**Example:**

```python
# Source: 沿用 Phase 4.06 FeishuProvider 的 loop.run_in_executor 包装模式
import asyncio
import lark_oapi as lark
from lark_oapi.api.docx.v1 import CreateDocumentRequest, CreateDocumentRequestBody


async def _async_call(sync_fn, *args, **kwargs):
    """asyncio.to_thread 包装同步 SDK 调用（Python 3.9+ stdlib）。"""
    return await asyncio.to_thread(sync_fn, *args, **kwargs)


class LarkDocsClient:
    async def create_document(self, *, title: str, folder_token: str | None = None) -> str:
        req = (
            CreateDocumentRequest.builder()
            .request_body(
                CreateDocumentRequestBody.builder()
                .title(title)
                .folder_token(folder_token)
                .build()
            )
            .build()
        )
        resp = await _async_call(self._client.docx.v1.document.create, req)
        if not resp.success():
            raise RuntimeError(f"Lark API error {resp.code}: {resp.msg}")
        return resp.data.document.document_id
```

### Pattern 9: Huly 二步流程封装

**What:** create document = create shell + collab service createContent + update_doc(content=blobRef)

**When to use:** HulyPlugin.create_document / replace_document_content

**Example:**

```python
# Source: hr/docs/huly-integration-architecture-2026-05-18.md §4.3
# Reference: @hcengineering/collaborator-client/src/client.ts (TS, AGPL-3.0 仅借鉴模式)

import urllib.parse
import json
import httpx
import time


class HulyCollabClient:
    """Huly collaborator service /rpc 客户端 — 不依赖 transactor REST。"""

    def __init__(self, *, collab_url: str, ws_token: str, timeout: float = 10.0):
        # collab_url 形如 "http://collaborator:3078"（docker network attach 后可达）
        self._collab_url = collab_url.rstrip("/")
        self._ws_token = ws_token
        self._timeout = timeout

    def _encode_doc_id(self, *, workspace_uuid: str, object_class: str,
                         object_id: str, object_attr: str) -> str:
        """文档级 RPC URL 段：urlEncoded("{ws}|{class}|{id}|{attr}")"""
        return urllib.parse.quote(
            f"{workspace_uuid}|{object_class}|{object_id}|{object_attr}",
            safe="",
        )

    async def create_content(self, *, workspace_uuid: str, object_class: str,
                               object_id: str, object_attr: str,
                               prosemirror_doc: dict) -> str:
        """POST /rpc/{encoded_doc_id} method=createContent → blob ref string."""
        encoded = self._encode_doc_id(
            workspace_uuid=workspace_uuid, object_class=object_class,
            object_id=object_id, object_attr=object_attr,
        )
        markup = json.dumps(prosemirror_doc, ensure_ascii=False)
        body = {
            "method": "createContent",
            "payload": {"content": {object_attr: markup}},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                f"{self._collab_url}/rpc/{encoded}",
                json=body,
                headers={"Authorization": f"Bearer {self._ws_token}"},
            )
        if r.status_code != 200:
            raise RuntimeError(
                f"collab.createContent HTTP {r.status_code}: {r.text[:200]}"
            )
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"collab.createContent error: {data['error']}")
        # 返回 {content: {attr: blobRef}}
        return data["content"]["content"]


# huly_plugin daemon doc.create_document handler
async def doc_create_document(params):
    title = params["title"]
    markdown = params["markdown"]
    teamspace_id = params.get("collection_id")  # 业务侧传

    pc = await _ensure_client()
    if not teamspace_id:
        raise ValueError("huly doc.create_document 必须传 collection_id (Teamspace _id)")

    # Step 1: create doc shell
    doc_id = await pc.ops.create_doc(
        "document:class:Document",
        teamspace_id,
        {
            "title": title,
            "content": "",  # 临时空 — 待 collab service 填 blob ref
            "parent": "document:ids:NoParent",
            "rank": str(int(time.time() * 1000)),
        },
    )

    # Step 2: markdown → ProseMirror JSON
    from ._internal.markdown_to_prosemirror import markdown_to_prosemirror
    pm_doc = markdown_to_prosemirror(markdown)

    # Step 3: collab service createContent → blob ref
    collab = HulyCollabClient(
        collab_url=os.environ["HULY_COLLAB_URL"],  # 注入 "http://collaborator:3078"
        ws_token=pc.rest.workspace_token,
    )
    blob_ref = await collab.create_content(
        workspace_uuid=pc.rest.workspace_uuid,
        object_class="document:class:Document",
        object_id=doc_id,
        object_attr="content",
        prosemirror_doc=pm_doc,
    )

    # Step 4: update_doc(content=blob_ref)
    await pc.ops.update_doc(
        "document:class:Document",
        teamspace_id,
        doc_id,
        {"content": blob_ref},
    )

    return {
        "plugin_name": "huly",
        "native_id": doc_id,
        "extras": {
            "teamspace_id": teamspace_id,
            "collab_blob_ref": blob_ref,
        },
    }
```

**Validation:**
- mock huly server 接受 doc shell + 返回 doc_id
- mock collab service 接受 createContent + 返回 blob_ref
- 集成测：真 Huly @ .44 调用全链路（v1 真 doc id 在 UI 可见）

### Pattern 10: ai_suggest_mentions LLM 钩子

**What:** v1.1 留接口 — DocCapability 提供 markdown → 推荐 @ 用户列表（用项目 LLM provider）

**When to use:** doc_write 节点配置时调用以辅助用户选 @ 谁（v1.5 节点接入时使用）

**Example:**

```python
# Source: 设计稿，借用 Phase 2.05 LLM node executor 路径（GLM / OpenAI provider）
# 不在 daemon 内调 LLM —— 跨进程隔离（Pitfall 8）

# DocCapability Protocol 扩展 (v1.1)
from typing import Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass(frozen=True)
class MentionSuggestion:
    """LLM 建议的 mention 候选。"""
    user_ref: "UserRef"
    confidence: float           # 0.0-1.0
    rationale: str              # 简短说明（"作者上下文提到 @ 张三审核此设计"）


@runtime_checkable
class DocCapability(Protocol):
    # ... existing methods
    async def ai_suggest_mentions(
        self,
        *,
        markdown: str,
        context: dict,                       # workspace_id / document_id / author_id / ...
    ) -> list[MentionSuggestion]:
        """LLM 推荐 mentions（v1 仅 Outline / Lark 实现，Huly v1.1 占位）。

        失败 fallback：返回空 list + structured log（不阻塞节点）。
        """
        ...


# OutlinePlugin / LarkDocsPlugin daemon 内 ai_suggest_mentions
async def doc_ai_suggest_mentions(params):
    """daemon 收到调用 → 读 prompt 模板 → 调主进程 LLM (subprocess can't reach LLM)。

    重要：daemon 不直接调 LLM —— 而是通过主进程的 capability bridge 回调。
    简化方案 (v1.1): daemon 把 markdown + context 序列化后 send_card-like 调主进程
    LLM facade 接口；主进程 LLM provider 路径同 Phase 2.05。
    """
    # v1 简化：daemon 不主动调 LLM；直接返回空 list，留 v1.5 实现
    # Plan 期决策：是否值得在 daemon 内直接调 LLM provider？
    return []
```

### Pattern 11: E2E browser-harness Multi-Plugin

**What:** 用 webapp-testing Skill (Playwright via browser-use 协议) 跑通：DAG 在 agent-builder UI 编辑 → 发布 → 运行 → 真 Outline + Lark + Huly 出文档

**When to use:** Wave 5 收官 gate（一个 spec 验证三 plugin 都 work）

**Example:**

```python
# Source: e2e_v2/ 已建结构 (Phase 4-10 共建)
# CLAUDE.md §2.2 / §3.5: browser-harness CDP 直连用户 Chrome

# e2e_v2/specs/test_phase5c_doc_plugins.py
import pytest


@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get("RUN_E2E"), reason="Standard E2E only")
async def test_doc_write_outline_real_render(browser_harness, api_client, dsl_builder):
    """DAG 拖 doc_write 节点（plugin=outline）→ 发布 → 运行 → Outline .44 真出文档。"""
    dsl = dsl_builder.with_doc_write(
        plugin="outline",
        collection="测试集合",
        title="E2E doc {{run_id}}",
        markdown="# E2E 测试文档\n\n这是 Phase 5.C 自动验证生成。",
    )
    workflow_id = await api_client.publish_workflow(dsl)
    instance_id = await api_client.run_workflow(workflow_id)
    await api_client.wait_for_completion(instance_id, timeout=30)

    # 验证 1：Outline API documents.info 找到该 doc
    state = await api_client.get_instance_state(instance_id)
    outline_doc_id = state["state"]["doc_write_result"]["native_id"]
    doc_info = await outline_client.documents_info(doc_id=outline_doc_id)
    assert "E2E 测试文档" in doc_info["text"]

    # 验证 2：browser-harness 打开 Outline UI 视觉确认渲染
    await browser_harness.goto(f"http://192.168.2.44:3000/doc/{outline_doc_id}")
    await browser_harness.wait_for_selector('h1:has-text("E2E 测试文档")')
    screenshot = await browser_harness.screenshot()
    assert screenshot is not None


# 类似 spec：test_doc_write_lark_real_render / test_doc_write_huly_real_render
```

### Pattern 12: Multi-Capability Plugin Test 4 维度

**What:** HulyPlugin 4-cap bundle 测试矩阵

**When to use:** Wave 3 HulyPlugin 集成 + Wave 5 E2E

**Example:**

| 维度 | Unit | Integration | E2E | 验证目标 |
|---|---|---|---|---|
| **共享 client lifecycle** | mock connect_huly + 多 capability 调用使用同一 client 实例 | 真 daemon spawn + 4 capability call 顺序，断言只有 1 次 login | E2E DAG 包含 doc_write + im_send，单实例运行 | 1 daemon 1 client + 4 facet 复用 |
| **per-capability method** | 各 capability handler 单测（doc_create / im_send_card / identity_resolve）| daemon spawn + 单 capability call + mock huly server | E2E 三 DAG 节点跑分别走 doc / im / identity | 每 capability method 路径正确 |
| **fault isolation** | mock daemon crash 后 4 个 pending future 全 set_exception | daemon 子进程 sys.exit(1) 同时 4 capability pending | E2E 不 cover（生产场景罕见） | 一 capability 错误不阻塞其他 |
| **license + AGPL 防御** | grep `# Inspired by`  注释在每 huly 文件 | unit test 检查文件头部有 attribution | (n/a) | hr port 文件全有 attribution |

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown → AST 解析 | 自己写 markdown parser | **`marko==2.2.2`** | CommonMark v0.31.2 完整支持 + 扩展系统；写 parser 容易遗漏 GFM 表 / footnote / 代码语言识别 |
| ProseMirror schema + transform | 手写 JSON dict 构造 | **`prosemirror==0.6.1`** | Huly server 接受 markup 字符串但严格 schema 校验；schema 不全会被静默接受但 UI 不渲染（hr §4.3 教训） |
| Lark Docs API HTTP 直调 | httpx 调 open.feishu.cn | **`lark-oapi==1.6.5`** | tenant_access_token 自动 refresh + Pydantic Request/Response 模型；Phase 4.06 已锁同版本不引重复 |
| Huly login + Tx + collab service 协议 | 重头实现 7 个 REST endpoint + Tx schema + ProseMirror markup | **hr port (`rest_client.py` 286 + `tx_factory.py` 220 + `tx_operations.py` 182 + `platform_client.py` 76 + `constants.py` 72 = 836 行 ~70% 零改 port)** | 已实战验证 13 user 14 容器 Huly stack；Tx schema / SocialIdentity 链路 / collab RPC 协议都已踩坑过 |
| Username → PersonUuid 解析每次查 Huly | 直接每次 find_one 两次 | **`cachetools.TTLCache(maxsize=10000, ttl=3600)` LRU** | hr 实测每个 send_dm 增加 200-500ms latency；高频路径必缓存 |
| Outline rate limiter 重试 | 自己 sleep/retry loop | **`tenacity` AsyncRetrying** (Phase 3.04 已锁) | Outline default `1000 req/min/IP`；需指数退避 +  429 单独处理 |
| docker_networks 接入容器名解析 | 解析 `/proc/<pid>/cgroup` 自己拆 | **`docker.from_env()` Python SDK** | hr §4.4 经验：连接失败常因 daemon 在新进程组但 cgroup 字段不一致；SDK 透明处理 |
| daemon ↔ 主进程 JSONRPC | 自己设计协议 | **Phase 5.B PlatformDaemonClient** 已建 | JSONRPC 2.0 over stdio + UUID4 request_id + line-delim envelope 已 production；不重写 |

**Key insight:** 本 phase 的工作量基准是 hr B-full-channel 836 行 + 551 行（共 1454 行 Python）+ 3 plugin manifest + ~5 个新 internal module（marko_render / collab_client / identity_resolver / ai_suggest_mentions / docker_networks 扩展）。**port + 改 capability 签名比从 0 设计快 3x**。最大风险是 **Huly server schema 变化导致的 markup 不渲染**（hr §4.3 教训）。

---

## Common Pitfalls

### Pitfall 1: Huly Document content 字段非 raw markdown（hr §4.3）— P0 必防

**What goes wrong:** `Document.content` 字段被设计为 collab service 的 blob reference，不是 markdown 字符串。直接传 markdown 给 `ops.update_doc(content=markdown_str)` server 端 200 OK 但 UI **完全空白不渲染**。

**Why it happens:** Huly 协作架构 — content 是被 collab service (port 3078) 通过 Y.js binary 同步的，`content` 字段只存 blob ref 让 UI 在加载时去 collab service 拉真实 doc。

**How to avoid:**
- HulyPlugin DocCapability 走二步流程（hr §4.3 + 本研究 §Pattern 9）
- 永不让主进程或 daemon 直接 `update_doc({"content": markdown})` —— 必须先 collab service createContent 拿 blob ref
- 单元测试断言 blob_ref 格式正确（"{docId}-content-{timestamp}"）

**Warning signs:** Huly UI 打开 doc 后 "Loading..." 一直不消失 / Browser console 报 `Unexpected token '<'` (nginx 未配 `/_collaborator/` proxy 或调用方未走 collab service)。

### Pitfall 2: Huly DM `chunter:DirectMessage` 静默 reject (hr §5.2) — P0 必防

**What goes wrong:** 创 `chunter:DirectMessage` 后立即 add ChatMessage → server Tx 提交 200 OK 但消息不写入 DB（ChatMessage 在 server 端被静默 drop）。

**Why it happens:** Huly server ACL/join 事件未与 collab service 完全同步 — 新建 DM 后短期 ACL 状态不一致。

**How to avoid:**
- HulyPlugin IMCapability 走 **per-user Channel 模式**（`chunter:Channel` 命名 `dm-{username}`）
- `_ensure_user_channel` lazy 创 + cache（同 PersonUuid LRU 模式）
- 不试 `chunter:DirectMessage`

**Warning signs:** 测试断言 `ChatMessage in DB` 一直失败但 Tx 提交无错；用户报告 "消息发送成功但收不到"。

### Pitfall 3: Lark Docs blocks/convert 单请求 10MB / 1000 block 限制 — P1

**What goes wrong:** 大 markdown 文档 convert 后超 1000 block，batch_create_blocks 返回 400 `Block count exceeds limit`，partial write 留 inconsistent state。

**Why it happens:** Lark Open Platform 官方限制：`single convert ≤ 10,485,760 chars`，`single create_blocks ≤ 1000 blocks`。

**How to avoid:**
- Markdown size precheck（> 10MB 直接 raise + 提示用户）
- block count > 800 时分批（留 200 余量）：调多次 `create_blocks` index=N 增量写
- 失败回滚（删 doc shell）让用户重试

**Warning signs:** test 用大 markdown (>5000 行) → 400 错；用户上传超大文档卡死。

### Pitfall 4: Outline rate limiter 429 — P1

**What goes wrong:** 高并发 doc_write 节点同 plugin daemon 调 Outline，触发 `RATE_LIMITER_DURATION_WINDOW=60s` 内 1000 req → 后续全 429。

**Why it happens:** Outline 默认 `1000 req/min/IP`；plugin daemon 是单 IP，租户共享。

**How to avoid:**
- tenacity AsyncRetrying + wait_exponential（1s/2s/4s） + 仅对 429 / 5xx 重试
- Outline self-host 调高 RATE_LIMITER 阈值（`.env: RATE_LIMITER_REQUESTS=10000`）
- 监控 structured log outcome="rate_limited" 频率

**Warning signs:** Phase 7 Run Viewer 显示 `outcome=error` 集中 + error message 含 "429 Too Many Requests"。

### Pitfall 5: docker network attach 失败模式 — P0

**What goes wrong:** 三种模式：
1. **docker daemon 不可用** (CI / 本地 dev macOS)：`docker.from_env()` raise；
2. **network 不存在** (`huly_huly_net` 拼写错 / Huly stack 未启)：`client.networks.get(name)` raise NotFound；
3. **container_id 找不到** (daemon 不在 docker container)：`/proc/<pid>/cgroup` 无 docker 段。

**Why it happens:** Decision 推荐 raise + structured log 不静默 — 这是好事但实现细节要每模式做出明确诊断。

**How to avoid:**
- Pattern 4 三 except 各自捕获 + 不同 RuntimeError 信息
- 测试三模式分别 mock（`MockDockerError`，`docker.errors.NotFound`，PID 找不到）
- 集成测试加 conditional skip `@pytest.mark.skipif(not _docker_available, reason="docker not running")`

**Warning signs:** Linux CI 中 plugin daemon spawn 失败 + 日志 `docker.network.connect failed: NotFound`。

### Pitfall 6: marko AST 节点名 vs ProseMirror 节点名不一致 — P1

**What goes wrong:** marko AST element name = `strong_emphasis` / `code_span` / `code_block`；ProseMirror node type = `strong` / `code` / `code_block`（部分一致部分不一致）。直接复制名字导致 Huly 静默接受但 UI 显示 raw text。

**Why it happens:** marko 遵循 CommonMark 命名（更冗长），ProseMirror schema 用更短的 type name。

**How to avoid:**
- Pattern 5 _MARK_MAP + _BLOCK_MAP 显式映射表
- Unit test 完整覆盖（heading 1-6 / paragraph / list ordered+unordered / blockquote / code_block lang / link / em / strong / code）
- 集成测：真 Huly @ .44 verify doc UI 真渲染（不是仅 DB 写入成功）

**Warning signs:** Huly UI 打开 doc 后所有内容显示成 raw markup JSON 字符串 → 节点 type name 不对。

### Pitfall 7: AllowlistTransport host wildcard (Phase 5.B 已锁 exact match) — P1

**What goes wrong:** 业务想加 `*.feishu.cn` 通配符 → Phase 5.B AllowlistTransport `host:port` 精确匹配拒绝。

**Why it happens:** Phase 5.B 锁定 exact match（CONTEXT decision 已写）— 防绕过；v2 扩。

**How to avoid:**
- Lark manifest 显式列出所有用到的 host：`open.feishu.cn:443`, `passport.feishu.cn:443`, `lf-cdn-tos.bytescm.com:443`（图片素材）
- 文档化在 plugin README — 让运维知道升级 lark-oapi 可能需补 host
- 不修改 AllowlistTransport（v2 才扩 wildcard）

**Warning signs:** 测试 Lark 真 API 时 `NetworkBlockedError: host=passport.feishu.cn`。

### Pitfall 8: hr port 文件无 license attribution → AGPL 风险 — P0 合规

**What goes wrong:** 直接 cp hr/backend/src/offboarding_flow/providers/huly/*.py 进 plugins/huly/_internal/ 不加任何注释 → 若 hr 项目是 AGPL（其实是 Apache-2.0，但 audit 不知道），整个 agent-builder 仓库被污染。

**Why it happens:** hr 项目当前未声明 license 头（其 pyproject.toml 显示 Apache-2.0 但 source 文件未带 attribution）；agent-builder 自己是 Apache-2.0，**保险起见所有 port 文件加 attribution**。

**How to avoid:**
- 每文件头部加：`# Inspired by hr/offboarding-flow design (commit 2ae8bf8) — not derived source; re-implemented under Apache-2.0`
- 提交前 grep 检查所有 `plugins/huly/_internal/*.py` 必有此 attribution
- License audit 测：`pytest test_license_attribution.py` 静态扫所有 huly internal file

**Warning signs:** code review 中发现 huly internal 文件无 attribution；hr 项目升级 license 时 agent-builder 风险曝光。

### Pitfall 9: lark_open_id 缓存 vs PersonUuid 双源（5.D 反向 sync 前置） — P1

**What goes wrong:** Lark `@user` 需要 `lark_open_id`，agent-builder users 表暂用业务 `user_id`，无 lark_open_id 列。LarkDocsPlugin IdentityCapability.resolve_user 调用要么硬编码本地映射要么调 Lark contact API（HR 域，Phase 5.D 才有）。

**Why it happens:** Phase 5.C 范围不含 HRCapability / user_platform_mappings 反向 sync —— Phase 5.D 才接入。

**How to avoid:**
- Phase 5.C v1 简化：LarkDocsPlugin manifest config 有 `username_to_lark_open_id: dict[str, str]` 字段（管理员手动填）
- IdentityCapability.resolve_user 直接读 manifest config map
- 文档化 Phase 5.D 后会改为 user_platform_mappings 查询

**Warning signs:** LarkDocsPlugin.add_comment 时 `@username` 退化为纯文本（lark_open_id 未配）。

### Pitfall 10: HulyPlatformClient daemon 内单例 + 多 facet 并发死锁 — P1

**What goes wrong:** 4 capability 并发调用 → 都 `await _ensure_client()` → asyncio.Lock 串行化第一个调用 → 但若第一个 connect 30s 超时，后 3 个 await 也卡住 30s。

**Why it happens:** lazy init pattern + lock 在首次 connect 慢路径变并发瓶颈。

**How to avoid:**
- daemon 启动时 eagerly 调用 `connect_huly()` 把 client 初始化好（不要 lazy）
- 或：login + selectWorkspace 的总超时降到 5s，30s 是 daemon invoke 上限不该再叠加 connect 超时
- 单测：3 并发 invoke 任一 ≤ 100ms（mock fast Huly server）

**Warning signs:** daemon spawn 后第一次 invoke 慢 30s + 同时 inflight 调用全等同样长。

### Pitfall 11: prosemirror 0.6.1 ListItem 必须含 paragraph 子节点 — P2

**What goes wrong:** marko AST 中 `list_item.children = [raw_text]`（inline），但 ProseMirror schema-list 要求 `list_item.content = [paragraph]`（必须包一层 paragraph）。直接转换 → ProseMirror schema validation fail or Huly UI 显示空列表。

**Why it happens:** marko CommonMark 模型 list_item 直接持 inline；ProseMirror block-only 模型 list_item.content[0] 必须是 block。

**How to avoid:**
- Pattern 5 `_convert_node("list_item")` 强制 wrap inline → paragraph
- prosemirror Python 0.6.1 schema 校验：测试时调 `schema.nodeFromJSON(pm_doc)` 真校验
- Huly @.44 集成测验证 bullet list 真渲染（不是 DB 写入成功）

**Warning signs:** 测试 markdown "- a\n- b" → ProseMirror JSON 里 listItem.content[0].type=text（错）而非 paragraph。

### Pitfall 12: tenacity AsyncRetrying 与 daemon timeout 叠加 — P2

**What goes wrong:** Outline 429 → tenacity 重试 3 次 + wait 1+2+4=7s + 每次请求 5s = 22s；而 Phase 5.B daemon_client invoke timeout 30s — 一次 retry 链就占 daemon 75% 余量。

**Why it happens:** invoke timeout 是 envelope 层；plugin daemon 内部 retry 是业务层；累计可能超时。

**How to avoke:**
- tenacity 最多 2 次（共 1+2=3s 等 + 3 次 HTTP 调用 ~10s）
- 或：动态读 timeout context — daemon 接收 invoke 时附带 deadline，retry 必须在 deadline 内
- 单测：retry 链 + invoke timeout 联调（mock 429 series）

**Warning signs:** plugin invoke 报 `asyncio.TimeoutError` 频率高，daemon log 显示进了 retry 但未完成。

---

## Code Examples

Verified patterns from authoritative sources:

### Outline documents.create (HIGH confidence — OpenAPI spec3.yml)

```python
# Source: https://github.com/outline/openapi/blob/main/spec3.yml
import httpx

async def outline_create_doc(base_url: str, api_token: str, *,
                                title: str, text: str, collection_id: str,
                                parent_document_id: str | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{base_url.rstrip('/')}/api/documents.create",
            headers={"Authorization": f"Bearer {api_token}"},
            json={
                "title": title,
                "text": text,                      # markdown 透传
                "collectionId": collection_id,
                "parentDocumentId": parent_document_id,
                "publish": True,
            },
        )
        r.raise_for_status()
        return r.json()["data"]   # {id, url, title, text, ...}
```

### Lark Docs blocks/convert (HIGH confidence — Feishu Open Platform 官方)

```python
# Source: https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/document/convert
import httpx

async def lark_convert_markdown(tenant_token: str, markdown: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://open.feishu.cn/open-apis/docx/v1/documents/blocks/convert",
            headers={"Authorization": f"Bearer {tenant_token}",
                       "Content-Type": "application/json"},
            json={"content_type": "markdown", "content": markdown},
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(f"Lark convert error: {body.get('code')} {body.get('msg')}")
        return body["data"]   # {first_level_block_ids: [...], blocks: [...]}
```

### Huly collab service createContent (HIGH confidence — TypeScript collaborator-client 源码 + hr §4.3)

```python
# Source: https://github.com/hcengineering/platform server/collaborator/src/server.ts
# + hr/docs/huly-integration-architecture-2026-05-18.md §4.3-4.5
import json
import urllib.parse
import httpx


async def huly_collab_create_content(collab_url: str, ws_token: str, *,
                                        workspace_uuid: str, object_class: str,
                                        object_id: str, object_attr: str,
                                        prosemirror_doc: dict) -> str:
    encoded_doc_id = urllib.parse.quote(
        f"{workspace_uuid}|{object_class}|{object_id}|{object_attr}",
        safe="",
    )
    markup = json.dumps(prosemirror_doc, ensure_ascii=False)
    body = {"method": "createContent", "payload": {"content": {object_attr: markup}}}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{collab_url.rstrip('/')}/rpc/{encoded_doc_id}",
            json=body,
            headers={"Authorization": f"Bearer {ws_token}"},
        )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"collab createContent error: {data['error']}")
    return data["content"]["content"]   # blob ref "{docId}-content-{ts}"
```

### marko ASTRenderer 用法 (HIGH confidence — marko 2.2.2 readthedocs)

```python
# Source: https://marko-py.readthedocs.io/en/latest/api.html
import marko
from marko.ast_renderer import ASTRenderer

md = marko.Markdown(renderer=ASTRenderer)
raw_ast = md.convert("# Hello\n\nWorld")
# raw_ast == {"element": "document", "children": [
#     {"element": "heading", "level": 1,
#       "children": [{"element": "raw_text", "children": "Hello", ...}]},
#     {"element": "paragraph",
#       "children": [{"element": "raw_text", "children": "World", ...}]},
# ]}
```

### prosemirror schema 节点构造 (HIGH confidence — prosemirror 0.6.1 PyPI 文档)

```python
# Source: https://pypi.org/project/prosemirror/  v0.6.1
from prosemirror.schema.basic import schema as basic_schema
from prosemirror.schema.list import add_list_nodes

# 扩展 basic_schema 含 bullet/ordered_list
schema = basic_schema.copy()
schema = schema.spec.update(nodes=add_list_nodes(schema.spec.nodes, "paragraph block*", "block"))

doc = schema.node("doc", {}, [
    schema.node("heading", {"level": 1}, [schema.text("Hello")]),
    schema.node("paragraph", {}, [schema.text("World")]),
])

# Validate
assert doc.check() is None  # raises if invalid
json_dict = doc.to_json()    # 序列化为 ProseMirror JSON
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Outline 仅 Markdown 全量 update | 同（self-host v2026 仍稳）| - | 直接 markdown 替换是 Outline 最简单也最推荐路径 |
| Lark Docs 仅 block API (无 markdown convert) | 2023 末加 `/docx/v1/documents/blocks/convert` 端点 | 2023-Q4 | 极大简化 markdown 写入；之前要手拆 block JSON |
| Huly Document.content = markdown raw | 2024 改 collab service blob ref（必须二步） | 2024 (Huly v0.7.300+) | hr §4.3 验证 v0.7.423 已是新方案；老 sample code 失效 |
| ProseMirror Python 仅 0.5.x | **0.6.1 (2026-02 release)** 含 schema-basic 1.2.4 + schema-list 1.5.1 | 2026-02-21 | 项目今天发版的版本符合规范 |
| Dify plugin daemon Go-based | agent-builder Phase 5.A 用 Python subprocess + JSONRPC over stdio | 2026-05-17 | 简化 — 不引入 Go runtime；与 Phase 5.A acid test 兼容 |

**Deprecated/outdated:**
- ❌ Huly Y.js binary delta（v1 不上 — collab service markup 字符串模式更稳）
- ❌ Outline 老 `documents.import` (markdown 直接 import) — 与 `documents.create` text 字段功能重复且字符限制更紧
- ❌ Lark 直接 `create_blocks` 不经 convert（手拆 block 已劝退）
- ❌ chunter:DirectMessage（hr §5.2 静默 reject — 永用 per-user Channel）

---

## Open Questions

1. **Huly daemon 在 macOS dev 用什么连 collab service？**
   - 已知：docker_networks 在 PosixResourceSandbox 是 no-op
   - 不清：macOS dev 怎么验证 daemon → collab service ping？mock server？SSH tunnel?
   - Recommendation：Wave 2 阶段先 mock huly collab server（aiohttp + /rpc 路由），Wave 5 才上 .44 真集成测

2. **OutlinePlugin comments.create 用 ProseMirror JSON 还是 markdown？**
   - 已知：Outline `comments.create` data 字段是 ProseMirror JSON
   - 不清：自己写 ProseMirror JSON 还是用 Outline 自己的 `/api/markdown.parse` 端点？后者不存在
   - Recommendation：复用 §Pattern 5 `markdown_to_prosemirror` (本来给 Huly 用) — 一个实现两用

3. **LarkDocsPlugin @ 用户的 markdown 语法 / Lark Block 语法不一致**
   - 已知：Lark Block 模型 @ 用 `<at user_id="ou_xxxxx"></at>` 锚点
   - 不清：markdown 透传后 `@用户` 文本能否被 Lark blocks/convert 自动识别为 user mention？
   - Recommendation：实测；若不行，在 markdown_to_prosemirror 之前对 mention 模板字符串做 pre-process (`@username` → `<at user_id="..."></at>`)

4. **HulyPlugin TrackerCapability v1 stub 接口要不要写？**
   - CONTEXT: TrackerCapability 是 stub（Phase 5.C 不实做）
   - 不清：要不要预先在 ADR-001 定义 Protocol 让 manifest 校验？
   - Recommendation：本 phase 不写 TrackerCapability Protocol；HulyPlugin manifest `capabilities` 不含 "tracker"（让 ADR-001 v1.1 加）

5. **ai_suggest_mentions LLM 在 daemon 内还是回主进程？**
   - 已知：daemon 独立进程，不能直接调主进程的 LLM provider
   - 不清：通过 JSONRPC 反向调主进程（"upcall"）还是 daemon 内重复一份 LLM client？
   - Recommendation：Plan 期决策 — 推荐 v1 daemon 内重复 LLM client（manifest config 注入 OPENAI_API_KEY via env_allowlist），简单但牺牲一点资源；v2 改 upcall 模式

6. **hr 项目实际 license**
   - 已知：hr/pyproject.toml 声明 Apache-2.0
   - 不清：hr README / 各文件头是否带 attribution？
   - Recommendation：Plan 0 reading doc 期间检查 hr 仓库 LICENSE 文件 + 至少 1 个 source 文件头 attribution（若无，Phase 5.C 文件加 `# Inspired by hr/offboarding-flow design under Apache-2.0` 防御）

---

## Sources

### Primary (HIGH confidence)

- **Phase 5.A acid test stub**: `/Users/admin/ai/resume/interview/liuxin/agent-builder/plugins/huly/huly_plugin.py` (5.A 现有 + JSONRPC + im.send_card 真实现 — 5.C 直接演进)
- **Phase 5.A Manifest schema**: `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/platforms/manifest.py` (PlatformManifest + SandboxConfig + load_manifest — 5.C 扩 docker_networks)
- **Phase 5.A DocCapability Protocol**: `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/platforms/capabilities/doc.py` (双路径 + 6 method)
- **Phase 5.A IMCapability Protocol**: `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/platforms/capabilities/im.py` (HulyPlugin 4-cap bundle 共用)
- **Phase 5.B SandboxRunner**: `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/platforms/sandbox/runner.py` (extend docker_networks)
- **Phase 5.B PlatformDaemonClient**: `/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/app/agent_builder/platforms/daemon_client.py` (sandbox_config wiring)
- **hr huly REST 客户端**: `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/rest_client.py` (286 行 — 直接 port 模板)
- **hr Tx factory**: `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_factory.py` (220 行)
- **hr Tx operations**: `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_operations.py` (182 行)
- **hr Platform client**: `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/platform_client.py` (76 行)
- **hr huly Doc provider**: `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly_doc_provider.py` (304 行 — 二步流程)
- **hr huly IM provider**: `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly_im_provider.py` (247 行 — per-user Channel)
- **hr Huly 整合架构文档**: `/Users/admin/ai/resume/interview/liuxin/hr/docs/huly-integration-architecture-2026-05-18.md` (1454 行权威说明 — 含 §4.3 二步流程 / §4.4 docker network / §4.5 collab RPC 协议 / §5.2 per-user Channel / §5.5 PersonUuid 解析)
- **ADR-001 (本 phase 权威 spec)**: `/Users/admin/ai/resume/interview/liuxin/agent-builder/docs/plans/2026-05-17-platform-plugin-framework-ADR.md` (§3.2 DocCapability + §5 PlatformBundle)
- **Outline OpenAPI spec3.yml**: https://github.com/outline/openapi/blob/main/spec3.yml (HIGH — documents.create/.update/.info/.delete + comments.create endpoint 全签名)
- **Lark Docs convert API 官方文档**: https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/document/convert (HIGH — 10MB / 1000 block 限制 + 31 block type 全列)
- **Lark Docs overview**: https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/docx-overview (HIGH — document_id + block_id 模型 + 6 doc API + 7 block API)
- **Huly collaborator-client TS 源码**: https://github.com/hcengineering/platform server/collaborator/src/server.ts (HIGH — /rpc 端点 + JWT Bearer 鉴权)
- **marko 2.2.2 official docs**: https://marko-py.readthedocs.io/en/latest/api.html (HIGH — Renderer extends + ASTRenderer JSON 输出)
- **prosemirror Python 0.6.1 PyPI**: https://pypi.org/project/prosemirror/ (HIGH — 2026-02-21 release + schema-basic 1.2.4 + schema-list 1.5.1)
- **Outline API 主页**: https://www.getoutline.com/developers (MEDIUM — overview)
- **Outline rate limiter docs**: https://docs.getoutline.com/s/hosting/doc/rate-limiter-HSqErsUgXH (HIGH — 1000 req/min/IP 默认 / RATE_LIMITER_REQUESTS env)

### Secondary (MEDIUM confidence)

- **WebSearch — "Outline documents.create text parentDocumentId collectionId rate limit"** (Cross-verified with OpenAPI spec)
- **WebSearch — "Lark Feishu Python SDK lark-oapi 1.6.5 docx documents api"** (Cross-verified with PyPI lark-oapi 1.6.5)
- **WebSearch — "marko python markdown parser AST to ProseMirror JSON conversion library"** (Cross-verified with readthedocs)
- **WebSearch — "Huly server v0.7.423 collaborator service workspace token authentication"** (hr §4.3 一手验证 + huly-selfhost ARCHITECTURE_OVERVIEW.md)
- **WebSearch — "docker network connect running container require root permission"** (Docker docs official + rootless mode notes)

### Tertiary (LOW confidence — Plan 期需进一步验证)

- ❓ **Lark `<at user_id="ou_xxxxx"></at>` markdown 内识别**：WebSearch 提到 Feishu 支持 @ 但未验证 markdown 透传 convert API 时是否识别。**Plan 期需 1h spike**。
- ❓ **Outline `comments.create` data 字段 ProseMirror schema 版本**：Outline 自己用 prosemirror-markdown 但版本未知；可能需对齐 prosemirror Python 0.6.1。
- ❓ **macOS dev 不能用 docker_networks 时如何端到端测 Huly**：本研究推荐 mock huly server，但真集成测必须 Linux CI 或 SSH tunnel + .44 — Plan 期 spike 验证。

---

## Phase Topology (Planner 参考)

**8 plans，5 wave，60-90% 可并行。** plan-check 阶段细化命名 + DoD。

| Wave | Plan | 名称（draft） | 依赖 | 并行性 | 估时 |
|---|---|---|---|---|---|
| **Wave 1** | **05c-01** | SandboxRunner `docker_networks` + manifest `sandbox.docker_networks` + Phase 5.B 集成强化 + reading doc Dify reading doc | (5.B) | — | ~25min |
| **Wave 2 并行** | **05c-02** | hr huly `_internal` port — rest_client + tx_factory + tx_operations + platform_client + constants（836 行零改 port 大头 + AllowlistTransport 改造 + license attribution）| 01 | ✓ parallel | ~30min |
| **Wave 2 并行** | **05c-03** | OutlinePlugin daemon — manifest + httpx client (documents.* + comments.create) + replace_document_content + add_comment + ai_suggest_mentions stub + 集成测 mock outline server | 01 | ✓ parallel | ~25min |
| **Wave 2 并行** | **05c-04** | LarkDocsPlugin daemon — manifest + lark-oapi 包装 (docx.v1.* + drive.v1.comment) + IdentityCapability (manifest username→lark_open_id map) + 集成测 mock lark server | 01 | ✓ parallel | ~30min |
| **Wave 3** | **05c-05** | HulyPlugin 4-cap bundle — manifest 升级 (4 capability + docker_networks) + huly_plugin.py 4 dispatcher + DocCapability 二步流程 (collab_client + markdown_to_prosemirror) + IMCapability per-user Channel + IdentityCapability LRU cache + 替换 5.A acid test stub | 02 | — | ~45min |
| **Wave 4 并行** | **05c-06** | ai_suggest_mentions LLM 钩子 — DocCapability Protocol v1.1 扩展 + LLM provider 复用路径 + 3 plugin prompt 模板 (Outline / Lark 实现 / Huly stub) + 失败 fallback 测试 | 03, 04, 05 | ✓ parallel | ~25min |
| **Wave 4 并行** | **05c-07** | Capability fallback service layer — supports_collaborative_edit=False 时 service 接收 delta → 自动 serialize markdown 走 replace；plugin discovery / installation 路径 wiring 三 plugin 全可注册 | 03, 04, 05 | ✓ parallel | ~20min |
| **Wave 5** | **05c-08** | E2E gate — browser-harness CDP 三 spec (Outline / Lark / Huly 真出文档真渲染) + Phase 7 Run Viewer structured log 覆盖 + license attribution audit test + Phase 5.A/B regression 全绿 | 06, 07 | — | ~40min |

**总计 8 plan / 5 wave / 估时 ~4h（并行后约 ~2.5h 关键路径）**。

**关键 license / quality 约束（每 plan 必有 reading doc Task 0）**：
- 每 plan 第一个 commit 是 reading doc（Dify reading + 必要时 Outline / Lark / Huly 参考）
- 所有 huly internal port 文件加 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source` 头部注释
- 每 plan 包含 Phase 5.A regression 271 platforms tests 通过 + Phase 5.B 5/5 acid test 通过的 DoD 检查

---

## Metadata

**Confidence breakdown:**
- Standard Stack: **HIGH** — Outline OpenAPI spec3.yml 一手 + Lark 官方 convert 文档 + Huly hr port 1454 行 production-validated + marko/prosemirror Python 版本 PyPI 现查
- Architecture: **HIGH** — ADR-001 §3.2/§5 权威 + Phase 5.A/B 全 25 plan 已稳定接口
- Pitfalls: **HIGH** — 12 项中 8 项来自 hr 实战教训（§4.3/4.4/4.5/5.2/5.5）+ 4 项 Phase 5.B 经验 + 1 项 lark-oapi 经验
- marko → ProseMirror mapping: **MEDIUM** — hr §4.5 给的 JSON 例子只覆盖 heading + bulletList；本研究 §Pattern 5 补充 12 元素 mapping，需 unit test 充分覆盖

**Research date:** 2026-05-18
**Valid until:** 2026-06-18（30 天 — Huly v0.7 schema 稳定 + Outline OpenAPI 稳定；fast-moving 项是 lark-oapi 版本，若 1.7+ 出需重 verify）

---

## RESEARCH COMPLETE
