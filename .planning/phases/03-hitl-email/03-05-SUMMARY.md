---
phase: 03-hitl-email
plan: "05"
subsystem: workflow
tags: [notification-node, langgraph, jinja2, email, decoupled, immutable-state]

# Dependency graph
requires:
  - phase: 03-hitl-email
    provides: 03-01 notifications ORM + UNIQUE 约束 / 03-04 NotificationService + send_hitl_email_job arq 入队基础设施
  - phase: 02-dsl
    provides: BaseNodeExecutor + DSLCompiler 上下文注入 (workspace_id / instance_id / redis / event_bus) / NODE_EXECUTORS 注册表模式 / NODE_SCHEMAS 校验框架
  - phase: 01-skeleton
    provides: Jinja2 autoescape + PUBLIC_BASE_URL env + async_session_maker
provides:
  - NotificationNodeExecutor (DSL 节点 type="notification")
  - NOTIFICATION_NODE_SCHEMA + NOTIFICATION_OUTPUT_FIELDS (JSON Schema 子集 + 输出字段集合)
  - NotificationService.enqueue_generic_email (通用邮件入队，与 enqueue_hitl_email 并列)
  - generic_notification.html (极简通用通知模板，autoescape=html)
  - email_jobs.send_hitl_email_job 扩展：payload.generic=True 时走通用模板路径
affects: [03-06 HITL public API（不直接依赖；可同节点 DAG 编排）, 03-10 E2E gate（DAG 含 notification 节点可端到端验证）, Phase 7 hr 离职流模板（"完成通知"节点是 Phase 7 模板的硬性前置）]

# Tech tracking
tech-stack:
  added: []  # 完全复用 Phase 1/2/3 已落基础设施，无新包
  patterns:
    - "节点 schema + 输出字段 frozenset 双 export 模式：DSLValidator 用 schema 校验 config，DSL UI / 引用追踪用 output_fields"
    - "复用 BaseNodeExecutor.execute 路径（非 override __call__）：Notification 节点不抛 GraphInterrupt，retry/timeout 装饰器透明 wrap"
    - "节点层 _is_valid_email 兜底过滤：在 service 入队前剔除明显错误的邮箱（避免 SMTP 浪费）"
    - "失败不阻断模式：单 recipient 抛错 → rollback + failed_count++ + 继续下一个 recipient（vs HITL 节点 fail-stop）"
    - "节点自管 DB session：async with async_session_maker() as db（与 send_hitl_email_job 同模式）— 避免事务耦合到 runner"
    - "node_state SELECT-or-INSERT：节点自管 row 创建（vs HITL 要求 ExecutionEngine 预创建 + 注入 state）"

key-files:
  created:
    - backend/app/agent_builder/workflow/nodes/notification.py
    - backend/app/agent_builder/workflow/node_schemas/notification_schema.py
    - backend/app/templates/email/generic_notification.html
    - backend/tests/test_notification_node_executor.py
    - docs/reading-dify-03-05-notification-node-2026-05-17.md
  modified:
    - backend/app/agent_builder/workflow/nodes/__init__.py  # NODE_EXECUTORS["notification"] = NotificationNodeExecutor
    - backend/app/agent_builder/workflow/node_schemas/__init__.py  # NODE_SCHEMAS["notification"] = (...)
    - backend/app/services/notification_service.py  # 新增 enqueue_generic_email 方法
    - backend/app/jobs/email_jobs.py  # _render_email_content 分流 + send_hitl_email_job 模板选择 + subject 组装分流

key-decisions:
  - "Dify 没有独立 Notification 节点（通知耦合在 HumanInputForm 投递链）→ 本项目按 CONTEXT §NODE-07 解耦：3 独立节点类 + 独立 schema + 独立 NODE_EXECUTORS key"
  - "复用 BaseNodeExecutor.execute 路径（vs HITL override __call__）：本节点不抛 GraphInterrupt，可享受 retry/timeout 装饰器，但 _retryable_exceptions 返回空 tuple（节点层不重试，service / job 已有 tenacity）"
  - "复用 03-04 send_hitl_email_job worker：通过 payload.generic 字段路由到 generic_notification.html，不创建新 arq job（避免 worker 注册爆炸）"
  - "channels=['email'] 唯一支持 + 其他 channel → skipped=True 不抛错：Phase 4 加 IM 通道时只需新增分支，不动节点契约"
  - "recipients oneOf list|str：DSL 编辑期允许两种格式，节点层规范化为 list；支持单 Jinja 表达式 '{{ user.email }}'"
  - "节点层 _is_valid_email 兜底过滤：service 不再二次校验（trust the boundary）；正则简易匹配（不追求 RFC 5322）"
  - "失败不阻断：单封失败仅 failed_count + rollback；graph 仍走完所有 recipient + 走 next 节点（CLAUDE.md §错误处理 vs HITL fail-stop）"
  - "自管 node_state 行：SELECT or INSERT 满足 FK 约束；vs HITL 节点要求 ExecutionEngine 预创建 + 注入 _node_state_id 到 state"
  - "subject 防 CR/LF 注入：节点 execute 阶段 Jinja 渲染后，worker 路径再用 replace('\\r', ' ').replace('\\n', ' ')[:200] 二次净化"
  - "通用模板 generic_notification.html 极简：仅 subject + body + recipient_email；不含 deeplinks/tokens/deadline（无回调）"
  - "payload 区分字段：notifications.payload.generic=True 标识为通用通知；vs HITL 邮件 payload 含 tokens/form_schema/deadline_at 等 8 字段"

patterns-established:
  - "节点类型解耦：HITL 节点 (NODE-02) + Notification 节点 (NODE-07) 共享底层（NotificationService / send_hitl_email_job / Jinja templates dir），独立顶层（节点类 / schema / 失败语义 / payload 结构）"
  - "BaseNodeExecutor.execute 三步式：1) _render_config 渲染 Jinja → 2) execute(config, state) 业务逻辑 → 3) 返回 dict[node_id]"
  - "并发副作用归外：节点 execute 自建 session（async_session_maker），不复用 runner 的 session — 与 send_hitl_email_job 同模式"

requirements-completed:
  - NODE-07  # Notification 节点（独立通知节点）
  - NOTI-01  # Email 通道（Phase 3 完整闭环 — HITL 邮件 + Notification 节点两条路径）

# Metrics
duration: ~10min
completed: 2026-05-17
test-count: 13  # 2 注册校验 + 4 主路径 Jinja + 3 边界 + 4 契约（节点自管 node_state 是 bonus）
file-count: 9  # 5 created + 4 modified
---

# Phase 3 Plan 05: Notification 节点（NODE-07）— 独立通知节点 Summary

**独立 Notification 节点（NODE-07）实现：与 HITL 节点（NODE-02）完全解耦的纯通知节点 — 不暂停 graph，不创建 hitl_token，不参与催办循环。复用 03-04 NotificationService（新增 enqueue_generic_email）+ send_hitl_email_job worker（通过 payload.generic 路由模板）。13 集成测试通过；Dify 没有独立 Notification 节点（耦合在 HumanInputForm 投递链）— 本项目按 CONTEXT §NODE-07 解耦决策已记入 reading doc §7 9 维度对照表。**

## Performance

- **Duration:** ~10 分钟（含 Task 0 reading doc + Task 1 实现 + Task 2 测试）
- **Started:** 2026-05-17T18:36:28Z
- **Completed:** 2026-05-17T18:46:25Z
- **Tasks:** 3 实际执行（Task 0 + Task 1 + Task 2）
- **Files created:** 5
- **Files modified:** 4
- **Test cases:** 13 通过（2 注册校验 + 4 主路径 + 3 边界 + 4 契约）

## Accomplishments

1. **NotificationNodeExecutor 实现**：
   - 走 `BaseNodeExecutor.execute(config, state)` 路径（不 override `__call__`，与 HITL 节点根本不同）
   - 失败不阻断：单 recipient 抛错 → `db.rollback() + failed_count += 1`；graph 仍走完所有 recipient
   - `channels=['email']` 唯一支持 + 其他通道 → `skipped=True` 不抛错（Phase 4 加 IM 时只需新增分支）
   - `recipients` 支持 `str` / `list[str]`（含 Jinja2 表达式，由 `BaseNodeExecutor._render_config` 自动渲染）
   - 节点层 `_is_valid_email` 兜底过滤无效邮箱（正则简易匹配，service 不再二次校验）
   - `_resolve_node_state_id` 自动 SELECT-or-INSERT `node_states` 行（满足 FK 约束）— 与 HITL 节点要求 ExecutionEngine 预创建不同

2. **NotificationService.enqueue_generic_email**：
   - 与 `enqueue_hitl_email` 并列的通用入队方法
   - 极简 payload：`{generic: True, subject, body, recipient_email}`（vs HITL 邮件 8 字段）
   - `reminder_round=0` 恒定（不参与催办循环）
   - 复用同一份 arq enqueue_job / asyncio.create_task fallback

3. **`send_hitl_email_job` worker 扩展**：
   - `_render_email_content` 增加 `if payload.generic is True` 分支 → 渲染 `generic_notification.html`
   - 模板选择路由：`generic → generic_notification.html` / `reminder_round>0 → hitl_reminder.html` / `else → hitl_decision.html`
   - subject 组装分流：generic 路径用 payload.subject（已 Jinja 渲染，再做 CR/LF 净化）；HITL 路径维持原 f-string 拼装

4. **NOTIFICATION_NODE_SCHEMA**（DSL 编辑期校验）：
   - 必填 `recipients` + `subject` + `body`
   - 可选 `channels`（默认 `["email"]`）
   - `recipients` 用 `oneOf [array, string]` 允许两种格式（DSL UI 友好）
   - `subject` maxLength=200 防超长

5. **generic_notification.html**（极简通用模板）：
   - 品牌头（蓝色 `#0ea5e9` 区分于 HITL 决策的 `#2563eb`）
   - 主题 + 正文（autoescape=html 防 XSS）
   - 不含 deeplinks / tokens / deadline（无回调）
   - 页脚显示收件人 + 不可退订声明

6. **13 集成测试覆盖**（CLAUDE.md 2.2 — 真实 PG / 不 mock DB）：
   - 2 注册校验：NODE_EXECUTORS + NODE_SCHEMAS
   - 4 主路径：单 recipient / 3 recipients / Jinja subject 渲染 / Jinja body 渲染 / Jinja recipient 表达式
   - 3 边界：无效 email 过滤 / 不支持 channel skipped / 部分失败仍继续
   - 4 契约：state 写入格式 / 不创建 hitl_token / 自动创建 node_state 行

## Task Commits

| Task | Name | Hash | Type |
|---|---|---|---|
| 0 | Dify Notification 节点阅读笔记（CLAUDE.md 2.7 GATE）| `6c40978` | docs |
| 1 | NotificationNodeExecutor + schema + template + service 扩展 + 注册 | `5a08eab` | feat |
| 2 | 13 集成测试通过（真实 PG）| `6796411` | test |

**Plan metadata commit** 由 final_commit 步骤创建（含 SUMMARY.md + STATE.md + ROADMAP.md 更新）。

## Files Created/Modified

### 新建

- `backend/app/agent_builder/workflow/nodes/notification.py` — NotificationNodeExecutor 类
- `backend/app/agent_builder/workflow/node_schemas/notification_schema.py` — NOTIFICATION_NODE_SCHEMA + NOTIFICATION_OUTPUT_FIELDS
- `backend/app/templates/email/generic_notification.html` — 极简通用通知模板
- `backend/tests/test_notification_node_executor.py` — 13 集成测试
- `docs/reading-dify-03-05-notification-node-2026-05-17.md` — Dify reading doc（CLAUDE.md 2.7 Task 0 GATE）

### 修改

- `backend/app/agent_builder/workflow/nodes/__init__.py` — NODE_EXECUTORS["notification"] 注册
- `backend/app/agent_builder/workflow/node_schemas/__init__.py` — NODE_SCHEMAS["notification"] 注册
- `backend/app/services/notification_service.py` — 新增 `enqueue_generic_email` 方法
- `backend/app/jobs/email_jobs.py` — `_render_email_content` 分流 generic 路径 + worker 模板/subject 选择

## Decisions Made

1. **不 override `__call__`**：HITL 节点 override 是因为 `interrupt()` 会抛 `GraphInterrupt`（控制流），tenacity 装饰器会吞掉；Notification 节点不抛 GraphInterrupt，因此走 BaseNodeExecutor 标准 execute 路径，享受 retry/timeout 装饰器（但 `_retryable_exceptions` 返回空 tuple — service / job 已有 tenacity 重试，节点层不重复）
2. **复用 send_hitl_email_job worker（vs 新建独立 job）**：通过 `payload.generic=True` 字段路由模板。不另起 arq function 名 — 避免 WorkerSettings.functions 注册爆炸 + 监控分类成本
3. **失败不阻断（vs HITL fail-stop）**：CLAUDE.md §错误处理强调"用户友好"；通知是 best-effort 副作用，不是 graph 流转的关键路径
4. **`_resolve_node_state_id` 自管**：与 HITL 节点不同 — HITL 要求 ExecutionEngine 在 enter 时预创建 node_states 行 + 注入 `_node_state_id` 到 state。Notification 节点更宽松（无回调依赖），自己 SELECT-or-INSERT
5. **`recipients` oneOf list|string**：DSL UI 视角，单 recipient 时用户写 `"recipients": "alice@x.com"` 比 `"recipients": ["alice@x.com"]` 自然；节点层规范化为 list 处理
6. **节点层 `_is_valid_email` 兜底**：CLAUDE.md §输入校验"never trust external data"；正则简易（不追求 RFC 5322），SMTP 服务器最终校验。无效邮箱仅过滤不抛错（与失败不阻断原则一致）
7. **`generic_notification.html` 不含 deeplinks**：Notification 节点不创建任何 token / callback URL — 通知是单向广播。模板字段差异（generic vs HITL 决策）由 worker 路径分流处理
8. **payload.generic=True 标记**：worker 通过此字段决定模板 + subject 组装路径 — 在 03-04 既有 schema 上做最小侵入扩展
9. **subject CR/LF 净化**：CLAUDE.md §安全 — 防 SMTP 头注入（如 `Subject: foo\r\nBcc: attacker@x.com`）；Jinja 渲染后 + 进 SMTP 前二次过滤
10. **节点自建 DB session（vs 复用 runner session）**：与 `send_hitl_email_job` 同模式；避免事务耦合到 runner（单 recipient 失败不应影响其它 recipient 的事务）

## Dify 参考点

详见 `docs/reading-dify-03-05-notification-node-2026-05-17.md`（commit `6c40978`）。本 plan 落实的核心借鉴 / 解耦：

| 维度 | Dify 原模式 | 本项目落点 | 文件 |
|---|---|---|---|
| **节点结构** | `BuiltinNodeTypes` 枚举 + `Node[NodeData]` 泛型基类 | `NODE_EXECUTORS["notification"]` + `BaseNodeExecutor` 继承 | `backend/app/agent_builder/workflow/nodes/notification.py` |
| **多通道扩展位** | `EmailDeliveryMethod / WebhookDeliveryMethod` 多 channel 抽象 | `channels: ["email"]` enum schema 字段（Phase 4 扩展 IM 时新增 enum 项 + 节点分支）| `notification_schema.py` |
| **入队 + 异步消费** | Celery `mail` queue + `_load_email_jobs` 自包含 dataclass | NotificationService.enqueue_generic_email + arq `send_hitl_email_job` 复用 03-04 框架 | `services/notification_service.py` + `jobs/email_jobs.py` |
| **Jinja 模板渲染** | `EmailDeliveryConfig.render_body_template` + `render_markdown_body` | `BaseNodeExecutor._render_config` 递归 Jinja + `generic_notification.html` autoescape=html | `nodes/base.py` + `templates/email/generic_notification.html` |
| **核心解耦点（vs Dify）** | Dify 把通知耦合在 HumanInputForm `_run` 副作用里（"想只发通知不暂停"没有原生支持）| 独立节点 NODE-07：不暂停 graph + 不创建 token + 不催办（reading doc §7 9 维度对照表）| `notification.py` 整体设计 |

**Attribution**：未拷贝 Dify 源码（Dify 是 AGPL-3.0，本项目是 Apache-2.0）。仅借鉴节点 schema 注册模式 + 多通道枚举设计 + Celery → arq 异步入队模式。NotificationNodeExecutor / NOTIFICATION_NODE_SCHEMA / generic_notification.html 全部独立创作（中文注释 + 异步风格 + 与 03-02 HITL 节点的解耦契约清晰列出）。

## Deviations from Plan

**轻微调整**（plan 内 `<notification_node>` code block 与最终实现差异）：

1. **[Rule 3 - Blocking] 节点不通过 state 注入 db / arq_pool**
   - PLAN.md `<notification_node>` 假设有 `self._workspace_id / _instance_id / _db / _arq_pool`（带下划线前缀）由 ExecutionEngine 注入
   - **实际**：BaseNodeExecutor `__init__` 已注入 `self.workspace_id / self.instance_id`（无下划线前缀）；`self._db` / `self._arq_pool` 不存在（节点函数不直接接收 DB session — 副作用归外原则）
   - **取舍**：节点 execute 内自建 `async with async_session_maker() as db`（与 send_hitl_email_job 同模式）+ arq_pool=None 走 asyncio.create_task fallback（与 NotificationService 一致）
   - 测试影响：13 测试通过；DB 操作完全自管，不依赖 runner 注入

2. **[Rule 2 - Critical] 节点自管 node_state_id（plan 未明示）**
   - PLAN.md 中 `node_state_id = UUID(state.get("__node_state_id"))` 假设由 ExecutionEngine 注入到 state
   - **实际问题**：runner.run_instance 是在节点 execute **之后** 才 upsert node_states 行（runner.py:213-222）；节点 execute 时该行尚未存在 — 注入空值 → notifications.node_state_id FK 约束违反
   - **解决**：实现 `_resolve_node_state_id(db)` 方法：先 SELECT or INSERT node_states 行（status='running'）；与 HITL 节点要求 ExecutionEngine 预创建不同 — Notification 节点宽松自管
   - **理由**：与 HITL 节点解耦设计一致 — Notification 不依赖 ExecutionEngine 的预 hook
   - 测试 `test_notification_node_creates_node_state_inline` 验证此契约

3. **[Rule 2 - Critical] 增加 payload.generic 字段路由模板**
   - PLAN.md 假设 generic 路径与 HITL 路径共用 send_hitl_email_job worker，但没有明示如何让 worker 区分两种模板
   - **实际**：在 NotificationService.enqueue_generic_email 写入 `payload.generic = True`；email_jobs.send_hitl_email_job 在 `_render_email_content` + 模板选择 + subject 组装三处增加 generic 分支
   - **理由**：最小侵入（不新建 arq function，复用 worker 框架）；payload 字段是 JSONB 不需要 schema migration
   - 测试 `test_notification_node_does_not_create_hitl_token` 验证 payload.generic 标识 + payload.tokens 不存在

## Issues Encountered

1. **CoveragePlugin 报告 41% 总覆盖率 < 60% 阈值**
   - 现象：`pytest --cov-fail-under=60` 失败（虽然 13 测试全部通过）
   - 分析：项目级阈值是检查"整个 backend 模块"，本 plan 只新增 3 文件 + 改 4 文件；未触及的旧文件覆盖率拉低总数
   - 影响：CI 路径下不影响功能验证；本 plan 内 `notification.py` 单文件覆盖率 87% 足够
   - 行动：**不修复**（CLAUDE.md SCOPE BOUNDARY — 不主动提升旧文件覆盖率）；记入 `.planning/phases/03-hitl-email/deferred-items.md` 留 03-10 E2E gate / Phase 7 完善

2. **流程 03-06 已存在前置 commit**（pre-existing parallel work）
   - 现象：git log 中 `d41aa52`/`eea0ce5`/`4afd86f` 在我 commit Task 1 之前已存在（03-06 HITL public API 部分实现）
   - 评估：与 03-05 平行进行，未冲突任何文件（03-06 改 `hitl_action_service.py` + `node_state.py` 加 payload 列；03-05 改 notification 节点 + schema）
   - 影响：无 — 03-05 是独立节点，与 03-06 API 通过 `notifications` 表松耦合

## User Setup Required

None — 本 plan 完全复用 Phase 1/2/3 既有基础设施：
- `BaseNodeExecutor` + `DSLCompiler` + `NODE_EXECUTORS` 注册表（Phase 2 已落）
- `NotificationService` + `send_hitl_email_job` + `templates/email/` 目录（Phase 3 Plan 04 已落）
- `_send_email` + `async_session_maker` + `PUBLIC_BASE_URL` env（Phase 1 已落）

## Next Plan Readiness

- ✅ **03-06 HITL public API**：与 Notification 节点解耦，无直接依赖；可独立推进
- ✅ **03-10 E2E gate**：DAG 中可编排 `notification` 节点测试"流程结束通知"端到端路径
- ✅ **Phase 7 hr 离职流模板**：本 plan 是 Phase 7 模板"完成通知"节点的硬性前置（hr 离职流必含此节点）
- ✅ **Phase 4 IM 通道扩展**：`channels` enum 已包含 feishu/wechat/dingtalk/slack 占位；Phase 4 实现时仅需在节点 execute 内增加分支调用对应 service（不动 schema / 不动 worker 框架）

## Self-Check

执行验证：
- [x] `backend/app/agent_builder/workflow/nodes/notification.py` 存在 + 已 commit (`5a08eab`)
- [x] `backend/app/agent_builder/workflow/node_schemas/notification_schema.py` 存在 + 已 commit (`5a08eab`)
- [x] `backend/app/templates/email/generic_notification.html` 存在 + 已 commit (`5a08eab`)
- [x] `backend/tests/test_notification_node_executor.py` 存在 + 已 commit (`6796411`)
- [x] `docs/reading-dify-03-05-notification-node-2026-05-17.md` 存在 + 已 commit (`6c40978`，Task 0 GATE)
- [x] `backend/app/agent_builder/workflow/nodes/__init__.py` 注册 NotificationNodeExecutor (`5a08eab`)
- [x] `backend/app/agent_builder/workflow/node_schemas/__init__.py` 注册 NOTIFICATION_NODE_SCHEMA (`5a08eab`)
- [x] `backend/app/services/notification_service.py` 含 enqueue_generic_email 方法 (`5a08eab`)
- [x] `backend/app/jobs/email_jobs.py` 含 generic 路径分流 (`5a08eab`)
- [x] 13 集成测试全部通过（CLAUDE.md 2.2 真实 PG）
- [x] 03-04 18 测试 + 03-02 24 测试无 regression
- [x] Task 0 reading doc commit 在所有 feat: commit 之前（6c40978 → 5a08eab → 6796411，CLAUDE.md 2.7 GATE 顺序正确）

## Self-Check: PASSED

所有声明的文件存在；所有声明的 commit 在 git log 中；13 测试全部通过；reading doc commit 在 feat commit 之前（CLAUDE.md 2.7 GATE 顺序）；03-04 / 03-02 既有测试均无 regression。

---
*Phase: 03-hitl-email*
*Plan: 05*
*Completed: 2026-05-17*
