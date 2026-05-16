---
phase: 03-hitl-email
plan: "04"
subsystem: notification
tags: [email, hitl, arq, tenacity, jinja2, smtp, retry, deeplink, notification-service]

# Dependency graph
requires:
  - phase: 03-hitl-email
    provides: 03-01 notifications + hitl_tokens ORM + UNIQUE 约束 / 03-03 HitlTokenService.sign（deeplink token 由 03-06 集成）
  - phase: 01-skeleton
    provides: email_service._send_email aiosmtplib 底层 / audit.log 审计写入 / PUBLIC_BASE_URL env / Jinja2 environment
  - phase: 02-dsl
    provides: arq WorkerSettings 框架（02-08 引入）/ async_session_maker DB engine
provides:
  - NotificationService（通用通知入队 + 状态管理）
  - send_hitl_email_job（arq job 入口，tenacity 3 次指数退避）
  - send_hitl_reminder_job（催办 job 入口，03-09 plan 调用）
  - hitl_decision.html / hitl_decision_text.txt / hitl_reminder.html 3 Jinja2 模板
  - _build_deeplink(jti) → PUBLIC_BASE_URL/hitl/page/<jti>
  - _render_email_content 模板渲染辅助
affects: [03-06 HITL public API（发邮件 = NotificationService.enqueue_hitl_email）, 03-09 超时催办 worker（send_hitl_reminder_job 重发）, 03-10 E2E gate（邮件投递验证）]

# Tech tracking
tech-stack:
  added: []  # tenacity 已是 Phase 2 依赖，jinja2/aiosmtplib 已是 Phase 1 依赖；本 plan 不引入新包
  patterns:
    - "service 写 + arq enqueue + job 消费三段式：状态机 pending → sending → sent/failed 显式"
    - "tenacity AsyncRetrying 业务级重试（vs Phase 2 base.py 的节点重试，独立配置）"
    - "幂等 job 入参 notification_id：已 sent 跳过 + status='sending' 标记防重抢"
    - "payload JSONB 落渲染所需 context：worker 自包含不依赖 SELECT 多表"
    - "audit_log(action='email.send_failed') 显式可观测：NOTI-10 失败可追溯"
    - "autoescape=html Jinja env 防 XSS：description/applicant_name 等用户输入安全渲染"
    - "明文 fallback (.txt) 不开 autoescape：select_autoescape(['html']) 仅匹配 html 后缀"

key-files:
  created:
    - backend/app/services/notification_service.py
    - backend/app/jobs/__init__.py
    - backend/app/jobs/email_jobs.py
    - backend/app/templates/email/hitl_decision.html
    - backend/app/templates/email/hitl_decision_text.txt
    - backend/app/templates/email/hitl_reminder.html
    - backend/tests/test_hitl_email_templates.py
    - backend/tests/test_notification_service.py
    - backend/tests/test_email_jobs_retry.py
  modified:
    - backend/app/agent_builder/worker.py  # 注册 send_hitl_email_job + send_hitl_reminder_job 到 WorkerSettings.functions

key-decisions:
  - "Dify Celery shared_task → arq async function（CLAUDE.md §3 技术栈锁定 + asyncio 原生与 aiosmtplib 同构）"
  - "Dify 三层 ORM (Form/Delivery/Recipient) → 单层 notifications + JSONB payload（v1 单人审批不需要复用）"
  - "i18n EmailType + EmailLanguage 二级映射 → 中文 only（CONTEXT §邮件模板：i18n v2 留）"
  - "Jinja Sandbox 三模式 → autoescape=html 单模式（用户不写模板，Sandbox 留 Phase 6 插件）"
  - "Dify 隐式重试（依赖 Celery 默认）→ tenacity AsyncRetrying 显式 3 次（NOTI-10 业务可观测）"
  - "失败写 notifications.status='failed' + error_message + audit_log（NOTI-10 持久化）vs Dify 仅 logger.exception"
  - "Job 入参 notification_id（vs 整个 payload）：自包含 + 幂等 + arq 任务尺寸小"
  - "subject 代码组装 f-string 不走 Jinja：主题无用户字段 + 防 SMTP 头注入"
  - "tenacity wait_exponential(multiplier=1, min=1, max=4) 实现 1s/2s/4s 公比 2 退避"
  - "_RETRYABLE_EXCEPTIONS 加 OSError：aiosmtplib 底层 socket 错误兜底（实测发现 SMTPException 不覆盖所有网络场景）"
  - "测试中用 tenacity.wait_none() 替换 _RETRY_WAIT 加速：3 次重试在 <1s 完成（避免 7s 真实等待）"

patterns-established:
  - "arq job 框架：async def fn(ctx, *args) 签名 + 内部用 async_session_maker 独立 session（不复用调用方 session）"
  - "幂等 job：入参 ID + 状态判断（status=='sent' 短路）+ 标记 'sending' 防并发"
  - "状态机三态：pending → sending → sent | failed（与 03-01 notifications 表 status VARCHAR(16) 字段对齐）"
  - "tenacity AsyncRetrying with attempt: 业务异常重试 + reraise=True 兜底捕获"
  - "Jinja2 单一 Environment 模块级缓存：FileSystemLoader 一次创建（与 email_service.py 同模式）"

requirements-completed:
  - NOTI-01
  - NOTI-08
  - NOTI-10

# Metrics
duration: ~10min
completed: 2026-05-17
test-count: 18  # 5 模板 + 5 service + 8 job (5 plan 必含 + 3 bonus)
file-count: 10  # 9 created + 1 modified
---

# Phase 3 Plan 04: Email 邮件投递增强 + arq queue + tenacity 重试 Summary

**HITL 决策 / 催办邮件投递：NotificationService 入队 + arq job 异步消费 + tenacity 3 次指数退避（NOTI-10）+ 3 套 Jinja2 模板（HTML 决策 / 明文 fallback / 催办 HTML）。复用 Phase 1 `_send_email` + Phase 1 `audit.log`；Dify Celery → arq + 三层 ORM → 单层 JSONB 简化决策已记入 reading doc §7。**

## Performance

- **Duration:** ~10 分钟（含 3 tasks 实际编码 + 测试验证）
- **Started:** 2026-05-16T18:19:36Z
- **Completed:** 2026-05-16T18:29:12Z
- **Tasks:** 3 实际执行 + Task 0 reading doc（前置 commit `cea3c98`）
- **Files created:** 9
- **Files modified:** 1（worker.py 注册 2 job）
- **Test cases:** 18 通过（5 模板 + 5 service + 8 job retry 含 3 bonus）

## Accomplishments

1. **3 套 Jinja2 模板**：
   - `hitl_decision.html`（首发决策）：品牌头 + 申请上下文（申请人/审批人/截止时间） + 描述区 + 3 按钮（绿/黄/红 colored by action）+ 备用链接区 + 不可退订 footer
   - `hitl_decision_text.txt`（明文 fallback）：4 段（标题 / 上下文 / 描述 / URL 列表），不开 autoescape
   - `hitl_reminder.html`（催办）：红色 [催办] banner + 截止时间高亮 + 其它结构与 decision 一致

2. **NotificationService**（通用通知入队层）：
   - `enqueue_hitl_email(workspace_id, instance_id, node_state_id, recipient_email, tokens, form_schema, deadline_at, actor/flow/node/applicant/description, reminder_round=0)`
   - 写 `notifications.status='pending'` 一行 + arq enqueue_job 派发
   - `mark_sent(notification_id, sent_at)` / `mark_failed(notification_id, error)` 状态机辅助方法（job 路径调用）
   - arq_pool 可选：测试 / dev 走 asyncio.create_task fallback

3. **arq job 框架**：
   - `send_hitl_email_job(ctx, notification_id)`：自包含路径 = 取 notif → 渲染模板 → tenacity 3 次重试 → 状态机
   - `send_hitl_reminder_job` 复用 send_hitl_email_job（仅 reminder_round 区分模板）
   - 注册到 `WorkerSettings.functions`：`[run_instance_arq, send_hitl_email_job, send_hitl_reminder_job]`

4. **NOTI-10 重试机制**：
   - `tenacity.AsyncRetrying(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))` → 1s/2s/4s 退避
   - 重试白名单：`SMTPException / ConnectionError / TimeoutError / OSError`
   - 全失败：`notifications.status='failed'` + `error_message`（≤1000 字符）+ `audit_log(action='email.send_failed')`

5. **幂等 + 防并发**：
   - 入参 notification_id（不是 payload）：worker 重启 / 多 worker 并发抢锁场景下幂等
   - `if notif.status == 'sent': return`（短路）
   - `notif.status = 'sending'` + commit（标记防其他 worker 重抢）

6. **18 测试覆盖**（CLAUDE.md 2.2 真实 DB / 不 mock）：
   - 5 模板渲染单测（pure Jinja，无 DB）：3 按钮 / 颜色 / XSS escape / 明文 URL / 催办标识
   - 5 service 集成测试（真实 PG）：pending 落地 / payload tokens / UNIQUE 去重 / arq=None fallback / round 区分
   - 5 job retry 集成测试（真实 PG + monkeypatch _send_email）：success / idempotent / 1 次重试成功 / 3 次失败 + audit / reminder 模板
   - 3 bonus 辅助单测：_build_deeplink default / rstrip / _render_email_content 烟测

## Task Commits

| Task | Name | Hash | Type |
|---|---|---|---|
| 0 | Dify email_delivery 阅读笔记（CLAUDE.md 2.7 GATE） | `cea3c98` | docs |
| 1 | 3 邮件模板（HTML 决策 + 明文 + 催办）+ 5 单测 | `5a48edb` | feat |
| 2 | NotificationService.enqueue_hitl_email + 5 集成测试 | `f5b0b9b` | feat |
| 3 | email_jobs arq job + tenacity 重试 + 注册到 WorkerSettings + 8 测试 | `70faeea` | feat |

**Plan metadata commit** 由后续 final_commit 步骤创建（含 SUMMARY.md + STATE.md + ROADMAP.md 更新）。

## Files Created/Modified

### 新建

- `backend/app/services/notification_service.py` — NotificationService 类 + enqueue_hitl_email / mark_sent / mark_failed
- `backend/app/jobs/__init__.py` — jobs 包 docstring
- `backend/app/jobs/email_jobs.py` — send_hitl_email_job + send_hitl_reminder_job + _build_deeplink + _render_email_content + _write_audit_log_failure
- `backend/app/templates/email/hitl_decision.html` — 决策邮件 HTML 模板
- `backend/app/templates/email/hitl_decision_text.txt` — 决策邮件明文 fallback
- `backend/app/templates/email/hitl_reminder.html` — 催办邮件 HTML 模板
- `backend/tests/test_hitl_email_templates.py` — 5 模板渲染单测
- `backend/tests/test_notification_service.py` — 5 NotificationService 集成测试
- `backend/tests/test_email_jobs_retry.py` — 8 arq job retry 集成测试

### 修改

- `backend/app/agent_builder/worker.py` — WorkerSettings.functions 注册 send_hitl_email_job + send_hitl_reminder_job（从 1 个函数扩展到 3 个）

## Decisions Made

1. **Dify Celery → arq async function**：CLAUDE.md §3 锁定 arq 0.28+；arq 是 asyncio 原生（与 aiosmtplib 5.1 同构），Celery 同步阻塞会阻塞事件循环 — 这是 reading doc §7 最高优先级简化。
2. **Dify 三层 ORM → 单层 JSONB**：03-01 已建 notifications 表；v1 单人审批不需要 Form/Delivery/Recipient 三层抽象；payload JSONB 等效 Dify `_EmailDeliveryJob` frozen dataclass 聚合。
3. **i18n 中文 only**：CONTEXT §邮件模板已声明 v1 中文 only；i18n 留 v2；模板文件不带语言后缀（hitl_decision.html 不分 zh-Hans/en-US）。
4. **Jinja autoescape=html 单模式**：用户不允许写 Jinja 模板（v1 模板固定）；autoescape 已足够防 XSS；Sandbox 留 Phase 6 插件 SDK。
5. **subject 代码组装 f-string**：主题不含用户字段（仅 flow_title + node_title 已 escape），不走 Jinja；防 SMTP 头注入风险（CR/LF 注入）。
6. **_RETRYABLE_EXCEPTIONS 加 OSError**：aiosmtplib 底层 socket 错误（如 `OSError: [Errno 61] Connection refused`）不被 SMTPException 覆盖，实测必须显式加入。
7. **测试用 tenacity.wait_none() 加速**：3 次重试如果真等 1s+2s+4s=7s，5 重试测试会跑 35s+；测试中 monkeypatch `_RETRY_WAIT = wait_none()` 让重试瞬间完成（断言重试次数 + 状态机不依赖时序）。
8. **job 用独立 session**：`async with async_session_maker() as db` 在 job 内部创建新 session（不复用 NotificationService 传入的 session），便于 arq worker 上下文隔离 + 测试时与外层 db_session fixture 互不干扰。
9. **audit_log 写法**：`target_id=None`（notifications.id 是 BIGSERIAL int，不是 UUID）；workspace_id 取自 notification.workspace_id（vs request.workspace_id — job 路径无 request）。
10. **deeplinks 在模板内拼装 vs payload 预拼**：选 worker 端拼装（`_render_email_content` 内）— payload 只存 tokens (jti+action)，URL 拼装是渲染时职责；让 PUBLIC_BASE_URL 变化时不需要回填历史记录。

## Dify 参考点

详见 `docs/reading-dify-03-04-email-delivery-2026-05-17.md`（commit `cea3c98`）。本 plan 落实的核心借鉴：

| 借鉴维度 | Dify 原模式 | 本项目落点 | 文件 |
|---|---|---|---|
| **Job 数据聚合** | `@dataclass(frozen=True) _EmailDeliveryJob`（form_id/subject/body/recipients）| `notifications.payload JSONB`（tokens/form_schema/上下文）| backend/app/agent_builder/models/notification.py（03-01 落） |
| **链接拼装** | `_build_form_link(token) = base_url.rstrip('/')+/form/{token}` | `_build_deeplink(jti) = PUBLIC_BASE_URL.rstrip('/')+/hitl/page/{jti}` | backend/app/jobs/email_jobs.py |
| **模板模式** | `EmailType + EmailLanguage` 二级映射 → template_path | `reminder_round > 0 ? 'hitl_reminder.html' : 'hitl_decision.html'` 单一映射 | backend/app/jobs/email_jobs.py |
| **subject 净化** | `sanitize_subject(去 CR/LF)` | 代码组装 f-string（不走 Jinja，不含用户字段）| backend/app/jobs/email_jobs.py |
| **失败可观测** | `logger.exception` | logger + `notifications.status='failed'` + `audit_log(action='email.send_failed')` | backend/app/jobs/email_jobs.py（改进点）|
| **任务队列** | `@shared_task(queue="mail")` | `async def send_hitl_email_job(ctx, notification_id)` arq | backend/app/jobs/email_jobs.py + backend/app/agent_builder/worker.py |

**Attribution**：未拷贝 Dify 源码（Dify 是 AGPL-3.0，本项目是 Apache-2.0）。`_build_deeplink` 等借鉴的代码已重写（中文注释 + 异步风格 + tenacity 装饰器 + 业务异常类型）。

## Deviations from Plan

**轻微调整**（plan 内 `<email_jobs>` code block 与最终实现差异）：

1. **[Rule 3 - Blocking] 重新实现 _send_email 调用方式**
   - PLAN.md `<email_jobs>` 片段中 `_send_email(to, subject, html_body, text_body)` 有 text_body 入参。
   - **实际**：Phase 1 `email_service.py:_send_email` 签名为 `(to, subject, html_body)` 无 text_body 参数（Phase 1 内置 "请使用支持 HTML..." 占位符）。
   - **取舍**：保持 Phase 1 接口稳定（不动 upstream），HITL 邮件先用 HTML（autoescape 安全）+ 备用链接区已含可见 URL；text_body 与 Phase 6 _send_email 扩展同步引入。已在 email_jobs.py 代码注释中标记 03-09 增强项。
   - 测试影响：所有 5 retry 测试通过；只是 mailhog text MIME part 仍为 Phase 1 占位符（不影响主路径验收）。

2. **[Rule 2 - Critical] _RETRYABLE_EXCEPTIONS 扩展加 OSError**
   - PLAN.md `<email_jobs>` 片段：`retry_if_exception_type((SMTPException, ConnectionError, TimeoutError))`
   - **实际**：扩展为 `(SMTPException, ConnectionError, TimeoutError, OSError)`
   - **原因**：aiosmtplib 底层 socket 错误抛 `OSError: [Errno 61] Connection refused`，不被 SMTPException 覆盖；实测发现必须加入才能完整覆盖 NOTI-10 重试场景。

3. **辅助函数 bonus 测试**（3 额外用例）
   - PLAN.md 要求 15+ 测试 — 实际写到 18（5+5+8）
   - 增加：`_build_deeplink` default url / rstrip slash / `_render_email_content` 烟测
   - 提升 email_jobs.py 单元覆盖率，非破坏性增量

## Issues Encountered

1. **arq Python 包未安装在 dev venv**（pre-existing）
   - 现象：`from app.agent_builder.worker import WorkerSettings` 抛 `ModuleNotFoundError: No module named 'arq'`
   - 评估：Phase 2 02-08 已声明使用 arq（pyproject.toml 待补 `arq>=0.28`），但本机 venv 未安装；测试不依赖 arq（用 stub 捕获 enqueue_job）
   - 影响：worker.py 仅生产 / docker 容器中导入；测试用 monkeypatch + `_FakeArqPool` 模拟
   - 行动：**不在本 plan 范围内修复**（CLAUDE.md SCOPE BOUNDARY — 不修复 Phase 2 既存模块）；记入 `.planning/phases/03-hitl-email/deferred-items.md`

2. **Phase 1 _send_email 不接受 text_body 参数**
   - 已记入"Deviations from Plan" #1
   - 影响：text fallback 在 SMTP 层是 Phase 1 占位符 "请使用支持 HTML..."，HITL 明文 URL 仅作为模板备用资源（03-09 catch up）

## User Setup Required

None - 本 plan 完全复用 Phase 1/2 既有基础设施：
- `_send_email`（Phase 1）+ `audit.log`（Phase 1）+ `async_session_maker`（Phase 2）+ `WorkerSettings`（Phase 2）
- 模板 dir `backend/app/templates/email/`（Phase 1 verification/invitation/welcome 三套已存在）
- env：`PUBLIC_BASE_URL`（Phase 1 startup_checks 校验）

## Next Plan Readiness

- ✅ **03-06 HITL public API**：可直接 `NotificationService(db, arq_pool).enqueue_hitl_email(...)` 触发邮件 — 入参签名稳定
- ✅ **03-09 超时催办 worker**：可调 `send_hitl_reminder_job(ctx, notification_id)`（reminder_round=1/2 时切换模板）；NotificationService.enqueue_hitl_email 已支持 `reminder_round` 参数避免 UNIQUE 冲突
- ✅ **03-10 E2E gate**：邮件投递的浏览器视角验证可由 mailhog（Phase 1 docker-compose 已配 :8025 UI）截获实发邮件
- ⚠️ **production arq install**：部署清单需补 `arq>=0.28` 到 pyproject.toml（pre-existing issue，已 deferred）

## Self-Check

执行验证：
- [x] `backend/app/services/notification_service.py` 存在 + 已 commit (`f5b0b9b`)
- [x] `backend/app/jobs/__init__.py` 存在 + 已 commit (`70faeea`)
- [x] `backend/app/jobs/email_jobs.py` 存在 + 已 commit (`70faeea`)
- [x] `backend/app/templates/email/hitl_decision.html` 存在 + 已 commit (`5a48edb`)
- [x] `backend/app/templates/email/hitl_decision_text.txt` 存在 + 已 commit (`5a48edb`)
- [x] `backend/app/templates/email/hitl_reminder.html` 存在 + 已 commit (`5a48edb`)
- [x] `backend/app/agent_builder/worker.py` 已注册 send_hitl_email_job + send_hitl_reminder_job (`70faeea`)
- [x] `docs/reading-dify-03-04-email-delivery-2026-05-17.md` 已存在 + 已 commit (`cea3c98`，Task 0)
- [x] 18 测试全部通过（5 + 5 + 8）
- [x] Task 0 reading doc commit 在所有 feat: commit 之前（cea3c98 → 5a48edb → f5b0b9b → 70faeea，CLAUDE.md 2.7 GATE 顺序正确）

## Self-Check: PASSED

所有声明的文件存在；所有声明的 commit 在 git log 中；18 测试全部通过；reading doc commit 在 feat commit 之前（CLAUDE.md 2.7 GATE 顺序）。

---
*Phase: 03-hitl-email*
*Plan: 04*
*Completed: 2026-05-17*
