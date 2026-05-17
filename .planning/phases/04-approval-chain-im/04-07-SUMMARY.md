---
phase: 04-approval-chain-im
plan: "07"
subsystem: notification-im
tags: [wecom, wechatpy, bot-webhook, markdown, im-provider, fallback, httpx, spike]
dependency_graph:
  requires:
    - 04-05 (IMProvider Protocol + Registry + IMCredentialsManager + im_jobs.send_hitl_card_job)
    - 04-01 (chain payload + ChainAdvanceResult — 通过 im_jobs 间接消费)
  provides:
    - WeComProvider 完整实现（IMProvider Protocol 鸭子类型）
    - 双路径架构：wechatpy app message + Bot Webhook fallback
    - build_wecom_app_message + build_wecom_webhook_markdown card builders
    - build_wecom_markdown_content 共享 markdown 内容生成器（4 action 中文链接）
    - build_wecom_supplement_text 兜底文本（update_card 不可用时用）
    - WeComCredentials.bot_webhook_key 字段扩展（默认 ""，向后兼容）
    - IMCredentialsManager 支持 fallback-only 模式（仅 bot_webhook_key 配置）
    - main.py lifespan 自动注册 WeComProvider（按 .env 凭据决定）
    - .env.example WECOM_* 4 字段说明
  affects:
    - Wave 5 plan 04-10（多通道 fan-out 调用 WeComProvider.send_hitl_card + supplement_text 兜底）
    - Wave 5 plan 04-11/12（端到端测试涉及 WeCom 通道）
    - Phase 4.5 Bot Trigger plan（subscribe/verify_webhook_signature 需各 Provider 实现）
tech-stack:
  added:
    - "wechatpy==1.8.18（CLAUDE.md §3 锁定；停更但 markdown API 仍可用 — spike 验证）"
  patterns:
    - "双路径 Provider 架构（主 SDK + httpx fallback）— 应对 SDK 停更风险"
    - "异常包装为 ConnectionError 触发 im_jobs tenacity 重试"
    - "supports_card_update 类属性 — 让调用方据此选择 update_card vs send_supplement_text"
    - "延迟 SDK import + _get_client 测试可 monkeypatch 拦截"
    - "_safe_error_message 截断错误信息防 secret 泄露 / 日志爆量"
    - "markdown 注入防护：方括号 / 反引号 / 星号 / 下划线 / 角括号转义"
key-files:
  created:
    - backend/app/agent_builder/notification/providers/wecom.py (345 行)
    - backend/app/agent_builder/notification/cards/wecom_card.py (189 行)
    - backend/tests/test_wecom_provider.py (310 行, 17 测试)
    - backend/tests/test_wecom_card_builder.py (188 行, 17 测试)
    - docs/reading-im-sdk-04-07-wecom-2026-05-17.md (236 行)
  modified:
    - backend/app/agent_builder/core/im_credentials.py（WeComCredentials 新增 bot_webhook_key 字段；_load_from_env 支持 fallback-only 模式）
    - backend/app/main.py（lifespan 添加 _register_im_providers + WeComProvider 注册）
    - backend/.env.example（新增 WECOM_* 4 字段说明）
key-decisions:
  - "[Phase 04-07] Spike 关键发现：wechatpy 1.8.18 完全无 template_card / button_interaction API；唯一能放置多链接的是 send_markdown（markdown 子集支持 [text](url)）"
  - "[Phase 04-07] 不引入 wxwork / wecom-api 替代 SDK（停更但未审计；增加供应链风险）"
  - "[Phase 04-07] 双路径架构：主路径 wechatpy app message（user-targeted）+ Fallback Bot Webhook（群投递，无 SDK 依赖）"
  - "[Phase 04-07] 自动 fallback 选择：app 凭据缺失但 bot_webhook_key 存在 → use_bot_fallback=True 自动开启"
  - "[Phase 04-07] update_card 显式抛 NotImplementedError + supports_card_update=False（让 04-10 调用方据此选择 send_supplement_text 兜底）"
  - "[Phase 04-07] WeChatClientException + 业务 errcode≠0 都包装为 ConnectionError（im_jobs tenacity 重试触发；token 抖动场景必须可重试）"
  - "[Phase 04-07] 错误消息截断 200 字符（CLAUDE.md security 防 secret 泄露 / 日志爆量）"
  - "[Phase 04-07] markdown 内容生成器在 app message / bot webhook 间共享（envelope 完全一致，仅外层 send 入口不同）"
  - "[Phase 04-07] 用户文本字段（flow_title / applicant_name / description）做 markdown 特殊字符转义 — 防注入"
  - "[Phase 04-07] WeComCredentials 新增 bot_webhook_key 字段默认 \"\"（向后兼容 — 现有 15 个 credentials 单元测试不需改）"
  - "[Phase 04-07] [Rule 1 - Test Bug] 自我修正：test_content_with_only_subset_of_deeplinks 原断言 '详情' not in content 误判（description 含'详情'静态 label）→ 改为 '[详情](' 形态匹配"
  - "[Phase 04-07] [Rule 1 - Test Bug] 自我修正：test_send_via_app_message_passes_correct_agent_id_and_recipient 断言 agent_id 为 str → 实际 wechatpy API 要求 int，调整为 1000002（int）"
patterns-established:
  - "双路径 IM Provider：当 SDK 主路径不稳定时，提供 httpx 直调 fallback（其他 Provider 04-06/08/09 也可借鉴）"
  - "supports_card_update 静态类属性：让 fan-out 调用方分发到 update_card vs supplement_text"
  - "延迟 SDK import + _get_client 私有方法：测试 monkeypatch 可拦截，主代码无需 SDK 即可导入"
  - "lifespan 注册按 IMCredentialsManager 自动选择：用户只配 .env，Provider 自动启用"
requirements-completed: [NOTI-03]
metrics:
  duration: "10min"
  completed_date: "2026-05-17"
  tasks: 4
  files_created: 5
  files_modified: 3
---

# Phase 4 Plan 07: WeCom IMProvider Summary

**WeCom IM 通知 Provider — wechatpy 1.8.18 + Bot Webhook 双路径架构，应对停更 SDK 无 template_card API 的限制，34 单元测试全绿，NOTI-03 完成**

## Performance

- **Duration:** ~10 min（含 Task 0 reading doc + Task 1 spike + Task 2 card builder + Task 3 Provider 实现）
- **Started:** 2026-05-17T10:51Z（reading doc commit）
- **Completed:** 2026-05-17T11:02Z（Provider impl commit）
- **Tasks:** 4（Reading doc + spike + card builder + Provider）
- **Files created:** 5
- **Files modified:** 3

## Accomplishments

- **完整 WeComProvider 实现**：满足 `IMProvider` Protocol 鸭子类型（runtime_checkable isinstance 通过）
- **双路径架构落地**：主路径 wechatpy app message + Fallback Bot Webhook，自动按凭据切换
- **34 测试覆盖**（17 card + 17 provider），含 Protocol 校验 / 主路径 / fallback / 异常包装 / 配置 fast-fail / supplement
- **Spike 结论明确**：wechatpy 1.8.18 完全无 template_card API → 决策走 markdown 4 链接方案（详见 reading doc）
- **lifespan 自动注册**：用户仅需配 `.env`，启动时按 `IMCredentialsManager` 决定 WeComProvider 启用模式
- **零回归**：上游 `test_im_provider_protocol.py` 18 测试 + `test_im_credentials_loader.py` 15 测试 + `test_im_jobs_skeleton.py` 10 测试全部继续通过

## Task Commits

1. **Task 0 + 1: Reading doc + Spike 结论** — `3ad60ff` (docs)
   - reading doc 含 Spike 部分（30min 上限内完成）
   - 关键发现：wechatpy 1.8.18 模块路径是 `enterprise` 不是 `work`；无 template_card 整个方法簇；只有 `send_markdown` 可放 4 链接
   - 决策表：主路径 markdown + fallback bot webhook（envelope 完全一致）

2. **Task 2: WeCom card builder + 17 单元测试** — `a332c8f` (feat)
   - `build_wecom_markdown_content`（共享生成器）
   - `build_wecom_app_message` / `build_wecom_webhook_markdown`（envelope 完全一致）
   - `build_wecom_supplement_text`（≤ 200 字符）
   - markdown 注入防护 + 2048 字节边界保护

3. **Task 3: WeComProvider + lifespan 注册 + 17 单元测试** — `a5902c2` (feat)
   - WeComProvider 完整实现（双路径 + supports_card_update=False + NotImplementedError）
   - WeComCredentials.bot_webhook_key 字段扩展 + _load_from_env 支持 fallback-only 模式
   - main.py lifespan 自动注册（按 IMCredentialsManager）
   - .env.example 新增 WECOM_* 4 字段说明

## Files Created/Modified

### 新建（5 文件）

- `backend/app/agent_builder/notification/providers/wecom.py` (345 行) — WeComProvider 主实现
- `backend/app/agent_builder/notification/cards/wecom_card.py` (189 行) — markdown 内容 + envelope 构造器
- `backend/tests/test_wecom_provider.py` (310 行, 17 测试) — Provider 单元/集成测试
- `backend/tests/test_wecom_card_builder.py` (188 行, 17 测试) — Card builder 单元测试
- `docs/reading-im-sdk-04-07-wecom-2026-05-17.md` (236 行) — Reading doc + Spike 结论

### 修改（3 文件）

- `backend/app/agent_builder/core/im_credentials.py` — `WeComCredentials` 新增 `bot_webhook_key: str = ""` 字段；`_load_from_env` 支持 fallback-only 模式
- `backend/app/main.py` — lifespan 添加 `_register_im_providers()` 启动钩子 + WeComProvider 注册
- `backend/.env.example` — 新增 WeCom Provider 章节（`WECOM_CORP_ID` / `WECOM_AGENT_ID` / `WECOM_SECRET` / `WECOM_BOT_WEBHOOK_KEY`）

## Spike 结果（关键决策依据）

**Task 1 wechatpy 1.8.18 templated card API spike**（30min 上限内 5min 完成）：

| 检查项 | 结果 |
|---|---|
| `pip install wechatpy==1.8.18` | ✅ 成功 |
| `from wechatpy.work import WeChatClient` | ❌ 失败（1.8.x 路径是 `enterprise` 不是 `work`） |
| `from wechatpy.enterprise import WeChatClient` | ✅ 成功 |
| `client.message.send_template_card` | ❌ 不存在 |
| `client.message.send_button_interaction` | ❌ 不存在 |
| 整个 message 方法簇含 'template' 关键字 | ❌ 不存在 |
| `client.message.send_text_card` | ✅ 存在（仅 1 按钮，无法满足 HITL 4 按钮需求） |
| `client.message.send_markdown` | ✅ 存在（markdown 子集支持 `[text](url)`，可放 4 链接） |

**决策**：
- ❌ 不引入替代 SDK（wxwork / wecom-api）— 未审计供应链风险更大
- ✅ **markdown 4 链接方案**：4 个 `[同意/退回/拒绝/详情](url)` 链接列表
- ✅ **双路径**：app message（user-targeted）+ bot webhook（群投递）共享同一 markdown 内容

详见 `docs/reading-im-sdk-04-07-wecom-2026-05-17.md` §Spike 结果。

## WeCom 主路径 vs Fallback 决策表

| 维度 | 主路径（app message） | Fallback（Bot Webhook） |
|---|---|---|
| 投递目标 | 特定用户（user_id） | 整个群（webhook URL 绑定） |
| 依赖 | wechatpy SDK（已停更） | 仅 httpx |
| 凭据 | corp_id + agent_id + secret | bot_webhook_key |
| 内容 | 完全一致 markdown（共享 `build_wecom_markdown_content`） | 同上 |
| envelope | `{msgtype: "markdown", markdown: {...}}` | 同上 |
| update API | 无（应用消息不支持） | 无（webhook 不支持） |
| supports_card_update | False | False |
| 启用条件 | `use_bot_fallback=False` 且 app 凭据齐全 | `use_bot_fallback=True`（自动 / 手动） |
| 自动选择 | app 凭据齐全时默认 | app 凭据缺失但 bot_webhook_key 存在时自动启用 |

## 凭据字段（IMCredentialsManager）

```python
@dataclass(frozen=True)
class WeComCredentials:
    corp_id: str                    # 主路径必需
    agent_id: str                   # 主路径必需
    secret: str                     # 主路径必需
    bot_webhook_key: str = ""       # Fallback 可选（Plan 04-07 新增）
```

**`.env` 加载逻辑**（`_load_from_env`）：

```
WECOM_CORP_ID + WECOM_AGENT_ID + WECOM_SECRET 齐全？
├─ 是 → WeComCredentials(corp_id, agent_id, secret, bot_webhook_key=可选)
│       └─ WeComProvider 主路径（可选 fallback 备用）
└─ 否 → WECOM_BOT_WEBHOOK_KEY 配置？
        ├─ 是 → WeComCredentials(corp_id="", agent_id="", secret="", bot_webhook_key=key)
        │       └─ WeComProvider 强制 fallback 模式
        └─ 否 → 完全不创建 → has_wecom() False → WeComProvider 不注册
```

## 测试结果（34 测试全绿）

### test_wecom_card_builder.py（17 用例）

| 测试 | 覆盖点 |
|---|---|
| TestBuildMarkdownContent (7) | 含 flow_title heading / 4 action 链接 / metadata 字段 / 部分 deeplinks / 未知 action 兜底 / 2048 byte 边界 / markdown 注入转义 |
| TestBuildAppMessage (4) | envelope msgtype=markdown / markdown.content 是 str / 含 4 链接 / 无多余 key |
| TestBuildWebhookMarkdown (4) | envelope msgtype=markdown / markdown.content 是 str / app+webhook 共享 content / 无多余 key |
| TestBuildSupplementText (2) | 含 actor 和 action 中文 / ≤ 200 字符 |

### test_wecom_provider.py（17 用例）

| 测试 | 覆盖点 |
|---|---|
| 1. test_provider_satisfies_im_provider_protocol | runtime_checkable isinstance 校验 |
| 2. test_provider_name_is_wecom_constant | name='wecom' |
| 3. test_supports_card_update_is_false | 企微限制 |
| 4. test_send_via_app_message_success | mock wechatpy client → errcode=0 / msgtype=markdown / msgid 提取 |
| 5. test_send_via_app_message_passes_correct_agent_id_and_recipient | int(agent_id) 自动转换 |
| 6. test_send_raises_connection_error_on_wechatpy_exception | WeChatClientException → ConnectionError |
| 7. test_send_raises_connection_error_on_app_errcode_nonzero | 业务 errcode 也包装 |
| 8. test_send_via_bot_webhook_success | httpx_mock 200 + errcode=0 / body 含 markdown |
| 9. test_send_via_bot_webhook_raises_on_http_error | httpx 4xx → ConnectionError |
| 10. test_send_via_bot_webhook_raises_on_errcode | webhook errcode=93000 → ConnectionError |
| 11. test_update_card_raises_not_implemented | 明确提示走 send_supplement_text |
| 12. test_subscribe_raises_not_implemented | Phase 4.5 预留 |
| 13. test_verify_webhook_signature_raises_not_implemented | Phase 4.5 预留 |
| 14. test_send_supplement_text_via_app_message | app msgtype=text 成功 |
| 15. test_send_supplement_text_via_bot_webhook | webhook msgtype=text 成功 |
| 16. test_init_raises_when_fallback_enabled_without_bot_key | 配置 fast-fail |
| 17. test_init_auto_enables_fallback_when_only_bot_key_configured | 自动 fallback 选择 |

### 上游测试零回归

- test_im_provider_protocol.py：18 ✅
- test_im_credentials_loader.py：15 ✅（WeComCredentials 字段扩展向后兼容）
- test_im_jobs_skeleton.py：10 ✅

**合计 77 测试 in 20.37s**。

## Decisions Made

### Spike 驱动决策

1. **不引入替代 SDK**：wxwork / wecom-api 虽有 template_card 支持，但未审计；停更比维护风险更大；wechatpy markdown 4 链接是等效体验
2. **markdown 4 链接 vs Template Card**：放弃 button button_list（wechatpy 不支持），用 `[同意](url)` 列表代替；视觉降级但功能等效

### 架构决策

3. **双路径共享 markdown**：`build_wecom_markdown_content` 由 app message / bot webhook 共用；envelope 仅外层 wrapper 不同（DRY）
4. **自动 fallback 选择**：app 凭据缺失但 bot_webhook_key 存在 → 自动 use_bot_fallback=True（用户无需手动配置 flag）
5. **errcode≠0 也重试**：业务错误（如 60011 no privilege）也包装为 ConnectionError 让 tenacity 重试（token 抖动 / 临时权限刷新场景；3 次失败后自然进入 audit_log）
6. **delay SDK import**：`_get_client()` 私有方法内 import wechatpy → 测试可 monkeypatch 拦截整个 client（不需要安装 wechatpy 也能 import wecom.py）
7. **supports_card_update 静态类属性**：04-10 fan-out 调用方读取此属性决定是否调 update_card 或 send_supplement_text

### 安全决策

8. **错误消息截断 200 字符**：防止 stack trace 含 secret / 日志爆量（CLAUDE.md security）
9. **markdown 注入防护**：方括号 / 反引号 / 星号 / 下划线 / 角括号转义 — 防用户名 / 流程名含 `[xxx](malicious)` 被解析为链接
10. **2048 字节边界**：超长 markdown 自动截断 description 字段 + 加 `...(已截断)` 标记（utf-8 字符边界对齐避免 invalid sequence）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Bug] test_content_with_only_subset_of_deeplinks 误判**

- **Found during:** Task 2（GREEN 阶段第一次运行）
- **Issue:** 测试断言 `"详情" not in content`，但 description 字段静态 label `**详情**：` 中含"详情"二字 → False 判定
- **Fix:** 改为 `"[详情](" not in content` —— 仅校验链接形态而非裸文本（精确匹配）；并把测试 fixture 的 description 改为 "审批描述" 避免再次冲突
- **Files modified:** `backend/tests/test_wecom_card_builder.py`
- **Commit:** a332c8f（同 Task 2 提交）

**2. [Rule 1 - Test Bug] agent_id 类型期望错误**

- **Found during:** Task 3（GREEN 阶段第一次运行）
- **Issue:** 测试断言 `agent_id == "1000002"`（str），实际 wechatpy API 要求 int（数字 agent_id），WeComProvider 自动转 int 是正确行为
- **Fix:** 改为 `agent_id == 1000002`（int）+ 注释说明 wechatpy 要求
- **Files modified:** `backend/tests/test_wecom_provider.py`
- **Commit:** a5902c2（同 Task 3 提交）

### Architectural Decisions

无 Rule 4 架构变更。所有决策都在 plan 范围内，由 Spike 结论自然导出。

---

**Total deviations:** 2 auto-fixed（2 bug — 均在测试端，发现期望与实际行为不符立即修正）
**Impact on plan:** 零功能影响 — 测试期望错误不代表实现错误，发现即修正。

## Issues Encountered

- 项目 `Settings` ENVIRONMENT 字面量限制为 `local/staging/production` — 当前 `.env` 设 `dev` 导致 `from app.main import app` 失败。**与本 plan 无关**（pre-existing），记入 `.planning/phases/04-approval-chain-im/deferred-items.md` 即可，本 plan 不修复（CLAUDE.md scope boundary）。

## User Setup Required

需在 `.env` 中配置 **任一组** 凭据才能启用 WeComProvider：

**主路径（应用消息，user-targeted）**：
```bash
WECOM_CORP_ID=<企业 corp_id>
WECOM_AGENT_ID=<应用 agent_id>
WECOM_SECRET=<应用 secret>
```

**Fallback（群机器人）**：
```bash
WECOM_BOT_WEBHOOK_KEY=<群机器人 webhook key>
```

**两组同时配**：默认走主路径，启动 log 显示 `mode=app_message`；可手动改 use_bot_fallback=True 切到 fallback。

**未配任何一组**：WeComProvider 不注册，启动 log 显示 warning，调用 `get_provider("wecom")` 抛 KeyError 提示已注册列表。

## Dify 参考点

详见 `docs/reading-im-sdk-04-07-wecom-2026-05-17.md`。

**Dify 借鉴**：
- `api/core/model_runtime/model_providers/`（多 provider 抽象设计）→ 本 plan 复用 04-05 已建立的 IMProvider Protocol + Registry 模式
- Dify email_delivery 用 Jinja 模板渲染 HTML → 本 plan **不用** Jinja（企微 markdown 子集简单，注入风险高于模板复杂度）

**关键差异**：
- 本 plan 双路径架构（主 SDK + httpx fallback）是 Dify 没有的（Dify 的 SDK 是 LLM API，无 fallback 必要）
- supports_card_update 类属性是本项目特有（IM Provider 抽象需求；Dify LLM 抽象无对应）

## Next Phase Readiness

### Wave 4 4 家 Provider 进度

| Plan | Provider | 状态 |
|---|---|---|
| 04-06 | FeishuProvider | ✅ commit `d35d7a4` |
| **04-07** | **WeComProvider** | **✅ 本 plan 完成** |
| 04-08 | DingTalkProvider | ✅ commit `f88fde5` |
| 04-09 | SlackProvider + MattermostProvider + Webhook | ✅ commit `5b9cdbe / 9afc5c7 / 3f9e21d` |

**Wave 4 全部 4 plans 已完成** → **Wave 5 启动条件成熟**。

### 04-10 多通道 fan-out 调用方需注意

调用 `update_card` 前必须先检查 `supports_card_update`：

```python
provider = get_provider("wecom")
if provider.supports_card_update:
    await provider.update_card(message_id=msg_id, new_content={...})
else:
    # 企微 / 钉钉走 supplement_text 兜底
    await provider.send_supplement_text(recipient=recipient, text="流程已处理")
```

### Phase 4.5 Bot Trigger plan

`WeComProvider.subscribe` / `verify_webhook_signature` 当前抛 NotImplementedError。
Phase 4.5 需在 wecom.py 中实现：
- 入站 webhook 接收（企微回调消息 / 群机器人 @ 提及）
- HMAC-SHA256 签名验证（参考企微开放平台文档）

---

## Self-Check: PASSED

文件检查（5 新建 + 3 修改）：

- FOUND: backend/app/agent_builder/notification/providers/wecom.py
- FOUND: backend/app/agent_builder/notification/cards/wecom_card.py
- FOUND: backend/tests/test_wecom_provider.py
- FOUND: backend/tests/test_wecom_card_builder.py
- FOUND: docs/reading-im-sdk-04-07-wecom-2026-05-17.md
- FOUND: backend/app/agent_builder/core/im_credentials.py（modified — bot_webhook_key 字段）
- FOUND: backend/app/main.py（modified — lifespan 注册）
- FOUND: backend/.env.example（modified — WECOM_* 4 字段）

提交检查（3 commit hash）：

- FOUND: 3ad60ff (Task 0 + 1 reading doc + spike)
- FOUND: a332c8f (Task 2 card builder + 17 tests)
- FOUND: a5902c2 (Task 3 WeComProvider + lifespan + 17 tests)

测试统计：

- 17 card builder 测试全绿
- 17 provider 测试全绿
- 18 + 15 + 10 上游 IM 测试零回归
- **合计 77 tests pass in 20.37s**

---

*Phase 04-approval-chain-im — Plan 07*
*Completed: 2026-05-17*
