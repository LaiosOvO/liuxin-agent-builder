# Phase 5.C: DocCapability 真接入 - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning
**Authoritative specs:**
- ADR-001 `docs/plans/2026-05-17-platform-plugin-framework-ADR.md` §3.2 DocCapability + §5 PlatformBundle
- **hr/offboarding-flow B-full-channel** `/Users/admin/ai/resume/interview/liuxin/hr/docs/huly-integration-architecture-2026-05-18.md` (1454 行 production-validated Python impl 可 port)
- Phase 5.A 05a-RESEARCH.md (Huly chunter / document plugin spec)

<domain>
## Phase Boundary

把 Phase 5.A DocCapability Protocol（仅 Mock + 设计）真接到 **3 个平台**：
- **Outline** (开源 markdown 协作，最简单 — 真 markdown create/update)
- **Lark Docs** (飞书文档 — markdown→Block 转换)
- **Huly** (一体化平台 — multi-capability bundle: doc + im + identity共享 daemon)

**hr 的 660 行 Python B-full-channel** 是 Huly plugin daemon 的**直接 port 模板**（含 rest_client.py / tx_factory.py / tx_operations.py / huly_doc_provider.py / huly_im_provider.py）。**不重头摸索**。

**Phase 5.C 不做**：
- HRCapability 真接入（Phase 5.D — 飞书企微钉钉 HR + Huly hr module + dept: 表达式）
- IdentityCapability `watch_user_changes` 反向 sync（Phase 5.D — 与 HR 同步绑定）
- Bot 入站触发 + Slash 分发（Phase 4.5 — 不在本 phase）
- DAG `doc_write` / `doc_mention` 节点（v1.5 — 本 phase 仅 Capability + plugin，节点接入留待 5.C 末或后续）

</domain>

<decisions>
## Implementation Decisions

### 1. 3 个 plugin 实现优先级 + 范围

**OutlinePlugin (P0 最简)**
- DocCapability only (单一 capability)
- `replace_document_content(markdown)` 直接走 Outline `POST /api/documents.update`
- `apply_document_delta` 抛 `NotImplementedError("Outline 不支持 CRDT delta — 用 replace")`
- `supports_collaborative_edit = False`
- 凭据：`api_token` only

**LarkDocsPlugin (P0 国内首选)**
- DocCapability + IdentityCapability (multi-capability)
- markdown → Lark Block 转换（用 `marko` AST + 严格映射）
- 评论 + @ 人通过 lark_open_id（IdentityCapability 提供）
- `supports_collaborative_edit = False`（飞书 Block 写入即提交，不是 CRDT delta）
- 凭据：`app_id + app_secret + tenant_access_token` 缓存

**HulyPlugin (P0 一体化 acid test 升级)**
- **4-capability bundle**: DocCapability + IMCapability + IdentityCapability + (TrackerCapability stub)
- 共享 `HulyPlatformClient` (单 daemon 进程 + 单 WS 连接)
- DocCapability 走 **二步流程**（create shell → collab service RPC → update content ref）
- `supports_collaborative_edit = True` → `apply_document_delta(ProseMirrorJSON)`
- IMCapability 走 **per-user Channel 模式** (DM 静默 reject hr 实战教训 §5.2)
- IdentityCapability 走 SocialIdentity → Employee mixin 链 + LRU cache
- 凭据：`huly_url + huly_workspace + huly_admin_email + huly_admin_password`

### 2. hr B-full-channel 1454 行 Python port 策略

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

**这是 Phase 5.C 的工作量基准** — port + 改 capability 签名比从 0 设计快 3x。

### 3. 网络白名单 + docker network attach (hr 教训 §4.4)

**Phase 5.B AllowlistTransport** 只验证了 application-level (httpx) 白名单 — Huly daemon 需要 attach `huly_huly_net` docker network 才能调 `collaborator:3078`。

**Phase 5.C 必加**：
- `SandboxRunner.spawn_with_limits()` 接受 `docker_networks: list[str]`
- manifest `sandbox.docker_networks: ["huly_huly_net"]` (新字段)
- daemon spawn 时 `docker network connect <network> <container_id>` (PosixResourceSandbox no-op，CgroupsV2Sandbox 才做)
- 测试：mock huly server 监听 `127.0.0.1:18087`，跳过真实 docker network

### 4. DocCapability replace_content vs apply_delta 双路径策略

- **OutlinePlugin / LarkDocsPlugin**: `supports_collaborative_edit = False`
  - 仅实现 `replace_document_content(markdown)` 全量替换
  - `apply_document_delta` raise `NotImplementedError`
  - Service layer fallback：用户传 delta 时检测 `supports_collaborative_edit` 自动序列化为 markdown 走 replace

- **HulyPlugin**: `supports_collaborative_edit = True`
  - 主路径 `apply_document_delta(ProseMirrorJSON)` 走 collab service RPC
  - `replace_document_content(markdown)` 做 `marko` parse → ProseMirror JSON → apply_delta（hr 二步流程）
  - **二步流程优先封装在 plugin daemon 内**，主进程仅传 markdown 或 delta，无需感知 collab service

### 5. IMCapability per-user Channel 模式（hr 教训 §5.2）

- HulyPlugin IMCapability.send_card 默认 RecipientSpec `kind="dm_user"` → 自动 fallback per-user `chunter:Channel` 命名 `dm-{username}`
- 不尝试 `chunter:DirectMessage`（server 静默 reject）
- 接口对外仍是 `kind="dm_user"`，业务无感

### 6. PersonUuid 解析缓存 (hr §5.5)

- HulyPlugin daemon 内置 `_resolve_account_cache: LRU(maxsize=10000)`
- 输入 username → SocialIdentity (key=`email:{user}@demo.local`) → Employee mixin → personUuid
- TTL: 1h（manifest config 可覆盖）
- 缓存 miss → 实时查 + 写缓存

### 7. ai_suggest_mentions LLM 钩子 (ADR-001 §3.2 v1.1 留接口)

- `DocCapability.ai_suggest_mentions(markdown, context) -> list[MentionSuggestion]` v1 仅在 OutlinePlugin / LarkDocsPlugin 实现（HulyPlugin v1.1 留 NotImplementedError）
- 用 agent-builder 已有 LLM provider (GLM / OpenAI)
- prompt 模板路径：`plugins/<name>/prompts/ai_suggest_mentions_zh.md` (plugin 自带)
- 失败 fallback：返回空 list + structured log

### 8. AGPL-3.0 license 防御 (Phase 5.A 已设)

- **不拷贝** hr/offboarding-flow 源码（hr 自己也是研究稿，未必清晰 license）
- **借鉴**：架构模式 / Tx 链路设计 / collab service RPC 调用方式 / 二步流程 / per-user Channel 绕开方案
- 重写实现，不复制 — 各文件加 `# Inspired by hr/offboarding-flow design, not derived source`

### 9. Capability test 三层（CLAUDE.md §2.2）

- **Unit**: DocCapability Protocol contract + 每 plugin facade marshalling
- **Integration**: 真 plugin daemon spawn + mock Outline/Lark/Huly server (aiohttp/httpx mock)
- **E2E**: browser-harness CDP 直连用户 Chrome —— 跑通"DAG → doc_write 节点 → 真 Outline/Lark/Huly 文档" 一条端到端（v1.5 节点接入时跑）

### 10. PlatformBundle facet 模式 (ADR-001 §5)

- HulyPlugin 是首个 multi-capability plugin (4 facet 共享 daemon)
- `HulyPlugin.doc / .im / .identity / .tracker` 都返回 facade 包装同一个 `HulyPlatformClient`
- Plugin 初始化时一次性 `login + selectWorkspace` 拿 ws_token，4 facet 复用
- 这是 Phase 5.A acid test 5/5 mock 模式的**真实生产升级**

### Claude's Discretion
- marko AST 转 ProseMirror JSON 的具体 mapping rule (hr 教训 §4.5 给了 JSON 例子但不全)
- daemon spawn 时 docker network attach 失败时的降级策略（推荐 raise + structured log，不静默）
- AllowlistTransport 是否支持 wildcard host (Phase 5.B 已规约 exact match — Phase 5.C 不扩)
- 缓存 invalidation 时机（推荐 plugin manifest 可声明 cache_ttl_seconds，默认 3600）
- structured log 字段 schema：plugin_name + workspace_id + capability + method + latency_ms + outcome (Phase 7 Run Viewer 钩子)

</decisions>

<specifics>
## Specific Ideas

- hr Huly 部署在 `192.168.2.44:8087` (Phase 1 SSH tunnel 已配)，集成测可直连
- hr `seed_huly_users.py` 13 users + SocialIdentity + Employee mixin 已就绪
- HulyPlugin daemon 测试可复用 hr 已 seed 的 Huly 实例 (节省 mock 工作)
- Outline 也部署在 .44 (docker-compose `outline`)，可直接集成测
- 飞书 Lark 凭据 user 已有，但 E2E 测试可能要走 sandbox app
- Phase 5.A HulyPlugin stub (5/5 acid test) 是 5.C HulyPlugin 的演进起点 — replace mock_huly_server.py 为真 huly_url

## reference impl 文件位置（plan 期必读）

- `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/rest_client.py` (286 行 — login + selectWorkspace + tx + find-all + ensure-person REST 调用)
- `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_factory.py` (220 行 — TxCreateDoc + TxCollectionCUD + TxUpdateDoc + TxRemoveDoc 构造)
- `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly/tx_operations.py` (182 行 — high-level create_doc / add_collection / update_doc / remove_doc API)
- `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly_doc_provider.py` (304 行 — 二步流程 create_document)
- `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/huly_im_provider.py` (247 行 — per-user Channel send_dm + ensure_user_in_channel)

</specifics>

<deferred>
## Deferred Ideas

- DAG 节点 `doc_write` / `doc_mention` 配置面板（v1.5 — 本 phase 仅 Capability + plugin，节点接入留下个 phase）
- Lark Docs CRDT delta（飞书 Block 改造为 collaborative — v2）
- Huly Tracker IssueCapability 完整接入（spike 已通过 — v1.1 加 Protocol）
- multi-platform doc 同步（Outline ↔ Lark mirror — v2）
- ai_suggest_mentions Dify Workflow 路径（dify-integration 文档 §4.4 方案 B — v2 双路）
- AllowlistTransport wildcard host (`*.feishu.cn`) — v2（Phase 5.B 锁定 exact match）

</deferred>

---

*Phase: 05c-doc-capability*
*Context gathered: 2026-05-18*
*Reference impl: hr/offboarding-flow B-full-channel 1454 行 Python (huly-integration-architecture-2026-05-18.md)*
