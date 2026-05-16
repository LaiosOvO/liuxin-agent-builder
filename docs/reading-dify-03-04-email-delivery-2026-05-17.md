# Dify 阅读笔记 — Email Delivery（mail_human_input_delivery_task + email_template_renderer）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> 适用 plan: 03-04 邮件投递 + arq queue + tenacity 重试

---

## 1. 项目概述（一句话）

Dify 的 HITL 邮件投递模块 `api/tasks/mail_human_input_delivery_task.py` 用 Celery `@shared_task(queue="mail")` 异步分发邮件，按 `HumanInputForm → HumanInputDelivery → HumanInputFormRecipient` 三层数据模型聚合邮件任务，调用 `mail.send(to, subject, html)` 真正发送；模板由 `libs/email_template_renderer.py` 用 Jinja2 SandboxedEnvironment 渲染。

---

## 2. 技术栈（关键技术选择）

| 维度 | Dify | 本项目 |
|---|---|---|
| 任务队列 | Celery `@shared_task(queue="mail")` | **arq 0.28**（CLAUDE.md §3 锁定，禁止 Celery） |
| SMTP | `extensions.ext_mail.mail.send` 抽象层（多 driver: smtp/sendgrid/resend） | aiosmtplib 5.1.0 单一 driver（Phase 1 _send_email 已封装） |
| 模板渲染 | Jinja2 `ImmutableSandboxedEnvironment` + 超时（防 SSRF/CPU 耗尽） | Jinja2 `FileSystemLoader + autoescape=html` （Phase 1 已建，sandbox 由 Phase 6 插件机制提供） |
| i18n | `EmailLanguage(zh-Hans / en-US)` + 双 template 路径 | **v1 中文 only**（CONTEXT §邮件模板：i18n 留 v2） |
| 重试 | **无显式重试**（依赖 Celery worker 默认 retry 策略） | **tenacity AsyncRetrying** 3 次指数退避（1s/2s/4s）— NOTI-10 要求 |
| 失败追溯 | `logger.exception` + 无 DB 状态机 | **写 notifications.status='failed' + error_message + audit_log** |

---

## 3. 架构要点（核心架构模式）

### 3.1 三层数据模型 → 邮件 Job 聚合

```
HumanInputForm（表单元数据）
  └── HumanInputDelivery（通道 = EMAIL/SMS/IM；channel_payload JSON）
        └── HumanInputFormRecipient（收件人 + access_token）

任务函数 dispatch_human_input_email_task(form_id):
  1. session.get(HumanInputForm, form_id)
  2. session.scalars(select(Delivery).where(form_id=..., type=EMAIL))
  3. for each delivery: scalars(select(Recipient).where(delivery_id=...))
  4. 聚合为 _EmailDeliveryJob dataclass(frozen=True)
       fields: form_id / subject / body / form_content / recipients[]
  5. for each recipient in job.recipients:
       form_link = f"{base_url}/form/{token}"
       body = render_body(job.body, form_link, variable_pool)
       subject = sanitize_subject(job.subject)
       mail.send(to, subject, html=body)
```

### 3.2 模板渲染 `render_email_template`

```python
# libs/email_template_renderer.py
def render_email_template(template: str, substitutions: Mapping[str, str]) -> str:
    mode = dify_config.MAIL_TEMPLATING_MODE  # UNSAFE / SANDBOX / DISABLED
    if mode == UNSAFE:
        return render_template_string(template, **substitutions)  # Flask 直接渲染
    if mode == SANDBOX:
        env = SandboxedEnvironment(timeout=timeout)  # 子类 ImmutableSandboxedEnvironment
        tmpl = env.from_string(template)
        return tmpl.render(substitutions)
    if mode == DISABLED:
        return template  # 不渲染（仅占位符替换）
```

3 模式可选：production 用 SANDBOX（防 Jinja SSTI），dev 用 UNSAFE（性能优先）。

### 3.3 i18n 抽象 `email_i18n.py`

```python
class EmailType(StrEnum):
    RESET_PASSWORD, INVITE_MEMBER, EMAIL_CODE_LOGIN, ...

class EmailLanguage(StrEnum):
    EN_US = "en-US"
    ZH_HANS = "zh-Hans"

@dataclass(frozen=True)
class EmailTemplate:
    subject: str
    template_path: str
    branded_template_path: str
```

每个 EmailType 对应 (en-US, zh-Hans) 两套 template_path；branded_template_path 用于企业版自定义品牌；从 `language_code` 转换默认 fallback 到 EN_US。

---

## 4. 可借鉴的设计模式（具体文件路径 + 模式名）

### 4.1 ✅ Pattern A: `_EmailDeliveryJob` dataclass(frozen=True) 聚合

**Dify 源码**：`api/tasks/mail_human_input_delivery_task.py:31-43`

```python
@dataclass(frozen=True)
class _EmailDeliveryJob:
    form_id: str
    subject: str
    body: str
    form_content: str
    recipients: list[_EmailRecipient]
```

**借鉴点**：Job 数据结构不可变，便于多 worker 并发 enqueue；recipients 是 list 内层 `_EmailRecipient(email, token)` 也是 frozen dataclass。

**本项目应用**：`NotificationService.enqueue_hitl_email` 入参直接是 service 方法签名（不需要 dataclass），但 arq job 入参带 `notification_id` 让 worker 自行 SELECT；payload JSONB 列已存渲染所需内容（tokens/form_schema/...），等同 dataclass 落 DB。

### 4.2 ✅ Pattern B: `_build_form_link(token)` 拼装函数

**Dify 源码**：`api/tasks/mail_human_input_delivery_task.py:46-48`

```python
def _build_form_link(token: str) -> str:
    base_url = dify_config.APP_WEB_URL
    return f"{base_url.rstrip('/')}/form/{token}"
```

**借鉴点**：base_url 从 config 读 + `rstrip('/')` 防双斜杠 + 路径前缀固定。

**本项目应用**：
```python
def _build_deeplink(jti: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/hitl/page/{jti}"
```

差异：Dify 用 `APP_WEB_URL` 配置项；我们用 `PUBLIC_BASE_URL` env（Phase 1 NET-01 已固化）。路径 `/hitl/page/<jti>` 与 03-06 plan 公网 API 对齐。

### 4.3 ✅ Pattern C: 模板模式 + 多通道占位

**Dify 源码**：`api/libs/email_i18n.py` `EmailType` enum + `(EmailType, EmailLanguage) → EmailTemplate` 二级映射

**借鉴点**：明确的"邮件类型枚举" + "类型 → 模板路径"映射，避免在业务代码中硬编码模板路径。

**本项目应用**：v1 简化 — 模板文件名直接由 `reminder_round > 0 ? 'hitl_reminder.html' : 'hitl_decision.html'` 决定（无 i18n）。i18n 留 v2。

### 4.4 ✅ Pattern D: `sanitize_subject` 主题净化

**Dify 源码**：`api/core/workflow/human_input_adapter.py` `EmailDeliveryConfig.sanitize_subject`

**借鉴点**：邮件主题去掉换行符（防 SMTP 头注入）+ 长度限制。

**本项目应用**：subject 由代码组装（`f"审批待办：{flow_title} - {node_title}"`），flow_title 入库时已限制长度；Jinja2 autoescape 处理 HTML body 的 XSS；subject 不走模板渲染，无需 sandbox。

### 4.5 ✅ Pattern E: 失败 logger.exception + 不中断 worker

**Dify 源码**：`mail_human_input_delivery_task.py:190-192`

```python
except Exception:
    logger.exception("Send human input email failed, form_id=%s", form_id)
```

Celery 任务异常会自动重试（依赖 broker 配置）。

**本项目改进**：除了 logger.exception，额外写 `notifications.status='failed' + error_message + audit_log`（NOTI-10 显式可观测），加 tenacity 3 次指数退避后才进入 failed 终态。

### 4.6 ⚠️ Pattern F: 三表分离的反向取舍

**Dify**：Form / Delivery / Recipient 三表 + 每次发送时 JOIN 三表聚合。
**本项目**：03-01 已将 HITL 数据合并为 `hitl_tokens`（jti+actor+action）+ `notifications`（投递记录）两表。

**为什么我们简化**：v1 单人审批 + 单通道（email）+ form_schema 已在 node_states.payload 里（02-01 已建）。Dify 三表是为应对企业版多收件人 + 多通道 + 表单复用三层需求；我们 phase 4+ 加 IM 时仍可在 notifications.channel 列扩展不需要拆表。

---

## 5. 与 hr/offboarding-flow 对照

| 维度 | hr 项目 | 本项目 |
|---|---|---|
| 邮件路径 | `apps/notifier-mail` Cloudflare Workers（基于 mailchannels API） | `backend/app/services/email_service.py` + aiosmtplib（自管 SMTP） |
| 重试 | mailchannels API 内置重试 + DLQ | tenacity AsyncRetrying 3 次指数退避（应用层显式） |
| 模板 | inline string template | Jinja2 文件模板（hitl_decision.html / hitl_reminder.html） |
| 任务队列 | Cloudflare Queues | arq + Redis |

**hr 的关键启发**：Mattermost 卡片消息 + 邮件双通道并行 — 我们 Phase 4 接入 IM 时复用 `NotificationService.enqueue_hitl_notifications`（channels=['email', 'feishu', ...]）。

---

## 6. 与本项目的关系（如何应用到当前 plan）

| Dify 模式 | 本项目落点 | 文件 |
|---|---|---|
| `_EmailDeliveryJob` frozen dataclass | `notifications.payload JSONB`（tokens + form_schema + deadline + 上下文） | backend/app/agent_builder/models/notification.py（03-01 已建） |
| `dispatch_human_input_email_task(form_id)` Celery shared_task | `send_hitl_email_job(ctx, notification_id)` arq function | backend/app/jobs/email_jobs.py（**本 plan 新建**） |
| `_build_form_link(token)` | `_build_deeplink(jti)` | backend/app/jobs/email_jobs.py |
| `mail.send(to, subject, html)` | `_send_email(to, subject, html_body, text_body)`（Phase 1 既存 + 本 plan 扩展 text_body） | backend/app/services/email_service.py |
| `render_email_template(template, substitutions)` | `_get_jinja_env().get_template(name).render(**ctx)` | backend/app/jobs/email_jobs.py |
| sanitize_subject | 代码组装主题，不走 Jinja（subject 无 XSS 风险） | backend/app/jobs/email_jobs.py |

---

## 7. 我们的简化决策（vs Dify 复杂度）

**强制 §7 小节** — CLAUDE.md 2.7 reading-first 要求显式记录"为什么不照搬 Dify"。

| 简化点 | Dify | 本项目 | 理由 |
|---|---|---|---|
| **队列框架** | Celery `@shared_task(queue="mail")` | **arq 0.28** `async def send_hitl_email_job(ctx, ...)` | CLAUDE.md §3 技术栈锁定，arq 是 asyncio 原生（与 aiosmtplib 同构）；Celery 同步阻塞会阻塞事件循环 |
| **数据模型** | 三层 ORM (Form / Delivery / Recipient) | **单层** notifications + JSONB payload | 03-01 已建；v1 单人审批不需要 form/recipient 复用 |
| **i18n** | EmailType + EmailLanguage 二级映射 | **中文 only**（hitl_decision.html / hitl_reminder.html / hitl_decision_text.txt 3 个文件） | CONTEXT §邮件模板：i18n v2；Dify 多语言是企业版价值，我们 v1 单租户中文 only |
| **模板模式** | Sandbox / Unsafe / Disabled 三模式 | **autoescape=html** 单模式 | autoescape 防 XSS 已足够（不允许用户写 Jinja 模板）；Sandbox 留 Phase 6 插件 SDK |
| **重试** | 无显式（依赖 Celery 默认） | **tenacity AsyncRetrying** 3 次（1s/2s/4s） | NOTI-10 显式要求 + 业务可观测性 |
| **失败追溯** | logger.exception | logger + **notifications.status='failed' + error_message** | NOTI-10 要求"失败状态可查"；后续 03-09 admin 告警 hook 用此字段 |
| **幂等** | 无（每次 enqueue 都全量发送） | arq job 入参 notification_id；**已 sent 则跳过** | 防多 worker 并发 / 重启时重复发送 |
| **变量池** | VariablePool 解析 Jinja 内嵌变量（业务可配模板） | **模板字段固定**（flow_title/node_title/applicant_name/...） | v1 用户不可自定义邮件模板，固定字段更安全 |
| **subject 模板化** | EmailDeliveryConfig.sanitize_subject + Jinja 渲染 | **代码组装** f-string（不走 Jinja） | 主题不需要用户字段，固定格式 + flow_title 已 escape |

**结论**：本 plan 实现 = Dify 三层数据模型 → 单层 + Celery → arq + 多 i18n → 中文 only + 隐式重试 → 显式 tenacity 重试。**借鉴的是设计模式 / 字段命名 / 链接拼装思路，不是源码**。

---

## Attribution

未拷贝 Dify 源码（Dify 是 AGPL-3.0，本项目是 Apache-2.0）。所有借鉴的代码（`_build_form_link`、`_EmailDeliveryJob` 等）已在本 plan 中**重写**（中文注释 + asyncio 风格 + tenacity 装饰器）。

---

## 验证清单（本 plan 完工时回查）

- [ ] `_build_deeplink(jti)` 函数与 Dify `_build_form_link` 等价但路径前缀不同
- [ ] arq job 注册到 WorkerSettings.functions
- [ ] 模板文件 3 个：hitl_decision.html / hitl_decision_text.txt / hitl_reminder.html
- [ ] tenacity AsyncRetrying 包裹 `_send_email`，指数退避 1s/2s/4s
- [ ] 失败路径写 notifications.status='failed' + error_message
- [ ] 15+ 测试通过（5 模板 + 5 service + 5 job retry）
- [ ] SUMMARY.md 含 "## Dify 参考点" 小节回指本 reading doc

---
*Plan: 03-04 Email Delivery + arq queue + tenacity retry*
*Reading completed: 2026-05-17*
