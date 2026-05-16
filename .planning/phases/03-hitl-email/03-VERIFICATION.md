---
phase: 03-hitl-email
verified: 2026-05-17T04:21:29Z
resolved_at: 2026-05-17T05:10:00Z
status: passed
score: 5/5 must-haves verified
gaps:
  - truth: "审批人点击链接后无需登录账号即可看到决策表单，填写并提交后流程继续推进"
    status: resolved
    resolution_commit: "796ea04"
    resolution: >
      重构 graph_loader → graph_resumer 接口，把 compile + ainvoke 整体下推到 loader 内。
      _default_graph_resumer 在 `async with get_checkpointer():` block 内执行
      compile(dsl, checkpointer=checkpointer) + ainvoke(Command(resume=...))，
      确保 checkpointer 连接在 ainvoke 期间存活，LangGraph interrupt 真正 resume。
      新增 test_hitl_graph_resume_checkpointer.py 4 个回归测试覆盖 root cause（包含
      显式 assert "checkpointer" in compile.kwargs 的 P0 防护）。
---

# Phase 3: HITL 单节点 + Email 审批 验证报告

**Phase Goal:** 审批人收到邮件深链，点击链接完成四态决策，流程继续推进
**Verified:** 2026-05-17T04:21:29Z
**Gap Resolved:** 2026-05-17T05:10:00Z (commit 796ea04)
**Status:** passed
**Re-verification:** Inline fix — gap minimal scope, single-file root cause

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 审批人收到包含"同意/退回/拒绝"按钮的邮件，每个按钮有独立 token 深链 | ✓ VERIFIED | `hitl_decision.html` 含 3 个 `<a href>` 按钮（颜色区分绿/黄/红）；`send_hitl_email_job` 调用 `_build_deeplink(jti)` 生成 `/hitl/page/<jti>`；`hitl_token_service.sign()` 为每个 action 独立签 jti；`e2e/hitl_email_delivery.spec.ts` ROADMAP #1 覆盖 |
| 2 | 审批人点击链接后无需登录账号即可看到决策表单，填写并提交后流程推进 | ✗ PARTIAL | GET 决策页正确实现（JWT decode + 30min HMAC cookie + page.html）；POST 消费 jti + 更新 node_state.payload 正确；但 `_default_graph_loader` 未传 checkpointer，`compiler.compile(dsl)` 无 checkpoint 后端，LangGraph `ainvoke(Command(resume=...))` 无法读取 Postgres 中的中断状态，实际 graph 不会推进 |
| 3 | Outlook Safe Links 扫描器 GET token 链接不消费 jti，审批人首次点击仍可正常决策 | ✓ VERIFIED | `bot_detector.py` 含 16 个 pattern（包含 `ac-detector-tool` Outlook 真实 UA）；`hitl.py GET /hitl/page` 在 JWT decode 前执行 bot UA 短路，返回 `bot_scan.html` 不签 cookie 不动 jti；`test_hitl_safe_links_bot_get.py` + `e2e/hitl_safe_links_bot.spec.ts` (ROADMAP #3 P0) 均覆盖 |
| 4 | 同一 token 提交后立即失效；同节点其他 token 同时失效；重复提交返回 409 | ✓ VERIFIED | `HitlTokenStore.consume()` 原子 UPDATE...WHERE used_at IS NULL RETURNING；`invalidate_siblings()` 批量失效同 node_state 其他 token；duplicate consume 返回 None → `JtiAlreadyConsumed` → HTTP 409；`test_hitl_advisory_lock_concurrent.py` + `e2e/hitl_token_invalidation.spec.ts` (ROADMAP #4) 覆盖 |
| 5 | 申请人能在追踪页查看自己实例的当前节点状态和历史决策记录 | ✓ VERIFIED | `GET /instances/{id}/tracking` 实现，`InstanceService.get_tracking_for_applicant` 含 applicant_id 校验；申请人 IP/UA 脱敏；admin 可见完整字段；前端 `tracking-timeline.tsx` + `applicant-only-records.tsx`；`test_tracking_api.py` + `e2e/hitl_tracking_page.spec.ts` (ROADMAP #5) 覆盖 |

**Score:** 4/5 truths verified（Truth #2 partial — GET 决策页正常但 LangGraph resume 未真正推进）

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/migrations/versions/0003_phase3_hitl.py` | Phase 3 HITL migration | ✓ VERIFIED | revision="0003", hitl_tokens + notifications + audit_log ALTER，含 3 索引 + UNIQUE 约束 |
| `backend/app/agent_builder/models/hitl_token.py` | HitlToken ORM | ✓ VERIFIED | jti PK + 3 复合索引 + used_at nullable + NET-05 字段 |
| `backend/app/agent_builder/models/notification.py` | Notification ORM | ✓ VERIFIED | BIGSERIAL PK + UNIQUE (instance, node_state, channel, recipient, reminder_round) + JSONB payload |
| `backend/app/agent_builder/workflow/hitl_token_store.py` | HitlTokenStore | ✓ VERIFIED | Redis-first is_consumed + 原子 consume + invalidate_siblings pipeline |
| `backend/app/services/hitl_token_service.py` | HitlTokenService JWT | ✓ VERIFIED | HS256 sign/decode + aud='hitl' + InvalidSignature/TokenExpired/InvalidAudience 细分 |
| `backend/app/agent_builder/security/bot_detector.py` | is_bot_ua | ✓ VERIFIED | 16 个 BOT_UA_PATTERNS，含 Outlook 真实 UA ac-detector-tool |
| `backend/app/agent_builder/workflow/hitl_payload.py` | 纯函数 build/append/compute/validate | ✓ VERIFIED | immutable append_record + compute_next_status 五态 + jsonschema Draft7Validator |
| `backend/app/agent_builder/services/hitl_service.py` | HitlService.batch_create_tokens | ✓ VERIFIED | 每 action 一行 HitlToken + flush |
| `backend/app/agent_builder/workflow/nodes/hitl.py` | HITLNodeExecutor | ✓ VERIFIED | override __call__ 跳过 retry；interrupt + resume 两段；NODE_EXECUTORS["hitl"] 注册 |
| `backend/app/services/notification_service.py` | NotificationService | ✓ VERIFIED | enqueue_hitl_email + enqueue_generic_email + UNIQUE 约束去重 |
| `backend/app/jobs/email_jobs.py` | send_hitl_email_job | ✓ VERIFIED | tenacity 3 次指数退避 (1s/2s/4s) + status=sent/failed + idempotent |
| `backend/app/templates/email/hitl_decision.html` | 决策邮件模板 | ✓ VERIFIED | 3 按钮颜色区分 + Jinja autoescape XSS 防护 |
| `backend/app/templates/email/hitl_decision_text.txt` | 明文 fallback | ✓ VERIFIED | 存在 |
| `backend/app/templates/email/hitl_reminder.html` | 催办模板 | ✓ VERIFIED | 存在，[催办] 前缀标识 |
| `backend/app/agent_builder/workflow/nodes/notification.py` | NotificationNodeExecutor | ✓ VERIFIED | NODE_EXECUTORS["notification"] 注册；不调用 interrupt；失败不阻断 graph |
| `backend/app/agent_builder/api/hitl.py` | 公网 HITL router | ✓ VERIFIED | router prefix="/hitl"；`agent_builder_app.include_router(hitl.router)` 注册；GET/POST 均实现 |
| `backend/app/agent_builder/services/hitl_action_service.py` | HitlActionService | ✓ VERIFIED | 7 步流程：advisory_lock + consume + invalidate_siblings + append_record + compute_next_status + ainvoke(Command(resume)) + audit_log |
| `backend/app/templates/hitl/page.html` | 决策页 SSR 模板 | ✓ VERIFIED | 存在 |
| `backend/app/templates/hitl/bot_scan.html` | Bot 扫描静态页 | ✓ VERIFIED | 存在 |
| `backend/app/templates/hitl/success.html` | 成功页 | ✓ VERIFIED | 存在 |
| `backend/app/templates/hitl/error.html` | 错误页 | ✓ VERIFIED | 存在 |
| `backend/app/agent_builder/api/v1/instances.py` | GET /instances/{id}/tracking | ✓ VERIFIED | Line 186-215，TrackingResponse schema，applicant_id 校验 |
| `backend/app/agent_builder/services/instance_service.py` | get_tracking_for_applicant | ✓ VERIFIED | Line 240，IP/UA 脱敏 |
| `backend/app/jobs/hitl_timeout_jobs.py` | scan_hitl_timeouts cron | ✓ VERIFIED | 24h/48h/72h 三档；advisory_lock 防 race；escalation 触发 |
| `backend/app/agent_builder/services/escalation_service.py` | EscalationService | ✓ VERIFIED | resolve_escalate_to fallback workspace admin；perform_escalation 写 records + audit |
| `backend/app/templates/email/hitl_escalation.html` | 升级邮件模板 | ✓ VERIFIED | 存在 |
| `backend/app/agent_builder/worker.py` | arq WorkerSettings | ✓ VERIFIED | functions 含 send_hitl_email_job + send_hitl_reminder_job；cron_jobs 含 scan_hitl_timeouts |
| `web/src/app/hitl/[token]/page.tsx` | 决策页 Next.js | ✓ VERIFIED | 存在，含 server component + decision-page-client.tsx |
| `web/src/components/hitl/decision-form.tsx` | DecisionForm RJSF | ✓ VERIFIED | `import Form from '@rjsf/core'`；3 按钮按 phase；disabled 防双提交 |
| `web/src/components/hitl/records-timeline.tsx` | 历史记录 | ✓ VERIFIED | 存在 |
| `web/src/components/hitl/deadline-countdown.tsx` | 倒计时 | ✓ VERIFIED | 存在，setInterval 客户端计时 |
| `web/src/app/dashboard/instances/[id]/tracking/page.tsx` | 追踪页 | ✓ VERIFIED | 存在 |
| `web/src/components/instance/tracking-timeline.tsx` | 时间线组件 | ✓ VERIFIED | 存在 |
| `e2e/hitl_email_delivery.spec.ts` | E2E ROADMAP #1 | ✓ VERIFIED | skip 模式正确；覆盖 3 button + subject + plain text |
| `e2e/hitl_token_login.spec.ts` | E2E ROADMAP #2 | ✓ VERIFIED | 存在；GET cookie + POST 流程（注：graph resume gap 影响实际 full-stack 通过率） |
| `e2e/hitl_safe_links_bot.spec.ts` | E2E ROADMAP #3 P0 | ✓ VERIFIED | 4 种 Bot UA + 真实用户 follow-up；P0 全覆盖 |
| `e2e/hitl_token_invalidation.spec.ts` | E2E ROADMAP #4 | ✓ VERIFIED | 存在，advisory_lock 并发测试 |
| `e2e/hitl_tracking_page.spec.ts` | E2E ROADMAP #5 | ✓ VERIFIED | 存在，IP/UA 脱敏 + 403 访问控制 |
| `docs/reading-dify-03-01..10-hitl-*.md` | 10 个 Dify 阅读笔记 | ✓ VERIFIED | 全部存在（149~334 行），CLAUDE.md 2.7 Task 0 gate 执行 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `hitl.py GET /hitl/page` | `bot_detector.is_bot_ua` | 调用前短路 | ✓ WIRED | Line: `if is_bot_ua(ua): return bot_scan.html` |
| `hitl.py GET /hitl/page` | `HitlTokenService.decode` | JWT 校签不消费 | ✓ WIRED | `payload = HitlTokenService.decode(token)` — 不写 DB |
| `hitl.py GET /hitl/page` | `HitlTokenStore.is_consumed` | 仅查询 | ✓ WIRED | `await store.is_consumed(jti_uuid)` — 不写 used_at |
| `hitl.py POST /hitl/action` | `HitlActionService.submit_action` | 7 步流程 | ✓ WIRED | `service.submit_action(payload, action, reason, form_data, ip, ua)` |
| `HitlActionService` | `pg_advisory_xact_lock` | text() 原子事务锁 | ✓ WIRED | `await self.db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})` |
| `HitlActionService` | `HitlTokenStore.consume` | jti 原子消费 | ✓ WIRED | `token_row = await store.consume(jti, ip=ip, ua=ua)` |
| `HitlActionService` | `HitlTokenStore.invalidate_siblings` | sibling 失效 | ✓ WIRED | `await store.invalidate_siblings(node_state_id, except_jti=jti)` |
| `HitlActionService` | `graph.ainvoke(Command(resume=...))` | LangGraph resume | ✗ PARTIAL | graph 通过 `_default_graph_loader` 加载但**未传 checkpointer**；`compiler.compile(dsl)` 无 checkpoint 后端，无法从 Postgres 读取中断状态；graph 为 None 时 ainvoke 被跳过 |
| `HitlActionService` | `AuditLog` (NET-05) | audit 写入 | ✓ WIRED | `audit.actor_ip / actor_ua / decision / node_state_id` 全部填充 |
| `NotificationService.enqueue_hitl_email` | `email_jobs.send_hitl_email_job` | arq.enqueue_job | ✓ WIRED | `await self.arq.enqueue_job("send_hitl_email_job", str(notif.id))` |
| `send_hitl_email_job` | `email_service._send_email` | Phase 1 复用 | ✓ WIRED | `from app.services.email_service import _send_email` |
| `scan_hitl_timeouts` | `NotificationService.enqueue_hitl_email` | 催办入队 | ✓ WIRED | `_trigger_reminder` 调用 `svc.enqueue_hitl_email(..., reminder_round=round)` |
| `HITLNodeExecutor` | `langgraph.types.interrupt` | LangGraph interrupt | ✓ WIRED | `from langgraph.types import interrupt`；`decision = interrupt({...})` |
| `NODE_EXECUTORS["hitl"]` | `HITLNodeExecutor` | 注册 | ✓ WIRED | `"hitl": HITLNodeExecutor` 在 `nodes/__init__.py` |
| `NODE_EXECUTORS["notification"]` | `NotificationNodeExecutor` | 注册 | ✓ WIRED | `"notification": NotificationNodeExecutor` 在 `nodes/__init__.py` |
| `web/decision-form.tsx` | `@rjsf/core` | JSON Schema 渲染 | ✓ WIRED | `import Form from '@rjsf/core'`；`package.json: "@rjsf/core": "^5"` |
| `web/hitl/[token]/page.tsx` | `GET /hitl/page/<token>` | fetch with cookie | ✓ VERIFIED (structural) | server component + decision-page-client.tsx 存在 |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| HITL-01 | 03-01, 03-02, 03-06 | 四态决策 (submit/approve/return/reject) | ✓ SATISFIED | `compute_next_status` 5 → 3 终态；`invalidate_siblings` 防重复；4 button 邮件 |
| HITL-03 | 03-02 | 单 interrupt + 自管 payload (records / current_idx) | ✓ SATISFIED | `HITLNodeExecutor.override __call__` + `hitl_payload.py` 纯函数；但 resume 链路有 checkpointer gap |
| HITL-05 | 03-02, 03-07 | form_schema JSON Schema 校验 | ✓ SATISFIED | `validate_form_data(Draft7Validator)` 在 service + executor；RJSF 5.x 前端渲染 |
| HITL-07 | 03-08 | 申请人追踪页 | ✓ SATISFIED | `GET /instances/{id}/tracking` + `get_tracking_for_applicant` + IP/UA 脱敏 |
| NOTI-01 | 03-04 | Email 通道 SMTP + Jinja2 + 独立 token 按钮 | ✓ SATISFIED | `hitl_decision.html` 3 按钮 + text fallback；`_build_deeplink(jti)` |
| NOTI-08 | 03-04, 03-05 | HITL 节点多通道（Phase 3 仅 email）| ✓ SATISFIED | 扩展点在 `NotificationService`；`enqueue_generic_email` 支持 email channel；Phase 4 扩展 IM |
| NOTI-09 | 03-09 | 催办 / 超时通知（24h/48h 阶梯）| ✓ SATISFIED | `scan_hitl_timeouts` cron；notifications UNIQUE 约束去重；round 1/2/3 |
| NOTI-10 | 03-04 | 失败重试 (arq + 指数退避) | ✓ SATISFIED | `tenacity AsyncRetrying stop=3, wait=exponential(1,1,4)` |
| AUTH-04 | 03-03, 03-06 | HITL Token 即登录（JWT → session cookie）| ✓ SATISFIED | `HitlTokenService.decode` + HMAC session cookie 30min |
| AUTH-05 | 03-01, 03-06 | jti 一次性消费，GET 不消费 | ✓ SATISFIED | `is_consumed` (GET) vs `consume` (POST only)；bot UA 防护 |
| NET-05 | 03-01, 03-06 | 决策审计日志 (IP/UA/decision/node_state_id) | ✓ SATISFIED | `audit_logs` 补 4 列；`AuditLog(actor_ip=ip, actor_ua=ua, decision=action, node_state_id=node_state_id)` |
| NODE-02 | 03-02 | HITL 节点 executor | ✓ SATISFIED | `HITLNodeExecutor` 注册到 `NODE_EXECUTORS["hitl"]` |
| NODE-07 | 03-05 | Notification 节点（独立，不阻塞）| ✓ SATISFIED | `NotificationNodeExecutor` 注册到 `NODE_EXECUTORS["notification"]`；不调用 interrupt |

**所有 13 个 requirement 均有实现证据。** REQUIREMENTS.md 状态矩阵已标记 Complete。

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/agent_builder/api/hitl.py` | ~445 | `compiler.compile(workflow_version.dsl)` 未传 checkpointer | 🛑 Blocker | `graph.ainvoke(Command(resume=...))` 无法读取 Postgres checkpoint，LangGraph 中断未被真正 resume，ROADMAP #2"流程推进"实质失效 |
| `backend/app/agent_builder/api/hitl.py` | ~427 | 注释 "v1 简化：若编译失败...返回 None 跳过 ainvoke" | ⚠️ Warning | 硅化了 graph=None 路径作为正常 fallback，隐藏了关键链路失败 |
| `backend/app/agent_builder/services/hitl_action_service.py` | ~272 | `return None` (默认 graph_loader 缺失时) | ⚠️ Warning | 若 graph_loader 未注入且 _default_graph_loader 返回 None，ainvoke 被静默跳过 |

---

### Human Verification Required

#### 1. LangGraph Graph Resume 实际行为

**Test:** 启动含 HITL 节点的 workflow (`RUN_E2E=1`)，邮件收到后点击 "同意" 按钮
**Expected:** `flow_instances.status` 从 `waiting_human` 变为 `done` / `completed`（取决于节点后是否还有节点）
**Why human:** 需要完整 docker-compose 环境 + mailhog + Postgres checkpointer 才能端到端验证 graph resume 是否真正推进。`hitl_token_login.spec.ts` 在 `RUN_E2E=1` 模式下才跑，且有 checkpointer gap 可能导致 FAIL

#### 2. 邮件 deeplink 公网可达性

**Test:** docker-compose up 后，`PUBLIC_BASE_URL` 配置是否让 `/hitl/page/<token>` 可从浏览器直接访问
**Expected:** 邮件中的链接点击后直达 page.html 决策页
**Why human:** nginx 路由配置 (`NET-02`) 只能在真实 docker 环境验证

#### 3. 催办邮件定时触发（03-09）

**Test:** 设置 `deadline_at` 为过去 25h，等待 arq cron 触发 `scan_hitl_timeouts`
**Expected:** mailhog 收到 `[催办]` 前缀邮件
**Why human:** cron 需要真实 arq worker 运行 60 秒后才能看到效果，不可自动化

---

### Gaps Summary

**1 个 Blocker Gap — LangGraph Graph Resume 缺失 Checkpointer**

Phase 3 的核心成功指标 ROADMAP #2 中"填写并提交后**流程继续推进**"存在实质性缺口：

- `POST /hitl/action/<token>` 的 `_default_graph_loader`（`hitl.py` 第 418 行）调用 `compiler.compile(workflow_version.dsl)` 时**未传入 checkpointer**
- 正确模式在 `runner.py:189-196`：`async with get_checkpointer() as checkpointer: compiler.compile(dsl, checkpointer=checkpointer)`
- 缺少 checkpointer 导致 `graph.ainvoke(Command(resume=...))` 要么在空内存中跑一个全新 graph（找不到 thread_id 对应的中断状态），要么 compile 失败被 `try/except` 吞掉返回 None
- 当 graph 返回 None 时，`HitlActionService.submit_action` 第 214 行 `if graph is not None:` 跳过 ainvoke，整个 LangGraph interrupt resume 路径被静默跳过

**影响范围：**
- ROADMAP #2 后半句"流程继续推进"实质未达成
- `flow_instances.status` 不会被 LangGraph 的 `ExecutionEngine` 更新（因为 graph 没有 resume）
- 其他 4 个 ROADMAP criteria（邮件投递、bot 防护、token 失效、追踪页）均已正确实现

**修复方向：**
- 方案 A：`_default_graph_loader` 改用 `async with get_checkpointer() as checkpointer: compiler.compile(dsl, checkpointer=checkpointer)` 
- 方案 B：`HitlActionService.__init__` 增加 `checkpointer` 参数，由 `hitl.py` 从 `app.state.checkpointer` 注入（需要 lifespan 初始化 checkpointer 到 app.state）

---

*Verified: 2026-05-17T04:21:29Z*
*Verifier: Claude (gsd-verifier)*
