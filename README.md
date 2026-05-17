# agent-builder

> 通用拖拽式 LangGraph 编排平台 — **"LangGraph as Service"**
> 非编码人员 5 分钟拖出"多通道审批 + 公网回调"的可视化工作流

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Skeleton: Onelevenvy/flock](https://img.shields.io/badge/Skeleton-Onelevenvy%2Fflock-orange)](https://github.com/Onelevenvy/flock)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16.2%2B-black)](https://nextjs.org/)

---

## 一、它是什么

面向 **HR / 行政 / 业务负责人**等非编码人员的可视化 LangGraph 编排平台。在 Web 画布上拖拽节点构建工作流 → 实时存为 DSL → 一键发布 → HITL 节点通过邮件 / 主流 IM（飞书/企微/钉钉/Slack/Mattermost）四态决策 → 配置公网入口后审批人点击 token 链接即登录决策。

**核心价值**：让非编码人员通过拖拽 5 分钟搭出"多通道审批 + 公网回调"的 LangGraph 工作流，并真实跑起来。如果其他都失败，至少这条主路径必须通：

> 拖一个 HITL 节点 → 配邮件收件人 → 发布 → 审批人收到邮件 → 点开链接同意 → 流程推进 ✓

---

## 二、当前进度

> 路线图：`Phase 1 → 2 → 3 → 4 → 4.5 → 5.A → 5.B → 5.C → 5.D → 6 → 7`

| Phase | 主题 | Plans | 状态 | 完成日 |
|-------|------|-------|------|--------|
| 1 | Skeleton + 账号体系（多租户隔离 / RBAC / 公网最小暴露面） | 6/6 | ✅ Complete | 2026-05-16 |
| 2 | DSL 引擎 + 基础节点（Canvas + 5 节点 + Postgres checkpoint + SSE 时间线） | 10/10 | ✅ Complete | 2026-05-17 |
| 3 | HITL 单节点 + Email 审批（四态决策 + Token 即登录 + Safe Links 防御） | 10/10 | ✅ Complete | 2026-05-17 |
| 4 | 审批链 + IM 通知（4 模式 × 飞书/企微/钉钉/Slack/Mattermost/通用 Webhook） | 12/12 | ✅ Complete | 2026-05-17 |
| 4.5 | Bot Triggers + Slash 分发 + Reply（双向 IM） | 1/6 | 🚧 Wave 1 完成 | — |
| 5.A | PlatformPlugin 框架（Dify-style，6 Capability Protocol + Manifest + Registry） | 7/7 | ✅ Complete | 2026-05-17 |
| 5.B | Plugin 沙箱 + Daemon 通信（PosixResource + CgroupsV2 + AllowlistTransport + Watchdog） | 5/5 | ✅ Complete | 2026-05-18 |
| **5.C** | **DocCapability 真接入（Outline + Lark + Huly multi-capability bundle）** | **0/8** | **🚧 进行中** | — |
| 5.D | HRCapability + Identity 反向 sync（dept: 表达式 + user_platform_mappings） | 0/TBD | ⏸ Not started | — |
| 6 | Plugin Marketplace（zip 上传 / dry-run / 注册 / 画布动态加载） | 0/TBD | ⏸ Not started | — |
| 7 | 可观测性 + 运维工具（每节点 Run Viewer + 时间线 Gantt + 历史回放） | 0/TBD | ⏸ Not started | — |

详见 `.planning/ROADMAP.md`。

---

## 三、需求覆盖

### v1 — 60 条需求 / 10 类目

| 类目 | 需求数 | 完成数 | 状态 |
|------|--------|--------|------|
| Editor（编辑器与 DSL） | 5 | 3 | EDIT-04/05 in Phase 5/6 |
| Node Types（节点类型） | 10 | 6 | NODE-04/08/09/10 in Phase 5 |
| Engine（执行引擎） | 5 | 5 | ✅ 全 Complete |
| HITL（四态决策） | 7 | 7 | ✅ 全 Complete |
| Notification（通知通道） | 10 | 10 | ✅ 全 Complete |
| IM Directory（双向同步 L3） | 5 | 0 | Phase 5.D |
| Auth（认证与权限） | 6 | 6 | ✅ 全 Complete |
| Network（公网入口与安全） | 5 | 5 | ✅ 全 Complete |
| Plugin（节点扩展） | 4 | 0 | Phase 5.A/B/C/D + 6 |
| Deploy（部署） | 3 | 2 | DEPL-03 in Phase 6 |
| **合计** | **60** | **44** | **73%** |

详见 `.planning/REQUIREMENTS.md`。

---

## 四、技术栈（锁定，不可换）

### Backend
- **Python 3.11+** / FastAPI 0.136+
- **LangGraph 1.2+** / langgraph-checkpoint-postgres 3.1+（**psycopg3** 驱动）
- SQLAlchemy 2.0.49（asyncpg 驱动）/ Alembic
- arq 0.28+（异步任务队列）/ Redis 7+
- PostgreSQL 15+
- **PyJWT 2.12.1**（不是 python-jose）

### Frontend
- **Next.js 16.2+**（不是 14）
- @xyflow/react 12+（DAG 画布）
- Zustand 5+（state management）

### IM SDK
- `lark-oapi==1.6.5`（1.6.0-1.6.3 已 yanked，强制 pin）
- `wechatpy==1.8.18`（停更，企微 templated card API 通过 Bot Webhook fallback）
- `dingtalk-stream==0.24.3`
- `slack-bolt==1.28.0` / Mattermost direct REST

### Testing
- pytest + pytest-asyncio + httpx.AsyncClient（**集成测真跑 DB，禁 mock**）
- vitest + @testing-library/react
- **E2E 用 [browser-harness](https://github.com/browser-use/browser-harness)**（CDP 直连用户 Chrome，禁 sync_playwright）

### Skeleton
**Fork [Onelevenvy/flock](https://github.com/Onelevenvy/flock)**（Apache-2.0, 1k★）— 拖拽 Canvas + LangGraph node/edge + Subgraph + MCP + 基础 HITL + FastAPI + Next.js + Postgres + Docker Compose。

---

## 五、关键设计决策

> 决策板：从研究综合 + 实施迭代沉淀，详见 `docs/plans/2026-05-16-agent-builder-design.md`

| # | 决策 | 理由 | 状态 |
|---|------|------|------|
| 1 | 执行引擎用 LangGraph + PostgresSaver | 原生 HITL interrupt + 持久化能力强 | ✅ Phase 2 |
| 2 | 画布转 DSL/JSON **解释执行**（非代码生成） | 热更新友好 / 状态机一张表 / 与 Dify/n8n 同路 | ✅ Phase 2 |
| 3 | HITL **四态**（执行人 submit/return/reject → 审核人 approve/return/reject） | 区分执行与审核职责 | ✅ Phase 3 |
| 4 | HITL **单 interrupt + 自管审批链状态**（payload 内 records / current_idx） | 避免 LangGraph thread checkpoint 膨胀 | ✅ Phase 3/4 |
| 5 | 审批链 **4 种模式**：单人 / 顺序会签 / 并行会签 / 或签 | 业务场景全覆盖 | ✅ Phase 4 |
| 6 | **Token 即登录**（不做独立 OAuth） | 外部审批人零摩擦；安全靠 jti 一次性 + 短期 cookie | ✅ Phase 3 |
| 7 | **Token GET 不消费 jti、POST 才消费** | **P0 防御** Outlook Safe Links / Microsoft Defender 邮件扫描器预 GET（hr 实战教训） | ✅ Phase 3 |
| 8 | LangGraph state schema **强制区分值字段 vs 引用字段**（重型数据走 Redis pointer） | 防 checkpoint 写入放大（15 步 × 100KB = 1.5MB/次），WAL 复制延迟可降 99% | ✅ Phase 2 |
| 9 | 多租户所有查询显式带 `workspace_id` WHERE + SQLAlchemy checkout `DISCARD ALL` hook | 防 PgBouncer 连接池上下文污染 | ✅ Phase 1 |
| 10 | Fork flock 后所有改动**集中新增模块**，不改 flock 上游文件 | 防上游 diverge 超 30% 后无法 merge | ✅ Ongoing |
| 11 | 公网部署 + nginx **仅放行** `/hitl/page/*` `/hitl/action/*` `/api/im/webhook/*` 三条路径 | 最小公网暴露面 | ✅ Phase 1 |
| 12 | IM 集成 **L3 双向同步**（拉用户/部门 + 卡片决策入口） | 节点 assignee 支持 `dept:研发部` 表达式 | 🚧 Phase 5.D |
| 13 | 节点扩展**三层**：内置 + 一等公民 + 插件 | 通用平台必备扩展性 | 🚧 Phase 5/6 |
| 14 | **PlatformPlugin** 框架（Dify-style，6 Capability Protocol：IM/Doc/HR/Identity/Trigger/Tool） | 一份 YAML manifest 多 capability 接入，等同 Dify 第三方平台接入能力 | ✅ Phase 5.A |
| 15 | Plugin 沙箱 **PosixResource baseline + CgroupsV2 opt-in + AllowlistTransport** | resource.setrlimit 防 fork bomb，cgroups 真 enforce CPU/mem，httpx Transport API 应用层网络白名单 | ✅ Phase 5.B |

---

## 六、Phase 5.C 范围（进行中）

> **DocCapability 真接入**：把 Phase 5.A 仅 Mock + 设计的 DocCapability Protocol，真接到 **3 个平台**。
> 工程基准：**hr/offboarding-flow B-full-channel 1454 行 Python 可 port**（不重起摸索）。

### 8 plans / 5 waves（并行后约 ~2.5h 关键路径）

| Wave | Plan | 主题 | 依赖 |
|------|------|------|------|
| 1 | `05c-01` | SandboxRunner `docker_networks` 扩展 + manifest schema | — |
| 2 ⇉ | `05c-02` | Huly `_internal` port（hr 5 文件 836 行 + AllowlistTransport + license attribution） | 01 |
| 2 ⇉ | `05c-03` | OutlinePlugin daemon（DocCapability only + 429 retry + mock outline server） | 01 |
| 2 ⇉ | `05c-04` | LarkDocsPlugin daemon（Doc + Identity 双 facet + marko 12 元素 → Lark Block） | 01 |
| 3 | `05c-05` | **HulyPlugin 4-cap bundle**（Doc + IM + Identity + Tracker stub + 二步流程 + per-user Channel + LRU） | 02 |
| 4 ⇉ | `05c-06` | `ai_suggest_mentions` LLM 钩子（DocCapability Protocol v1.1 + llm_mention_helper） | 03/04/05 |
| 4 ⇉ | `05c-07` | Capability fallback service layer（delta→markdown 自动 serialize + plugin discovery wiring） | 03/04/05 |
| 5 | `05c-08` | **E2E gate**（browser-harness 3 spec + license audit + 5.A/B regression + VERIFICATION） | 06/07 |

### 关键设计

- **3 个 plugin 实现策略**：
  - **OutlinePlugin**（P0 最简）：DocCapability only，markdown 全量 replace
  - **LarkDocsPlugin**（P0 国内首选）：Doc + Identity 双 facet，marko AST → Lark Block 严格映射
  - **HulyPlugin**（P0 一体化 acid test 升级）：**4-cap bundle**（Doc/IM/Identity/Tracker）共享单 daemon + 单 WS 连接
- **Huly 二步流程**：create shell（TxCreateDoc）→ collab service RPC（createContent via WS）→ update content ref（TxUpdateDoc）
- **per-user Channel 模式**（hr §5.2 教训）：`chunter:DirectMessage` 静默 reject → fallback per-user `chunter:Channel` 命名 `dm-{username}`
- **PersonUuid LRU cache**（hr §5.5）：daemon 内置 `_resolve_account_cache: LRU(maxsize=10000, TTL=1h)`
- **docker network attach**（hr §4.4 教训）：CgroupsV2Sandbox 真 `docker network connect`，PosixResourceSandbox no-op
- **AGPL-3.0 防御**：每文件首行 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source`，重写实现不复制源码

详见 `.planning/phases/05c-doc-capability/`。

---

## 七、强制规则（违反即返工）

> 详见 `CLAUDE.md`

1. **并行优先**（§2.1）：能并行就并行，独立 plans/tasks/Bash 调用必须并行 dispatch
2. **三层测试**（§2.2）：每 feature 必有 unit + integration + E2E；**集成测禁 mock DB，E2E 必用 browser-harness**
3. **Fork 纪律**（§2.3）：永不改 flock 上游文件，所有改动作为新增 module/file
4. **多租户隔离基线**（§2.4）：所有业务表加 `workspace_id` + 复合索引，所有 query 经 `WorkspaceScopedQuery` 自动注入
5. **Token 安全**（§2.5）：`GET /hitl/page/<token>` 不消费 jti（防 Safe Links 扫描器）
6. **State Pointer Pattern**（§2.6）：重型数据走 Redis pointer，state 体积 ≤ 4KB
7. **Reference-First**（§2.7）：实现前必须读对应 Dify / 参考项目模块 + 写 reading doc 作为 plan 的第一个 commit（Task 0 硬性 gate）

---

## 八、部署架构 + 边界

> **核心定位（2026-05-18 确认）：agent-builder 是 *HTTP 客户端 / 适配器 / MCP 封装层*，不是容器编排器。**

### 职责边界

- ✅ **做**：通过 REST API 调外部 SaaS（Outline / Lark Docs / Huly / 飞书 / 企微 / 钉钉 / Slack / Mattermost 等），把它们的能力**封装成 Capability Protocol**（DocCapability / IMCapability / IdentityCapability / HRCapability 等）以及 MCP server
- ❌ **不做**：不负责被调服务怎么部署（docker / k8s / 裸金属 / SaaS 托管 — 都不关心）；不在 app 容器内启子 docker 容器；不做容器网络运行时编排

### 部署约束

- **部署目标**：docker 容器化（docker-compose 一键起 api / worker / web / postgres / redis / nginx）
- **严禁 DinD**（no Docker-in-Docker）：容器内不挂 `docker.sock`，不跑 `docker run`，不调 `docker network connect`
- **Plugin daemon = Python subprocess**（PosixResourceSandbox + resource.setrlimit + AllowlistTransport），不是子容器
- **跨网络访问**走标准网络配置（compose `networks` external 声明 / DNS / hostname:port），不在 runtime attach 网络

### 一键启动

```bash
# 克隆
git clone git@github.com:LaiosOvO/liuxin-agent-builder.git
cd liuxin-agent-builder

# 配置（按需修改 SMTP / HMAC_SECRET / DATABASE_URL）
cp .env.example .env

# 一键启动（api / worker / web / postgres / redis / nginx）
docker-compose up -d

# 浏览器访问
open http://localhost:3000
```

### 跨网络 plugin 接入

被调服务（如 Huly `collaborator:3078`）的可达性由**部署者**配置，agent-builder 仅做 HTTP 调用。常见模式：

| 部署场景 | 配置方式 |
|---------|---------|
| 同 host docker-compose | `docker-compose.yml` 声明 `networks: { huly_net: { external: true } }`，app 容器启动时 join |
| 跨 host | 反代 / VPN / DNS 解析到目标 URL，env 注入 `HULY_URL=https://huly.internal:8087` |
| SaaS 托管 | 直接公网 URL，env 注入 |
| 同 host 进程 | 直接 `localhost:8087` |

无论哪种，**plugin daemon 内部代码不变**——`httpx.AsyncClient(transport=AllowlistTransport([target_host]))` 即可。

### MCP 封装（v1.1+）

每个 PlatformPlugin 的 Capability 可暴露为 MCP server（标准 stdio 或 SSE），允许第三方 AI agent（Claude Desktop / Cursor / OpenAI Assistant 等）直接调用 agent-builder 已封装的平台能力（如"用 LarkDocsPlugin 写文档"）。

### 开发流程

```bash
# 后端
cd backend
uv sync
uv run pytest tests/platforms/ tests/platforms_integration/ -v

# 前端
cd web
pnpm install
pnpm dev

# E2E（需先用 --remote-debugging-port=9222 启动 Chrome）
cd e2e
uv run pytest -v -k "smoke"
```

---

## 九、文档导航

- `.planning/PROJECT.md` — 项目上下文与决策板
- `.planning/REQUIREMENTS.md` — 60 条 v1 需求 + traceability
- `.planning/ROADMAP.md` — 7 phases + Phase 4.5/5.A/5.B/5.C/5.D
- `.planning/phases/{phase}/` — 每 phase 的 CONTEXT / RESEARCH / PLAN / SUMMARY / VERIFICATION
- `docs/plans/` — ADR 与设计稿
- `docs/reading-dify-*.md` — Dify / 参考项目阅读笔记（Reference-First Task 0 产物）
- `CLAUDE.md` — AI 协作约定（强制规则、Reference-First、E2E 工具链）

---

## 十、许可证

[Apache License 2.0](LICENSE) — 与 Onelevenvy/flock 一致。

参考项目许可证边界（**严禁拷贝源码**，仅借鉴设计模式 / 数据结构 / 边界考虑）：

- Dify — AGPL-3.0
- hr/offboarding-flow — Apache-2.0（但无 source header，按 AGPL 风险处理）

---

## 十一、贡献

项目当前由作者 [@LaiosOvO](https://github.com/LaiosOvO) 个人维护，AI 协作开发使用 Claude Code。

PR 流程：
1. fork → feature 分支 `feature/phase-N-<slug>`
2. 遵守 `CLAUDE.md` 强制规则（特别是 Reference-First 与 三层测试）
3. CI 通过 → merge → 删分支
4. 永不 `--no-verify` / 永不 force-push 到 main

---

*Last updated: 2026-05-18 — Phase 5.C plan-phase 完成 + Wave 1 启动*
