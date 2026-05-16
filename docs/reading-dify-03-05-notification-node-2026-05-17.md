# Dify 阅读笔记 — Notification 节点（独立通知节点 NODE-07）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit `e7e6fe88`, local clone `/Users/admin/ai/ref/dify/repo/`)
> Stars: ~141k
> Plan: 03-05（独立 Notification 节点 — NODE-07 / NOTI-01）

---

## 1. 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 工作流平台，其工作流引擎用类型化节点（agent / tool / knowledge_index / trigger_webhook / ...）构建 DAG。**Dify 并未提供"独立的 Notification 节点"**：所有通知能力（邮件、IM 卡片、超时提醒）都耦合在 HITL（HumanInputForm）的投递链路里，作为表单递交的副作用一并触发。

## 2. 技术栈（关键技术选择）

| 维度 | Dify 实现 | 本项目 03-05 选择 |
|---|---|---|
| 节点基类 | `graphon.nodes.base.node.Node[NodeData]`（带泛型 NodeData） | `BaseNodeExecutor` 抽象类（Plan 02-04 落） |
| 节点注册 | `BuiltinNodeTypes` 枚举 + `_NODE_TYPE_CLASSES` dict | 手动 `NODE_EXECUTORS["notification"] = NotificationNodeExecutor` |
| 节点行为 | `_run() -> Generator[NodeEventBase, None, None]`（流式事件） | `async def execute(config, state) -> dict`（一次返回） |
| 通知触发 | Celery `@shared_task(queue="mail")` 在表单递交后 apply_async | arq `enqueue_job("send_hitl_email_job", ...)`（Plan 03-04 已落） |
| 模板渲染 | `EmailDeliveryConfig.render_body_template`（变量池 + Markdown）| Jinja2 `select_autoescape(['html'])`（autoescape 防 XSS） |
| 失败处理 | `logger.exception` 即结束 | `failed_count + 1` 写 state，graph **不阻断** |

## 3. 架构要点（简图）

### 3.1 Dify HumanInput 投递链（耦合模式）

```
HumanInputForm 节点 (_run)
   │
   ├─ 写 HumanInputForm + HumanInputDelivery + HumanInputFormRecipient（三表）
   │
   ├─ apply_async(dispatch_human_input_email_task, kwargs=...)
   │       │
   │       └── Celery worker
   │             ├─ _load_email_jobs(session, form): SELECT 3 表组装 _EmailDeliveryJob list
   │             ├─ render_body_template(body, url=form_link, variable_pool)
   │             └─ mail.send(...)
   │
   └─ raise GraphInterrupt(HumanInputRequired)  ← graph 暂停
                                  ↑
       通知发送是"递交副作用"，与节点暂停在同一节点函数内
```

**关键发现**：Dify 的通知能力**不是独立节点**，而是 HITL 节点 `_run` 在抛 `HumanInputRequired` 之前的副作用调用。如果用户想"只发通知不暂停 graph"，Dify 没有原生支持，得自己 plumb（如 Webhook 节点 + 业务邮件后端）。

### 3.2 本项目 NotificationNode（解耦模式）

```
NotificationNodeExecutor.execute(config, state)
   │
   ├─ Jinja 渲染 subject/body/recipients (BaseNodeExecutor._render_config)
   │       上下文 = state（可引用 {{ start.applicant.email }}）
   │
   ├─ 过滤无效 email（不含 @ 直接跳过，不抛错）
   │
   ├─ for recipient in recipients:
   │     try:
   │         notif = await NotificationService.enqueue_generic_email(...)   # 03-04 已建底层
   │         sent_count += 1
   │     except Exception:
   │         failed_count += 1                                                # 不阻断
   │
   └─ return {self.node_id: {sent_count, failed_count, notification_ids}}    # 写 state
              ↓
       graph 继续走 next 节点（不 interrupt，不创建 hitl_token，不进入催办循环）
```

## 4. 可借鉴的设计模式

| 借鉴维度 | Dify 原模式 | 本项目落点 | 文件 |
|---|---|---|---|
| **节点 schema 注册** | `BuiltinNodeTypes.HUMAN_INPUT_FORM` 枚举 + JSON Schema | `NODE_SCHEMAS["notification"] = (NOTIFICATION_NODE_SCHEMA, NOTIFICATION_OUTPUT_FIELDS)` | `backend/app/agent_builder/workflow/node_schemas/notification_schema.py` |
| **多通道扩展位** | `EmailDeliveryMethod / WebhookDeliveryMethod` 多种 channel 抽象 | `channels: ["email"]` schema 字段（Phase 3 仅 email，Phase 4 扩展 feishu/wechat/dingtalk/slack/...） | `notification_schema.py` enum 字段 |
| **入队 + 异步消费** | Celery `mail` queue + `_load_email_jobs` 自包含 dataclass | NotificationService.enqueue_generic_email + arq `send_hitl_email_job` 复用 03-04 框架 | `services/notification_service.py` |
| **Jinja 模板渲染** | `EmailDeliveryConfig.render_body_template` + `render_markdown_body` | `_render_config` 递归渲染 + `generic_notification.html` 通用模板（autoescape=html） | `BaseNodeExecutor._render_config` + `templates/email/generic_notification.html` |
| **email 列表 + token 链路** | `HumanInputFormRecipient.access_token` 一对一 | NotificationNode 不创建 token（不需要回调），recipients 直接是邮箱字符串 | （NotificationNode 简化点） |

## 5. 与本项目的关系（如何应用到当前 plan）

1. **节点结构**：照搬 Dify "节点类 + 类型枚举 + JSON Schema" 三件套，但简化为"节点类（NotificationNodeExecutor） + 注册表（NODE_EXECUTORS） + Schema（notification_schema.py）"。
2. **payload 数据**：借鉴 Dify `_EmailDeliveryJob @dataclass(frozen=True)` 把所有渲染所需字段聚合的思路，本项目复用 03-04 NotificationService 已建的 `notifications.payload JSONB`（subject/body/recipient 三件套）。
3. **Jinja 变量插值**：完全照搬 BaseNodeExecutor 已实现的 `_render_config` 递归 Jinja 渲染（02-04 已建）— 用户写 `{{ start.applicant.email }}` 即可在 recipient 字段引用 Start 节点输出。
4. **复用 03-04 NotificationService.enqueue_hitl_email 的入队基础设施**：但 HITL 邮件需要 `tokens / form_schema / actor_name / deadline_at`，Notification 节点不需要这些（无 token 无表单无截止）。所以 **新增 NotificationService.enqueue_generic_email** 方法，参数只要 `recipient_email / subject / body`，复用底层 arq 入队 + status 状态机。
5. **不创建 hitl_token + 不进入催办循环**：channel='email' + reminder_round=0（**永远是 0**，不参与 NOTI-09 催办 worker 的扫描），所以即使 send_hitl_email_job 接到这条 notification，也只发一次（无重试，无升级）。

## 6. 实现取舍清单

- [x] **不暂停 graph**：execute 返回后 graph 立刻继续（vs HITL 节点 `interrupt()` 抛 GraphInterrupt 暂停）
- [x] **失败不阻断**：单个 recipient 入队失败 → `failed_count += 1` + state 写入；graph 仍走 next。设计原则："通知是 best-effort 副作用，不是 graph 流转的关键路径"
- [x] **autoescape Jinja**：模板默认 autoescape=html 防 XSS（与 03-04 一致），用户输入字段（如 `{{ description }}`）安全渲染
- [x] **channels: ["email"] 唯一支持**：Phase 3 不支持其他 channel（Phase 4 才加 feishu/wechat 等）；channels 含其他值时 → `skipped=True` 不抛错
- [x] **recipients 支持 Jinja**：`recipients: "{{ start.user.email }}"` 在 _render_config 阶段被渲染为字符串 → 节点内 wrap 成单元素 list
- [x] **state 写入格式**：`{node_id: {sent_count, failed_count, notification_ids}}` — 与 BaseNodeExecutor 输出契约一致，下游节点可引用 `{{ notif_1.sent_count }}` 做条件判断
- [x] **复用 03-04 模板基础设施**：新增 `templates/email/generic_notification.html`（极简：subject + body 双 block 渲染），与 HITL 决策模板独立

---

## 7. 与 HITL 节点的核心区别（NODE-02 vs NODE-07）

| 维度 | HITL 节点（NODE-02 / Plan 03-02 落）| Notification 节点（NODE-07 / 本 plan）|
|---|---|---|
| **暂停 graph？** | ✅ `interrupt(payload)` 抛 GraphInterrupt 暂停 graph 等待 resume | ❌ 不暂停，发送后立即继续到 next 节点 |
| **创建 hitl_token？** | ✅ ExecutionEngine 在 enter 时为每个 action 创建独立 JWT token + 写 hitl_tokens 表 | ❌ 不创建任何 token，无 callback URL |
| **payload 是？** | interrupt payload（node_state_id / form_schema / deadline_at / current_actor）| 仅 `{recipient, subject, body}` 三件套（无 token / 无 form） |
| **失败处理？** | RED：节点抛错 → graph 异常终止（可重试整个 graph） | YELLOW：单发失败 → `failed_count + 1`，graph 仍走完 |
| **催办循环？** | ✅ 默认 24h deadline → arq 超时 worker 扫描 → reminder_round 1/2/3 升级（NOTI-09） | ❌ reminder_round 永远 0，**不参与催办**（首发即终态） |
| **DB checkpoint 写入** | ✅ 暂停时 LangGraph 自动写完整 state 到 PG checkpoint | ❌ 无暂停 = 无中间 checkpoint，与普通 task 节点同 |
| **resume 重跑语义** | 节点函数会在 resume 时从头重跑（副作用归外，Plan 03-02 决策点）| 不会被 resume（无 interrupt）；如果 graph 失败重试，可能会重发（依赖 graph 顶层重试策略）|
| **典型用例** | 审批/退回/拒绝四态决策，需用户回调推进 | 流程结束通知 HR / 失败告警邮件 / 进度更新邮件 |
| **JSON Schema 必填字段** | `assignees`（决策人）| `recipients` + `subject` + `body` |
| **NODE_EXECUTORS key** | `"hitl"` | `"notification"` |
| **依赖 ExecutionEngine 注入字段** | `__node_state_id` / `__workspace_id` / `__instance_id` | `__workspace_id` / `__instance_id`（写 notifications 表多租户用）+ `__node_state_id`（关联 node_states 行用）|

**核心隔离原则**：

> HITL 节点 = 流程控制权交给人 + 等待回调 + 创建凭证 + 进入催办循环
> Notification 节点 = 单向广播 + 不等待 + 不创建凭证 + 无催办

两个节点**共享**：
- 同一份 NotificationService（03-04 已建）
- 同一份 arq worker（send_hitl_email_job 路径）
- 同一个 Jinja2 模板目录（`templates/email/`）

两个节点**独立**：
- 不同的 NODE_EXECUTORS key + 独立 schema
- 不同的 payload 结构（HITL 有 tokens/form_schema，Notification 没有）
- 不同的失败语义（HITL 失败 = 节点失败；Notification 失败 = state 标记，节点成功）

## 8. 与 hr/offboarding-flow 对照

hr 项目离职流程中"完成通知节点"对应本 plan 设计：
- 离职邮件给 HR / 部门主管 / 申请人
- 不需要回调（已是流程终态前的最后一步）
- 单封失败不阻断 → 仍生成离职报告（写 audit）

本 plan 的 NotificationNode 完全满足 hr 用例 — 这是 Phase 7 hr 模板能跑通的前置条件。

---

## 9. Attribution

未拷贝 Dify 源码（Dify 是 AGPL-3.0，本项目是 Apache-2.0）。仅借鉴：
- 节点 schema 的"枚举驱动 channel"模式（重写为 JSON Schema enum）
- `_EmailDeliveryJob` 数据聚合思路（本项目用 notifications.payload JSONB 替代）
- `_build_form_link` URL 拼装风格（Plan 03-04 已落 `_build_deeplink`）

NotificationNodeExecutor / NOTIFICATION_NODE_SCHEMA / generic_notification.html 全部是独立创作（中文注释 + 异步风格 + state 写入契约与 03-02 解耦）。

---

*Plan: 03-05*
*Reading doc gate: ✅ CLAUDE.md 2.7 (本文档是 Plan 03-05 的 Task 0，先 commit 才允许写代码)*
