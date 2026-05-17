# IM SDK 阅读笔记 — Plan 04-07 WeComProvider 实现

> 日期: 2026-05-17
> 范围: 企微 (WeCom) IM 出站投递 — wechatpy 1.8.18 + Bot Webhook fallback
> CLAUDE.md §3：`wechatpy==1.8.18`（停更，templated card API 需 spike）
> CLAUDE.md §2.7：参考项目纪律 — 实现前先读 SDK / 官方文档；将发现写入本文档；先 commit 本文档再写代码
> 上游 reading doc：`docs/reading-im-sdk-04-05-providers-2026-05-17.md`（5 家 SDK 总览）

---

## 项目概述（一句话）

为 **企业微信（WeCom）** 实现 `IMProvider` Protocol 出站投递 — 因 wechatpy 1.8.18 停更且
**无现代 template_card API**，最终决策**双路径**：

1. **Primary（app message）**：wechatpy `send_markdown` 应用消息（user-targeted，需 corp_id + agent_id + secret）
2. **Fallback（bot webhook）**：群机器人 webhook（无需 SDK，需 `WECOM_BOT_WEBHOOK_KEY`，仅群投递）

两路径共用同一个 markdown 文本格式（4 个 `[文案](url)` 链接 = 同意/退回/拒绝/详情）。

---

## 技术栈（关键技术选择）

| 项 | 选择 | 理由 |
|---|---|---|
| SDK | `wechatpy==1.8.18` | CLAUDE.md §3 锁定；停更但仍可装 |
| 卡片格式 | **Markdown 消息**（非 template_card） | wechatpy 1.8.18 **没有** template_card API（spike 验证 — 见下方 §Spike 结果） |
| 应用消息 API | `wechatpy.enterprise.WeChatClient.message.send_markdown` | 注意：1.8.18 模块路径是 `enterprise` 不是 `work` |
| Bot Webhook API | `POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}` + `{msgtype: markdown}` | 不需 SDK；用 `httpx.AsyncClient` |
| 异常类 | `wechatpy.exceptions.WeChatClientException` | 包装为 `ConnectionError` 让 `im_jobs` tenacity 重试 |
| 凭据字段 | `corp_id` + `agent_id` + `secret`（应用消息）<br>`bot_webhook_key`（Bot Webhook） | 已在 04-05 `WeComCredentials` 落地（前 3 字段）；本 plan 新增 bot_webhook_key 字段（可选） |
| update_card | **不支持** | 企微应用消息 / Bot Webhook 都没有 update API → `update_card` 抛 `NotImplementedError`；调用方走 `send_supplement_text` 兜底 |
| supports_card_update | `False`（属性） | 让 04-10 fan-out 调用方据此选择 supplement_text |

---

## 架构要点（核心架构模式）

```
┌──────────────────────────────────────────────────────────────────┐
│ im_jobs.send_hitl_card_job (04-05)                              │
│   → get_provider("wecom")                                        │
│   → provider.send_hitl_card(recipient, deeplinks, ...)          │
└──────────────────────┬───────────────────────────────────────────┘
                       ↓
              ┌────────┴────────┐
              │ WeComProvider   │  use_bot_fallback? ──┐
              │ name = "wecom"  │                      │
              └────────┬────────┘                      │
              False    │                      True     │
                       ↓                               ↓
        ┌──────────────────────────┐     ┌────────────────────────┐
        │ _send_via_app_message    │     │ _send_via_bot_webhook  │
        │   wechatpy client        │     │   httpx.AsyncClient    │
        │   .message.send_markdown │     │   POST webhook URL     │
        │   to=user_id (recipient) │     │   to=group (无 recipient)│
        └──────────────────────────┘     └────────────────────────┘
                       │                               │
                       └───── markdown 内容相同 ────────┘
                              build_wecom_app_markdown
                              build_wecom_webhook_markdown
```

**关键决策**：
- 两条路径**共用** `build_wecom_markdown_content` 生成 4 链接 markdown
- 仅外层 envelope 不同（app message vs webhook msgtype）
- 测试可独立 mock wechatpy client 或 httpx_mock，两路径独立覆盖

---

## Spike 结果（Task 1，30min 上限内完成）

**目标**：验证 wechatpy 1.8.18 是否还能调通 templated_card API（CLAUDE.md §3 标注「templated card API 需 spike」）

**方法**：
```python
# 1. 安装 wechatpy==1.8.18
pip install wechatpy==1.8.18

# 2. 检查模块结构
import wechatpy
# wechatpy.__version__ == '1.8.18' ✓
# wechatpy.work 模块不存在 ✗（现代版本路径）
# wechatpy.enterprise 模块存在 ✓（1.8.x 老路径）

# 3. 检查 message API
from wechatpy.enterprise import WeChatClient
client = WeChatClient.__new__(WeChatClient)
# client.message 方法列表：
#   send                ✓
#   send_text           ✓
#   send_markdown       ✓ (支持 [text](url) 链接)
#   send_text_card      ✓ (1 个按钮，btntxt 默认 "详情")
#   send_image / file / voice / video / articles / mp_articles
#   ❌ NO send_template_card
#   ❌ NO send_button_interaction
#   ❌ 整个 send 方法簇内无 'template' 关键字
```

**结论**：
- wechatpy 1.8.18 完全**没有** templated card / button_interaction API
- 老版 SDK 卡片相关只有 `send_text_card`（1 按钮，无法满足 HITL 4 按钮需求）
- `send_markdown` 是唯一能在一条消息内放置**多个可点击链接**的 API（markdown 子集支持 `[text](url)`）

**决策**：
- ❌ 不引入 `wxwork` / `wecom-api` 替代 SDK（增加未审计依赖，停更比维护风险更大；wechatpy 仍能用 markdown 实现等效体验）
- ✅ **采用 markdown 4 链接方案**（主路径 app message + fallback bot webhook）
- ✅ markdown 内容生成器 `build_wecom_markdown_content` 在 app message / bot webhook 间共享
- ✅ Bot Webhook fallback 在凭据不全（缺 corp_id/agent_id/secret 任一）时**自动启用**（如果 bot_webhook_key 已配置）

**衡量**：
- 用户体验：4 个 markdown 链接点击直接跳决策页（与按钮等效，区别仅是视觉样式）
- 兼容性：markdown 子集在 PC 客户端 / 移动端 / 微工作台都支持（仅微工作台不支持 markdown — 但 1.8.18 文档说明此局限，企业用户场景以 PC/Mobile 为主）

---

## 可借鉴的设计模式（具体文件路径 + 模式名 + 一句话说明）

### 1. wechatpy `send_markdown` 内部走 `send` 通用入口

源码：`wechatpy/enterprise/client/api/message.py`

```python
def send_markdown(self, agent_id, user_ids, content, party_ids='', tag_ids=''):
    msg = {"msgtype": "markdown", "markdown": {"content": content}}
    return self.send(agent_id, user_ids, party_ids, tag_ids, msg=msg)
```

**借鉴点**：本 plan 不直接调 `send_markdown`（避免 stub 时还要 patch 一层）；
直接调 `client.message.send(agent_id, user_ids, msg={...})` — 测试 monkeypatch 一处即可。

### 2. wechatpy 异常体系

源码：`wechatpy/exceptions.py`

```python
class WeChatException(Exception): pass
class WeChatClientException(WeChatException): pass  # API 错误
```

**借鉴点**：在 `WeComProvider._send_via_app_message` 中 catch `WeChatClientException` →
重新抛为 `ConnectionError`（im_jobs tenacity 仅重试 ConnectionError/TimeoutError/OSError，
业务错误如 `invalid corpid` 会被识别为 network error 而重试 3 次后失败 → audit_log；
若想跳过重试可在 catch 内判 `errcode` 决定是否 raise — 本 plan 保持简单：所有 wechatpy
异常都视为可重试，3 次失败后转 failed）

### 3. 企微 Bot Webhook 文档示例（官方）

```bash
curl 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY' \
  -H 'Content-Type: application/json' \
  -d '{
    "msgtype": "markdown",
    "markdown": {
      "content": "实时新增用户反馈<font color=\"warning\">132例</font>"
    }
  }'
```

**借鉴点**：
- 响应格式：`{"errcode": 0, "errmsg": "ok"}` — 与应用消息一致
- 仅需 webhook key 即可（无 access_token 维护）
- markdown 支持 `<font color>` 标签（warning/info/comment 三色）— 本 plan 不用（保持简单）

### 4. 04-05 IMProvider Protocol 接口

源码：`backend/app/agent_builder/notification/providers/base.py`

**借鉴点**：
- `IMProvider.send_hitl_card` 7 个 keyword 参数 — 本 plan 保持完全一致签名
- `IMProvider.update_card` 抛 NotImplementedError — 本 plan **必须** 显式 raise（企微限制）
- `IMProvider.subscribe / verify_webhook_signature` 抛 NotImplementedError — Phase 4.5 实现
- runtime_checkable Protocol → `isinstance(WeComProvider(), IMProvider) is True` 验证用例

### 5. 04-05 MockIMProvider 调用记录模式

源码：`backend/app/agent_builder/notification/providers/mock.py`

**借鉴点**：
- 测试用 monkeypatch 拦截 wechatpy client.message.send 调用 → 记录 args + 返回 `{errcode: 0}`
- `pytest_httpx` 模拟 webhook 响应 — 04-05 没用到，本 plan 首次使用

---

## 与本项目的关系（如何应用到当前 plan）

| 决策 | 本 plan 代码位置 |
|---|---|
| Markdown 内容生成 | `cards/wecom_card.py::build_wecom_markdown_content(payload)` |
| App message 卡片 envelope | `cards/wecom_card.py::build_wecom_app_message(...)` 返回 `{msgtype, markdown}` dict |
| Webhook 卡片 envelope | `cards/wecom_card.py::build_wecom_webhook_markdown(...)` 同上 dict（msgtype 一致，envelope 一致） |
| `_send_via_app_message` | `providers/wecom.py::WeComProvider._send_via_app_message` |
| `_send_via_bot_webhook` | `providers/wecom.py::WeComProvider._send_via_bot_webhook` |
| 路径选择 | `WeComProvider.__init__(use_bot_fallback=...)` + `send_hitl_card` 内 if-else |
| update_card 限制 | `WeComProvider.update_card` 显式 `raise NotImplementedError` |
| `supports_card_update` 属性 | `WeComProvider.supports_card_update = False`（让 04-10 fan-out 据此选择 supplement_text） |
| 凭据扩展 | `IMCredentialsManager.has_wecom_bot_webhook()` + `get_wecom_bot_webhook_key()` 新增 getter（与 `wecom()` 共存；bot_webhook_key 独立配置） |
| 环境变量 | `WECOM_BOT_WEBHOOK_KEY`（可选）— `.env.example` 新增 |
| 注册到 lifespan | `backend/app/main.py` lifespan startup 内 `register_provider(WeComProvider(...))` — 仅当至少有一种凭据可用时注册 |

---

## 风险登记 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| wechatpy 停更，未来 1-2 年可能完全无法用 | 应用消息路径失效 | Bot Webhook fallback 始终可用（不依赖 SDK，纯 httpx） |
| 企微 access_token 刷新逻辑可能与现行 API 不兼容 | `client.message.send` 401 | `WeChatClientException` 被包装为 `ConnectionError` 触发 tenacity 重试；3 次失败后 audit_log + 用户可手动切到 Bot Webhook |
| markdown 子集变更（企微历史上多次调整） | `<font>` 标签 / link 格式失效 | 本 plan 仅用最稳定的 `[text](url)` + 列表项；不用 `<font>` 等高级特性 |
| 微工作台不支持 markdown | 个别客户端体验下降 | 文档明确说明（用户主要在 PC/Mobile 客户端审批） |
| Bot Webhook key 泄露 | 任何人可向该群发消息 | `.env` 不入仓；按 CLAUDE.md §6 校验 |

---

## 不做的事（明确边界）

- ❌ 不引入 `wxwork` 或 `wecom-api` 等替代 SDK（虽然有现代 template_card 支持，但都未审计）
- ❌ 不实现 `subscribe` / `verify_webhook_signature`（Phase 4.5）
- ❌ 不实现 OAuth 用户授权（HITL 用户决策走 web 决策页，不在企微内表单填写）
- ❌ 不引入企微 corp 内部用户目录同步（Phase 5 — `dept:` 表达式依赖）

---

## 参考链接

- 企微开放平台 — 应用消息 markdown：https://developer.work.weixin.qq.com/document/path/90236#markdown%E6%B6%88%E6%81%AF
- 企微开放平台 — 群机器人 webhook：https://developer.work.weixin.qq.com/document/path/91770
- wechatpy GitHub：https://github.com/wechatpy/wechatpy（最后 release 2020-09，已停更）
- wechatpy 1.8.18 PyPI：https://pypi.org/project/wechatpy/1.8.18/
- 上游 reading doc：`docs/reading-im-sdk-04-05-providers-2026-05-17.md`

---

*Phase 04-approval-chain-im — Plan 07 reading doc*
*Spike 完成 + 决策记录：2026-05-17*
