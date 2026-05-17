# Dify 阅读笔记 — 多通道并发投递（Plan 04-10）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> Plan: 04-10（NotificationService 多通道 fan-out — NOTI-08）

## 项目概述（一句话）

Dify 的 HumanInput 邮件投递模块（`api/tasks/mail_human_input_delivery_task.py`）展示了**单通道（email-only）投递链路**的最小实现 — 一个 Celery `@shared_task` 负责加载 Form / Delivery / Recipient 三层关联表、为每个 recipient 渲染表单链接 + 模板正文 + 发送邮件；本 plan 要把这种单通道模式扩展为**多通道 fan-out**（同时通过 email + 5 家 IM provider 投递）。

## 技术栈对比

| 维度 | Dify 现状 | 本 plan 04-10 |
|------|----------|---------------|
| 通道数 | 仅 email | email + feishu + wecom + dingtalk + slack + mattermost + webhook（7 个） |
| Task 框架 | Celery `@shared_task(queue="mail")` | arq async function（与 Phase 3 03-04 一致） |
| 数据模型 | Form / Delivery / Recipient 三层 ORM | 单表 notifications（Plan 03-01）+ JSONB payload |
| Fan-out 时机 | dispatch task 内逐 recipient 循环 send | NotificationService.enqueue_hitl_multichannel 一次 commit → 每 channel 入队 |
| Recipient 解析 | EmailDeliveryConfig + variable_pool 渲染 | 用户表 `im_bindings` JSONB 字段查映射 `{feishu: ou_xxx, wecom: ...}` |
| 失败模型 | try/except 整 task 一锅 logger.exception | per-channel try/except + per-channel notifications.status |
| 去重 | 业务层无显式约束（依赖 dispatch 调用方） | DB UNIQUE (instance, node_state, channel, recipient, reminder_round) |

## 架构要点

### Dify 单通道架构（参考）

```
dispatch_human_input_email_task(form_id) [Celery task]
    │
    ├─ Session.get(HumanInputForm, form_id)
    ├─ _load_email_jobs(session, form)
    │     │
    │     ├─ SELECT HumanInputDelivery WHERE form_id=:fid AND method=EMAIL
    │     ├─ for delivery in deliveries:
    │     │     ├─ SELECT HumanInputFormRecipient WHERE delivery_id=:did
    │     │     └─ for recipient in recipients:
    │     │           → _EmailRecipient(email, token)
    │     └─ jobs.append(_EmailDeliveryJob(form_id, subject, body, recipients))
    │
    ├─ _load_variable_pool(workflow_run_id)
    │
    └─ for job in jobs:
          for recipient in job.recipients:
              form_link = _build_form_link(recipient.token)
              body = _render_body(template, form_link, var_pool)
              subject = sanitize_subject(template)
              mail.send(to=recipient.email, subject, html=body)  ← 同步阻塞
```

**特征**：
- task 入口直接是 `form_id`（粗粒度）
- 三层 JOIN 查询解决"一个 form 有多个 delivery、一个 delivery 有多个 recipient"
- 失败整 task 一起 catch（**单个 recipient 失败会污染其他 recipient**）
- 没有 channel concept — 通道在 Delivery.delivery_method_type 字段（EMAIL/...）

### 本 plan 04-10 多通道 fan-out 架构

```
NotificationService.enqueue_hitl_multichannel(
    channels=['email', 'feishu', 'wecom'],
    recipient_email='user@example.com',
    recipient_im_bindings={'feishu': 'ou_xxx', 'wecom': 'WuPing'},
    ...
)
    │
    ├─ for channel in channels:
    │     ├─ if channel == 'email': recipient = recipient_email
    │     ├─ else: recipient = recipient_im_bindings.get(channel)
    │     │       if not recipient: log.warning + continue  ← 缺 binding 跳过
    │     ├─ payload = self._build_hitl_payload(tokens, schema, ...)
    │     └─ notif = Notification(workspace_id, channel, recipient, status='pending', payload)
    │
    ├─ db.flush + db.commit  ← 所有 notifications 行一次性提交
    │
    └─ for notif in created:  ← commit 后才 enqueue（防 worker 抢跑事务未提交）
          job_name = 'send_hitl_email_job' if email else 'send_hitl_card_job'
          arq.enqueue_job(job_name, str(notif.id))
```

**关键改进**：
- **粒度细化**：每个 (channel, recipient) 对应一行 notifications + 一个 arq job（独立 status + 独立 retry）
- **失败隔离**：per-notification status，单通道失败不阻塞其他通道
- **事务边界**：所有 INSERT 在一个事务内 commit，再 enqueue jobs（Pitfall 2 防止 worker 抢跑事务未提交的行）
- **idempotent**：UNIQUE (instance, node_state, channel, recipient, reminder_round) 防多 worker 重发
- **声明式 channel**：通过 schema enum + DSL 节点 config 显式声明，不依赖 Delivery method 字段

## 可借鉴的设计模式

### 模式 1: Recipient 解析延迟到投递阶段

**Dify 源码**（mail_human_input_delivery_task.py:51-59）：
```python
def _parse_recipient_payload(payload: str) -> tuple[str | None, RecipientType | None]:
    try:
        payload_dict: dict[str, Any] = json.loads(payload)
    except Exception:
        logger.exception("Failed to parse recipient payload")
        return None, None
    return payload_dict.get("email"), payload_dict.get("TYPE")
```

Dify 在 task 内解析 recipient（JSON 字段），允许 Form 创建时不强制 recipient 校验。

**应用到本 plan**：
- `im_bindings: JSONB` 字段（已在 `users.im_bindings`）也走运行时解析
- `recipient_im_bindings.get(channel)` 缺失返回 None → log.warning + 跳过该 channel（不抛错，与 Dify recipient_type 不匹配跳过策略一致）
- **本 plan 改进**：缺失日志含足够上下文（actor email + instance_id + channel）便于排查

### 模式 2: Transaction 边界与 task enqueue 顺序

**Dify 源码**（mail_human_input_delivery_task.py:154-167）：
```python
with _open_session(session_factory) as session:
    form = session.get(HumanInputForm, form_id)
    if form is None:
        return
    ...
    jobs = _load_email_jobs(session, form)
# session 退出 + 自动 commit ← 在 session 外才 mail.send
variable_pool = _load_variable_pool(form.workflow_run_id)
for job in jobs:
    for recipient in job.recipients:
        ...
        mail.send(...)  ← 这里已不在事务中
```

Dify 显式在 `with session:` 外执行 `mail.send`，避免在事务内发邮件（防"事务回滚但邮件已发"的悬空状态）。

**应用到本 plan**：
- `enqueue_hitl_multichannel` 内先 `db.add(notif)` × N + `db.flush + db.commit`
- **commit 之后**才循环 `arq.enqueue_job`
- 这样保证：
  - worker 不会读到事务未提交的行（Postgres MVCC 隔离已保证；显式 commit 是更强保证）
  - 即使 enqueue_job 失败（Redis 抖动），notifications 行已落地，可由 cron scan + 重发机制兜底
  - 即使 commit 后某次 enqueue_job 失败，前面的 enqueue 已完成（fail-fast 而非 all-or-nothing）

### 模式 3: 统一 dispatch 入口 + 内部 dispatch 子任务

**Dify 模式**：单一 task 入口（`dispatch_human_input_email_task`）处理整批，内部 for loop 调 mail.send。

**本 plan 改进**：拆分为
- 入队层：`enqueue_hitl_multichannel`（同步 + 事务）创建 N 行 notifications + N 个 arq job
- 工作层：`send_hitl_email_job` / `send_hitl_card_job`（异步 worker）独立处理每行

**为什么拆**：
- arq job 自带重试机制（tenacity 1s/2s/4s × 3），不需要 Dify 在 task 内手写 retry
- 单个 job 失败不影响其他 job（Dify 是 task 级一锅炒）
- worker 并发度可独立 scale（多 IM 通道共享一个 worker pool 不同 channel）

### 模式 4: 借鉴 Dify "no recipients then continue" 容错

**Dify 源码**（mail_human_input_delivery_task.py:88-89）：
```python
if not recipient_entities:
    continue
```

**应用到本 plan**：
- 如果某 channel 的 binding 缺失，**continue 跳过该 channel** 但不影响其他 channel
- 如果 channels 全部缺 binding（最差情况），返回空 list（调用方可决策是否报错）

### 模式 5: UNIQUE 约束去重（Phase 3 已落，本 plan 复用）

**Dify 没有**显式 UNIQUE 约束 — 依赖业务层 dispatch 调用方不重复触发。

**本 plan 已有**（Plan 03-01 notifications 表 + Plan 03-04 enqueue_hitl_email 已验证）：
```sql
CONSTRAINT uq_notifications_dedup UNIQUE (instance_id, node_state_id, channel, recipient, reminder_round)
```

- **多通道扩展是 channel 维度的去重**（同一 (instance, node_state, recipient) 在不同 channel 不冲突）
- 多 worker 并发抢同一通道同一 recipient 时第二次写入触发 IntegrityError，调用方应 rollback（已在 NotificationService 内处理）

## 与本项目的关系

### 直接应用

1. **enqueue_hitl_multichannel 设计**（plan §multichannel_design）：
   - 模式 2（事务边界）→ commit 后才 enqueue_job
   - 模式 1（recipient 解析延迟）→ im_bindings.get(channel) 缺失跳过
   - 模式 3（拆分入队 / 工作层）→ 写 N 行 → enqueue N 个 job → worker 独立处理
   - 模式 5（UNIQUE 去重）→ 复用 Phase 3 已建约束

2. **enqueue_generic_im_card 设计**（plan §multichannel_design）：
   - 与 `enqueue_generic_email`（已存在）平行，仅 channel 不同
   - payload 极简（subject + body + recipient_im，无 tokens / form_schema）
   - 复用 send_hitl_card_job worker（其 payload 处理可向后兼容 — generic=True 走简化路径）

3. **NotificationNodeExecutor 扩展**（plan §node_extension_design）：
   - 借鉴 Dify "for job in jobs: for recipient in job.recipients" 嵌套循环
   - 但平铺为 "for channel in channels: for recipient in normalized_recipients"
   - 节点层 try/except per recipient 防单封失败阻塞（与 Phase 3 03-05 现状一致）

### 不复用 Dify 的部分

| 不用 | 原因 |
|------|------|
| Form / Delivery / Recipient 三层 ORM | 本项目 v1 单表 notifications + JSONB（Plan 03-04 已确立） |
| Celery `@shared_task` + `queue="mail"` | 本项目用 arq（CLAUDE.md §3 锁定） |
| `_render_body` Markdown 渲染 | 本项目 Jinja2 autoescape=html（Plan 03-04 已确立） |
| `EmailDeliveryConfig.sanitize_subject` | 本项目代码层 CR/LF 净化（email_jobs.py 已落） |
| `_load_variable_pool` | 本项目走 LangGraph state（节点配置已渲染） |
| `mail.is_inited()` 早退检查 | 本项目 SMTP / IM provider 在 startup_checks 校验 |

### Per channel 失败状态独立

Dify 单 task 失败 → 整 task fail。本 plan 改进：
- 每个 channel 写一行 notifications，独立 status
- worker 处理某行失败 → 仅该行 status='failed'，其他 channel 不受影响
- 测试用例 `test_multichannel_skip_channel_without_binding` 验证此独立性

### Reading doc 是 Plan 04-10 的 Task 0 commit gate

按 CLAUDE.md §2.7 "Reference-First" 规则：本 doc 必须 commit 之后才能开始 Task 1+ 写代码。CI 可机械化检查 commit log：
- `docs/reading-dify-04-10-multichannel-2026-05-17.md` commit 必须在所有 `(feat|refactor)\(04-10\):` commit 之前

## 关键决策（基于阅读结果）

1. **复用 Phase 3 NotificationService 类**（不拆新 service）— enqueue_hitl_email / enqueue_generic_email 保留向后兼容，新增 enqueue_hitl_multichannel 和 enqueue_generic_im_card
2. **不在事务内 enqueue_job** — Dify 模式 + 本项目 Pitfall 2 防护
3. **缺 binding 跳过 + warning**（不抛错）— 用户可能只为部分 channel 配置了 IM 账号
4. **Per channel notification row** — 失败状态独立，便于运维追溯
5. **schema 加 channels enum**：7 个值（email + 6 个 IM）— hitl_schema + notification_schema 都加
6. **向后兼容**：现有 DSL 无 channels 字段 → 默认 ['email']，Phase 3 测试 100% 通过

## 许可证说明

Dify 是 **AGPL-3.0**，本项目 agent-builder 是 **Apache-2.0**。本 doc 仅借鉴**设计模式 / 数据结构思路 / 边界处理考虑**，**不复制 Dify 源码**。所有实现在 `backend/app/services/notification_service.py` 内独立编写。

---

*Reading doc — Plan 04-10 Task 0*
*Completed: 2026-05-17*
