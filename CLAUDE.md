# agent-builder — Claude 工作指南

本文件是 agent-builder 项目级 Claude 指令，**优先级高于** `~/.claude/rules/` 全局规则；与之冲突时以本文件为准。

---

## 1. 项目一句话

通用拖拽式 LangGraph 编排平台（"LangGraph as Service"）。可视化建工作流 → 部署 → HITL 节点通过邮件 / 主流 IM 完成四态决策 → 公网回调推进状态机。

详见：
- `.planning/PROJECT.md` — 项目上下文
- `.planning/REQUIREMENTS.md` — 60 条 v1 requirements，10 个类目
- `.planning/ROADMAP.md` — 7 个 phase
- `docs/plans/2026-05-16-agent-builder-design.md` — 完整设计文档（决策板 15 条）

---

## 2. 强制规则（违反即返工）

### 2.1 并行开发优先（Parallelize aggressively）

**能并行就并行**。Phase 内的 plans、plan 内的 tasks、独立 agent 的工作，必须用并行模式处理：

- **GSD 执行**：`config.json` 已设 `parallelization: false` 用于规划安全，但**实际开发中**优先 dispatch 并行 agent
- **同一 Phase 内独立 plans**：用 `superpowers:dispatching-parallel-agents` 一次性 dispatch 多个 Task
- **同一 plan 内独立 tasks**：用 `superpowers:subagent-driven-development` 走并行
- **判断标准**：tasks 之间没有**写入冲突**（同一文件/同一表的并发写）且不共享中间状态时，必须并行
- **反模式**：串行做 3 个独立 Bash 调用、串行 spawn 3 个 agent、串行编辑 3 个独立文件

### 2.2 全流程测试（Whole-flow tests）

每个 phase 的 plan 必须包含 **3 层测试**：

1. **单元测试**（Unit）：函数/组件级别，覆盖率 ≥ 80%
2. **集成测试**（Integration）：API + DB + Redis 真实跑，**不 mock 数据库**
3. **端到端测试**（E2E，**用 browser-harness via `webapp-testing` skill / Playwright**）：从浏览器视角走通完整用户流程

E2E 是**第一公民**，不是"可选的最后一步"。验收准则：**所有 phase 必须有 E2E 测试覆盖 ROADMAP.md 中该 phase 的所有 success criteria**。

#### E2E 关键场景清单（每个 phase 必有）

| Phase | E2E 必测场景 |
|-------|------------|
| 1 | setup 首启流程 / 注册 + 邮箱验证 / 登录 / 邀请用户 / RBAC 边界（双 workspace 互访 403）/ nginx 仅放行路径扫描 |
| 2 | 拖一个 4 节点 DAG → 发布 → 运行 → 看时间线 / DSL 成环阻挡 / 服务重启实例恢复 |
| 3 | HITL 节点邮件深链点击 → 决策提交 → 流程推进 / Safe Links 扫描器模拟 GET 不消费 jti / 重复提交 409 |
| 4 | 多人审批链 4 模式 / 飞书卡片点击跳转决策页 / 任一拒绝触发其它 token 失效 |
| 5 | IM 同步触发后 assignee `dept:研发部` 解析正确 / 步进调试 |
| 6 | 上传插件 zip → dry-run → 注册 → 拖到画布 → 沙箱执行 |
| 7 | hr 离职预置模板端到端跑通 + Timeline + 审计日志 |

#### 工具栈

- 后端测试：`pytest` + `pytest-asyncio` + `httpx.AsyncClient`（真实 DB 用 `testcontainers-postgres` / `pytest-postgresql`，不 mock）
- 前端测试：`vitest` + `@testing-library/react`
- **E2E 测试**：**`browser-use/browser-harness`**（https://github.com/browser-use/browser-harness — 12.9k stars, MIT, Python, LLM-driven self-healing harness）— 测试用例放 `e2e/` 目录；clone 到 `/Users/admin/ai/ref/agent/browser-harness/`，第一次用前必读其 README + 写 reading doc（CLAUDE.md §2.7 模式）
- **历史 Playwright spec**（Phase 1/2/3 `e2e/*.spec.ts`）暂保留不删；Phase 4+ 新 E2E 用 browser-harness（用户 2026-05-17 指令）
- **Safe Links 模拟**：E2E 必包含 `MICROSOFT_DEFENDER_BOT` UA / `OUTLOOK_SAFE_LINKS_BOT` UA 触发 token 链接 GET 的用例

### 2.3 不改 flock 上游文件（Fork discipline）

- **永不** edit flock 现有目录树下的文件；所有改动作为**新增** module/file
- **永不** merge upstream（fork 是 snapshot）
- CI 检查：PR diff 中 flock 原文件改动行数 / 总改动行数 > 10% 时阻断（防 diverge）

### 2.4 多租户隔离基线

- 所有业务表加 `workspace_id` 列 + 复合索引第一列 `(workspace_id, id)` / `(workspace_id, created_at)`
- 所有 `select()` 经 `WorkspaceScopedQuery` 抽象层，自动注入 `WHERE workspace_id = :current_workspace`
- SQLAlchemy `@event.listens_for(engine, "checkout")` hook `DISCARD ALL`（防 PgBouncer session 残留 — Pitfall 6）
- E2E 测试：双 workspace 账号互访任意 endpoint 必须 403 或空集

### 2.5 Token 安全：GET 不消费 jti

- `GET /hitl/page/<token>` 仅校验签名 + 签发 30min session cookie，**不动 `used_at`**
- `POST /hitl/action/<token>` 才消费 jti（Redis `SET NX` + Postgres advisory lock）
- E2E 必包含 Outlook Safe Links / Microsoft Defender 模拟 UA 触发 GET 的回归用例（Pitfall 3，P0）
- "GET 即消费 jti" 是**永不可接受**的实现

### 2.6 State Pointer Pattern（防 checkpoint 膨胀）

- LangGraph state schema 强制区分**值字段** vs **引用字段**
- 重型数据（DSL 原文 / LLM 原始输出 / IM 卡片 raw body / 上传文件）走 Redis pointer：`__ptr__:redis:state:<uuid>`
- state 只存指针，体积按字段大小限制 ≤ 4KB（pre-commit lint 校验）
- Pitfall 1 防护（100 并发 WAL 减少 99.8%）

---

### 2.7 Dify 参考实现优先（Reference-First）

**强制规则**：实现任何节点 / 编排引擎 / 画布 UI / 工作流 API 之前，**必须先读对应 Dify 模块代码**，把发现的设计模式 / 数据结构 / 边界情况记入 plan 的 `<reference>` 段。

**Why**：Dify 是国内最成熟的开源工作流平台，2 年 + 数百贡献者的生产打磨。从零设计同类系统等于走它走过的坑。我们 fork 的 flock 已带 Dify 路径但许多接口非完整复刻；本项目可视化编排定位与 Dify 高度重叠，**参考其工程实现是减少 bug 与设计弯路的最快方式**。

**适用范围**：**前端 + 后端都强制**。

**Dify 仓库路径**：`/Users/admin/ai/ref/dify/repo/` (Phase 1 已 clone, 含 commit `e7e6fe88` (auto-pulled 2026-05-16))

**模块映射表（实现这些功能前必读对应 Dify 路径）**：

| 我们要实现的 | Dify 后端必读 | Dify 前端必读 |
| ---- | ---- | ---- |
| **DSL Schema / Workflow 模型** | `api/core/workflow/workflow_entry.py`, `api/models/workflow.py`, `api/core/workflow/entities/` | `web/app/components/workflow/types.ts` (BlockEnum 等) |
| **DSL 编译 / 节点工厂** | `api/core/workflow/node_factory.py`, `api/core/workflow/graph_engine/` | — |
| **节点执行运行时** | `api/core/workflow/node_runtime.py`, `api/core/workflow/nodes/` 各节点子目录 | — |
| **Start 节点** | `api/core/workflow/nodes/start/` | `web/app/components/workflow/nodes/start/` |
| **End 节点** | `api/core/workflow/nodes/end/` | `web/app/components/workflow/nodes/end/` |
| **LLM 节点** | `api/core/workflow/nodes/llm/` | `web/app/components/workflow/nodes/llm/` |
| **Tool 节点 / HTTP** | `api/core/workflow/nodes/tool/`, `api/core/workflow/nodes/http_request/` | `web/app/components/workflow/nodes/tool/`, `web/app/components/workflow/nodes/http/` |
| **IfElse / 条件分支** | `api/core/workflow/nodes/if_else/` | `web/app/components/workflow/nodes/if-else/` |
| **HITL / Human Input** | `api/core/workflow/human_input_adapter.py`, `api/models/human_input.py`, `api/core/workflow/nodes/human_input/` | `web/app/components/workflow/nodes/human-input/` |
| **Notification / Email 模板** | `api/core/workflow/email_delivery/` (含 `mail_human_input_delivery_task.py`) | — |
| **变量引用 / Jinja 渲染** | `api/core/workflow/utils/variable_template_parser.py` | `web/app/components/workflow/variable-template-input/` |
| **画布 Canvas 主组件** | — | `web/app/components/workflow/index.tsx` (28KB), `custom-edge.tsx` |
| **节点面板 / Palette** | — | `web/app/components/workflow/nodes/components.ts`（NodeComponentMap） |
| **节点配置 Panel** | — | `web/app/components/workflow/panel/` 下各节点子目录 |
| **DSL 校验 / Issue UI** | `api/services/workflow_service.py` 中 validate 部分 | `web/app/components/workflow/hooks/` 验证 hooks |
| **Workflow 列表 / 实例列表** | `api/controllers/console/app/workflow.py`, `api/controllers/console/app/workflow_run.py` | `web/app/components/workflow-app/`, `web/app/components/app/workflow-log/` |
| **WebSocket / 实时同步** | `api/core/app/apps/workflow/workflow_app_runner.py` (stream 逻辑) | `web/app/components/workflow/run/` |
| **Plugin Daemon / 节点扩展** | `api/services/plugin/`, dify-plugin-daemon 仓库 | `web/app/components/plugins/` |

**执行流程（每个 plan 内必须做，违反即返工）**：

1. **声明阶段**：在 plan 工作开始时，用一句话写下「我实现的是什么模块」+「Dify 有没有类似功能」
2. **Read 阶段**：用 `Read` 工具至少打开映射表中**对应行的 1 个前端 + 1 个后端**文件
3. **🚦 阅读文档阶段（硬性 GATE）**：将阅读结果写入 `docs/reading-dify-{plan-slug}-{date}.md`，**并先 commit 此文档**才能继续写代码。文档格式遵循 `~/.claude/rules/common/reference-projects.md` 模板：
   ```
   # Dify 阅读笔记 — {模块名}
   > 日期: YYYY-MM-DD
   > 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
   > Stars: ~141k
   ## 项目概述（一句话）
   ## 技术栈（关键技术选择）
   ## 架构要点（核心架构模式，用简图说明）
   ## 可借鉴的设计模式（具体文件路径 + 模式名 + 一句话说明）
   ## 与本项目的关系（如何应用到当前 plan）
   ```
4. **Implement 阶段**：阅读文档已 commit ✓ → 才允许写代码
5. **Verify 阶段**：测试 + SUMMARY.md 中含 "Dify 参考点" 小节（指回 reading doc）

**Reading doc 是 plan 的第一个 commit（Task 0），后续任何代码 commit 必须在它之后**。CI/code review 可机械化检查：plan 内第一个 feat/refactor commit 之前必须有对应的 reading doc commit。

**反模式（违反规则）**：
- 完全闭门造车，未读任何 Dify 模块
- 读了但没在 plan / SUMMARY 中记录借鉴点
- 抄袭 Dify 代码不留 attribution（**不要直接复制 Dify 源码** — 它是 AGPL；只借鉴**设计模式 / 数据结构 / 边界考虑**，自己写实现）

**许可证注意**：Dify 是 **AGPL-3.0**，我们的 agent-builder 是 **Apache-2.0**（与 flock 一致）。**严禁拷贝 Dify 源码**到我们仓库；仅允许参考设计模式 / 命名规范 / 数据结构思路。如果某段实现你觉得"几乎一样"，**重写一遍换语法**确保是独立创作。

---

## 3. 技术栈锁定（不可换）

详见 `.planning/research/STACK.md`。摘要：

- Python 3.11+ / FastAPI 0.136+ / **PyJWT 2.12.1（不是 python-jose）**
- LangGraph 1.2+ / **langgraph-checkpoint-postgres 3.1+ → psycopg3**（不是 psycopg2）
- SQLAlchemy 2.0.49 → asyncpg（与 checkpoint 的 psycopg3 共存不冲突）
- arq 0.28+ 做异步任务队列（不是 Celery）
- **Next.js 16.2+（不是 14）** / @xyflow/react 12+ / Zustand 5+
- IM SDK：lark-oapi==1.6.5（1.6.0-1.6.3 已 yanked，强制 pin）/ wechatpy==1.8.18（停更，企微 templated card API 需 spike）/ dingtalk-stream==0.24.3 / slack-bolt==1.28.0

---

## 4. 开发流程约定

### 4.1 GSD 工作流

项目走 `/gsd:*` 工作流：
- `/gsd:discuss-phase N` — 沉淀 phase 决策
- `/gsd:plan-phase N` — 拆 plans
- `/gsd:execute-phase N` — 执行（auto_advance 已开）
- `/gsd:verify-work` — 验证 phase 完成

### 4.2 Commit 风格

- 中文 message（`feat:` / `fix:` / `docs:` 等 conventional commit 前缀保留英文）
- 单功能单 commit，避免大杂烩

### 4.3 文档语言

- 文档 / 注释 / commit message：**中文**
- 变量名 / 函数名 / 文件名：**英文**
- UI 默认中文（i18n v1 不做）

---

## 5. Git Workflow

- Remote：`git@github.com:LaiosOvO/liuxin-agent-builder.git`
- 主分支：`main`
- Feature 分支：`feature/phase-N-<slug>`
- 每个 plan 完成 → 创建 PR → CI 通过 → merge → 删分支
- **永不** `--no-verify`、`--force` 到 `main`
- **永不** 提交 `.env`、`*.key`、`*.pem` 等敏感文件

---

## 6. 安全 / 密钥

- `.env` 已在 `.gitignore`，**永不**入仓
- `.env.example` 可以入仓但只放占位符（如 `SMTP_PASSWORD=<your-smtp-password>`）
- `HMAC_SECRET` 启动时校验长度 ≥ 32 字节，否则服务拒绝启动
- 敏感字段在日志中必须脱敏（`password` / `token` / `secret` / `key` 字样匹配自动 mask）

---

## 7. 当前阶段

**Phase 1: Skeleton + 账号体系** —— 详见 `.planning/phases/01-skeleton/01-CONTEXT.md`

下一步：`/gsd:plan-phase 1`
