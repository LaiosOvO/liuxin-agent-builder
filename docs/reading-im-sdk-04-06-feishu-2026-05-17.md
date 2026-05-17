# 飞书 lark-oapi 1.6.5 SDK + Interactive Card 2.0 阅读笔记 — Plan 04-06

> 日期: 2026-05-17
> 仓库: https://github.com/larksuite/oapi-sdk-python (commit baseline 1.6.5)
> 文档: https://open.feishu.cn/document/server-docs/im-v1/message-card/send-message-cards/specifications-and-functions
> Stars: ~700 (SDK), 飞书开放平台官方维护
> Plan: `04-06` — FeishuProvider 实现（IMProvider Protocol，NOTI-02）
> 范围：仅出站投递 + 卡片更新；入站 webhook 留 Phase 4.5

---

## 1. 项目概述（一句话）

飞书官方 Python SDK，封装飞书开放平台 Open API 的同步 + 异步调用，本项目用其
`im.v1.message.create` 投递 Interactive Card 2.0 + `im.v1.message.patch` 更新已发卡片为
只读"已被 X 处理"状态。

---

## 2. 技术栈关键技术选择

- **lark-oapi 1.6.5**（CLAUDE.md §3 强制版本锁定）
  - 1.6.0 / 1.6.1 / 1.6.2 / 1.6.3 已被 yanked（pip 拒绝安装）
  - 1.6.4 存在 但跳过；1.6.5 是当前稳定线
- **同步 client**：`lark.Client.builder().app_id(...).app_secret(...).build()`
  - SDK 内部为同步阻塞 IO，在 FastAPI / asyncio 中必须 `loop.run_in_executor(...)` 包装
  - tenant_access_token 自动管理（SDK 内置 cache + 自动刷新）
- **依赖**：`pycryptodome 3.23+`（飞书 webhook 签名校验用，Phase 4.5）+
  `requests` + `websockets 15.x`

---

## 3. SDK 版本验证（CLAUDE.md §3 强制启动校验）

**陷阱**：`lark.__version__` 属性不存在！直接访问返回 `'unknown'`。
**正确做法**：用 `importlib.metadata.version("lark-oapi")` 取真实安装版本：

```python
from importlib.metadata import PackageNotFoundError, version as _pkg_version

_EXPECTED_LARK_VERSION = "1.6.5"

def _resolve_lark_version() -> str:
    try:
        return _pkg_version("lark-oapi")
    except PackageNotFoundError:
        return "unknown"
```

启动校验：
- 实际 != 1.6.5 → `log.warning(...)`（不抛错 — 开发环境可能短暂不一致）
- 测试通过 `monkeypatch` 替换返回值模拟版本不一致场景

---

## 4. 架构要点（核心架构模式）

### 4.1 Client 构造（Builder 模式）

```python
import lark_oapi as lark

client = (
    lark.Client.builder()
    .app_id("cli_xxx")
    .app_secret("xxxxxxx")
    .log_level(lark.LogLevel.WARNING)   # 飞书 SDK 内部日志级别
    .build()
)
```

特点：
- 单例：一个 `Client` 实例可重用（内部 token cache）
- 线程安全（SDK 文档声明）
- **延迟初始化**：本项目 Provider 用 `@property client` 延迟构造，避免 module import 时建立连接

### 4.2 API 调用 = Request builder + Response 解析

```python
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
)

request = (
    CreateMessageRequest.builder()
    .receive_id_type("open_id")    # 必填：open_id / user_id / union_id / email / chat_id
    .request_body(
        CreateMessageRequestBody.builder()
        .receive_id("ou_xxx")       # 飞书用户 open_id
        .msg_type("interactive")    # 卡片类型
        .content(json_str_card)     # JSON 字符串（必须 json.dumps 卡片）
        .build()
    )
    .build()
)
response = client.im.v1.message.create(request)
```

**Response 结构**（继承 `BaseResponse`）：
- `response.success()` → bool（`code == 0` 时 True）
- `response.code` → int（错误码）
- `response.msg` → str（错误描述）
- `response.data` → `CreateMessageResponseBody` 含 `message_id` 等字段
- `response.get_log_id()` → str（飞书 trace 日志 ID，工单排查用）

---

## 5. Interactive Card 2.0 JSON Schema 速查

### 5.1 卡片骨架

```json
{
  "config": { "wide_screen_mode": true },
  "header": {
    "title": { "tag": "plain_text", "content": "📋 审批待办：流程名" },
    "template": "blue"   /* blue / green / yellow / red / grey */
  },
  "elements": [
    { "tag": "div", "fields": [ /* lark_md 双列字段 */ ] },
    { "tag": "div", "text": { "tag": "lark_md", "content": "**详情**\n..." } },
    { "tag": "hr" },
    { "tag": "action", "actions": [ /* button list */ ] }
  ]
}
```

### 5.2 Element tag 含义

| tag | 用途 | 备注 |
|---|---|---|
| `div` | 内容块（text 单条 / fields 双列） | `lark_md` 支持有限 markdown（粗体、换行、@） |
| `hr` | 水平分隔线 | 无 props |
| `action` | 按钮容器 | actions 数组 = 多按钮 |
| `note` | 灰色小字注释 | 决策后角标"✓ 已被 X 处理" |
| `markdown` | 富文本 markdown | 与 div+lark_md 等价但写法不同 |

### 5.3 Button 类型 — `multi_url` vs `request`

| type | 行为 | 我们选择 |
|---|---|---|
| `multi_url` | 用户点击 → 浏览器跳转外部 URL（含 pc/mobile/android/ios 分发） | ✓ **本项目用此类型** |
| `request` | 用户点击 → 飞书后端回调 webhook，不跳转 | ✗ Phase 4.5 双向交互再用 |

**multi_url 4 URL 字段**（必须全填，否则降级桌面端默认）：

```json
{
  "tag": "button",
  "text": { "tag": "plain_text", "content": "同意" },
  "type": "primary",       /* primary / default / danger */
  "multi_url": {
    "url": "https://app.example.com/hitl/page/<jti>",
    "pc_url": "https://app.example.com/hitl/page/<jti>",
    "android_url": "https://app.example.com/hitl/page/<jti>",
    "ios_url": "https://app.example.com/hitl/page/<jti>"
  }
}
```

### 5.4 按钮颜色映射（HITL 4 action）

| action | type 字段 | 视觉 | 用例 |
|---|---|---|---|
| `approve` | `primary` | 蓝色实心 | 同意 |
| `return` | `default` | 浅灰描边 | 退回上游节点 |
| `reject` | `danger` | 红色实心 | 拒绝（终止流程） |
| `submit` | `default` | 浅灰描边 | 表单提交（详情链接） |

---

## 6. 卡片更新 API（patch_message）

### 6.1 调用

```python
from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

req = (
    PatchMessageRequest.builder()
    .message_id("om_xxx")           # 原 send 返回的 message_id
    .request_body(
        PatchMessageRequestBody.builder()
        .content(json.dumps(new_card_json))   # 新卡片 JSON 字符串
        .build()
    )
    .build()
)
resp = client.im.v1.message.patch(req)
```

### 6.2 限制

- **24h 时间窗**：发送后 24h 内可 patch；超时返回 `code=234016`（消息已过期）
- **仅卡片类型支持 patch**：text / image 等 msg_type 不可 patch
- **content 字段是字符串**：必须 `json.dumps(new_card_dict)`，不可直接传 dict

### 6.3 本项目使用模式

```python
# 卡片决策后转为只读 + 角标"✓ 已被 X 处理"
def build_feishu_processed_card(*, original_card: dict, processed_by: str) -> dict:
    new_card = {**original_card}                            # 浅拷贝避免修改原 dict
    new_card["elements"] = [                                # 过滤 action 块
        e for e in new_card["elements"] if e.get("tag") != "action"
    ]
    new_card["elements"].append({                           # 追加 note 角标
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": f"✓ 已被 {processed_by} 处理"}],
    })
    new_card["header"]["template"] = "grey"                 # 头部变灰
    return new_card
```

---

## 7. 错误码映射（关键）

| code | 含义 | 处理策略 |
|---|---|---|
| 0 | 成功 | — |
| 11201 | token 过期 / app_secret 错误 | log + audit_log（用户运维介入）— 不重试 |
| 99991663 | 飞书内部服务器错误 | 抛 `ConnectionError` → tenacity 重试 |
| 230020 | receive_id 不存在 / 用户已离职 | log + audit_log — 不重试 |
| 234016 | 消息已过期（patch 24h 外） | log warning 仅；视为正常 — 流程已超时 |
| 网络 / DNS 错误 | requests.ConnectionError | 抛 `ConnectionError` → tenacity 重试 |

**重试策略**（与 04-05 `im_jobs` tenacity 一致）：
- 抛 `ConnectionError / TimeoutError / OSError` → tenacity 3 次 1s/2s/4s
- 其他业务错误 → 直接 fail + audit_log + 不重试

---

## 8. 异步集成（asyncio + run_in_executor）

lark-oapi 1.6.5 是**同步**实现（基于 requests），FastAPI / asyncio 场景必须包装：

```python
import asyncio

async def send_hitl_card(self, ...) -> dict:
    request = (...)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,                                # 默认 ThreadPoolExecutor
        self.client.im.v1.message.create,
        request,
    )
    ...
```

**替代方案**（未采用）：lark-oapi 文档提到的 `AsyncClient` — Plan 04-06 阅读时
SDK 1.6.5 文档未明确公开此类，避免使用未文档化 API。

---

## 9. Provider 注册时机（FastAPI lifespan）

`backend/app/main.py` 的 `lifespan` 在 startup 阶段：

```python
from app.agent_builder.notification.providers.base import register_provider
from app.agent_builder.notification.providers.feishu import FeishuProvider
from app.agent_builder.core.im_credentials import IMCredentialsManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 既有 init_db ...
    creds = IMCredentialsManager()
    if creds.has_feishu():
        register_provider(
            FeishuProvider(
                app_id=creds.feishu().app_id,
                app_secret=creds.feishu().app_secret,
            )
        )
    yield
    # Shutdown
```

特点：
- **按 .env 配置**：未配置飞书凭据 → 不注册（其他 Provider 同理）
- **失败不阻断**：注册失败 log error 但不抛错（启动继续）
- **测试隔离**：测试不通过 lifespan 注册；直接调 `register_provider(MockIMProvider(...))`

---

## 10. 可借鉴的设计模式

| 模式 | 来源 | 本项目应用 |
|---|---|---|
| Builder 链式构造 | lark SDK request/response | 本项目 `FeishuProvider.__init__` 内 client builder |
| 同步 SDK 在 async 内包装 | Python 标准模式 | `loop.run_in_executor(None, sync_call, request)` |
| Response.success() → bool 判定 | lark BaseResponse | 失败 `raise ConnectionError(f"...code={code} msg={msg}")` |
| 延迟客户端构造 | 通用模式 | `@property client` 防 import 时网络调用 |
| 包元数据查版本 | importlib.metadata 标准库 | `version("lark-oapi")` 取代不存在的 `lark.__version__` |

---

## 11. 与本项目的关系（如何应用到 04-06）

本 plan 04-06 实现：

1. **FeishuProvider** (`backend/app/agent_builder/notification/providers/feishu.py`)
   - 满足 IMProvider Protocol（鸭子类型）
   - `send_hitl_card` → `client.im.v1.message.create` + interactive content
   - `update_card` → `client.im.v1.message.patch`
   - `send_supplement_text` → `client.im.v1.message.create` + text content
   - `subscribe / verify_webhook_signature` → 抛 NotImplementedError（Phase 4.5 留）
   - SDK 版本校验通过 `importlib.metadata`，非 `lark.__version__`

2. **build_feishu_hitl_card** (`backend/app/agent_builder/notification/cards/feishu_card.py`)
   - 纯函数，入参 = HitlCardPayload 字段或独立参数
   - 输出 = Interactive Card 2.0 JSON dict（**未** json.dumps，由 Provider 序列化）
   - 4 按钮 multi_url + 颜色按 action 映射

3. **build_feishu_processed_card**
   - 决策后用：保留 header（变灰） + content + 移除 action + 追加 note 角标

4. **main.py lifespan**：按 IMCredentialsManager.has_feishu() 条件注册

5. **测试**：
   - **单元测试**（test_feishu_card_builder.py）：纯函数 JSON 结构断言 — 4+ 用例
   - **集成测试**（test_feishu_provider.py）：monkeypatch `client.im.v1.message.create/patch`
     返回 mock response（不打飞书真实 API）— 5+ 用例

---

## 12. 不复制 Dify 源码（许可证）

Dify 是 AGPL-3.0，本项目 Apache-2.0。**仅借鉴设计模式 / SDK 调用模式**，独立实现卡片
JSON 构造与 Provider 类。Dify 本身不直接提供飞书 IM 卡片投递抽象（Dify 是 LLM 多
provider 接入，IM Notification 由插件市场实现），可参考性有限 — 本项目主要参考
**lark-oapi SDK 文档 + hr/offboarding-flow 接口风格**（已在 04-05 reading doc 列出）。

---

*Plan 04-06 reading doc completed: 2026-05-17 — Task 0 reading gate 通过后才允许写代码*
