---
phase: 04-approval-chain-im
plan: "08"
subsystem: notification-im
tags: [im-provider, dingtalk, action-card, oapi, dingtalk-stream, asyncsend-v2]
dependency_graph:
  requires:
    - 04-05 (IMProvider Protocol + Registry + IMCredentialsManager + HitlCardPayload)
    - 04-01 (notifications.payload tokens 字段)
  provides:
    - DingTalkProvider 实现（PROVIDER_DINGTALK = "dingtalk"）
    - build_dingtalk_action_card / build_dingtalk_supplement_text (cards/dingtalk_card.py)
    - _ZH_LABELS 中文按钮映射（approve/return/reject/detail/submit）
    - agent_builder/main.py lifespan IM Provider 按需注册基础设施
    - dingtalk-stream==0.24.3 锁定依赖
  affects:
    - 04-10 (multichannel fan-out — 通过 IMProvider Registry 路由到 DingTalkProvider)
    - 04-12 (E2E approval-chain — 钉钉通道 token 流转)
    - 04.5 (Bot Trigger — subscribe / verify_webhook_signature 接口已预留)
tech-stack:
  added:
    - dingtalk-stream==0.24.3 (钉钉官方 stream SDK — 仅用 Credential + get_access_token)
  patterns:
    - 同步 SDK + asyncio.to_thread 桥接（保留 SDK 5min token buffer 缓存）
    - httpx.AsyncClient 直调 OAPI（SDK 不暴露工作通知 ActionCard send）
    - frozen dataclass _DingTalkSendResult 内部响应解析（immutability）
    - pure function build_dingtalk_action_card（无状态、无副作用、不修改入参）
    - lifespan 按需注册：凭据齐全才注册 Provider；缺失 warn 不阻断启动
    - aclose() 资源回收（httpx client 连接池在 shutdown 时关闭）
    - ConnectionError 统一包装（OAPI errcode != 0 / 网络错 / 5xx → tenacity 可重试）
key-files:
  created:
    - backend/app/agent_builder/notification/cards/dingtalk_card.py (113 行)
    - backend/app/agent_builder/notification/providers/dingtalk.py (271 行)
    - backend/tests/test_dingtalk_card_builder.py (213 行, 19 测试)
    - backend/tests/test_dingtalk_provider.py (370 行, 18 测试)
    - docs/reading-im-sdk-04-08-dingtalk-2026-05-17.md (268 行)
  modified:
    - backend/app/agent_builder/main.py (lifespan 新增 IM Provider 注册 + aclose)
    - backend/pyproject.toml (锁定 dingtalk-stream==0.24.3)
key-decisions:
  - "[Phase 04-08] OAPI 直调 vs SDK 调用：dingtalk-stream 0.24.3 不暴露工作通知 ActionCard send 方法 — 走 httpx.AsyncClient 直调 /topapi/message/corpconversation/asyncsend_v2"
  - "[Phase 04-08] access_token 获取走 SDK：保留 SDK get_access_token 的 5min buffer 缓存逻辑 + asyncio.to_thread 桥接同步 requests 调用"
  - "[Phase 04-08] btn_orientation='0' 字符串硬编码横排（钉钉 OAPI 要求 string 类型，PC + 手机最佳兼容）"
  - "[Phase 04-08] update_card 抛 NotImplementedError：钉钉工作通知 ActionCard 静态不支持改 — 提示用 send_supplement_text 兜底（04-10 multichannel fan-out 用）"
  - "[Phase 04-08] ConnectionError 包装：OAPI errcode != 0（如 40078 token 过期）也包成 ConnectionError，触发 tenacity 重试新 token 后可成功"
  - "[Phase 04-08] _ZH_LABELS 中文 label 映射 + 未知 action 退化为原字符串（防新 action 类型加入时报错）"
  - "[Phase 04-08] 按钮固定走 btn_json_list（即使 1 个按钮也用列表 — 避免 single_title/single_url 与 btn_json_list 互斥触发 OAPI 错）"
  - "[Phase 04-08] HTTP client 注入式（默认按需创建 + asyncio.Lock 防并发竞争）— 测试可 monkeypatch；与 04-05 抽象层一致"
  - "[Phase 04-08] DINGTALK_AGENT_ID 直接从 env 读（非 IMCredentialsManager 字段 — 它是部署 config 而非凭据本身，避免改 04-05 已完成 plan）"
  - "[Phase 04-08] markdown 各字段间用 '\\n\\n'（双换行）保证钉钉客户端识别段落分隔"
  - "[Phase 04-08] lifespan 按需注册策略：has_dingtalk() 检查 + DINGTALK_AGENT_ID 校验都通过才注册，缺失 warn 不阻断启动"
  - "[Phase 04-08] subscribe / verify_webhook_signature 抛 NotImplementedError + 含 'Phase 4.5' 字样（Bot Trigger plan 时各 Provider 自实现）"
requirements-completed: [NOTI-04]
metrics:
  duration: "9min"
  completed_date: "2026-05-17"
---

# Phase 4 Plan 08: 钉钉 IM Provider (DingTalk ActionCard) Summary

**钉钉工作通知 ActionCard 出站投递实现 — dingtalk-stream 0.24.3 token 获取 + httpx 直调 OAPI asyncsend_v2 + 4 中文按钮横排卡片 + send_supplement_text 静态卡片兜底**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-17T02:50:24Z
- **Completed:** 2026-05-17T02:59:00Z
- **Tasks:** 3 (Reading doc + Card builder + Provider)
- **Files created:** 5 (1 SDK reading doc + 2 code + 2 tests)
- **Files modified:** 2 (main.py lifespan + pyproject.toml)
- **Tests added:** 37 (19 card builder + 18 provider)
- **Total IM tests passing:** 80 (43 from this plan + 37 existing — 0 regression)

## Accomplishments

- **DingTalkProvider** 实现 IMProvider Protocol 鸭子类型校验通过（runtime_checkable）
- **ActionCard JSON** 正确构造：msgtype="action_card" + btn_orientation="0" 横排 + 3 中文按钮（同意/退回/拒绝）
- **OAPI 集成**：httpx.AsyncClient 直调 `/topapi/message/corpconversation/asyncsend_v2` + asyncio.to_thread 桥接 SDK 同步 token 获取
- **错误统一包装**：OAPI errcode != 0 / 网络错 / 5xx → ConnectionError → im_jobs tenacity 3 次 1s/2s/4s 自动重试
- **静态卡片兜底**：update_card 抛 NotImplementedError 提示用 send_supplement_text；send_supplement_text 实现 msgtype="text" 工作通知
- **lifespan 注册基础设施**：按需注册（凭据齐全才注册），aclose 资源回收（httpx 连接池）
- **Phase 4.5 接口预留**：subscribe / verify_webhook_signature 抛 NotImplementedError + 提示

## Task Commits

每个 task 原子 commit（CLAUDE.md §4.2 单功能单 commit）：

1. **Task 0: Reading doc gate** - `926648d` (docs: 钉钉 ActionCard SDK + OAPI 阅读笔记)
2. **Task 1: ActionCard 构造器** - `0dae1ee` (feat: build_dingtalk_action_card + 19 单元测试)
3. **Task 2: DingTalkProvider + 注册** - `f88fde5` (feat: DingTalkProvider + 18 集成测试 + lifespan)

**Plan metadata commit:** 见末尾（含 SUMMARY.md / STATE.md / ROADMAP.md / REQUIREMENTS.md 更新）

## ActionCard JSON 示例

`build_dingtalk_action_card(HitlCardPayload(...))` 输出（送入 OAPI asyncsend_v2 的 msg 字段）：

```json
{
  "msgtype": "action_card",
  "action_card": {
    "title": "审批待办：员工入职流程",
    "markdown": "### 审批待办：员工入职流程\n\n**节点**: HR 审批\n\n**申请人**: 张三\n\n**审批人**: 李四\n\n**截止时间**: 2026-05-18T10:00:00Z\n\n**详情**:\n入职信息已填写完毕，请审批。\n",
    "btn_orientation": "0",
    "btn_json_list": [
      {"title": "同意", "action_url": "https://app.example.com/hitl/page/jti-approve"},
      {"title": "退回", "action_url": "https://app.example.com/hitl/page/jti-return"},
      {"title": "拒绝", "action_url": "https://app.example.com/hitl/page/jti-reject"}
    ]
  }
}
```

**关键字段说明**：
- `msgtype: "action_card"` — 钉钉约定下划线分隔（vs 飞书驼峰）
- `btn_orientation: "0"` — **字符串** 0 表示横排（"1" 竖排）
- `btn_json_list` — 多按钮列表（与 `single_title` / `single_url` 单按钮模式互斥）
- 每按钮 `action_url` 跳 Web 决策页（钉钉按钮仅支持 URL，无表单交互）

## OAPI 调用流程

```
1. DingTalkProvider.send_hitl_card(recipient, ...)
   ↓
2. self._get_access_token()
   ├─ 检查 sdk_client（不存在则延迟创建 dingtalk_stream.DingTalkStreamClient）
   └─ asyncio.to_thread(sdk_client.get_access_token)
      → SDK 内部 5min buffer 缓存命中 → 返回 cached token
      → 未命中 → 同步 POST /v1.0/oauth2/accessToken → 缓存 + 返回
   ↓
3. build_dingtalk_action_card(payload) → ActionCard JSON dict
   ↓
4. self._post_to_oapi(
       "/topapi/message/corpconversation/asyncsend_v2",
       access_token,
       {"agent_id": ..., "userid_list": recipient, "msg": card_msg}
   )
   ├─ httpx.AsyncClient.post(...) — base_url=https://oapi.dingtalk.com
   ├─ HTTP 500 → ConnectionError（临时不可用）
   ├─ HTTP 4xx → ConnectionError（客户端错）
   ├─ httpx.ConnectError / TimeoutException → ConnectionError（网络错）
   └─ 200 + JSON 解析 → _DingTalkSendResult(errcode, errmsg, task_id)
   ↓
5. result.errcode != 0 → ConnectionError(f"...errcode={code} errmsg={msg}")
   result.errcode == 0 → return {"message_id": task_id, "raw_response": {...}}
```

## 测试结果（37 测试全绿 + 80 IM 测试 0 regression）

### test_dingtalk_card_builder.py（19 用例 — 单元）

| 测试 | 覆盖点 |
|---|---|
| test_build_card_contains_action_card_msgtype | msgtype="action_card" 钉钉约定 |
| test_build_card_has_required_action_card_fields | title/markdown/btn_orientation/btn_json_list 4 字段 |
| test_build_card_btn_orientation_horizontal_string_zero | btn_orientation="0" 字符串横排 |
| test_build_card_markdown_contains_all_fields | flow_title/node_title/applicant/actor/deadline/description 全字段 |
| test_build_card_markdown_uses_heading_and_bold | ### 标题 + ** 加粗渲染 |
| test_build_card_title_includes_flow_title | ActionCard.title 含 flow_title |
| test_build_card_3_buttons_for_standard_approval | approve/return/reject 3 按钮 |
| test_build_card_btn_labels_chinese_for_known_actions | 同意/退回/拒绝中文映射 |
| test_build_card_unknown_action_uses_raw_label | 未知 action 不抛错 |
| test_build_card_with_empty_deeplinks_returns_empty_btn_list | 空 deeplinks 合法 |
| test_build_card_preserves_deeplink_url | URL 完整保留无截断 |
| test_build_card_does_not_mutate_payload | immutability：不改入参 |
| test_build_card_returns_new_dict_each_call | 每次返回新 dict（无单例） |
| test_zh_label_for_known_actions | _zh_label_for 5 标准 action |
| test_zh_label_for_unknown_action_returns_raw | 未知 action 返回原字符串 |
| test_zh_labels_contains_4_standard_actions | _ZH_LABELS 含 approve/return/reject/detail |
| test_supplement_text_uses_chinese_label | 补发文本中文 label |
| test_supplement_text_handles_unknown_action | 未知 action 不抛错 |
| test_supplement_text_under_200_chars | 长度 ≤ 200 |

### test_dingtalk_provider.py（18 用例 — 集成 mock httpx）

| 测试 | 覆盖点 |
|---|---|
| test_provider_implements_improvider_protocol | runtime_checkable isinstance 校验 |
| test_provider_name_is_dingtalk | name="dingtalk" == PROVIDER_DINGTALK |
| test_send_hitl_card_calls_oapi_with_correct_payload | asyncsend_v2 URL + agent_id + userid_list + msg 字段 |
| test_send_hitl_card_returns_message_id_from_task_id | message_id 来自 OAPI task_id |
| test_send_hitl_card_action_card_msgtype_correct | body.msg.msgtype="action_card" + btn_orientation + 3 按钮 |
| test_send_hitl_card_includes_access_token_in_query_params | access_token 在 URL query string |
| test_send_hitl_card_passes_recipient_as_userid_list | recipient → body.userid_list |
| test_send_hitl_card_raises_connection_error_on_oapi_errcode_nonzero | errcode=40078 → ConnectionError |
| test_send_hitl_card_raises_connection_error_on_network_failure | httpx.ConnectError → ConnectionError |
| test_send_hitl_card_raises_connection_error_on_500 | HTTP 503 → ConnectionError |
| test_get_access_token_raises_connection_error_when_sdk_returns_none | SDK 返 None → ConnectionError |
| test_update_card_raises_not_implemented_with_supplement_hint | update_card 抛错 + 提示用 send_supplement_text |
| test_send_supplement_text_uses_text_msgtype | msgtype="text" + text.content |
| test_send_supplement_text_raises_connection_error_on_oapi_failure | supplement OAPI 失败也包 ConnectionError |
| test_subscribe_raises_not_implemented | Phase 4.5 占位 |
| test_verify_webhook_signature_raises_not_implemented | Phase 4.5 占位 |
| test_dingtalk_send_result_is_frozen | _DingTalkSendResult immutability |
| test_aclose_closes_http_client | aclose 关闭 httpx + 可重复调用 |

### 回归测试（80 测试，0 regression）

```
tests/test_dingtalk_card_builder.py     19 passed
tests/test_dingtalk_provider.py         18 passed
tests/test_im_provider_protocol.py      18 passed  (04-05)
tests/test_im_credentials_loader.py     15 passed  (04-05)
tests/test_im_jobs_skeleton.py          10 passed  (04-05)
─────────────────────────────────────
Total                                   80 passed in 12.38s
```

## 钉钉 SDK 参考点

详见 `docs/reading-im-sdk-04-08-dingtalk-2026-05-17.md`。

| 参考来源 | 借鉴点 | 本项目对应 |
|---|---|---|
| `dingtalk_stream.Credential` 类 | client_id + client_secret 简洁构造 | `DingTalkCredentials(app_key, app_secret)` (04-05 已建) |
| `DingTalkStreamClient.get_access_token` | 5min buffer 缓存 + 同步 requests | asyncio.to_thread 桥接 + 复用 SDK 缓存 |
| 钉钉 OAPI ActionCard 文档 | msgtype/action_card/btn_json_list 结构 | build_dingtalk_action_card 函数式构造 |
| 钉钉错误码 40078 / 60011 | access_token / userid 错误识别 | 统一包成 ConnectionError 让 tenacity 处理重试 |

**关键决策**（vs 其他 4 家 Provider）：

| Feature | 钉钉（本 plan） | 飞书（04-06） | 企微（04-07） |
|---------|-------------|-------------|-------------|
| SDK 调用 | OAPI HTTP（SDK 仅用 token） | lark_oapi Client 全调 | wechatpy API |
| 卡片类型 | action_card（静态） | interactive（动态） | template_card（静态） |
| update_card | ❌ NotImpl | ✅ patch_card | ❌ NotImpl |
| 按钮 | btn_json_list horizontal | actions block | button_list |

## Decisions Made

参见 frontmatter `key-decisions` — 12 个决策详细记录。

**核心：**
- OAPI HTTP 直调（SDK 不暴露 ActionCard send）
- SDK token 缓存复用（避免重写 5min buffer 逻辑）
- ConnectionError 统一包装（让 tenacity 透明处理重试）
- update_card 故意不实现（提示用 send_supplement_text — 与企微一致）
- lifespan 按需注册（凭据 + AGENT_ID 双校验）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pyproject.toml 缺 dingtalk-stream 依赖锁**
- **Found during:** Task 2（Provider 实现时）
- **Issue:** CLAUDE.md §3 锁定 dingtalk-stream==0.24.3，但 pyproject.toml 未列入。手工 `uv pip install` 仅本地生效，CI / 新环境会缺。
- **Fix:** pyproject.toml dependencies 末尾加 `"dingtalk-stream==0.24.3"`
- **Files modified:** backend/pyproject.toml
- **Verification:** `.venv/bin/python -c "import dingtalk_stream; print(dingtalk_stream.version.VERSION_STRING)"` → 0.24.3
- **Committed in:** f88fde5 (Task 2 commit)

**2. [Rule 2 - Missing Critical] lifespan 缺 IM Provider 注册基础设施**
- **Found during:** Task 2（Provider 实现完才发现 agent_builder/main.py lifespan 没注册任何 IM Provider）
- **Issue:** 04-05 已经建好 Registry，但 startup 时未挂载 Provider — 04-08 Provider 实现完毕但 production 不可用
- **Fix:** lifespan 新增 `_register_im_providers_if_configured` + `_close_registered_im_providers`，钉钉作为首个 Provider 接入：has_dingtalk() 检查 + DINGTALK_AGENT_ID env 校验都通过才注册。**为 Wave 4 其他 3 家 Provider（飞书/企微/Slack/Mattermost）建好扩展点**。
- **Files modified:** backend/app/agent_builder/main.py
- **Verification:** `python -c "from app.agent_builder.main import agent_builder_app; print('OK')"` → 加载成功，30+ 路由不变
- **Committed in:** f88fde5 (Task 2 commit)

**3. [Rule 1 - Bug] dingtalk-stream 不在 conda 全局 env，仅在 .venv**
- **Found during:** Task 0 后期（导入 dingtalk_stream 报错）
- **Issue:** 初次 `python -c "import dingtalk_stream"` 用了 conda 全局 env (`/Volumes/T7/programe/env/conda/bin/python`)，SDK 未装；项目实际用 `backend/.venv/bin/python`
- **Fix:** 切换到 `.venv/bin/python` + `uv pip install dingtalk-stream==0.24.3` + 同步 pyproject.toml
- **Files modified:** backend/.venv/...（运行时安装）+ pyproject.toml
- **Verification:** `.venv/bin/python` 下成功 import + 测试全绿
- **Committed in:** f88fde5（pyproject.toml 锁定）

---

**Total deviations:** 3 auto-fixed (1 blocking + 1 missing critical + 1 bug)
**Impact on plan:** 全部必要修正，无 scope creep。deviation 2（lifespan 基础设施）超出本 plan 单 Provider 边界但是 Wave 4 必经环节，提早建好节省其他 3 个 Provider plan 的重复劳动。

## Issues Encountered

- **dingtalk-stream 0.24.3 SDK 不暴露工作通知 ActionCard 发送方法**：SDK 主要面向 stream 模式接收 webhook，发送侧仅有群机器人卡片（AICardReplier）。**决策：跳过 SDK，httpx 直调 OAPI**（reading doc 已论证）。
- **SDK get_access_token 是同步 requests 调用**：阻塞 event loop 风险。**决策：asyncio.to_thread 包装**（每次创建线程开销可忽略，且保留 SDK 5min buffer 缓存逻辑）。
- **conda 全局 env vs backend/.venv 混淆**：初次测试用错 Python 解释器导致 SDK import 失败。已切换到 `.venv/bin/python` 并锁定 pyproject.toml。

## User Setup Required

部署 production 时需配置以下 env 变量才能启用钉钉通道：

```
DINGTALK_APP_KEY=<your_app_key>
DINGTALK_APP_SECRET=<your_app_secret>
DINGTALK_AGENT_ID=<your_agent_id_int>
```

未配置时 lifespan 仅 warn 不阻断启动；其他 IM 通道（飞书 / 企微 / Slack / Mattermost）独立工作。

钉钉开放平台后台需：
1. 创建企业内部应用
2. 启用「工作通知消息」权限
3. 复制 AppKey / AppSecret / AgentId 到 .env

## Next Phase Readiness

**Wave 4 剩余可继续并行**：
- 04-06 (Feishu) — 复用本 plan 建好的 lifespan 注册扩展点
- 04-07 (WeCom) — 同上
- 04-09 (Slack + Mattermost) — 同上

**Wave 5 (04-10) multichannel fan-out** 可使用：
- `get_provider("dingtalk")` 路由到本 plan 实现
- `send_supplement_text` 作为决策推进后通知其他通道用户的兜底（钉钉静态卡片无法 update）

**Phase 4.5 Bot Trigger** 接口已预留：
- `DingTalkProvider.subscribe` / `verify_webhook_signature` 抛 `NotImplementedError` 含 "Phase 4.5" 字样
- 4.5 plan 实现时启动 `DingTalkStreamClient.start_forever()` + `register_callback_handler` 即可，不改 Protocol

---

## Self-Check: PASSED

文件检查（6 个）：
- FOUND: .planning/phases/04-approval-chain-im/04-08-SUMMARY.md
- FOUND: backend/app/agent_builder/notification/cards/dingtalk_card.py
- FOUND: backend/app/agent_builder/notification/providers/dingtalk.py
- FOUND: backend/tests/test_dingtalk_card_builder.py
- FOUND: backend/tests/test_dingtalk_provider.py
- FOUND: docs/reading-im-sdk-04-08-dingtalk-2026-05-17.md

提交检查（3 个 task commit hash）：
- FOUND: 926648d (Task 0 reading doc)
- FOUND: 0dae1ee (Task 1 card builder + 19 测试)
- FOUND: f88fde5 (Task 2 DingTalkProvider + 18 测试 + lifespan)

测试统计：
- 37 新增测试全绿（19 单元 + 18 集成）
- 80 IM 测试总通过（包含 04-05 抽象层 43 + 本 plan 37），0 regression
- 总耗时 9 min

---

*Phase 04-approval-chain-im — Plan 08*
*Completed: 2026-05-17*
