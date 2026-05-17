# IM SDK 阅读笔记 — Plan 04-09 Slack + Mattermost + 通用 Webhook IMProviders

> 日期: 2026-05-17
> 范围: Slack Web API + Mattermost API v4 + 通用 Webhook（自研 HMAC 签名规范）
> 仓库参考:
>   - Slack: https://api.slack.com/methods/chat.postMessage + https://api.slack.com/block-kit
>   - Mattermost: https://api.mattermost.com/ + https://docs.mattermost.com/integrate/plugins/server/api.html
>   - hr/offboarding-flow (`/Users/admin/ai/ref/hr/offboarding-flow/`) — Mattermost driver 已有
>   - Dify (`/Users/admin/ai/ref/dify/repo/`) — 无 IM Provider 抽象（仅 LLM）
> CLAUDE.md §3 SDK 版本基线 — Slack-bolt 1.28.0 / Mattermost httpx 直调

---

## 项目概述（一句话）

为 Slack（Block Kit 卡片 + chat.update）、Mattermost（attachment + post patch）、通用 Webhook（POST JSON + HMAC-SHA256 签名防伪造）三种平台实现 `IMProvider` Protocol，**全部用 httpx 直调 REST API**（不引入 slack-bolt 或 mattermost-driver 重依赖），与 Plan 04-05 的抽象层无缝对接。

---

## 与 Dify 对比

Dify **没有 IM Provider 抽象**（仅 LLM 多厂商接入）。本 plan 借鉴 `api/core/model_runtime/model_providers/` 的**多 provider 抽象设计**（已在 04-05 reading doc 详述，本文不重复）。

**Dify 没有"通用 Webhook"投递通道**，本项目 NOTI-07 独立设计（参考 GitHub / Slack Incoming Webhook / Telegram Bot API 等通用模式）。

---

## hr/offboarding-flow 对比

hr 项目有 Mattermost driver stub（用 `mattermostautodriver`），本 plan **不复用源码**（许可证不同 + 减少依赖），仅借鉴：

| hr 设计 | 本项目对应 |
|---|---|
| `MattermostDriver.posts.create_post(...)` | `httpx.AsyncClient.post("/api/v4/posts", ...)` 直调 |
| `MattermostDriver.posts.patch_post(...)` | `httpx.AsyncClient.put("/api/v4/posts/{id}/patch", ...)` 直调 |
| Driver 内置 access_token cache | 本项目用 bot_token Bearer header（无 OAuth flow，Phase 4 简化） |

**为什么不用 mattermost-driver / mattermostautodriver**：
1. 重依赖（含 websocket 客户端、模型层、自动重连等 — 本项目仅需出站 POST/PUT）
2. httpx 已是项目核心依赖（v0.28.1，与 FastAPI/asyncpg 共用 connection pool）
3. 测试用 pytest-httpx 直接 mock HTTP 调用更简单（不需要 driver 内部 mock）

---

## Slack Web API 速查

### 凭据

- `SLACK_BOT_TOKEN`：Bot User OAuth Token（`xoxb-...`）
- 通过 Header `Authorization: Bearer xoxb-...` 传递

### 核心 API

| API | Method | Endpoint | 用途 |
|---|---|---|---|
| `chat.postMessage` | POST | `https://slack.com/api/chat.postMessage` | 发送卡片消息（Block Kit） |
| `chat.update` | POST | `https://slack.com/api/chat.update` | 更新已发送的卡片（**关键差异点：Slack 支持 update**） |
| `chat.postMessage` | POST | 同上 | 发送补充文本（不带 blocks，仅 text 参数） |

**所有 API 返回 JSON**：
```json
{
  "ok": true,            // 成功标志
  "ts": "1234567890.123456",  // message_id（用于后续 chat.update）
  "channel": "C123ABC456",
  "message": { ... }     // 原始消息体
}
```

失败：`{"ok": false, "error": "channel_not_found" / "invalid_auth" / ...}`

### Block Kit 卡片结构

```python
blocks = [
    {"type": "header", "text": {"type": "plain_text", "text": "审批待办：员工入职"}},
    {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": "*节点*\nHR 审批"},
            {"type": "mrkdwn", "text": "*申请人*\n张三"},
            {"type": "mrkdwn", "text": "*审批人*\n李四"},
            {"type": "mrkdwn", "text": "*截止时间*\n2026-05-18 18:00"},
        ],
    },
    {"type": "section", "text": {"type": "mrkdwn", "text": "*详情*\n请审批 ..."}},
    {"type": "divider"},
    {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "同意"},
                "url": "https://example.com/hitl/page/<jwt>?op=approve",
                "style": "primary",   # primary / danger / default(无)
            },
            # ... return / reject / detail
        ],
    },
]
```

**Style 映射**：
- `approve` → `"primary"`（蓝色按钮）
- `reject` → `"danger"`（红色按钮）
- `return` / `detail` → 不设 style（默认）

### 错误处理

- HTTP 200 + `ok: false` → 业务错误（如 invalid_token），抛 `RuntimeError`（不重试）
- HTTP ≥ 500 → 服务端错误，抛 `ConnectionError`（tenacity 重试）
- HTTP 4xx（429 限流除外）→ 抛 `RuntimeError`
- HTTP 429 → 抛 `ConnectionError`（带 Retry-After header，但本 Phase 不主动 honor）

### Update 限制

- Slack `chat.update` 必须传入正确的 `ts` 和 `channel`（postMessage 时返回的）
- 24 小时内可更新；之后返回 `message_not_found`
- 本 Phase 4 不处理 24h 过期（Phase 7 监控）

---

## Mattermost API v4 速查

### 凭据

- `MATTERMOST_URL`：Mattermost 实例 base URL（如 `https://mm.example.com`）
- `MATTERMOST_BOT_TOKEN`：Bot Access Token（`xxxxxxxx...`）
- Header `Authorization: Bearer <bot_token>`

### 核心 API

| API | Method | Endpoint | 用途 |
|---|---|---|---|
| Create Post | POST | `{base_url}/api/v4/posts` | 发送 attachment 消息 |
| Patch Post | PUT | `{base_url}/api/v4/posts/{post_id}/patch` | 更新已发送的卡片 |
| Create Post (text only) | POST | 同上 | 补充文本（不带 props.attachments） |

**Post 请求体**：
```json
{
    "channel_id": "ch_abc123",   // recipient 是 channel_id 或 DM channel id
    "message": "审批待办：员工入职",   // 顶部 fallback 文本
    "props": {
        "attachments": [
            {
                "fallback": "审批待办：员工入职",
                "color": "#2196F3",
                "text": "### 审批待办：...\n\n- **节点**: ...",
                "actions": [
                    {
                        "id": "approve",
                        "name": "同意",
                        "integration": {
                            "url": "https://example.com/hitl/page/<jwt>?op=approve",
                            "context": {"action": "approve"}
                        },
                        "style": "good"   # good / danger / default
                    },
                    # ... return / reject / detail
                ]
            }
        ]
    }
}
```

**响应**：
```json
{
    "id": "post_id_xyz",     // 后续 patch 用
    "create_at": 1234567890000,
    "channel_id": "ch_abc123",
    "message": "...",
    "props": { ... }
}
```

### Patch（update）

```
PUT /api/v4/posts/<post_id>/patch
Body: {"message": "已被 X 审批", "props": {"attachments": [...]}}
```

只需传入要更新的字段，其他保留。

### Style 映射

- `approve` → `"good"`（绿色）
- `reject` → `"danger"`（红色）
- `return` / `detail` → `"default"`

---

## 通用 Webhook 速查（自研 NOTI-07）

### 设计目标

让用户配置任意 HTTP endpoint URL，本系统 **POST JSON payload** + **HMAC-SHA256 签名 header** 防伪造。用户端验签后可接入自有审批系统 / 自动化平台 / 自有 IM。

### 凭据

- `WEBHOOK_DELIVERY_URL`：用户配置的 HTTPS URL（Phase 4 全局；多 URL 留 Phase 6 workspace 级）
- HMAC 密钥 = `HMAC_SECRET`（与 JWT 共用，已在 startup_checks 校验 ≥ 32 字节）

### 请求

```
POST <WEBHOOK_DELIVERY_URL>
Headers:
  Content-Type: application/json
  X-Agent-Builder-Signature: <hmac_sha256_hex_64chars>
  X-Agent-Builder-Event: hitl_decision_required  // 或 hitl_supplement / hitl_card_update
Body:
{
    "event": "hitl_decision_required",
    "instance_id": "...",
    "node_state_id": "...",
    "flow_title": "员工入职",
    "node_title": "HR 审批",
    "applicant_name": "张三",
    "actor_name": "李四",
    "deadline_at": "2026-05-18T18:00:00Z",
    "description": "请审批 ...",
    "deeplinks": [
        {"action": "approve", "url": "..."},
        {"action": "return", "url": "..."},
        {"action": "reject", "url": "..."},
        {"action": "detail", "url": "..."}
    ]
}
```

### HMAC 签名计算

```python
import hmac
import hashlib
import json
import os

payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
signature = hmac.new(
    key=os.environ["HMAC_SECRET"].encode("utf-8"),
    msg=payload_json,
    digestmod=hashlib.sha256,
).hexdigest()  # 64 字符
```

**关键点**：
- `sort_keys=True`：保证 JSON 字段顺序稳定（用户端可复现）
- `separators=(",", ":")`：紧凑序列化（避免空格差异）
- Body 必须用相同字节序列发送（先序列化再签名再发）

### 用户端验签示例

```python
# 用户接收端伪码
import hmac, hashlib

raw_body = request.body                              # 原始字节
sig = request.headers["X-Agent-Builder-Signature"]
expected = hmac.new(
    key=os.environ["HMAC_SECRET"].encode("utf-8"),
    msg=raw_body,
    digestmod=hashlib.sha256,
).hexdigest()
if not hmac.compare_digest(sig, expected):
    return 403
```

### 行为差异

- `update_card`：抛 `NotImplementedError`（用户自定义 webhook 一般不支持 update — Phase 4.5 可选添加 `event=hitl_card_update` POST）
- `send_supplement_text`：再 POST 一份新 payload，`event="hitl_supplement"`，body 仅含 `text` 字段
- 失败（HTTP ≥ 500 / 网络错误）→ 抛 `ConnectionError`（tenacity 重试）
- 业务错误（HTTP 4xx）→ 抛 `RuntimeError`（不重试）

---

## 可借鉴的设计模式

| 模式 | 实现位置 | 借鉴自 |
|---|---|---|
| **httpx.AsyncClient 直调 REST API** | 3 个 provider 通用 | hr/offboarding-flow（Mattermost driver 简化版） |
| **Authorization: Bearer Token** | Slack / Mattermost | OAuth 2.0 标准 |
| **HMAC-SHA256 签名 + sort_keys 稳定序列化** | WebhookProvider | GitHub Webhook signature 模式 |
| **provider.supports_card_update 属性** | 各 Provider 类 | Phase 4 CONTEXT 设计 — 决策后是否调 update 还是 send_supplement |
| **错误分级**：5xx → ConnectionError（重试），4xx → RuntimeError（业务错误，不重试） | 3 个 provider 通用 | Phase 3 email_jobs 模式 |
| **`{"ok": false}` 业务错误识别** | SlackProvider | Slack Web API 风格特有 |

---

## 与本项目的关系

| Plan | 借鉴方式 |
|---|---|
| 04-09 Slack | httpx 直调 chat.postMessage + chat.update，Block Kit JSON 构造（不用 slack-bolt） |
| 04-09 Mattermost | httpx 直调 /api/v4/posts + /api/v4/posts/{id}/patch，attachment JSON 构造 |
| 04-09 Webhook | 通用 POST + HMAC-SHA256 签名 + 自定义 event 字段 |
| 04-10（下游） | im_jobs.send_hitl_card_job 调用本 plan 3 个 provider，无需修改 |

### 关键决策

1. **不引入 slack-bolt / mattermost-driver**：用 httpx 直调，3 个 provider 共用一种调用模式（CLAUDE.md immutability：每个调用创建新 httpx.AsyncClient with 超时）
2. **PROVIDER_WEBHOOK 新增到 base.py KNOWN_PROVIDERS**：从 5 家扩到 6 家
3. **WebhookCredentials 新增到 im_credentials.py**：环境变量 `WEBHOOK_DELIVERY_URL`
4. **HMAC 签名复用 HMAC_SECRET**：与 JWT 共用（已在 startup_checks 强制 ≥ 32 字节）
5. **supports_card_update 属性**：Slack ✓ / Mattermost ✓ / Webhook ✗

### 反模式（违反规则会返工）

- 拷贝 slack-sdk 源码或 mattermost-driver 源码（许可证 / 重依赖）
- 在抽象层（providers/base.py）import 任何 SDK
- 在 WebhookProvider 内修改 HMAC_SECRET 派生密钥（用 HMAC_SECRET 自身签名即可）
- 跳过 sort_keys=True（导致用户端验签失败 — Python dict 顺序在 3.7+ 是插入顺序，但 JSON 序列化时若未 sort_keys 会导致 dict 字段顺序差异）

---

## 测试策略

- **单元测试**（CardBuilder 3 个）：
  - 输入 HitlCardPayload → 输出符合各家 JSON schema 的 dict
  - 测试 button style 映射（approve→primary/good，reject→danger）
  - 测试 4 个标准 action 全部生成 button/action
- **集成测试**（3 个 Provider）：
  - 用 pytest-httpx mock REST API 返回
  - 验证 URL / Headers（含 Bearer token / HMAC 签名）/ JSON Body 正确
  - 验证 update_card / send_supplement_text 路径
  - 验证错误响应 → ConnectionError（重试）/ RuntimeError（不重试）
  - WebhookProvider 特有：HMAC 签名 round-trip 验签测试（自验签确保算法对）
- 不依赖外部网络（CI 友好）

---

## 风险与权衡

| 风险 | 缓解 |
|---|---|
| Slack chat.update 24h 限制 | Phase 7 监控 + Phase 4.5 fallback send_supplement_text |
| Mattermost 用户没安装 Bot → channel_id 不可知 | Phase 5 IM 目录同步实现 user→channel 解析 |
| Webhook 用户端解析失败（如 schema 变更） | event 字段加版本号 `event="hitl_decision_required.v1"`（Phase 6 引入） |
| HMAC 密钥泄漏 → 用户端被伪造请求 | HMAC_SECRET 已在 startup_checks 强制 ≥ 32 字节，运维通过 secret manager 注入 |
| httpx 默认超时太长 | 显式传 `httpx.Timeout(10.0)` |

---

*Reading doc completed: 2026-05-17 — Plan 04-09 IMProviders*
