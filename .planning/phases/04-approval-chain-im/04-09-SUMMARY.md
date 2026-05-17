---
phase: 04-approval-chain-im
plan: "09"
subsystem: notification-im
tags: [im-provider, slack, mattermost, webhook, hmac-signature, block-kit, attachment, httpx]
dependency_graph:
  requires:
    - 04-05 (IMProvider Protocol + Registry + IMCredentialsManager + CardBuilder Protocol)
  provides:
    - SlackProvider（httpx 直调 Slack Web API + Block Kit）
    - MattermostProvider（httpx 直调 /api/v4/posts + attachment）
    - WebhookProvider（通用 POST JSON + HMAC-SHA256 签名 — NOTI-07）
    - SlackCardBuilder / MattermostCardBuilder / WebhookCardBuilder
    - PROVIDER_WEBHOOK 常量（扩展 KNOWN_PROVIDERS 从 5 家到 6 家）
    - WebhookCredentials @dataclass(frozen=True) + IMCredentialsManager.webhook()
    - compute_signature / verify_signature / serialize_payload 签名工具
    - 3 个 Webhook event 常量（hitl_decision_required / hitl_supplement / hitl_card_update）
  affects:
    - Wave 5 plan 04-10（多通道 fan-out）— 直接使用 register_provider 注册 3 个 provider
    - Plan 04-05 已建抽象层（无修改，仅扩展 PROVIDER_WEBHOOK + WebhookCredentials）
tech-stack:
  added:
    - "httpx>=0.28.1 已在项目依赖；不引入 slack-bolt / mattermost-driver / mattermostautodriver"
  patterns:
    - "httpx.AsyncClient with timeout 直调 REST API（3 个 provider 通用调用模式）"
    - "Authorization: Bearer Token header（Slack / Mattermost）"
    - "HMAC-SHA256 签名 + sort_keys 稳定序列化（Webhook，仿 GitHub Webhook 模式）"
    - "错误分级：5xx/429/网络错误 → ConnectionError；4xx → RuntimeError（业务错误不重试）"
    - "Slack 业务错误细分：ok=false + (ratelimited|timeout|service_unavailable|fatal_error) → ConnectionError 触发重试"
    - "supports_card_update 属性：Slack ✓ / Mattermost ✓ / Webhook ✗"
    - "@dataclass(frozen=True) 凭据（CLAUDE.md immutability）"
    - "tuple(deeplinks) 转换（保证 HitlCardPayload immutable）"
    - "hmac.compare_digest 防时序攻击"
key-files:
  created:
    - backend/app/agent_builder/notification/cards/slack_card.py (113 行)
    - backend/app/agent_builder/notification/providers/slack.py (218 行)
    - backend/app/agent_builder/notification/cards/mattermost_card.py (108 行)
    - backend/app/agent_builder/notification/providers/mattermost.py (218 行)
    - backend/app/agent_builder/notification/cards/webhook_payload.py (118 行)
    - backend/app/agent_builder/notification/providers/webhook.py (231 行)
    - backend/tests/test_slack_card_builder.py (137 行, 8 测试)
    - backend/tests/test_slack_provider.py (231 行, 11 测试)
    - backend/tests/test_mattermost_card_builder.py (130 行, 8 测试)
    - backend/tests/test_mattermost_provider.py (235 行, 13 测试)
    - backend/tests/test_webhook_provider.py (336 行, 19 测试)
    - docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md (349 行)
  modified:
    - backend/app/agent_builder/notification/providers/base.py (加 PROVIDER_WEBHOOK + KNOWN_PROVIDERS 6 家)
    - backend/app/agent_builder/notification/providers/__init__.py (导出 PROVIDER_WEBHOOK)
    - backend/app/agent_builder/core/im_credentials.py (加 WebhookCredentials + webhook() getter + has_webhook + list_configured 包含 webhook)
    - backend/tests/test_im_provider_protocol.py (test_known_providers_frozenset_contains_5 → 6)
    - backend/tests/test_im_credentials_loader.py (test_load_warns_on_missing/no_warning 加 webhook 断言 + autouse fixture 加 WEBHOOK_DELIVERY_URL)
decisions:
  - "[Phase 04-09] 3 个 provider 全部用 httpx 直调 REST API — 不引入 slack-bolt 与 mattermost-driver 重依赖（CLAUDE.md 项目 dep 精简原则；httpx 已是 FastAPI / asyncpg / pytest-httpx 共用）"
  - "[Phase 04-09] [Rule 3 - Blocking] slack-bolt 1.28.0 SDK 未安装且 plan 仅需 chat.postMessage / chat.update 2 个 API，用 httpx 等价实现，无功能损失 + 减少 13MB 依赖"
  - "[Phase 04-09] Slack message_id 编码为 'channel:ts' 复合字符串（chat.update 需要两者，但 Protocol 只返回 str）"
  - "[Phase 04-09] Mattermost message_id 用原生 post id（patch 端点用 path 参数 /api/v4/posts/{id}/patch）"
  - "[Phase 04-09] WebhookProvider HMAC 签名复用项目 HMAC_SECRET（已在 startup_checks 校验 ≥ 32 字节，不引入新密钥管理）"
  - "[Phase 04-09] serialize_payload 用 sort_keys=True + separators=(',', ':') 保证用户端可复现验签（GitHub Webhook 模式）"
  - "[Phase 04-09] signature header 名 'X-Agent-Builder-Signature'（项目特定，避免与 X-Hub-Signature/X-Webhook-Signature 等通用命名冲突）"
  - "[Phase 04-09] WebhookProvider.update_card 抛 NotImplementedError 而非静默 no-op：调用方应路由到 send_supplement_text"
  - "[Phase 04-09] Webhook event 字段独立 envelope（不是 query/header）— 用户端解析更直接"
  - "[Phase 04-09] PROVIDER_WEBHOOK 加入 KNOWN_PROVIDERS：6 家而非 5 家 — 必须修改 04-05 现有 test_known_providers_frozenset_contains_5 → 6"
  - "[Phase 04-09] WebhookCredentials 仅承载 delivery_url（HMAC_SECRET 走 env，不入 dataclass）"
  - "[Phase 04-09] Slack 业务错误细分：ok=false + (ratelimited|timeout|service_unavailable|fatal_error) → ConnectionError 触发重试；其他 invalid_auth/channel_not_found → RuntimeError 立即失败"
  - "[Phase 04-09] Mattermost base_url 自动 strip 尾部 / —防用户配置错"
  - "[Phase 04-09] WebhookProvider 显式 hmac_secret 参数 + env fallback：测试可隔离；生产从 env 读"
  - "[Phase 04-09] [Rule 1 - Bug] test_card_builder_satisfies_card_builder_protocol 改用 callable/attribute 断言（CardBuilder 是非 runtime_checkable Protocol，不能用 isinstance）"
metrics:
  duration: "16min"
  completed_date: "2026-05-17"
---

# Phase 4 Plan 09: Slack + Mattermost + 通用 Webhook IMProviders Summary

**一句话**: 3 个 IM Provider 一并实现 — Slack (NOTI-05, Block Kit + chat.update) / Mattermost (NOTI-06, attachment + post patch) / 通用 Webhook (NOTI-07, POST JSON + HMAC-SHA256 签名)，全部用 httpx 直调 REST API 不引入重 SDK，59 单元测试全绿 (Slack 19 + Mattermost 21 + Webhook 19)；KNOWN_PROVIDERS 扩展到 6 家，Plan 04-05 抽象层完全向后兼容。

---

## 完成的工作

### 1. SlackProvider + SlackCardBuilder（NOTI-05）

新增 `backend/app/agent_builder/notification/{providers,cards}/slack*.py`：

**Block Kit 卡片结构**：
- header（"审批待办：{flow_title}"）
- section with fields（节点 / 申请人 / 审批人 / 截止时间）
- section with description
- divider
- actions block（4 个 button）

**按钮样式映射**：
- `approve` → `style="primary"`（蓝）
- `reject` → `style="danger"`（红）
- `return` / `detail` → 无 style 字段（默认）

**SlackProvider 关键设计**：
- httpx 直调 `https://slack.com/api/chat.postMessage` 与 `chat.update`
- `Authorization: Bearer xoxb-...` header
- message_id 复合编码 `"channel:ts"`（chat.update 需要两者）
- 错误分级：
  - HTTP 5xx / 429 → `ConnectionError`（tenacity 重试）
  - HTTP 4xx → `RuntimeError`（不重试）
  - HTTP 200 + `ok: false`：
    - `ratelimited` / `timeout` / `service_unavailable` / `fatal_error` → `ConnectionError`（重试）
    - 其他（`invalid_auth` / `channel_not_found` / ...）→ `RuntimeError`
- `supports_card_update = True`

### 2. MattermostProvider + MattermostCardBuilder（NOTI-06）

新增 `backend/app/agent_builder/notification/{providers,cards}/mattermost*.py`：

**Attachment 结构**：
- `message`（顶部 fallback 文本）
- `props.attachments[0]`：
  - `fallback` / `color="#2196F3"` / `text` (Markdown ### + bullet list)
  - `actions[]`：4 个 button 含 `integration.url` + `context.action`

**按钮样式映射**：
- `approve` → `style="good"`（绿）
- `reject` → `style="danger"`（红）
- `return` / `detail` → `style="default"`

**MattermostProvider 关键设计**：
- httpx 直调 `POST {base_url}/api/v4/posts` + `PUT {base_url}/api/v4/posts/{id}/patch`
- `Authorization: Bearer <bot_token>` header
- message_id 用原生 Mattermost post id
- `base_url` 自动 strip 尾部 `/`（防配置错）
- 错误分级：5xx/429 → `ConnectionError`；其他 4xx → `RuntimeError`
- `supports_card_update = True`

### 3. WebhookProvider + WebhookCardBuilder（NOTI-07）

新增 `backend/app/agent_builder/notification/{providers,cards}/webhook*.py`：

**通用 envelope schema**：
```json
{
  "event": "hitl_decision_required",  // 或 hitl_supplement / hitl_card_update
  "recipient": "user_xyz",
  "instance_id": "...",
  "node_state_id": "...",
  "flow_title": "...",
  "node_title": "...",
  "applicant_name": "...",
  "actor_name": "...",
  "deadline_at": "...",
  "description": "...",
  "deeplinks": [{action, url}, ...]
}
```

**HMAC-SHA256 签名机制**：
- 密钥：复用项目 `HMAC_SECRET`（startup_checks 已校验 ≥ 32 字节）
- 序列化：`json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")`
- 签名：`hmac.new(secret, body, sha256).hexdigest()` → 64 字符 hex
- Headers:
  - `X-Agent-Builder-Signature: <64 hex>`
  - `X-Agent-Builder-Event: hitl_decision_required` / `hitl_supplement`
  - `Content-Type: application/json`
- 用户端验签（参考 reading doc）：用相同 sort_keys 复现 body，`hmac.compare_digest`

**WebhookProvider 关键设计**：
- `update_card` 抛 `NotImplementedError`（通用 webhook 无 update 概念）
- `send_supplement_text` → POST 新 envelope（`event="hitl_supplement"`，body 仅含 `text`）
- 错误分级：5xx/429/网络错误 → `ConnectionError`；4xx → `RuntimeError`
- `supports_card_update = False`
- 构造参数 `hmac_secret` 显式 + env 回退（测试隔离）

**导出辅助函数**（供用户端 SDK 复用）：
- `compute_signature(payload_bytes, secret) -> str`
- `verify_signature(payload_bytes, signature, secret) -> bool`
- `serialize_payload(payload) -> bytes`

### 4. 抽象层扩展（PROVIDER_WEBHOOK + WebhookCredentials）

- `PROVIDER_WEBHOOK = "webhook"` 加入 `KNOWN_PROVIDERS` frozenset（5 家 → 6 家）
- `WebhookCredentials @dataclass(frozen=True)` — 仅 `delivery_url` 字段（HMAC_SECRET 走 env）
- `IMCredentialsManager`：
  - `_webhook` 字段 + `_load_from_env` 读取 `WEBHOOK_DELIVERY_URL`
  - `webhook() -> WebhookCredentials`（未配置抛 RuntimeError）
  - `has_webhook() -> bool`
  - `list_configured()` 包含 `"webhook"`

---

## 测试结果（59 新增 + 33 既有 = 92 全绿）

### test_slack_card_builder.py（8 用例）

| 测试 | 覆盖点 |
|---|---|
| test_build_blocks_4_buttons | 4 deeplink → 4 button + action_id 编码 |
| test_build_blocks_approve_primary_style | approve → style=primary |
| test_build_blocks_reject_danger_style | reject → style=danger |
| test_build_blocks_no_style_for_return_and_detail | return/detail 无 style 字段 |
| test_block_kit_structure_header_section_actions | header/section/section/divider/actions 顺序 |
| test_card_builder_satisfies_card_builder_protocol | 鸭子类型 attribute / callable |
| test_build_hitl_card_returns_blocks_and_text | dict 含 blocks + text fallback |
| test_build_supplement_text_format | "已被 X 同意" 格式 |

### test_slack_provider.py（11 用例）

| 测试 | 覆盖点 |
|---|---|
| test_slack_provider_satisfies_improvider_protocol | IMProvider 鸭子类型 |
| test_supports_card_update_is_true | True |
| test_constructor_rejects_empty_bot_token | ValueError |
| test_send_hitl_card_posts_to_chat_postMessage | POST + headers + body |
| test_send_hitl_card_returns_ts_and_channel_as_message_id | "channel:ts" 复合 |
| test_send_hitl_card_5xx_raises_connection_error | 503 → ConnectionError |
| test_send_hitl_card_ok_false_raises_runtime_error | invalid_auth → RuntimeError |
| test_send_hitl_card_ok_false_ratelimited_raises_connection_error | ratelimited → ConnectionError |
| test_update_card_calls_chat_update_with_channel_and_ts | chat.update path |
| test_update_card_rejects_malformed_message_id | 无 : 抛 ValueError |
| test_send_supplement_text_uses_chat_postMessage_without_blocks | 仅 text 字段 |

### test_mattermost_card_builder.py（8 用例）

| 测试 | 覆盖点 |
|---|---|
| test_build_attachment_4_actions | 4 actions + 必需字段 |
| test_build_attachment_approve_style_good | approve → good |
| test_build_attachment_reject_style_danger | reject → danger |
| test_build_attachment_return_and_detail_default_style | default |
| test_attachment_markdown_text_contains_all_fields | Markdown text 全字段 + color |
| test_build_hitl_card_returns_message_and_props | message + props.attachments |
| test_card_builder_satisfies_card_builder_protocol | 鸭子类型 |
| test_build_supplement_text_format | "已被 X 拒绝" |

### test_mattermost_provider.py（13 用例）

| 测试 | 覆盖点 |
|---|---|
| test_mattermost_provider_satisfies_improvider_protocol | IMProvider 鸭子类型 |
| test_supports_card_update_is_true | True |
| test_constructor_rejects_empty_base_url_or_token | ValueError |
| test_base_url_trailing_slash_stripped | URL 规范化 |
| test_send_hitl_card_posts_to_api_v4_posts | POST + headers + body |
| test_send_hitl_card_returns_post_id_as_message_id | 原生 post id |
| test_send_hitl_card_5xx_raises_connection_error | 503 → ConnectionError |
| test_send_hitl_card_4xx_raises_runtime_error | 404 → RuntimeError |
| test_send_hitl_card_429_raises_connection_error | 429 → ConnectionError |
| test_update_card_uses_patch_endpoint | PUT /api/v4/posts/<id>/patch |
| test_update_card_rejects_empty_message_id | ValueError |
| test_update_card_rejects_empty_new_content | message/props 必传一 |
| test_send_supplement_text_posts_without_attachments | 仅 channel_id + message |

### test_webhook_provider.py（19 用例）

| 测试 | 覆盖点 |
|---|---|
| test_webhook_provider_satisfies_improvider_protocol | IMProvider 鸭子类型 |
| test_supports_card_update_is_false | False |
| test_constructor_rejects_empty_delivery_url | ValueError |
| test_compute_signature_64_hex_chars | hex 64 字符 |
| test_signature_changes_when_payload_changes | payload 变 → sig 变 |
| test_serialize_payload_sort_keys_and_compact | 不同字段顺序 → 相同字节序列 |
| test_verify_signature_round_trip | compute + verify 闭环 |
| test_compute_signature_rejects_empty_secret | 空 secret → RuntimeError |
| test_send_hitl_card_posts_to_delivery_url | POST + body envelope |
| test_send_hitl_card_includes_hmac_signature_header | X-Agent-Builder-Signature 64 hex + Event header |
| test_send_hitl_card_signature_round_trip_verifies | **mock 拦截 request 后用同密钥重算 → 匹配 header** |
| test_send_hitl_card_envelope_contains_required_fields | 11 个必需字段 |
| test_send_hitl_card_returns_message_id | "webhook:<hash>:<recipient>" |
| test_send_hitl_card_5xx_raises_connection_error | 502 → ConnectionError |
| test_send_hitl_card_4xx_raises_runtime_error | 403 → RuntimeError |
| test_send_hitl_card_429_raises_connection_error | 429 → ConnectionError |
| test_update_card_raises_not_implemented | NotImplementedError |
| test_send_supplement_text_posts_supplement_event | event=hitl_supplement |
| test_secret_from_env_when_not_in_constructor | env fallback |

### 既有测试回归（33 用例全绿）

- `test_im_provider_protocol.py`：18 用例（含 KNOWN_PROVIDERS 6 家断言更新）
- `test_im_credentials_loader.py`：15 用例（含 webhook env 断言）
- `test_im_jobs_skeleton.py`：10 集成测试（im_jobs 调用 MockIMProvider，无回归）

**总计 92 测试全绿 in 8.46s（不含集成 PG）**

---

## 凭据 / 环境变量字段映射

| Provider | .env 变量名 | dataclass 字段 |
|----------|------------|----------------|
| slack | `SLACK_BOT_TOKEN` | `bot_token` |
| mattermost | `MATTERMOST_URL`, `MATTERMOST_BOT_TOKEN` | `base_url`, `bot_token` |
| webhook | `WEBHOOK_DELIVERY_URL` | `delivery_url` |

HMAC 签名密钥：`HMAC_SECRET`（与 JWT 共用，全局环境变量；startup_checks 校验 ≥ 32 字节）

---

## Webhook HMAC 签名协议（用户端集成参考）

### 出站 request 格式

```
POST <user-configured-url> HTTP/1.1
Host: user.example.com
Content-Type: application/json
X-Agent-Builder-Signature: <64-char-hex>
X-Agent-Builder-Event: hitl_decision_required

{"actor_name":"李四","applicant_name":"张三","deadline_at":"2026-05-18T18:00:00Z",
"deeplinks":[{"action":"approve","url":"..."}],"description":"请审批",
"event":"hitl_decision_required","flow_title":"员工入职","instance_id":"",
"node_state_id":"","node_title":"HR 审批","recipient":"user_xyz"}
```

注意 body 已 `sort_keys=True`，用户端必须用相同方式序列化才能复现签名。

### 用户端验签伪码（Python）

```python
import hmac
import hashlib
import os

raw_body = request.body                                  # raw bytes
sig_header = request.headers["X-Agent-Builder-Signature"]

expected = hmac.new(
    key=os.environ["HMAC_SECRET"].encode("utf-8"),
    msg=raw_body,
    digestmod=hashlib.sha256,
).hexdigest()

if not hmac.compare_digest(sig_header, expected):
    return 403  # 签名不匹配（防伪造）
```

### 3 个 event 类型

| event | 触发时机 | body 字段 |
|---|---|---|
| `hitl_decision_required` | HITL 节点初次投递 | 完整 envelope（含 deeplinks） |
| `hitl_supplement` | 流程已被其他人处理 | recipient + text |
| `hitl_card_update` | Phase 4.5 预留 | TBD |

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] slack-bolt 1.28.0 未安装 → 改用 httpx 直调 Slack Web API**

- **Found during:** Task 2（pyproject.toml 与运行时检查均无 slack-bolt）
- **Issue:** Plan 04-09 指定 slack-bolt 1.28.0，但项目依赖未含；plan 仅需 chat.postMessage / chat.update 2 个简单 API
- **Fix:** SlackProvider 用 httpx.AsyncClient 直调 `https://slack.com/api/chat.*` REST endpoint；功能等价 + 减少 13MB 依赖 + 与 Mattermost/Webhook 统一调用模式
- **Files modified:** backend/app/agent_builder/notification/providers/slack.py
- **Commit:** 5b9cdbe

**2. [Rule 1 - Bug] CardBuilder 非 runtime_checkable Protocol，test_card_builder_satisfies 用 isinstance 报错**

- **Found during:** Task 2（test_slack_card_builder.py 首次运行）
- **Issue:** `CardBuilder` Protocol 在 04-05 base.py 中未加 `@runtime_checkable`，但 test 用 `isinstance(builder, CardBuilder)` 校验 → `TypeError: Instance and class checks can only be used with @runtime_checkable protocols`
- **Fix:** 改用 `callable(getattr(builder, "build_hitl_card"))` + `assert builder.provider_name == PROVIDER_*` 鸭子类型属性断言；不修改 04-05 抽象层（避免 ripple effect）
- **Files modified:** backend/tests/test_slack_card_builder.py
- **Commit:** 5b9cdbe（同 Slack 提交）

**3. [Rule 3 - Blocking] PROVIDER_WEBHOOK 必须加入 KNOWN_PROVIDERS — 影响 04-05 既有测试**

- **Found during:** Task 1（基础设施扩展）
- **Issue:** Plan 04-05 已硬编码 `len(KNOWN_PROVIDERS) == 5`；本 plan 添加 webhook 必须扩到 6
- **Fix:** 同时更新：
  - `base.py` 加 `PROVIDER_WEBHOOK = "webhook"` 进 frozenset
  - `test_im_provider_protocol.py::test_known_providers_frozenset_contains_5` → `contains_6`
  - `test_im_credentials_loader.py::test_load_warns_on_missing` 加 webhook 断言
  - `test_im_credentials_loader.py::test_load_no_warning_when_all_configured` 加 `WEBHOOK_DELIVERY_URL` env
  - `clear_im_env autouse fixture` 加 `WEBHOOK_DELIVERY_URL` 清理
- **Files modified:** backend/app/agent_builder/notification/providers/base.py, backend/tests/test_im_provider_protocol.py, backend/tests/test_im_credentials_loader.py
- **Commit:** 3f9e21d

### Architectural Decisions

无 Rule 4 架构变更 — 所有改动在 Plan 04-05 抽象层的扩展边界内。

---

## 关键技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Slack SDK 选型 | httpx 直调 REST API | 不引入 slack-bolt（13MB + 与项目 httpx 模式不一致） |
| Mattermost SDK 选型 | httpx 直调 v4 API | 不引入 mattermost-driver（websocket 重依赖 — 出站仅需 POST/PUT） |
| Webhook 签名算法 | HMAC-SHA256（GitHub Webhook 模式） | 业界标准；用户端 stdlib hmac 即可验签 |
| Webhook 签名密钥 | 复用 `HMAC_SECRET` | startup_checks 已校验 ≥ 32 字节；不引入新密钥管理 |
| 序列化稳定性 | `sort_keys=True + separators=(",", ":")` | 用户端 dict 字段顺序可能不同，必须固定 |
| Signature header 名 | `X-Agent-Builder-Signature` | 项目特定（避免与 X-Hub-Signature 等通用名冲突） |
| Event 字段位置 | envelope body + 镜像 header | body 用户解析方便；header 便于路由前置检查 |
| Slack message_id 编码 | `"channel:ts"` 复合字符串 | chat.update 需要两者，Protocol 仅返回 str |
| Slack 业务错误分级 | ok=false + ratelimited/timeout/service_unavailable/fatal_error → ConnectionError | 这些是可恢复错误，应触发 tenacity 重试 |
| Mattermost base_url 处理 | 自动 strip 尾部 `/` | 防用户配置错（`https://mm.example.com/` 与 `https://mm.example.com` 行为一致） |
| WebhookProvider update_card | `NotImplementedError` | 通用 webhook 无 update 语义；调用方应路由到 supplement |
| WebhookCredentials | 仅 `delivery_url` 字段 | HMAC_SECRET 是全局密钥，不入 per-provider dataclass |
| 错误分级通用规则 | 5xx/429/网络 → ConnectionError；其他 4xx → RuntimeError | 与 Phase 3 email_jobs 一致（运维一致性） |

---

## Dify 参考点

详见 `docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md`。

Dify **没有 IM Provider 抽象**（仅 LLM 多厂商接入），本 plan 借鉴 Plan 04-05 已建立的抽象层：

- **Dify 没有"通用 Webhook"投递通道** — NOTI-07 独立设计（参考 GitHub Webhook signature 模式）
- **httpx 直调 vs 重 SDK**：与 04-05 Reading doc 推断的"凭据与实现分离 / 延迟实例化"一致
- **签名算法**：参考 GitHub Webhook 的 `X-Hub-Signature-256`（SHA256 HMAC + hex digest）

**hr/offboarding-flow 对比**：hr 项目有 `MattermostDriver` stub，本 plan 不复用源码（许可证不同 + 减少依赖），仅借鉴接口风格（`send_message` / `update_message`）。

---

## Wave 5 下游依赖（04-10 多通道 fan-out）

| 接入点 | 用法 |
|---|---|
| `register_provider(SlackProvider(...))` | FastAPI lifespan startup |
| `register_provider(MattermostProvider(...))` | 同上 |
| `register_provider(WebhookProvider(...))` | 同上 |
| `get_provider("slack").send_hitl_card(...)` | im_jobs 内已有逻辑（04-05），无需修改 |
| `supports_card_update` 属性 | 04-10 决策后路由：`if provider.supports_card_update: update_card else: send_supplement_text` |

---

## Self-Check: PASSED

文件检查（12 个新建 + 5 个修改）：
- FOUND: backend/app/agent_builder/notification/cards/slack_card.py
- FOUND: backend/app/agent_builder/notification/providers/slack.py
- FOUND: backend/app/agent_builder/notification/cards/mattermost_card.py
- FOUND: backend/app/agent_builder/notification/providers/mattermost.py
- FOUND: backend/app/agent_builder/notification/cards/webhook_payload.py
- FOUND: backend/app/agent_builder/notification/providers/webhook.py
- FOUND: backend/tests/test_slack_card_builder.py
- FOUND: backend/tests/test_slack_provider.py
- FOUND: backend/tests/test_mattermost_card_builder.py
- FOUND: backend/tests/test_mattermost_provider.py
- FOUND: backend/tests/test_webhook_provider.py
- FOUND: docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md
- FOUND (modified): backend/app/agent_builder/notification/providers/base.py
- FOUND (modified): backend/app/agent_builder/notification/providers/__init__.py
- FOUND (modified): backend/app/agent_builder/core/im_credentials.py
- FOUND (modified): backend/tests/test_im_provider_protocol.py
- FOUND (modified): backend/tests/test_im_credentials_loader.py

提交检查（5 个 commit hash）：
- FOUND: 9f420e0（Task 0 reading doc — HARD GATE）
- FOUND: 3f9e21d（Task 1 PROVIDER_WEBHOOK + WebhookCredentials 抽象层扩展）
- FOUND: 5b9cdbe（Task 2 SlackProvider + SlackCardBuilder + 19 测试）
- FOUND: 9afc5c7（Task 3 MattermostProvider + MattermostCardBuilder + 21 测试，含从 parallel plan 一并入的 feishu 文件）
- FOUND: 714980d（Task 4 WebhookProvider + HMAC 签名 + 19 测试）

测试统计：
- 59 新增单元测试全绿（Slack 19 + Mattermost 21 + Webhook 19）
- 33 既有测试回归全绿（18 protocol + 15 credentials，含扩展断言）
- 10 既有集成测试（im_jobs_skeleton）回归全绿
- Total 102 tests pass in 8.46s + 13.00s

---

*Phase 04-approval-chain-im — Plan 09*
*Completed: 2026-05-17 (16min duration)*
