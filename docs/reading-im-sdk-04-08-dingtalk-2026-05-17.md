# 钉钉 IM SDK 阅读笔记 — DingTalkProvider (Plan 04-08)

> 日期: 2026-05-17
> 仓库: https://github.com/open-dingtalk/dingtalk-stream-sdk-python (pip dingtalk-stream==0.24.3)
> 文档: https://open.dingtalk.com/document/orgapp/the-message-types-and-data-format
> 文档: https://open.dingtalk.com/document/orgapp/get-access-token
> 文档: https://open.dingtalk.com/document/orgapp/the-work-notice-sends-the-card-asynchronously

---

## 项目概述

`dingtalk-stream` 是阿里钉钉官方维护的 **stream 模式 + 主动消息发送** SDK，主打长连接接收 webhook 事件（机器人 callback）。
针对 Phase 4 **出站投递** 场景，我们只用到 SDK 的 `Credential` + `DingTalkStreamClient.get_access_token`；
**真正的 ActionCard 投递走 OAPI HTTP 接口**（SDK 不直接暴露工作通知发送方法）。

---

## 技术栈关键事实

- **包版本锁定**：`dingtalk-stream==0.24.3` (CLAUDE.md §3)
- **依赖**：`requests` (同步), `websockets` (stream 模式)；本项目 Phase 4 仅用 token 获取 + httpx 直调 OAPI
- **API 风格**：SDK 内部用 `requests` 同步；本项目用 `asyncio.to_thread` 包装或直接用 `httpx.AsyncClient` 调 OAPI
- **认证**：`appKey + appSecret` → `POST /v1.0/oauth2/accessToken` → `accessToken`（钉钉新版 OAuth2，旧版 `gettoken` 已弃用）

---

## 架构要点

### dingtalk-stream SDK 关键类

```
Credential(client_id=app_key, client_secret=app_secret)
  ↓
DingTalkStreamClient(credential, logger)
  ├─ get_access_token() → str | None  ← 内部 token 缓存（5min 提前过期）
  ├─ start_forever() / start()         ← Phase 4.5 stream 接收 webhook 时用
  ├─ register_callback_handler()        ← Phase 4.5 入站事件处理
  └─ open_connection() / keepalive()    ← stream 长连接维护
```

### ActionCard 消息结构（关键：本项目用）

钉钉工作通知 ActionCard 走 `POST /topapi/message/corpconversation/asyncsend_v2`（旧版）
或 `POST /v1.0/robot/groupMessages/send`（机器人）。Phase 4 我们用**工作通知**：

```json
{
  "agent_id": 123456,
  "userid_list": "user_id_1",
  "msg": {
    "msgtype": "action_card",
    "action_card": {
      "title": "审批待办：员工入职流程",
      "markdown": "### 审批待办...\n**节点**: HR 审批\n...",
      "single_title": null,
      "single_url": null,
      "btn_orientation": "0",
      "btn_json_list": [
        {"title": "同意", "action_url": "https://app.example.com/hitl/page/<jti>"},
        {"title": "退回", "action_url": "https://app.example.com/hitl/page/<jti>"},
        {"title": "拒绝", "action_url": "https://app.example.com/hitl/page/<jti>"}
      ]
    }
  }
}
```

**关键字段**：
- `msgtype: "action_card"` （下划线分隔 — 注意 vs 飞书的驼峰）
- `btn_orientation: "0"` 横排，`"1"` 竖排
- `single_title + single_url` vs `btn_json_list` **互斥**：要么 1 个跳转按钮，要么多个按钮列表
- 钉钉每个按钮**只能挂 URL**（无表单交互）— 与本项目 Web 决策页方案 100% 匹配

### 错误码

| code  | 说明                          | 处理 |
|-------|-------------------------------|------|
| 40078 | access_token 过期             | 重新获取 token 重试 |
| 40014 | access_token 无效             | 重新获取 |
| 60011 | userid 不存在                 | 业务错误，不重试 |
| 41030 | userid_list 超过 100          | 业务错误（本项目单用户投递） |
| -1    | 网络/超时                     | ConnectionError → tenacity 重试 |

### update_card 能力

**钉钉工作通知 ActionCard 是静态卡片，不支持发送后修改**（与企微类似）。
- 本项目 `update_card` → `raise NotImplementedError`
- 04-10 multichannel fan-out 决策推进后通过 `send_supplement_text` 发"流程已被 X 处理"补通知

钉钉**互动卡片（AI Card / Markdown Card Instance）**支持 update（`AICardReplier.update_card`），
但仅限**群机器人**场景，不适用于工作通知。Phase 4 不实现，留 Phase 4.5 IM Bot Trigger 评估。

---

## 可借鉴的设计模式

### 1. SDK Credential 简洁包装（dingtalk-stream credential.py 16 行）

```python
class Credential(object):
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
```

**借鉴点**：与本项目 `DingTalkCredentials(app_key, app_secret)` frozen dataclass 几乎一致，
但我们用 `@dataclass(frozen=True)` 强制 immutability — 比 SDK 的 plain class 更安全。

### 2. Token 缓存（dingtalk-stream stream.py:get_access_token）

```python
# SDK 内部缓存 access_token + 5min buffer
self._access_token = {'accessToken': '...', 'expireTime': now + 7200 - 300}
```

**借鉴点**：5min 提前过期 buffer 避免 token 临过期失败 — 本项目 DingTalkProvider 沿用此策略。
不重复实现：**直接调 `DingTalkStreamClient.get_access_token` 拿缓存**，无需自管。

### 3. 同步 SDK + async 业务的整合

SDK 用 `requests` 同步；本项目业务全 async。两种方案：
- **方案 A**：用 `asyncio.to_thread(client.get_access_token)` 包装（简单，但每次创建线程开销）
- **方案 B**：完全跳过 SDK get_access_token，自己用 `httpx.AsyncClient` 直接 POST OAuth endpoint（无 SDK 依赖）

**本项目选方案 A**：保留 SDK 依赖（SDK 锁版本 + 复用 token 缓存逻辑），单点 `to_thread` 调用成本可忽略。

### 4. ActionCard JSON 构造（独立 cards/dingtalk_card.py 模块）

按 04-05 抽象：`CardBuilder` Protocol → DingTalkCardBuilder → `build_hitl_card(payload) -> dict`。
本项目 `dingtalk_card.py` 模块：
- `build_dingtalk_action_card()` 函数式构造（无状态，pure function）
- 内部映射 `deeplink.action` ('approve'/'return'/'reject') → 中文按钮 label ('同意'/'退回'/'拒绝')
- `btn_orientation: "0"` 硬编码横排（决策板：横排在钉钉 PC + 手机端均可显示完整 3 按钮）

---

## 与本项目的关系

### Plan 04-08 (DingTalkProvider) 实现要点

**模块组织**：
```
backend/app/agent_builder/notification/
  ├─ providers/
  │   ├─ base.py        ← Plan 04-05 IMProvider Protocol（已有）
  │   ├─ mock.py        ← Plan 04-05 MockIMProvider（已有）
  │   └─ dingtalk.py    ← 本 plan 新增 DingTalkProvider
  └─ cards/
      ├─ base.py        ← Plan 04-05 HitlCardPayload + CardBuilder Protocol（已有）
      └─ dingtalk_card.py  ← 本 plan 新增 build_dingtalk_action_card
```

**DingTalkProvider 实现要点**：

1. **构造**：接受 `DingTalkCredentials` + agent_id (int) + 可选 `http_client` (httpx) — 测试可注入
2. **send_hitl_card** 流程：
   - 调 `_get_access_token()` （asyncio.to_thread wrapping SDK）
   - 用 `build_dingtalk_action_card` 构造 ActionCard JSON
   - `POST https://api.dingtalk.com/topapi/message/corpconversation/asyncsend_v2?access_token=...`
   - 解析 `errcode == 0` → 提取 `task_id` 作为 message_id
   - `errcode != 0` → raise ConnectionError（含 errcode + errmsg）
3. **update_card**：`raise NotImplementedError("钉钉 ActionCard 工作通知不支持 update — 调用 send_supplement_text")`
4. **send_supplement_text**：发送 `msgtype="text"` 工作通知
5. **subscribe / verify_webhook_signature**：Phase 4.5 留 `NotImplementedError`

**Card Builder 实现要点**：

```python
def build_dingtalk_action_card(payload: HitlCardPayload) -> dict:
    markdown = (
        f"### 审批待办：{payload.flow_title}\n\n"
        f"**节点**: {payload.node_title}\n\n"
        f"**申请人**: {payload.applicant_name}\n\n"
        f"**审批人**: {payload.actor_name}\n\n"
        f"**截止时间**: {payload.deadline_at}\n\n"
        f"**详情**:\n{payload.description}\n"
    )
    btn_json_list = [
        {
            "title": _zh_label_for(dl["action"]),
            "action_url": dl["url"],
        }
        for dl in payload.deeplinks
    ]
    return {
        "msgtype": "action_card",
        "action_card": {
            "title": f"审批待办：{payload.flow_title}",
            "markdown": markdown,
            "btn_orientation": "0",
            "btn_json_list": btn_json_list,
        },
    }

_ZH_LABELS = {
    "approve": "同意",
    "return": "退回",
    "reject": "拒绝",
    "detail": "查看详情",
}
```

### 测试策略

**单元测试** (`test_dingtalk_card_builder.py` ≥ 3 用例)：
1. `test_build_card_contains_action_card_msgtype`
2. `test_build_card_btn_orientation_horizontal_string_zero`
3. `test_build_card_markdown_contains_all_fields`
4. `test_build_card_btn_labels_chinese_for_known_actions`
5. `test_build_card_with_empty_deeplinks_returns_empty_btn_list`
6. `test_build_card_returns_dict_not_mutates_payload`

**集成测试** (`test_dingtalk_provider.py` ≥ 7 用例)：
1. `test_dingtalk_provider_implements_improvider_protocol` (runtime_checkable)
2. `test_dingtalk_provider_name_is_dingtalk`
3. `test_send_hitl_card_calls_oapi_with_correct_payload` (monkeypatch httpx + SDK)
4. `test_send_hitl_card_returns_message_id_from_task_id`
5. `test_send_hitl_card_raises_connection_error_on_oapi_errcode_nonzero`
6. `test_send_hitl_card_raises_connection_error_on_network_failure`
7. `test_update_card_raises_not_implemented_with_supplement_hint`
8. `test_send_supplement_text_uses_text_msgtype`
9. `test_send_hitl_card_unknown_action_uses_raw_label`
10. `test_send_hitl_card_calls_get_access_token_before_send`

---

## 关键决策（决策板提取）

| 决策 | 选择 | 理由 |
|------|------|------|
| OAPI 调用方式 | httpx 直调 OAPI HTTP | SDK 无原生工作通知 ActionCard send；OAPI 直调控制粒度高 |
| Token 获取 | `asyncio.to_thread(client.get_access_token)` | 保留 SDK 依赖锁定 + 复用 5min buffer 缓存逻辑 |
| ActionCard 字段 | `btn_orientation="0"` (横排) + `btn_json_list` (3 按钮) | 钉钉 PC + 手机端最佳兼容性 |
| update_card | 抛 NotImplementedError | 工作通知 ActionCard 静态；走 send_supplement_text 补通知 |
| Action label | 'approve'→'同意' / 'return'→'退回' / 'reject'→'拒绝' / 未知→原 action | 中文 UI 默认（CLAUDE.md §4.3 i18n v1 不做） |
| 错误包装 | OAPI errcode != 0 → ConnectionError | 触发 im_jobs tenacity 3 次重试（与企微/飞书一致） |
| HTTP client | httpx.AsyncClient 注入式（默认创建） | 测试可 monkeypatch；与 04-05 抽象层一致 |
| API endpoint | `/topapi/message/corpconversation/asyncsend_v2` (旧版) | 字段更稳定；新版 `/v1.0/robot/oToMessages/batchSend` 留 Phase 5 评估 |

---

## 与企微 (04-07) / 飞书 (04-06) 的差异

| Feature       | 钉钉 ActionCard          | 企微 Template Card        | 飞书 Interactive Card  |
|---------------|--------------------------|---------------------------|------------------------|
| 卡片类型      | action_card              | template_card             | interactive            |
| 按钮组        | btn_json_list (action_url) | button_list (跳转)        | actions block (URL)    |
| 横排支持      | btn_orientation="0"      | 自动                       | actions.layout         |
| update_card   | ❌ 静态                  | ❌ 静态                   | ✅ patch_card           |
| Markdown      | ✅ markdown 字段         | ❌ 字段化 text_notice     | ✅ markdown element     |
| SDK 调用      | OAPI HTTP                 | wechatpy API              | lark_oapi.Client       |

**统一抽象**：3 家都通过 `IMProvider.send_hitl_card` 接受同一 `HitlCardPayload`，各自 CardBuilder 映射到原生卡片字段。

---

## 安全/许可证

- dingtalk-stream==0.24.3 是 **Apache-2.0**（兼容本项目）
- 钉钉 OAPI 公开文档无许可证限制
- 凭据通过 `IMCredentialsManager.dingtalk()` 获取（env: DINGTALK_APP_KEY / DINGTALK_APP_SECRET / DINGTALK_AGENT_ID）
- access_token 不写日志（日志脱敏规则覆盖 'token' 关键字）

---

*Plan 04-08 reading doc — Phase 4 Wave 4*
*Read 2026-05-17 by Claude executor*
