---
phase: 04-approval-chain-im
plan: "10"
subsystem: notification-multichannel
tags: [multichannel, fan-out, noti-08, im-dispatch, schema-extension, recipient-binding]
dependency_graph:
  requires:
    - 04-05 (IMProvider Protocol + Registry + im_jobs.send_hitl_card_job + IMCredentialsManager)
    - 04-06..09 (5+1 家具体 IM Provider 实现 — feishu/wecom/dingtalk/slack/mattermost/webhook)
    - 03-04 (NotificationService.enqueue_hitl_email + email_jobs.send_hitl_email_job)
    - 03-05 (NotificationNodeExecutor 基础 + enqueue_generic_email)
    - 03-01 (notifications 表 + UNIQUE 约束)
  provides:
    - NotificationService.enqueue_hitl_multichannel (channels[] → fan-out N 行 + N 个 arq job)
    - NotificationService.enqueue_generic_im_card (Notification 节点 IM 通道入口)
    - NotificationService._build_hitl_payload helper (immutability + DRY)
    - NotificationService._fallback_dispatch helper (arq_pool=None 时 asyncio.create_task)
    - NOTIFY_CHANNELS_ENUM 共享常量 (hitl_schema + notification_schema 共用 7 个值)
    - hitl_schema.notify_channels 字段 (default=['email'] 向后兼容)
    - notification_schema.channels enum 修正 (wechat → wecom)
    - NotificationNodeExecutor 多 channel 分发 (email → email_jobs / IM → im_jobs)
    - _normalize_recipients(raw, channel) helper (email 校验 / IM 接受任意字符串)
  affects:
    - Phase 4 Wave 6+ (NOTI-09 催办循环可复用多通道入队)
    - Phase 5 (im_directory 同步将填充 users.im_bindings → multichannel 自动可用)
    - Phase 6 (插件机制可加新通道无需改 NotificationService — 只需新 PROVIDER_* + KNOWN_PROVIDERS 扩展)
tech-stack:
  added: []
  patterns:
    - "Fan-out N channels → N notifications rows + N arq jobs (per-channel status 独立)"
    - "事务边界: 所有 INSERT commit 后才循环 enqueue_job (防 Pitfall 2 worker 抢跑)"
    - "Per-channel payload dict 副本 (immutability — worker 写回不污染其他 channel)"
    - "im_bindings.get(channel) 缺失 → log warning + continue (不阻塞其他 channel)"
    - "Channel 分类常量 _EMAIL_CHANNEL / _IM_CHANNELS frozenset (NotificationService 与 nodes/notification 共享)"
    - "结构化日志 logger.info('notification.multichannel.enqueued', extra={channels, ...})"
    - "Schema enum 共享常量 NOTIFY_CHANNELS_ENUM (hitl + notification schema DRY)"
    - "_normalize_recipients(raw, channel): email 严校验邮箱 / IM 宽容接受任意字符串"
    - "向后兼容: 旧 DSL 无 channels 字段 → 默认 ['email'] (Phase 3 测试 100% 通过)"
    - "Per-channel try/except: 单 channel 失败不阻塞其他 (rollback per-recipient 后继续)"
key-files:
  created:
    - backend/tests/test_notification_service_multichannel.py (633 行, 13 集成测试)
    - backend/tests/test_hitl_schema_channels.py (215 行, 16 单元测试)
    - backend/tests/test_notification_node_multichannel.py (461 行, 10 集成测试)
    - docs/reading-dify-04-10-multichannel-2026-05-17.md (234 行)
  modified:
    - backend/app/services/notification_service.py (+283 行: enqueue_hitl_multichannel + enqueue_generic_im_card + _build_hitl_payload + _fallback_dispatch + 通道分类常量 + 模块 docstring)
    - backend/app/agent_builder/workflow/node_schemas/hitl_schema.py (+27 行: notify_channels 字段 + NOTIFY_CHANNELS_ENUM 模块常量)
    - backend/app/agent_builder/workflow/node_schemas/notification_schema.py (-8/+19 行: 修正 wechat→wecom + 共享 enum import)
    - backend/app/agent_builder/workflow/nodes/notification.py (+72/-44 行: 多 channel 分发 + _normalize_recipients helper)
    - backend/tests/test_notification_node_executor.py (1 测试改名 + 用例从 feishu 改为 sms 反映新行为)
    - .planning/phases/04-approval-chain-im/deferred-items.md (新增 pre-existing test_all_node_types_registered 登记)
decisions:
  - "[Phase 04-10] enqueue_hitl_multichannel 是新方法（不修改 enqueue_hitl_email 签名）— 保持 Phase 3 测试 100% 向后兼容"
  - "[Phase 04-10] _build_hitl_payload helper 提取 — DRY 但 enqueue_hitl_email 保留原实现避免破坏现有 5 测试"
  - "[Phase 04-10] 事务边界 commit 后才 enqueue_job — Dify 模式 2 + 本项目 Pitfall 2 防护（worker 抢跑事务未提交行）"
  - "[Phase 04-10] im_bindings 缺失 → log warning + skip channel（不抛错）— 用户可能只为部分 channel 配置 IM 账号"
  - "[Phase 04-10] 每行独立 payload dict 副本 — im_jobs 写回 im_message_id 不污染其他 channel 行"
  - "[Phase 04-10] channels=[] / 未知 channel → ValueError — fail-fast 配置错误"
  - "[Phase 04-10] _ALL_KNOWN_CHANNELS frozenset 校验 — 防 schema 与 service 层 channels enum 不一致"
  - "[Phase 04-10] enqueue_generic_im_card 与 enqueue_generic_email 平行 API — 不引入 generic_multichannel 一锅炒（简洁性 > DRY）"
  - "[Phase 04-10] enqueue_generic_im_card(channel='email') → ValueError — 强制走 enqueue_generic_email 避免歧义"
  - "[Phase 04-10] NOTIFY_CHANNELS_ENUM 模块常量 — hitl_schema + notification_schema 共享一个 list 引用（identity check 测试覆盖）"
  - "[Phase 04-10] notification_schema 'wechat' → 'wecom' — 与 PROVIDER_WECOM / _IM_CHANNELS 全栈命名一致 (修正 Phase 3 残留)"
  - "[Phase 04-10] 旧 DSL 无 channels/notify_channels 字段 → 默认 ['email'] — Phase 3 测试 0 regression"
  - "[Phase 04-10] _normalize_recipients 按 channel 类型分校验策略 — email 严格 / IM 宽容（避免 IM user_id 被误过滤）"
  - "[Phase 04-10] 单 channel 失败不阻塞其他 — per-channel try/except 包裹整 channel 循环"
  - "[Phase 04-10] 单 recipient 失败 rollback 后继续 — 与 03-05 enqueue_generic_email per-recipient 行为一致"
  - "[Phase 04-10] [Rule 1 - Bug] test_notification_node_unsupported_channel_skipped 改为 test_notification_node_unknown_channel_skipped — Plan 04-10 feishu 已支持，sms 才是真正未知"
  - "[Phase 04-10] 结构化日志 message='notification.multichannel.enqueued' + extra={channels, notification_ids, instance_id, ...} — Phase 7 ELK / Loki 查询友好"
  - "[Phase 04-10] [Rule 3 - Blocking] deferred-items.md 登记 test_dsl_schema.py::test_all_node_types_registered 失败 — Plan 03-05 引入 notification 时遗留，与 04-10 改动无关"
  - "[Phase 04-10] _fallback_dispatch 内部封装 asyncio.create_task — arq_pool=None 测试 / dev 模式不强依赖 Redis"
metrics:
  duration: "22min"
  completed_date: "2026-05-17"
  tasks: 4
  files_created: 4
  files_modified: 6
  tests_added: 39
  tests_regression: 0
---

# Phase 4 Plan 10: NotificationService 多通道 fan-out + Schema 扩展 + 节点分发 Summary

**一句话**: NOTI-08 多通道并发投递完整实现 — `NotificationService.enqueue_hitl_multichannel` 一次调用 fan-out 到 email + 5 家 IM provider（事务边界 commit 后才 enqueue 防 Pitfall 2 + 每行独立 payload 防 worker 写回污染 + im_bindings 缺失跳过不阻塞）+ `enqueue_generic_im_card` 与 `enqueue_generic_email` 平行 API + `hitl_schema.notify_channels` / `notification_schema.channels` 共享 `NOTIFY_CHANNELS_ENUM` 7 值（向后兼容默认 ['email']）+ `NotificationNodeExecutor.execute()` 多 channel 分发（per-channel 失败隔离 + email 严校验邮箱 / IM 宽容接受任意字符串），39 新集成/单元测试全绿 0 regression。

---

## 完成的工作

### 1. Reading doc gate (Task 0)

`docs/reading-dify-04-10-multichannel-2026-05-17.md` — 234 行对比 Dify `mail_human_input_delivery_task.py` 单通道架构 vs 本 plan 多通道 fan-out，提取 5 个可借鉴模式（recipient 解析延迟 / 事务边界 / 拆分 dispatch / 容错跳过 / UNIQUE 去重）+ 明确不复用部分（三层 ORM / Celery / Markdown 渲染），首个 commit 满足 CLAUDE.md §2.7 HARD GATE。

### 2. NotificationService 多通道方法 (Task 1)

新增 `backend/app/services/notification_service.py`：

#### `enqueue_hitl_multichannel`
```python
async def enqueue_hitl_multichannel(
    self,
    *,
    workspace_id, instance_id, node_state_id,
    recipient_email,
    recipient_im_bindings: dict[str, str] | None,  # {feishu: "ou_x", wecom: "WuPing"}
    tokens, form_schema, deadline_at,
    actor_name, flow_title, node_title, applicant_name, description,
    channels: list[str],  # ["email", "feishu", "wecom"]
    reminder_round: int = 0,
) -> list[Notification]:
```

**行为**：
- 校验 channels 非空 + 全部已知（不在 _ALL_KNOWN_CHANNELS → ValueError）
- 每 channel 解析 recipient：
  - `email` → 用 `recipient_email`
  - IM → `recipient_im_bindings[channel]`，缺失则 `log.warning("im_bindings 缺 %s")` + skip
- 每 channel 创建独立 payload dict 副本（防 worker 写回 im_message_id 污染其他）
- **事务边界**：所有 INSERT → `db.commit()` → for-loop `arq.enqueue_job`（reading doc §模式 2）
- 结构化日志 `notification.multichannel.enqueued` + extra `{channels, notification_ids, instance_id, ...}`
- 返回 list[Notification]（缺 binding 的 channel 不在返回中）

#### `enqueue_generic_im_card`
```python
async def enqueue_generic_im_card(
    self, *, workspace_id, instance_id, node_state_id,
    recipient, channel,  # channel 必须是 IM channel
    subject, body,
) -> Notification:
```

**行为**：
- `channel='email'` → ValueError（强制走 `enqueue_generic_email`）
- payload 极简 `{generic: True, subject, body, recipient_im}`
- 入队 `send_hitl_card_job`（不是 email job）

#### Helpers
- `_build_hitl_payload`：共享 HITL payload 构造（immutability — tokens 新列表 + form_schema 浅拷贝）
- `_fallback_dispatch`：arq_pool=None 时 `asyncio.create_task` 直接驱动 worker

### 3. Schema 扩展 (Task 2)

#### hitl_schema.py
- 新增 **NOTIFY_CHANNELS_ENUM** 模块级常量（7 个值）— 与 NotificationService `_ALL_KNOWN_CHANNELS` 同义
- HITL_NODE_SCHEMA 加 `notify_channels` 字段：
  - `type: array`，`items.enum: NOTIFY_CHANNELS_ENUM`
  - `minItems: 1`，`default: ["email"]`（向后兼容）

#### notification_schema.py
- `from hitl_schema import NOTIFY_CHANNELS_ENUM`（DRY，共享 list 引用）
- channels enum 修正：**'wechat' → 'wecom'**（与 PROVIDER_WECOM 全栈命名一致）
- 测试 `test_shared_enum_consistency_hitl_and_notification` 用 `is` 验证两 schema 引用同一 list

### 4. NotificationNodeExecutor 多 channel 分发 (Task 3)

`backend/app/agent_builder/workflow/nodes/notification.py` `execute()` 改造：

```python
async def execute(self, config: dict, state: dict) -> dict[str, Any]:
    channels = config.get("channels") or ["email"]  # 向后兼容
    valid_channels = [c for c in channels if c == "email" or c in _IM_CHANNELS]
    # 完全无效 → skipped=True；混合 → 警告 + 仅保留 valid

    raw_recipients = config.get("recipients")
    # ... workspace/instance 校验 ...

    async with async_session_maker() as db:
        node_state_id = await self._resolve_node_state_id(db)
        svc = NotificationService(db=db, arq_pool=None)

        for channel in valid_channels:
            channel_recipients = _normalize_recipients(raw_recipients, channel)
            for recipient in channel_recipients:
                try:
                    if channel == "email":
                        notif = await svc.enqueue_generic_email(...)
                    else:
                        notif = await svc.enqueue_generic_im_card(...)
                    notification_ids.append(notif.id)
                    sent_count += 1
                except Exception:
                    await db.rollback()
                    failed_count += 1
    return {"sent_count", "failed_count", "notification_ids"}
```

**新增 helper**：
```python
def _normalize_recipients(raw, channel: str) -> list[str]:
    """规范化 recipients 为 list[str]，按 channel 类型决定校验策略。
    - email channel: _is_valid_email 严校验
    - IM channel: 接受任意非空字符串（IM user_id 因厂商而异）
    """
```

**修订既有测试**：
- `test_notification_node_unsupported_channel_skipped` 改名 `test_notification_node_unknown_channel_skipped`
- 用例从 `channels=['feishu']` 改为 `channels=['sms']`（Plan 04-10 feishu 已支持）

### 5. 共享通道分类常量

为防 `notification_service.py` 与 `nodes/notification.py` 通道列表不同步：
- 两文件都定义 `_EMAIL_CHANNEL = "email"` 和 `_IM_CHANNELS: frozenset = frozenset({...})`
- 7 个值与 schema NOTIFY_CHANNELS_ENUM 严格对齐

---

## 测试结果（39 新测试全绿 + 28 既有 0 regression）

### test_notification_service_multichannel.py（13 集成测试 — 真实 PG）

| # | 测试 | 覆盖点 |
|---|------|--------|
| 1 | test_multichannel_email_only | channels=['email'] → 1 行 + send_hitl_email_job |
| 2 | test_multichannel_email_and_feishu | channels=['email','feishu'] + bindings → 2 行不同 job |
| 3 | test_multichannel_skip_channel_without_binding | bindings 缺 feishu → 仅 email + caplog warning |
| 4 | test_multichannel_enqueue_after_commit | commit 后才 enqueue (mock arq 内 SELECT 验证) |
| 5 | test_enqueue_generic_im_card_writes_row | channel=feishu → 1 行 + send_hitl_card_job |
| 6 | test_enqueue_generic_im_card_unique_constraint | 相同 (inst,ns,channel,recipient,round) → IntegrityError |
| 7 | test_multichannel_reminder_round_unique | round=1 与 0 不冲突 |
| 8 | test_multichannel_no_im_bindings_dict_none | bindings=None → 仅 email 入队 |
| 9 | test_multichannel_empty_channels_raises | channels=[] → ValueError |
| 10 | test_multichannel_unknown_channel_raises | channels=['sms'] → ValueError |
| 11 | test_enqueue_generic_im_card_rejects_email_channel | channel='email' → ValueError |
| 12 | test_multichannel_payload_immutable_across_channels | 每行独立 payload dict (修改一行不影响其他) |
| 13 | test_multichannel_structured_log_emitted | caplog 'notification.multichannel.enqueued' + extra 字段 |

### test_hitl_schema_channels.py（16 单元测试 — 纯 schema 校验）

| # | 测试 | 覆盖点 |
|---|------|--------|
| 1 | test_hitl_schema_default_notify_channels_is_email | default=['email'] |
| 2 | test_hitl_schema_invalid_channel_rejected | 'sms' → ValidationError |
| 3 | test_hitl_schema_multiple_channels_accepted | ['email','feishu','wecom'] 通过 |
| 4 | test_hitl_schema_empty_channels_rejected | [] minItems=1 |
| 5 | test_hitl_schema_notify_channels_minItems_constraint | minItems=1 严格 |
| 6 | test_hitl_schema_backward_compat_without_notify_channels | 无字段通过 (向后兼容) |
| 7 | test_hitl_schema_all_7_channels_individually_valid | 7 个值各单合法 |
| 8 | test_notification_schema_default_channels_is_email | default=['email'] |
| 9 | test_notification_schema_multiple_channels_ok | ['email','feishu','slack'] 通过 |
| 10 | test_notification_schema_empty_channels_rejected | [] minItems=1 |
| 11 | test_notification_schema_invalid_channel_rejected | 'sms' → ValidationError |
| 12 | test_notification_schema_wechat_replaced_by_wecom | 'wechat' 不在 enum, 'wecom' 在 |
| 13 | test_notification_schema_backward_compat_without_channels | 无字段通过 |
| 14 | test_shared_enum_consistency_hitl_and_notification | 两 schema 共享 list (identity check) |
| 15 | test_shared_enum_contains_7_values | NOTIFY_CHANNELS_ENUM 含 7 个值 |
| 16 | test_notification_schema_all_7_channels_individually_valid | 7 个值各单合法 |

### test_notification_node_multichannel.py（10 集成测试 — 真实 PG）

| # | 测试 | 覆盖点 |
|---|------|--------|
| 1 | test_execute_email_only_backward_compat | 无 channels 字段 → 默认 ['email'] + 1 行 |
| 2 | test_execute_email_and_feishu_dispatches_both | channels=['email','feishu'] → 2 行不同 channel |
| 3 | test_execute_skips_invalid_email_for_email_channel | email channel 过滤 invalid 邮箱 |
| 4 | test_execute_partial_failure_continues | feishu 失败 + email 成功 → sent=1 failed=1 |
| 5 | test_execute_im_channel_accepts_any_recipient_string | IM 接受 'ou_abc_xyz_no_email' |
| 6 | test_execute_multiple_im_channels_all_dispatched | 3 个 IM channel 都入队 |
| 7 | test_execute_unknown_channel_skipped_within_mixed | channels=['email','sms','feishu'] → sms 跳过 + warn |
| 8 | test_execute_payload_distinct_per_channel | 每行 payload 独立 dict |
| 9 | test_execute_failed_count_isolated_per_channel | email 失败 + feishu 成功 → sent=1 failed=1 |
| 10 | test_execute_state_contains_notification_ids_for_all_channels | state.notification_ids 含所有 channel ID |

### 既有测试 0 regression

| 套件 | 测试数 | 状态 |
|---|---|---|
| test_notification_service.py | 5 | ✅ 全绿 |
| test_notification_node_executor.py | 13 | ✅ 全绿（test_notification_node_unknown_channel_skipped 已更新） |
| test_im_jobs_skeleton.py | 10 | ✅ 全绿 |
| test_im_credentials_loader.py | 15 | ✅ 全绿 |
| test_im_provider_protocol.py | 18 | ✅ 全绿 |
| test_notification_model.py | 4 | ✅ 全绿 |
| test_dingtalk_provider.py | 18 | ✅ 全绿 |
| test_wecom_provider.py | 17 | ✅ 全绿 |
| test_slack_provider.py | 11 | ✅ 全绿 |
| test_mattermost_provider.py | 13 | ✅ 全绿 |
| test_webhook_provider.py | 19 | ✅ 全绿 |

**总计：39 新 + 28 全 Phase 3+4 既有 = 67+ 测试全绿；126 IM Provider 测试 0 regression**

---

## NotificationService.enqueue_hitl_multichannel API 速查

### 入参示例

```python
await svc.enqueue_hitl_multichannel(
    workspace_id=ws_id,
    instance_id=inst_id,
    node_state_id=ns_id,
    recipient_email="approver@example.com",   # email channel 用
    recipient_im_bindings={                   # IM channel 用
        "feishu":   "ou_4b2c3d...",
        "wecom":    "WuPing",
        "dingtalk": "user12345",
        "slack":    "U02ABCD",
        # 未配置 mattermost / webhook 时 → 该 channel 跳过
    },
    tokens=hitl_tokens_list,                  # HITL token 列表 (jti + action)
    form_schema={"type": "object", ...},
    deadline_at=datetime(2026, 5, 18, 18),
    actor_name="李四",
    flow_title="员工入职流程",
    node_title="HR 审批",
    applicant_name="张三",
    description="请审批...",
    channels=["email", "feishu", "wecom"],    # 多通道并发投递
    reminder_round=0,                         # 0=首次 / 1/2/3=催办
)
```

### 返回示例

```python
[
    <Notification id=42 channel='email' recipient='approver@example.com' status='pending'>,
    <Notification id=43 channel='feishu' recipient='ou_4b2c3d...' status='pending'>,
    <Notification id=44 channel='wecom' recipient='WuPing' status='pending'>,
]
# 注意：如果 bindings 缺某 channel，那行不在返回 list 中（已 skip + warn）
```

### 异常路径

| 异常 | 触发条件 |
|---|---|
| `ValueError("channels 必须至少包含一个通道")` | channels=[] |
| `ValueError("未知 channels: [...]")` | 含不在 7 个允许值的 channel |
| `IntegrityError` | 相同 (instance, ns, channel, recipient, round) 二次入队 |

---

## im_bindings JSON 结构示例（v1）

`users.im_bindings` 是 JSONB 字段，存储用户在各 IM 平台的 ID 映射：

```json
{
  "feishu": "ou_4b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e",
  "wecom": "WuPing",
  "dingtalk": "user_abcdef123456",
  "slack": "U02ABCD1234",
  "mattermost": "userid_mm_xyz789",
  "webhook": "https://user.example.com/webhook/123"
}
```

**Phase 4 简化（v1）**：
- 字段是 `dict[str, str]`（key = channel name，value = recipient identifier）
- 缺失 key → 该 channel 跳过（不抛错）
- 由调用方（如 HITL 节点 enter 时）从 user.im_bindings 提取，传给 enqueue_hitl_multichannel

**Phase 5 扩展（IM 目录同步）**：
- 自动从飞书 / 企微 / 钉钉 SCIM API 拉取员工列表
- 同步到 users.im_bindings + users.department
- 之后 multichannel 自动可用（无需用户手动配置）

---

## channels schema enum (NOTIFY_CHANNELS_ENUM)

```python
NOTIFY_CHANNELS_ENUM = [
    "email",        # Phase 3 03-04 已实现 (send_hitl_email_job)
    "feishu",       # Phase 4 04-06 已实现 (FeishuProvider + Interactive Card 2.0)
    "wecom",        # Phase 4 04-07 已实现 (WeComProvider + Markdown + Bot Webhook fallback)
    "dingtalk",     # Phase 4 04-08 已实现 (DingTalkProvider + ActionCard via OAPI)
    "slack",        # Phase 4 04-09 已实现 (SlackProvider + Block Kit)
    "mattermost",   # Phase 4 04-09 已实现 (MattermostProvider + attachment)
    "webhook",      # Phase 4 04-09 已实现 (WebhookProvider + HMAC-SHA256 签名)
]
```

`hitl_schema.HITL_NODE_SCHEMA.properties.notify_channels` 和
`notification_schema.NOTIFICATION_NODE_SCHEMA.properties.channels` 共享同一 list 引用。

---

## Dify 参考点

详见 `docs/reading-dify-04-10-multichannel-2026-05-17.md`。

### 借鉴的 5 个模式

| Dify 源码 | 本 plan 应用 |
|-----------|-------------|
| `_parse_recipient_payload` 延迟解析 | `im_bindings.get(channel)` 缺失跳过 |
| `with session:` 外才 `mail.send` | `db.commit()` 后才循环 `arq.enqueue_job` |
| 单一 task 入口处理整批 | 拆分: enqueue 层 (sync 事务) + worker 层 (async 重试) |
| `if not recipient_entities: continue` | 缺 binding → log warning + continue |
| 业务层无 UNIQUE | DB UNIQUE (instance, ns, channel, recipient, round) Phase 3 已落 |

### 不复用 Dify

| 不用 | 原因 |
|------|------|
| Form / Delivery / Recipient 三层 ORM | 本项目 v1 单表 notifications + JSONB |
| Celery `@shared_task(queue="mail")` | arq async function (CLAUDE.md §3 锁定) |
| `_render_body` Markdown 渲染 | Jinja2 autoescape=html |
| `EmailDeliveryConfig.sanitize_subject` | 代码层 CR/LF 净化 (email_jobs.py 已落) |
| `_load_variable_pool` | LangGraph state (节点配置已渲染) |

### 许可证

Dify 是 **AGPL-3.0**，本项目 **Apache-2.0**。**未复制源码** — 仅借鉴**设计模式 / 数据结构思路 / 边界处理考虑**。

---

## 关键技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 是否修改 enqueue_hitl_email | **不修改**（新增 enqueue_hitl_multichannel） | 保持 Phase 3 测试 100% 向后兼容 |
| _build_hitl_payload 是否在 enqueue_hitl_email 内使用 | **不**（仅多通道方法用） | 避免破坏既有 5 测试 |
| im_bindings 缺失行为 | log warning + skip（不抛错） | 用户可能只为部分 channel 配置 IM |
| 事务边界 | commit 后才 enqueue_job | Dify 模式 2 + 本项目 Pitfall 2 |
| 每行 payload | 独立 dict 副本 | im_jobs 写回 im_message_id 不污染其他 channel |
| channels 校验 | 严校验 + ValueError | fail-fast 配置错（vs silent skip） |
| enqueue_generic_im_card(channel='email') | ValueError | 强制走 generic_email（避免歧义） |
| Schema enum 共享 | NOTIFY_CHANNELS_ENUM 模块常量 | DRY + identity check 测试覆盖 |
| 'wechat' → 'wecom' 修正 | 修正 | 与 PROVIDER_WECOM / _IM_CHANNELS 全栈一致 |
| 旧 DSL 无 channels 字段 | 默认 ['email'] | Phase 3 测试 0 regression |
| _normalize_recipients email 严校验 | 保留 | 邮件投递 SMTP 拒绝无效邮箱很贵 |
| _normalize_recipients IM 宽容 | 接受任意非空字符串 | IM user_id 格式因厂商而异，无统一正则 |
| 单 channel 失败 | 不阻塞其他 channel | per-channel try/except |
| 结构化日志 message | 'notification.multichannel.enqueued' | Phase 7 ELK / Loki 查询友好 |

---

## Wave 6+ 下游 / Phase 5+ 上游依赖

| 下游使用 | 接入点 |
|---|---|
| Wave 6 NOTI-09 催办循环 | enqueue_hitl_multichannel(reminder_round=1/2/3) 复用同一接口 |
| Phase 5 IM 目录同步 | 自动填充 users.im_bindings → multichannel 自动可用 |
| Phase 4 HITL 节点 enter 时 | 改 enqueue_hitl_email → enqueue_hitl_multichannel (后续 plan 切换) |
| Phase 4 EscalationService | escalate notification 可用 multichannel (升级邮件 + IM 通知) |
| Phase 6 插件机制 | 新通道无需改 NotificationService — 仅扩展 PROVIDER_* + KNOWN_PROVIDERS |

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_notification_node_unsupported_channel_skipped 测试断言过时**

- **Found during:** Task 3（运行回归测试）
- **Issue:** Plan 03-05 的原测试假设 'feishu' 是 unsupported channel → 期望 skipped=True。Plan 04-10 把 feishu 加为 supported（走 enqueue_generic_im_card），此测试失败
- **Fix:** 重命名 `test_notification_node_unsupported_channel_skipped` → `test_notification_node_unknown_channel_skipped`，用例从 `channels=['feishu']` 改为 `channels=['sms']`（真正未知 channel）。语义更精确，且未来加新 channel 时不需要再改此测试
- **Files modified:** backend/tests/test_notification_node_executor.py
- **Commit:** f76eb2b（Task 3）

**2. [Rule 3 - Blocking] test_dsl_schema.py::test_all_node_types_registered 预先存在失败**

- **Found during:** Task 2（schema 测试运行时发现）
- **Issue:** `expected = {"end","hitl","if_else","llm","start","tool"}` 6 元素集合，但 Plan 03-05 已加入 `notification` 到 NODE_SCHEMAS（7 元素）。此 test 自 Plan 03-05 起就失败
- **Fix:** 不在 04-10 范围内修复（CLAUDE.md §scope rule — 仅 by current task's changes），登记到 `.planning/phases/04-approval-chain-im/deferred-items.md` 第 2 条等下次 Phase 4 plan 附带修复或单独 hotfix
- **Verification:** `git stash` + 运行此测试仍失败 → 确认与 04-10 无关
- **Files modified:** .planning/phases/04-approval-chain-im/deferred-items.md（仅登记）

### Architectural Decisions

无 Rule 4 架构变更 — 所有改动在 Plan 04-05 IMProvider 抽象层 + Plan 03-04 NotificationService 基础上扩展，未引入新数据库表 / 新服务层 / 新依赖。

### 与原 plan context 的小调整

**1. enqueue_hitl_email 未重构（保留原签名）**

Plan §multichannel_design 暗示可重构 enqueue_hitl_email 用 _build_hitl_payload，但为保 Phase 3 5 测试 0 regression，决定 enqueue_hitl_email 保留原实现，_build_hitl_payload 仅服务于新方法。

**2. 新增 _fallback_dispatch helper（plan 未明示）**

plan 未提及 arq_pool=None 时如何派发 IM job。决定抽 `_fallback_dispatch(notif, job_name)` helper 统一处理 email/IM 两种 job 名，与 enqueue_hitl_email 现有 fallback 逻辑一致。

---

## Self-Check: PASSED

文件检查（4 创建 + 6 修改）：

- FOUND: backend/tests/test_notification_service_multichannel.py
- FOUND: backend/tests/test_hitl_schema_channels.py
- FOUND: backend/tests/test_notification_node_multichannel.py
- FOUND: docs/reading-dify-04-10-multichannel-2026-05-17.md
- FOUND (modified): backend/app/services/notification_service.py
- FOUND (modified): backend/app/agent_builder/workflow/node_schemas/hitl_schema.py
- FOUND (modified): backend/app/agent_builder/workflow/node_schemas/notification_schema.py
- FOUND (modified): backend/app/agent_builder/workflow/nodes/notification.py
- FOUND (modified): backend/tests/test_notification_node_executor.py
- FOUND (modified): .planning/phases/04-approval-chain-im/deferred-items.md

提交检查（4 commits — Task 0+1+2+3）：

- FOUND: 3de01df (Task 0 reading doc HARD GATE)
- FOUND: 9a8a706 (Task 1 NotificationService multichannel + 13 tests)
- FOUND: 852b8a4 (Task 2 schema NOTIFY_CHANNELS_ENUM + 16 tests)
- FOUND: f76eb2b (Task 3 NotificationNodeExecutor dispatch + 10 tests)

测试统计：

- 39 新增测试全绿（13 service multichannel + 16 schema + 10 node multichannel）
- 28 既有相关测试 0 regression（5 service + 13 node executor + 10 im_jobs）
- 126 既有 IM provider 测试 0 regression（4-05/06/07/08/09 各家 provider 全绿）
- Total ~190 测试涉及通知路径全绿

---

*Phase 04-approval-chain-im — Plan 10*
*Completed: 2026-05-17 (22min)*
