# IM SDK 阅读笔记 — Plan 04-05 IMProvider 抽象层

> 日期: 2026-05-17
> 范围: 飞书 / 企微 / 钉钉 / Slack / Mattermost 5 家 IM SDK 速查
> 参考项目（接口设计借鉴）:
>   - hr/offboarding-flow (Mattermost / lark / wecom stubs) — `/Users/admin/ai/ref/hr/offboarding-flow/`
>   - Dify model_providers (`/Users/admin/ai/ref/dify/repo/api/core/model_runtime/model_providers/`)
> CLAUDE.md §3 SDK 版本锁定基线 — 不可换

---

## 项目概述（一句话）

为 5 家 IM 平台抽象统一的 **IMProvider Protocol** 接口 + Registry，让 Phase 4 Wave 4
四个并行 Provider 实现 plan（04-06/07/08/09）都能 plug 进同一调用方（`im_jobs.send_hitl_card_job`），
不在抽象层引入任何 IM SDK 真实依赖（具体 SDK import 留给 Provider 实现 plan）。

---

## 与 Dify 对比

Dify **没有 IM Provider 抽象**（仅 LLM API 多厂商接入）。但 Dify
`api/core/model_runtime/model_providers/` 的 **多 provider 抽象设计**值得借鉴：

| Dify 模式 | 本项目对应 |
|---|---|
| `ModelProvider` 抽象基类 + 各厂商插件式 plugin/yaml | `IMProvider` Protocol + Registry register_provider |
| `model_provider_factory.get_provider_schema()` | `get_provider(name)` 工厂函数 |
| Provider yaml + credential schema | `IMCredentialsManager` + per-provider `frozen dataclass` |
| Provider lifecycle (init/cleanup) | FastAPI lifespan 注入 + clear_providers fixture |

**借鉴要点**：
1. **Protocol over ABC**：用 `typing.Protocol` 不用 `abc.ABC`，鸭子类型更灵活（CLAUDE.md python/patterns.md 推荐）
2. **凭据与实现分离**：Dify 的 credential schema 独立 yaml，本项目用 frozen dataclass per provider
3. **延迟实例化**：Dify provider 真正调用时才 init client，本项目同样在 Provider 实现的 `__init__` 之外延迟创建 SDK client

---

## hr/offboarding-flow 对比（接口设计借鉴）

hr 项目已有 IMProvider / DocProvider Protocol 与 mattermost/lark/wecom stub，
本 plan **仅借鉴接口风格**，不复制源码（hr 是独立项目，许可证不同）：

| hr Protocol 方法 | 本项目对应 | 差异 |
|---|---|---|
| `async def send_message(channel, text)` | `async def send_hitl_card(recipient, ...)` | 我们 HITL 决策卡片字段化，hr 是纯文本 |
| `async def update_message(msg_id, content)` | `async def update_card(message_id, new_content)` | 一致 |
| `async def authenticate()` | 留 Phase 4.5 Bot Trigger plan 实现 | Phase 4 仅出站 |

---

## 5 家 SDK 速查表

### 1. 飞书 — lark-oapi 1.6.5

- **GitHub**: https://github.com/larksuite/oapi-sdk-python
- **PyPI**: `lark-oapi==1.6.5` (1.6.0–1.6.3 已 yanked, 必须 pin)
- **客户端类**: `lark.Client`
- **核心入口**: `client.im.v1.message.create()` 发卡片，`client.im.v1.message.patch()` 更新
- **卡片格式**: Interactive Card 2.0 — JSON `{ "msg_type": "interactive", "content": "<json string>" }`
- **凭据字段**: `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
- **支持 update**: ✓ 通过 `messages/v1/{message_id}/patch`
- **认证**: `tenant_access_token` 自动管理（SDK 内置 token cache）
- **已知风险**: 1.6.x 版本 yanked 历史 — startup 时 assert `lark.__version__ == "1.6.5"`

### 2. 企微 — wechatpy 1.8.18

- **GitHub**: https://github.com/wechatpy/wechatpy (停更)
- **PyPI**: `wechatpy==1.8.18` (停更，但仍可装)
- **客户端类**: `wechatpy.work.WeChatClient`
- **核心入口**: `client.message.send_template_card(...)`
- **卡片格式**: Template Card `text_notice` + `button_list` 字段
- **凭据字段**: `WECOM_CORP_ID` / `WECOM_AGENT_ID` / `WECOM_SECRET`
- **支持 update**: ✗ 静态卡片（无 update API）— 走 `send_supplement_text` 补发
- **认证**: 自动管理 `access_token` cache
- **已知风险**:
  - 停更，templated card API 2026 年是否仍可用需 Plan 04-08 spike
  - 若失败 fallback Bot Webhook（损失 user-targeted 投递能力）

### 3. 钉钉 — dingtalk-stream 0.24.3

- **GitHub**: https://github.com/open-dingtalk/dingtalk-stream-sdk-python
- **PyPI**: `dingtalk-stream==0.24.3`
- **客户端类**: `dingtalk_stream.DingTalkStreamClient`
- **核心入口**: `client.send_message_to_user(user_id, msg)` 或 OAPI 直调 `https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2`
- **卡片格式**: ActionCard `btnOrientation=0` (横排按钮)
- **凭据字段**: `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET`
- **支持 update**: ✗ ActionCard 无 update API
- **认证**: 自动管理 `accessToken`

### 4. Slack — slack-bolt 1.28.0

- **GitHub**: https://github.com/slackapi/bolt-python
- **PyPI**: `slack-bolt==1.28.0`
- **客户端类**: `slack_bolt.App` + `app.client.chat_postMessage()`
- **核心入口**: `app.client.chat_postMessage(channel, blocks)` 发，`app.client.chat_update(ts, blocks)` 更新
- **卡片格式**: Block Kit (`section` + `actions` block，按钮带 `action_id`)
- **凭据字段**: `SLACK_BOT_TOKEN` (xoxb-...)
- **支持 update**: ✓ 通过 `chat.update` (需要保存 `ts` timestamp)
- **认证**: 单 token 即可 (无 access_token refresh)

### 5. Mattermost — 无专用 SDK, 直 httpx

- **API doc**: https://api.mattermost.com/ (v4 REST API)
- **客户端类**: 自实现 thin wrapper around `httpx.AsyncClient`
- **核心入口**: `POST /api/v4/posts` body `{channel_id, message, props: {attachments}}`
- **卡片格式**: Markdown attachment + actions array (类 Slack legacy attachment 格式)
- **凭据字段**: `MATTERMOST_URL` (e.g. `https://mm.example.com`) / `MATTERMOST_BOT_TOKEN`
- **支持 update**: ✓ 通过 `PUT /api/v4/posts/{post_id}/patch`
- **认证**: Bearer token (long-lived)
- **依赖最小**: 不引入 SDK，只用 `httpx` (已依赖)

---

## 凭据字段映射表（IMCredentialsManager 用）

```
| Provider   | .env 变量名                                          | dataclass 字段           |
|------------|------------------------------------------------------|--------------------------|
| feishu     | FEISHU_APP_ID, FEISHU_APP_SECRET                     | app_id, app_secret       |
| wecom      | WECOM_CORP_ID, WECOM_AGENT_ID, WECOM_SECRET          | corp_id, agent_id, secret |
| dingtalk   | DINGTALK_APP_KEY, DINGTALK_APP_SECRET                | app_key, app_secret      |
| slack      | SLACK_BOT_TOKEN                                      | bot_token                |
| mattermost | MATTERMOST_URL, MATTERMOST_BOT_TOKEN                 | base_url, bot_token      |
```

**加载策略**：启动时全部 `_load_from_env`，缺失字段 **warn 不抛错**（按需配置 — 用户可能只用 2-3 家）。

---

## 可借鉴的设计模式

### 模式 1：Protocol over ABC（Python typing.Protocol）

```python
@runtime_checkable
class IMProvider(Protocol):
    name: str
    async def send_hitl_card(...) -> dict: ...
    async def update_card(...) -> None: ...
```

**好处**：
- `isinstance(mock, IMProvider)` 鸭子类型校验通过（runtime_checkable）
- MockIMProvider 不需要继承基类，只要方法签名匹配即可
- 测试隔离干净（无继承链）

### 模式 2：模块级 Registry（dict + factory）

```python
_PROVIDERS: dict[str, IMProvider] = {}

def register_provider(provider: IMProvider) -> None:
    _PROVIDERS[provider.name] = provider

def get_provider(name: str) -> IMProvider:
    return _PROVIDERS[name]

def clear_providers() -> None:  # fixture 用
    _PROVIDERS.clear()
```

**好处**：
- 无需 DI 框架（FastAPI Depends 不适合 — provider 应在 startup 一次注册）
- 测试可 `clear_providers()` 隔离

### 模式 3：Frozen Dataclass per Provider Credentials

```python
@dataclass(frozen=True)
class FeishuCredentials:
    app_id: str
    app_secret: str
```

**好处**：
- 不可变（CLAUDE.md immutability 原则）
- 类型清晰（vs 通用 dict[str, str]）
- Provider 实现侧 type-safe 取字段

### 模式 4：Phase 4.5 接口预留（NotImplementedError）

```python
async def subscribe(self, on_event: Any) -> None:
    raise NotImplementedError(f"{self.name} subscribe 将于 Phase 4.5 实现")
```

**好处**：
- Protocol 一次定义完整，Phase 4 Provider 实现暂不实现 subscribe
- Phase 4.5 不需要改 Protocol，仅在各 Provider 添加方法即可（向后兼容）

---

## 与本项目的关系

### Plan 04-05 实现范围

1. **IMProvider Protocol**: `notification/providers/base.py`
2. **ProviderRegistry**: 同文件 `_PROVIDERS` + register/get/clear
3. **MockIMProvider**: `notification/providers/mock.py` (测试 + E2E 用)
4. **IMCredentialsManager**: `core/im_credentials.py` (.env 加载 + 5 个 frozen dataclass)
5. **im_jobs.py**: `jobs/im_jobs.py` (`send_hitl_card_job` 克隆 `email_jobs.send_hitl_email_job` 模板)
6. **CardBuilder 抽象基类**: `notification/cards/base.py` (Phase 4 仅声明，4 家 provider plan 各自实现)

### Wave 4 下游依赖

Plan 04-06/07/08/09 (4 家 IM Provider 并行实现) 都将：
1. `from app.agent_builder.notification.providers.base import IMProvider, register_provider`
2. 实现自己的 Provider 类，满足 Protocol
3. 在 FastAPI lifespan 注册 `register_provider(MyFeishuProvider(creds))`
4. `im_jobs.send_hitl_card_job` 通过 `get_provider(channel)` 取到 Provider 调用

---

## SDK 版本锁定理由（CLAUDE.md §3）

- **lark-oapi 1.6.5**: 1.6.0–1.6.3 已 yanked (PyPI 撤回)，1.6.4 受影响；1.6.5 是当前稳定版
- **wechatpy 1.8.18**: 停更但当前可用；备选 Bot Webhook fallback (Plan 04-08 spike)
- **dingtalk-stream 0.24.3**: 当前最新稳定
- **slack-bolt 1.28.0**: 当前最新稳定
- **mattermost 用 httpx**: 不依赖 SDK 减少 v4 API 跨版本兼容风险

---

## 风险登记

| 风险 | 严重度 | 应对 |
|---|---|---|
| wechatpy 停更，templated card 可能失效 | HIGH | Plan 04-08 第一个 task 必须 spike；失败 fallback Bot Webhook |
| lark-oapi 1.6.5 import 失败 | LOW | startup assert `lark.__version__ == "1.6.5"`（Plan 04-07） |
| Phase 4.5 subscribe 接口提前预留可能 over-design | LOW | NotImplementedError 是最简实现，Phase 4.5 自由扩展 |
| dingtalk-stream 客户端长连接资源管理 | MEDIUM | Plan 04-09 用 OAPI 直调（不维护长连接），简化生命周期 |
| Mattermost v4 API 跨版本字段名变化 | LOW | 限定测试 / 文档 Mattermost 7.x+ |

---

## 不实现的范围（Plan 04-06+ 各自实现）

- 飞书 / 企微 / 钉钉 / Slack / Mattermost **具体 Provider 类**（5 家 SDK 真实调用）
- 各家**卡片模板** JSON / Block Kit / Markdown attachment（5 家 build_*_card）
- IM Bot **入站 webhook** + Slash 分发（→ Phase 4.5）
- IM Directory **双向同步**（→ Phase 5）
- Workspace **级 IM 凭据 UI**（→ Phase 6）

---

## Reading doc 完成检查

- [x] 5 家 SDK GitHub README + PyPI 信息核对完整
- [x] 凭据字段 .env 映射表清晰
- [x] hr/offboarding-flow Protocol 接口设计对比
- [x] Dify 多 provider 模式借鉴点提取
- [x] Phase 4.5 / Phase 5 / Phase 6 边界明确
- [x] 风险登记 + 应对方案
- [x] SDK 版本锁定理由

**结论**：reading doc 完成，Plan 04-05 实现路径清晰；可进入 Task 1 写代码。
