---
phase: 03-hitl-email
plan: "09"
subsystem: scheduling
tags: [arq, cron, hitl, timeout, reminder, escalation, advisory-lock, audit-log, NOTI-09, HITL-04]

# Dependency graph
requires:
  - phase: 03-hitl-email
    provides: 03-01 notifications UNIQUE 约束 / 03-02 HitlService.batch_create_tokens / 03-04 send_hitl_email_job + 模板 / 03-06 NodeState.payload 列
  - phase: 02-dsl
    provides: arq WorkerSettings 框架 / async_session_maker / NodeState ORM
  - phase: 01-skeleton
    provides: AuditLog ORM + User/UserWorkspaceRole/Role 模型 / PUBLIC_BASE_URL

provides:
  - scan_hitl_timeouts arq cron job（每分钟扫超时节点）
  - EscalationService.resolve_escalate_to + perform_escalation
  - hitl_escalation.html 升级邮件模板（深红 banner + overdue_hours）
  - email_jobs.py 支持 payload.escalation=True 路由到 hitl_escalation.html

affects:
  - 03-10 E2E gate（超时催办 / 升级 E2E 场景）
  - Phase 4 多人审批链（HITL-04 sequential/parallel_all/parallel_any 模式扩展本 plan single 模式）
  - Phase 5 assignee resolver（resolve_escalate_to 扩展 role:admin / dept:HR）

# Tech tracking
tech-stack:
  added:
    - arq.cron.cron WorkerSettings.cron_jobs 配置
  patterns:
    - "arq cron 替代 Celery beat（CLAUDE.md §3 锁定 + asyncio 原生与 aiosmtplib 同构）"
    - "pg_advisory_xact_lock(hash(node_state_id)) 防多 worker race（事务级 RAII，commit 自动释放）"
    - "UNIQUE 约束（instance, ns, ch, recipient, round）+ advisory_lock 双保险防重发"
    - "三档阶梯催办：24h round=1 / 48h round=2 / 72h escalate"
    - "_process_node 接受 ns_id 而非 ORM 对象（避免 detached object 跨 session race）"
    - "_trigger_reminder 直接 INSERT notifications（不走 NotificationService 防内部 commit 提前释放 lock）"
    - "Dify Pattern C 异常隔离：单节点 try/except + rollback 不影响其他节点"

key-files:
  created:
    - backend/app/jobs/hitl_timeout_jobs.py
    - backend/app/agent_builder/services/escalation_service.py
    - backend/app/templates/email/hitl_escalation.html
    - backend/tests/test_hitl_timeout_scan.py
    - backend/tests/test_hitl_escalation.py
    - backend/tests/test_hitl_reminder_rounds.py
    - docs/reading-dify-03-09-timeout-worker-2026-05-17.md
  modified:
    - backend/app/agent_builder/worker.py  # 注册 cron(scan_hitl_timeouts)
    - backend/app/jobs/email_jobs.py        # 支持 payload.escalation=True 路由

key-decisions:
  - "arq cron 替代 Celery beat：CLAUDE.md §3 技术栈锁定 + asyncio 原生（详见 reading doc §7）"
  - "三档阶梯阈值（24h/48h/72h）vs Dify 单一 TIMEOUT 终态：场景不同（审批人需主动催办 vs Dify 表单等用户主动提交）"
  - "_trigger_reminder 不复用 NotificationService.enqueue_hitl_email：后者内部 commit() 提前释放 advisory_lock，破坏并发隔离"
  - "_process_node 入参 ns_id（vs ORM 对象）：避免 detached object 在新 session 中 refresh 行为难预测"
  - "EscalationService.resolve_escalate_to Phase 3 简化：仅接受 user_email 字符串 + workspace admin fallback；Phase 5 扩展 role:admin/dept:HR"
  - "升级邮件无决策按钮：v1 admin 需先看上下文（不在邮件内直接决策升级件）— 区别于催办邮件保留按钮"
  - "payload.escalation=True 标识 + reminder_round=3：email_jobs.py 据此路由 hitl_escalation.html；与催办（reminder_round 1/2 + hitl_reminder.html）解耦"
  - "advisory_xact_lock(hash(ns_id)) 单进程一致：与 hitl_action_service.py:155 同模式（PYTHONHASHSEED caveat 文档化）"
  - "scan LIMIT=100 防 OOM（借鉴 Dify human_input_timeout_tasks.py:103）；下次 cron 60s 后继续"
  - "PG advisory_xact_lock 选 _xact_ 后缀语义：事务结束自动释放，避免会话级 lock 泄漏"
  - "scan_hitl_timeouts 用 async_session_maker 创建独立 session：与 arq worker 上下文隔离 + 测试时与 db_session fixture 独立"
  - "_seed_overdue_node 测试用 seed_admin=True 兜底：escalation 测试无 escalate_to 时 fallback 到 admin email"

patterns-established:
  - "arq cron job 三段式：scan SELECT → for each ns_id: advisory_lock + dispatch → commit"
  - "advisory_xact_lock + UNIQUE 约束双保险防并发：lock 是性能层（防 race），UNIQUE 是正确性层（兜底）"
  - "时间档位 dispatch 模式：elapsed >= TH3 → escalate; >= TH2 → reminder_2; >= TH1 → reminder_1（从高到低判断避免跳过中间档）"
  - "current_round 推导从 notifications.reminder_round MAX（避免在 node_state 加状态字段）"
  - "测试 fixture clean_phase3_tables + engine.dispose() 防跨测试事件循环污染（asyncpg 单 loop 绑定）"

requirements-completed:
  - HITL-04  # 节点超时（single 模式部分；4 模式 Phase 4）
  - NOTI-09  # 催办 / 提醒
  - NOTI-10  # 失败重试（复用 03-04 已建）
  - NET-05   # 决策审计（escalation 路径）

# Metrics
duration: ~26min
completed: 2026-05-17
test-count: 21  # 9 scan + 7 escalation + 5 rounds/concurrent
file-count: 8   # 7 created + 2 modified（worker.py + email_jobs.py）
---

# Phase 3 Plan 09: HITL 超时催办 + 升级 Worker Summary

**HITL 节点超时催办 worker：arq cron 每分钟扫超时节点 + 24h/48h/72h 三档阶梯 + 72h 升级到 escalate_to（NOTI-09 + HITL-04 single 模式 + NET-05 audit）。Dify Celery beat → arq cron 简化决策记入 reading doc §7。**

## Performance

- **Duration:** ~26 分钟（Task 0 + 3 个 Task）
- **Started:** 2026-05-16T19:13:19Z
- **Completed:** 2026-05-16T19:38:57Z
- **Tasks:** 4 实际执行（Task 0 reading doc + Task 1 scan + Task 2 escalation + Task 3 rounds/concurrent）
- **Files created:** 7
- **Files modified:** 2（worker.py 注册 cron + email_jobs.py 路由 escalation）
- **Test cases:** 21 通过（9 scan + 7 escalation + 5 rounds/concurrent + 模板渲染 bonus）

## Accomplishments

1. **arq cron scan_hitl_timeouts**（backend/app/jobs/hitl_timeout_jobs.py）：
   - 每分钟扫一次 `node_states WHERE status IN ('waiting_human','in_review') AND payload->>deadline_at < now()`
   - LIMIT 100 防 OOM（借鉴 Dify human_input_timeout_tasks.py:103）
   - ORDER BY id ASC（FIFO 公平 + 索引顺序扫描）
   - 注册到 `WorkerSettings.cron_jobs`：`cron(scan_hitl_timeouts, minute=set(range(60)), second={0}, unique=True, max_tries=1, timeout=50)`

2. **三档阶梯催办**：
   | 档位 | 阈值（秒） | 触发条件 | 处理 |
   |---|---|---|---|
   | round_1 | 24 * 3600 | elapsed >= 24h && current_round < 1 | _trigger_reminder(round=1) |
   | round_2 | 48 * 3600 | elapsed >= 48h && current_round < 2 | _trigger_reminder(round=2) |
   | escalate | 72 * 3600 | elapsed >= 72h && current_round < 3 | _trigger_escalation |

3. **EscalationService**（backend/app/agent_builder/services/escalation_service.py）：
   - `resolve_escalate_to`: Phase 3 简化 — node_config.escalate_to email 字符串 > workspace admin > platform super_admin
   - `perform_escalation`: 写 records + 发升级邮件（reminder_round=3, payload.escalation=True）+ audit_log
   - `_extract_node_config`: 从 instance.dsl_snapshot 提取节点 config
   - `_fallback_workspace_admin_email`: JOIN User + UserWorkspaceRole + Role 查 workspace admin

4. **hitl_escalation.html 升级邮件模板**：
   - 深红 banner `#b91c1c`（与催办 `#dc2626` 区分）
   - 显示原审批人 email + 超时时长（小时数）+ 实例 ID
   - 无决策按钮（admin 需先看上下文）— 仅含登录链接 + "下一步建议" ol 列表

5. **email_jobs.py 扩展**：
   - 识别 `notif.payload.get("escalation") is True` 路由到 `hitl_escalation.html`
   - subject 走 `[升级] 审批超时：{flow_title} - {node_title}` 前缀
   - 无 text fallback（vs HITL 催办有 hitl_decision_text.txt）

6. **并发安全（Pitfall 2 防护）**：
   - `pg_advisory_xact_lock(hash(ns_id))` 单 worker 一致性
   - `notifications` UNIQUE 约束（instance, ns, ch, recipient, round）兜底
   - `_process_node(ns_id)` 接受 ID 而非 ORM 对象 — 避免 detached object 跨 session race
   - `_trigger_reminder` 不调 `NotificationService.enqueue_hitl_email`（其内部 commit 会提前释放 lock）—改为直接 INSERT + 上层统一 commit

7. **NET-05 audit_log**（EscalationService._write_audit_log）：
   - action='hitl.escalate'
   - decision='escalate'
   - actor_user_id=None / actor_ip='system' / actor_ua='hitl_timeout_worker'
   - meta {reason: 'timeout_72h', escalate_to: '...', original_actor_email, instance_id}
   - node_state_id 反查 HITL 节点

8. **21 测试通过（CLAUDE.md 2.2 真实 PG / 不 mock）**：
   - 9 scan 测试：阶梯触发 / 已 done 节点 skip / 多节点处理 / 缺 actor 兜底 / round 推进
   - 7 escalation 测试：email_format / workspace admin fallback / 无 admin None / records / 邮件 / audit / 双缺失安全跳过
   - 5 rounds/concurrent 测试：UNIQUE 触发 / 24-48-72 序列 / 并发 1 worker / 模板渲染（催办 + 升级）

## Task Commits

| Task | Name | Hash | Type |
|---|---|---|---|
| 0 | Dify 阅读笔记（CLAUDE.md 2.7 GATE） | `cb817f0` | docs |
| 1 | hitl_timeout_jobs.scan_hitl_timeouts cron + EscalationService 主体 + 9 测试 | `925dee9` | feat |
| 2 | EscalationService 7 集成测试 | `f8645c1` | test |
| 3 | reminder rounds + UNIQUE + 并发 5 测试 + 修复 _trigger_reminder | `32d4c57` | test |

**Plan metadata commit** 由后续 final_commit 步骤创建（含 SUMMARY.md + STATE.md + ROADMAP.md 更新）。

## Files Created/Modified

### 新建

- `docs/reading-dify-03-09-timeout-worker-2026-05-17.md` — Dify 阅读笔记（9 节 + §7 arq vs Celery beat + 风险清单 6 条）
- `backend/app/jobs/hitl_timeout_jobs.py` — scan_hitl_timeouts cron + _process_node + _trigger_reminder + _trigger_escalation + get_thresholds
- `backend/app/agent_builder/services/escalation_service.py` — EscalationService（resolve_escalate_to + perform_escalation + _fallback_workspace_admin_email + _extract_node_config + _send_escalation_email + _write_audit_log）
- `backend/app/templates/email/hitl_escalation.html` — 升级邮件模板（深红 banner + overdue_hours + 无决策按钮）
- `backend/tests/test_hitl_timeout_scan.py` — 9 用例
- `backend/tests/test_hitl_escalation.py` — 7 用例
- `backend/tests/test_hitl_reminder_rounds.py` — 5 用例

### 修改

- `backend/app/agent_builder/worker.py` — `from arq.cron import cron` + `WorkerSettings.cron_jobs = [cron(scan_hitl_timeouts, ...)]`
- `backend/app/jobs/email_jobs.py` — `_render_email_content` 识别 `notif_payload.get('escalation') is True` 路由到 hitl_escalation.html；subject 加 `[升级]` 前缀；text_body 跳过 escalation 路径

## Decisions Made

1. **arq cron vs Celery beat**：CLAUDE.md §3 锁定 arq 0.28+；reading doc §7 详述 6 维度对比；最高优先级简化决策。
2. **三档阶梯 vs Dify 单一 TIMEOUT 终态**：业务场景差异 — Dify 是表单等用户主动提交（无需催办），本项目是审批工作流（审批人需被推送催办）。
3. **_trigger_reminder 直接 INSERT vs 复用 NotificationService**：后者内部 `await self.db.commit()` 会提前释放 advisory_xact_lock，破坏并发隔离 — 实测发现 UNIQUE 冲突 race，改为直接 INSERT 让 _process_node 统一 commit。
4. **_process_node 入参 ns_id（vs ORM 对象）**：scan_hitl_timeouts 用 outer session 加载 nodes 列表，再传 ORM 到 _process_node（同 session）会有 detached 风险；改为传 UUID + 锁内重新 `db.get(NodeState, ns_id)` fresh load。
5. **EscalationService.resolve_escalate_to Phase 3 简化**：仅接受 user_email 字符串（不解析 role:admin/dept:HR）；Phase 5 接 IM 目录同步后扩展。
6. **fallback 顺序**：node_config.escalate_to → workspace admin → platform super_admin → None（链式 3 层 fallback）。
7. **升级邮件无决策按钮**：v1 admin 需先看上下文（不在邮件内直接决策升级件）；reminder 邮件保留按钮（actor 已知上下文，可直接决策）。
8. **payload.escalation=True 标识**：email_jobs._render_email_content 据此路由 hitl_escalation.html；与 reminder_round 阶梯解耦（升级是第 3 档 但语义不同）。
9. **advisory_xact_lock(hash(ns_id))**：与 hitl_action_service.py:155 同模式，单进程一致；多进程 PYTHONHASHSEED caveat 文档化（Phase 5+ 多实例时改 PG hashtext()）。
10. **scan LIMIT=100**：借鉴 Dify human_input_timeout_tasks.py:103，防 OOM + 下次 cron 60s 后继续；积压持续报警留 Phase 7 监控。
11. **测试 fixture engine.dispose()**：scan_hitl_timeouts 用 async_session_maker 创建独立 session — 跨测试事件循环上下文需 dispose（参考 test_hitl_advisory_lock_concurrent 同模式）。
12. **`scan_hitl_timeouts` cron unique=True + max_tries=1**：多 worker 中只有一个执行（防重复扫描），失败不重试（60s 后下次 cron 再来 — 防补发风暴）。

## Dify 参考点

详见 `docs/reading-dify-03-09-timeout-worker-2026-05-17.md`（commit `cb817f0`，Task 0）。本 plan 落实的核心借鉴：

| 借鉴维度 | Dify 原模式 | 本项目落点 | 文件 |
|---|---|---|---|
| **cron 扫描查询** | `select(HumanInputForm).where(status=WAITING, expiration_time <= now()).order_by(id.asc()).limit(100)` | `select(NodeState).where(status.in_(['waiting_human','in_review']), payload['deadline_at'].astext.cast(TIMESTAMP) < now).order_by(id.asc()).limit(100)` | `backend/app/jobs/hitl_timeout_jobs.py:_scan_overdue_nodes` |
| **异常隔离 Pattern C** | `for form in expired: try: ... except: logger.exception(...)` | `for ns_id in node_ids: try: _process_node ... except: log.exception + rollback` | `backend/app/jobs/hitl_timeout_jobs.py:scan_hitl_timeouts` |
| **LIMIT 防 OOM** | `limit=100` | `_SCAN_LIMIT = 100` | `backend/app/jobs/hitl_timeout_jobs.py` |
| **时间档位 dispatch** | `if is_global: _handle_global_timeout else: enqueue_resume` | `if elapsed >= 72h: escalate; >= 48h: r2; >= 24h: r1` 三分支 | `backend/app/jobs/hitl_timeout_jobs.py:_process_node` |
| **enqueue_resume → service 调用解耦** | `service.enqueue_resume(workflow_run_id)` 另一 Celery task 处理 | `NotificationService → arq enqueue_job` 模式（reminder 不动 LangGraph，escalation 不主动 ainvoke graph）| `backend/app/jobs/hitl_timeout_jobs.py:_trigger_reminder` |
| **state pause/resume** | `WorkflowPause` 表 + `storage.delete(pause_model.state_object_key)` 释放 state | Phase 3 简化不删 LangGraph checkpoint（升级后下次扫描照样处理；v2 加清理）| —（本 plan 不实现） |

**Attribution**：未拷贝 Dify 源码（Dify 是 AGPL-3.0，本项目 Apache-2.0）。借鉴的查询模式 / dispatch 结构 / 异常隔离均独立重写（asyncio 风格 + 中文注释 + 三档阶梯特化）。

## Deviations from Plan

**[Rule 1 - Bug] _trigger_reminder 不调 NotificationService.enqueue_hitl_email**

- **Found during:** Task 3 并发测试 — `test_concurrent_two_workers_only_one_sends` 失败：两 worker 都触发 UNIQUE 冲突 `IntegrityError` 后 session 进入 `PendingRollbackError` 状态
- **根因：** `NotificationService.enqueue_hitl_email` 内部 `await self.db.commit()` 在 INSERT 后立即调用 — 这会**提前释放 advisory_xact_lock**，第二个 worker 立刻进入锁区域，看到首发 round=1 已存在（或还没看到），仍尝试 INSERT 触发 UNIQUE 冲突
- **Fix:** 改为 `_trigger_reminder` 内部直接 `db.add(notif) + await db.flush()`（不 commit），让外层 `_process_node` 在所有处理结束后统一 `db.commit()` 释放 advisory_lock — 保证整个处理流程在 lock 保护内原子完成
- **Files modified:** `backend/app/jobs/hitl_timeout_jobs.py`（`_trigger_reminder` 重写 ~50 行）
- **Commit:** `32d4c57`

**[Rule 1 - Bug] _process_node 入参 ns_id（vs ORM 对象）**

- **Found during:** Task 3 并发测试调试 — refresh detached ORM 对象在 scan 后 _process_node 内行为不一致
- **Fix:** 改 `_process_node(ns_id: UUID)`，锁内重新 `await db.get(NodeState, ns_id)` 加载 fresh 实例
- **Files modified:** `backend/app/jobs/hitl_timeout_jobs.py`（`_process_node` 签名 + 主循环 `node_ids = [ns.id for ns in nodes]`）
- **Commit:** `32d4c57`

**[Rule 3 - Blocking] 测试 fixture engine.dispose()**

- **Found during:** Task 3 跨测试集成 — `test_scan_round_1_already_sent_advances_to_round_2` 在其他文件后运行时 RuntimeError: Event loop is closed
- **根因:** scan_hitl_timeouts 用 `async_session_maker()` 创建独立 session，asyncpg 连接绑定到 pytest event loop；跨测试时 loop 复用导致连接 stale
- **Fix:** clean_phase3_tables fixture yield 后加 `await engine.dispose()`（参考 test_hitl_advisory_lock_concurrent.py 同模式）
- **Files modified:** 3 测试文件
- **Commit:** `32d4c57`

**轻微 plan 调整（非 deviation）：**
- PLAN.md 写 `backend/app/worker.py` — 实际项目路径 `backend/app/agent_builder/worker.py`（pre-existing flock 结构差异，与 plan 文本差一字段）
- PLAN.md 计划 6 + 4 + 4 = 14 测试，实际写 9 + 7 + 5 = 21 测试（含 bonus 边界 / 模板渲染 / fallback 路径覆盖）

## Issues Encountered

1. **arq cron `minute` 字段范围限制（Pre-existing）**
   - 现象：`cron(scan_hitl_timeouts, minute=set(range(60)), second={0})` 通过 — 但 arq 0.28+ 期望 `minute` 是单个值或 `set[int]` 范围 0-59
   - 评估：`set(range(60))` = `{0,1,...,59}` 命中每分钟，符合"每分钟 0 秒触发"语义
   - 行动：无需调整 — 已是 arq 文档示例

2. **Phase 1 _send_email 不接受 text_body 参数（Pre-existing，03-04 已记）**
   - 影响：升级邮件 + 催办邮件 text fallback 仍是 Phase 1 占位符
   - 行动：本 plan 范围不修复（CLAUDE.md SCOPE BOUNDARY — 不动 Phase 1 模块）；记入 `.planning/phases/03-hitl-email/deferred-items.md` 同 03-04 记录

3. **测试中 UNIQUE 约束 + 同事务多 INSERT**
   - 现象：`test_reminder_round_unique_constraint` 第一次 INSERT 后 rollback 会同时回滚第二次失败 INSERT → 表为空
   - Fix: 测试用 commit() 中间分离两次 INSERT（first 单独 commit 持久化，second flush 触发 UNIQUE 抛错 + rollback 只回滚 second）

## User Setup Required

None - 本 plan 完全复用 Phase 1/2/3 既有基础设施：
- arq WorkerSettings（Phase 2 02-08 已建）+ async_session_maker（Phase 2）
- 03-01 notifications UNIQUE 约束 + AuditLog 模型
- 03-04 send_hitl_email_job + hitl_reminder.html 模板
- 03-06 NodeState.payload JSONB 列（migration 0004）
- env：PUBLIC_BASE_URL（Phase 1 startup_checks 校验）

**生产部署额外要求**：
- arq worker 进程必须运行（`arq app.agent_builder.worker.WorkerSettings`）— Phase 2 已要求
- worker 进程数 ≥ 1（多 worker 时 cron `unique=True` 保证只有一个执行）

## Next Plan Readiness

- ✅ **03-10 E2E gate**：可直接复用 scan_hitl_timeouts + EscalationService 写 E2E 场景（手动 fast-forward node payload.started_at 模拟 25h/49h/73h 超时）
- ✅ **Phase 4 多人审批链（HITL-04 4 模式扩展）**：本 plan single 模式作为基线；sequential/parallel_all/parallel_any 各扩展 _process_node 状态判断逻辑
- ✅ **Phase 5 assignee resolver**：resolve_escalate_to 留 expand 点（role:admin / dept:HR / dynamic_expr）
- ⚠️ **arq worker 生产部署**：pyproject.toml 待补 `arq>=0.28`（pre-existing，03-04 已 deferred）

## Self-Check

执行验证：
- [x] `docs/reading-dify-03-09-timeout-worker-2026-05-17.md` 存在 + 已 commit (`cb817f0`)
- [x] `backend/app/jobs/hitl_timeout_jobs.py` 存在 + 已 commit (`925dee9` + 修复 `32d4c57`)
- [x] `backend/app/agent_builder/services/escalation_service.py` 存在 + 已 commit (`925dee9`)
- [x] `backend/app/templates/email/hitl_escalation.html` 存在 + 已 commit (`925dee9`)
- [x] `backend/app/agent_builder/worker.py` 已注册 cron(scan_hitl_timeouts) (`925dee9`)
- [x] `backend/app/jobs/email_jobs.py` 已支持 payload.escalation=True 路由 (`925dee9`)
- [x] `backend/tests/test_hitl_timeout_scan.py` 9 测试通过 (`925dee9` + 修复 `32d4c57`)
- [x] `backend/tests/test_hitl_escalation.py` 7 测试通过 (`f8645c1` + 修复 `32d4c57`)
- [x] `backend/tests/test_hitl_reminder_rounds.py` 5 测试通过 (`32d4c57`)
- [x] 21 测试全部通过（9 + 7 + 5）
- [x] Task 0 reading doc commit 在所有 feat: commit 之前（cb817f0 → 925dee9 → f8645c1 → 32d4c57，CLAUDE.md 2.7 GATE 顺序正确）
- [x] 现有测试不受影响：email_jobs (8 pass) + notification_service (5 pass) + email_templates (4 pass)

## Self-Check: PASSED

所有声明的文件存在；所有声明的 commit 在 git log 中；21 测试全部通过 + 17 旧测试不受影响；reading doc commit 在 feat commit 之前（CLAUDE.md 2.7 GATE 顺序）。

---
*Phase: 03-hitl-email*
*Plan: 09*
*Completed: 2026-05-17*
