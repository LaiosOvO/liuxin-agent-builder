# Dify 阅读笔记 — HITL Schema 三表关系 + 索引模式

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> 本 plan: agent-builder 03-01（hitl_tokens + notifications + audit_log alter）

## 项目概述

Dify 是国内最成熟的开源 LLM 应用 / 工作流平台，HITL（Human Input）子系统位于 `api/models/human_input.py` + `api/core/workflow/human_input_*.py` + `api/services/human_input_service.py`，采用 **三表分离**（Form / Delivery / Recipient）的范式管理"流程暂停 → 多通道投递 → 多收件人响应"的整条决策链路。本次阅读用于指导我们 03-01 plan 的**简化版**两表设计（hitl_tokens + notifications）。

## 技术栈（HITL 模块部分）

- **ORM**：SQLAlchemy 2.x `Mapped[T]` + `mapped_column` 风格
- **类型映射**：`StringUUID`（基于 `sa.VARCHAR(36)` 的 UUID 字符串包装）+ `EnumText` 枚举存文本
- **token 生成**：`libs.helper.generate_string(22)` 随机 22 字符（base62 ≈ 130 bit 熵），存 VARCHAR(32) 列
- **关系**：`Mapped[list[Child]] = relationship(..., lazy="raise")` —— **强制显式预加载**，禁止隐式 N+1
- **状态枚举**：StrEnum 在独立模块 `graphon.nodes.human_input.enums`（HumanInputFormStatus / HumanInputFormKind）
- **payload 多态**：`recipient_payload` JSON 列 + Pydantic `Annotated[Union[...], Field(discriminator="TYPE")]` 实现 5 种收件人类型分发

## 架构要点

```
┌────────────────────────────────────────────────────────────────────┐
│                  HumanInputForm（表单 - 1）                        │
│  pk=id, tenant_id, app_id, workflow_run_id, node_id, form_kind     │
│  form_definition / rendered_content / status / expiration_time     │
│  selected_action_id, submitted_data, submitted_at, submission_user_id │
│  completed_by_recipient_id（指向 winning Recipient）               │
│                                                                    │
│  index: (workflow_run_id, node_id)                                 │
│  index: (status, expiration_time) ← 超时扫描加速                   │
│  index: (status, created_at)                                       │
└──────────────────┬─────────────────────────────────────────────────┘
                   │ 1:N
┌──────────────────▼─────────────────────────────────────────────────┐
│              HumanInputDelivery（投递通道 - N）                    │
│  pk=id, form_id (FK Form), delivery_method_type (email/im/...)     │
│  delivery_config_id, channel_payload (rendered)                    │
│  index: (form_id)                                                  │
└──────────────────┬─────────────────────────────────────────────────┘
                   │ 1:N
┌──────────────────▼─────────────────────────────────────────────────┐
│         HumanInputFormRecipient（收件人 + token - M）              │
│  pk=id, form_id, delivery_id (FK Delivery)                         │
│  recipient_type (EMAIL_MEMBER/EMAIL_EXTERNAL/CONSOLE/...)          │
│  recipient_payload JSON (discriminated union 5 种)                 │
│  access_token VARCHAR(32) UNIQUE ← 一封邮件一个 token              │
│  index: (form_id), (delivery_id)                                   │
└────────────────────────────────────────────────────────────────────┘
```

**核心思想**：表单元数据（业务）+ 通道（基础设施）+ 收件人/token（消费凭证）三层正交。
- 一个 Form 可以经 email + IM 两个 Delivery
- 一个 Delivery 可以发给 5 个 Recipient（每人一个 token）
- 同节点多收件人 → 任一 token 消费即写 Form.completed_by_recipient_id

## 可借鉴的设计模式

### 1. `(status, expiration_time)` 复合索引加速超时扫描
- 位于 `api/models/human_input.py:36`
- `sa.Index("human_input_forms_status_expiration_time_idx", "status", "expiration_time")`
- **借鉴**：03-09 超时催办 worker 每分钟扫一次 `SELECT * FROM node_states WHERE status IN ('waiting_human','in_review') AND deadline_at < now()`，必须有 `(status, deadline_at)` 索引否则全表扫
- **本 plan 应用**：notifications 表加 `(status, created_at)` 索引（NOTI-10 SMTP 重试扫描）

### 2. token 一次性消费 + 多 token 隔离
- 位于 `api/models/human_input.py:212-218`
- `access_token: VARCHAR(32) NULLABLE=False UNIQUE default=_generate_token`
- **借鉴**：每个收件人一个独立 token，单 token 消费不影响其他
- **本 plan 应用**：hitl_tokens.jti UUID PK + `(node_state_id, used_at)` 索引；POST 消费时 `UPDATE WHERE used_at IS NULL RETURNING *`，原子获取

### 3. submitted_* 三字段把"被消费"信息汇集到 Form 表
- 位于 `api/models/human_input.py:64-69` 的 `selected_action_id / submitted_data / submitted_at / submission_user_id / submission_end_user_id`
- **借鉴**：Form 一次只能被消费一次（业务规则），所以提交细节直接落 Form 而非 Recipient
- **本 plan 应用**：我们因 jti 唯一，把 `used_at / used_ip / used_ua` 直接放 hitl_tokens 表（合并 Dify 的 Form.submitted_* + Recipient.access_token），单表完成

### 4. EnumText（枚举存 VARCHAR）+ StrEnum 状态机
- 位于 `api/models/human_input.py:54-57` + `api/models/types.py` EnumText
- **借鉴**：枚举不存 INT/SMALLINT，存 VARCHAR(16) 文本，DB 可读性高 + Alembic 不需要枚举类型 migration
- **本 plan 应用**：hitl_tokens.action VARCHAR(16) 存 submit/approve/return/reject；notifications.status VARCHAR(16) 存 pending/sending/sent/failed

### 5. 收件人 payload JSON + 类型分发
- 位于 `api/models/human_input.py:130-191`
- `recipient_payload: Text` + Pydantic `discriminator="TYPE"` 分 5 种
- **借鉴**：payload 列存渲染后的内容（debug + 重试 + 回放），TYPE 字段区分通道
- **本 plan 应用**：notifications.payload JSONB 存渲染后邮件正文（subject/body_html/body_text/buttons），方便 03-09 催办 worker 直接重发同样模板而无需重新渲染

### 6. lazy="raise" 关系防 N+1
- 位于 `api/models/human_input.py:78-89, 113-128, 220-237`
- 所有 relationship 默认 `lazy="raise"`，必须显式 `selectinload` / `joinedload`
- **借鉴**：开发期防 N+1 误用，强制每次 JOIN 显式
- **本 plan 应用**：本 plan 不直接落 relationship（避免 service 层 join 复杂度），先用 JOIN 查询 + Repository 层封装

## 与本项目的关系（设计取舍）

### 我们简化的 2 表设计

| 我们的表 | 对应 Dify | 取舍说明 |
|---|---|---|
| `hitl_tokens` (jti / instance / node_state / actor / action / used_*) | Dify Form.submission_* + Recipient.access_token | jti UUID 同时担当 Recipient 的访问凭证 + Form 的完成标记，单表 |
| `notifications` (id / workspace / instance / node_state / channel / recipient / status / payload / reminder_round) | Dify Delivery + Recipient（投递 + 收件人合表） | UNIQUE 约束 (instance_id, node_state_id, channel, recipient, reminder_round) 保证催办去重；不分 form_id |
| (无独立 Form 表) | Dify HumanInputForm | 表单元数据已在 node_states.payload JSONB 里（Phase 2 已建），不需要单独 Form 表 |

**简化理由**：
1. **v1 单人审批**（03-CONTEXT.md 已确认）：一节点一 actor，没必要拆 Form / Recipient 三层
2. **node_states.payload 已存表单**：form_schema / current_actor / records 都在 Phase 2 既有的 node_states 表 JSONB 里
3. **jti UUID + Postgres 原子 UPDATE**：用 Postgres `UPDATE...WHERE used_at IS NULL RETURNING` 替代 Dify 的应用层锁

### 不照抄的点（Dify 是 AGPL，禁拷贝）

- Token 生成方式：Dify `generate_string(22)` 字符串 → 我们用 PyJWT HS256（含 payload 校验 + iss/aud/exp），不用 Dify 的 access_token 方案
- 表名：human_input_forms → hitl_tokens（含义更清晰；token 是凭证非表单）
- 索引命名：human_input_forms_*_idx → ix_hitl_tokens_*（遵守我们 Base.metadata naming_convention）

### 借鉴的设计原则

1. **超时扫描复合索引** `(status, deadline-like-field)` 放 notifications 而非 hitl_tokens
2. **token VARCHAR/UUID UNIQUE** 单字段 PK，原子消费靠 DB 约束
3. **payload JSON** 存渲染后内容方便 debug + 重发
4. **status 字符串枚举** 不用 INT，DB 可读
5. **状态机字段命名** `used_at` / `used_ip` / `used_ua` 跟 Dify `submitted_*` 命名风格一致

## 与 hr 项目对照（业务字段映射）

> 注：`/Users/admin/ai/ref/hr/` 在本环境中未 clone，本节根据 03-CONTEXT.md 决策原文 + agent-builder PRD 双通道通知章节 推导。

| hr/offboarding-flow 概念 | agent-builder Phase 3 | 实现位置 |
|---|---|---|
| 离职审批通知（邮件 + Mattermost） | NOTI-01 邮件 + NOTI-02..07 IM（Phase 4） | notifications.channel + notifications.payload |
| 审批人 multi-attempt | reminder_round (0..N) + UNIQUE 去重 | notifications.reminder_round + uq_notifications_dedup |
| 审计字段 IP/UA/decision | audit_logs ALTER ADD actor_ip/actor_ua/decision/node_state_id | 0003 migration ADD COLUMN |
| 审批结果 4 态 submit/approve/return/reject | hitl_tokens.action VARCHAR(16) | 03-CONTEXT §Token 4-action |
| LangGraph interrupt / resume | hitl_tokens.used_at → 触发 Command(resume) | 03-02 plan 节点 executor |

## 设计借鉴清单 → 落 plan 决策（必须）

| Dify 模式 | 03-01 落地 |
|---|---|
| `(status, expiration_time)` 复合索引 | `ix_notifications_status_created` 索引（NOTI-10 重试扫描） |
| Recipient.access_token VARCHAR UNIQUE | `hitl_tokens.jti UUID PRIMARY KEY` |
| 三表分离（Form / Delivery / Recipient） | **简化为两表**（hitl_tokens 担当 Form + Recipient；notifications 担当 Delivery + Recipient 投递维度） |
| submitted_* 三字段并入 Form 表 | `hitl_tokens.used_at + used_ip + used_ua` 三字段（原子消费 + 审计） |
| EnumText 文本枚举 | `hitl_tokens.action VARCHAR(16)` / `notifications.status VARCHAR(16)` |
| recipient_payload JSON discriminator | `notifications.payload JSONB`（NOTI-01 v1 仅 email 通道，但 schema 留 channel 字段为后续 IM 扩展） |
| lazy="raise" 关系 | 本 plan 不引入 relationship；Service 层显式 JOIN |

---

**结论**：03-01 不拷贝 Dify 三表结构，但借用其**索引模式 + 字段命名 + JSON 多态 payload 思路**，做单表"jti + actor + action"统一管理。后续 03-02..03-09 plan 中如出现 form_kind / submission_user_id 类需求，再考虑是否分表（v1 单人审批不需要）。
