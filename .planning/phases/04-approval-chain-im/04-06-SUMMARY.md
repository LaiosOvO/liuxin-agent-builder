---
phase: 04-approval-chain-im
plan: "06"
subsystem: notification-im
tags: [feishu, im-provider, interactive-card-2.0, lark-oapi, multi-url-button]
dependency_graph:
  requires:
    - 04-05 (IMProvider Protocol + Registry + IMCredentialsManager + HitlCardPayload)
    - lark-oapi 1.6.5 SDK (CLAUDE.md §3 锁定)
  provides:
    - FeishuProvider 实现 IMProvider Protocol (PROVIDER_FEISHU="feishu")
    - build_feishu_hitl_card / build_feishu_processed_card / build_feishu_supplement_text
    - main.py lifespan FeishuProvider 注册 (按 mgr.has_feishu() 条件)
    - lark-oapi==1.6.5 在 pyproject.toml 锁定
  affects:
    - Wave 5 04-10 (multichannel fan-out 调 get_provider("feishu") + im_jobs.send_hitl_card_job)
    - Phase 4.5 (Bot Trigger plan 覆盖 FeishuProvider.subscribe / verify_webhook_signature)
tech-stack:
  added:
    - "lark-oapi==1.6.5 (Builder 模式 client + im.v1.message.create/patch + tenant_access_token cache)"
    - "pycryptodome 3.23+ (lark-oapi 传递依赖，飞书 webhook 签名校验用 — Phase 4.5)"
  patterns:
    - "importlib.metadata.version 获取真实版本 (lark.__version__ 属性不存在)"
    - "@property 延迟 client 初始化 (避免 import 时建网络连接)"
    - "loop.run_in_executor 包装同步 SDK 在 asyncio 内执行"
    - "Interactive Card 2.0 JSON 结构 (config + header + elements[div/hr/action/note])"
    - "multi_url button 4 URL 字段全填 (url/pc_url/android_url/ios_url) 防降级"
    - "按钮颜色映射 (approve=primary/reject=danger/return=default)"
    - "ConnectionError 触发 im_jobs.tenacity 重试 / 234016 跳过 / 非关键路径只 log warning"
    - "immutability — build_feishu_processed_card 不修改入参 dict"
key-files:
  created:
    - backend/app/agent_builder/notification/cards/feishu_card.py (222 行)
    - backend/app/agent_builder/notification/providers/feishu.py (315 行)
    - backend/tests/test_feishu_card_builder.py (334 行, 26 测试)
    - backend/tests/test_feishu_provider.py (455 行, 19 测试)
    - docs/reading-im-sdk-04-06-feishu-2026-05-17.md (338 行)
  modified:
    - backend/app/agent_builder/main.py (lifespan 添加 has_feishu() 注册分支，+19 行)
    - backend/pyproject.toml (新增 "lark-oapi==1.6.5"，+1 行)
decisions:
  - "[Phase 04-06] 用 importlib.metadata.version('lark-oapi') 取版本，不用 lark.__version__ — 后者在 1.6.5 不存在（reading doc §3 验证）"
  - "[Phase 04-06] @property client 延迟初始化 — 避免 module import 时建网络连接（与单元测试 client.im.v1.message.create monkeypatch 兼容）"
  - "[Phase 04-06] 同步 lark SDK 在 async 内通过 loop.run_in_executor(None, ...) 包装 — 不采用未文档化的 AsyncClient（reading doc §8）"
  - "[Phase 04-06] multi_url 4 URL 字段全填 — 飞书桌面端若缺 pc_url 会降级到 url（reading doc §5.3）"
  - "[Phase 04-06] 按钮颜色映射定义为模块级 _ACTION_COLOR_MAP / _ACTION_LABEL_MAP dict — 集中维护 + 测试可断言常量"
  - "[Phase 04-06] update_card 24h 时间窗过期 (code=234016) → log warning 不抛错 — 流程超时正常情况，避免无谓 tenacity 重试"
  - "[Phase 04-06] send_supplement_text 失败仅 log warning 不抛错 — 非关键路径，主流程已通过 update_card / 卡片状态完成"
  - "[Phase 04-06] build_feishu_processed_card 浅拷贝 + 重组 elements 列表 — CLAUDE.md immutability，测试 deepcopy 对比验证不修改入参"
  - "[Phase 04-06] subscribe / verify_webhook_signature 抛 NotImplementedError + Phase 4.5 提示 — 与 IMProvider Protocol 默认行为一致"
  - "[Phase 04-06] 测试用 monkeypatch 替换 client.im.v1.message.create/patch — 不打飞书真实 API（单元测试不依赖外部服务）"
  - "[Phase 04-06] _MockLarkResponse 实现 BaseResponse 完整接口 (code/msg/data/success()/get_log_id()) — 测试 fixture 模拟成功 + 失败 + 24h 过期 3 场景"
metrics:
  duration: "12min"
  completed_date: "2026-05-17"
  tasks: 3
  files_created: 5
  files_modified: 2
  tests_added: 45
---

# Phase 4 Plan 06: Feishu IMProvider 实现 Summary

**一句话**: 飞书 IM Provider 完整实现 — 实现 IMProvider Protocol (PROVIDER_FEISHU)，通过 lark-oapi 1.6.5 SDK 投递 Interactive Card 2.0 决策卡片（4 按钮 + 4 字段双列 + multi_url 4 URL 全填）+ patch_message 卡片更新（24h 过期降级）+ 文本补发兜底；importlib.metadata 取版本规避 SDK 缺失 `__version__` 属性陷阱；同步 SDK 在 asyncio 内通过 `loop.run_in_executor` 包装；main.py lifespan 按 `mgr.has_feishu()` 条件注册；45 单元测试全绿（26 card + 19 provider）。

---

## 完成的工作

### 1. 卡片构造器 (cards/feishu_card.py — 3 纯函数)

#### build_feishu_hitl_card

返回飞书 Interactive Card 2.0 JSON dict（**未** json.dumps — 序列化由 Provider 做）：

```python
{
  "config": {"wide_screen_mode": True},
  "header": {
    "title": {"tag": "plain_text", "content": "📋 审批待办：员工入职流程"},
    "template": "blue",
  },
  "elements": [
    {"tag": "div", "fields": [4 个 lark_md 双列字段 节点/申请人/审批人/截止时间]},
    {"tag": "div", "text": {"tag": "lark_md", "content": "**详情**\n..."}},
    {"tag": "hr"},
    {"tag": "action", "actions": [N 个 multi_url button]},
  ],
}
```

按钮颜色映射（模块级常量）：

| action | type | 中文 label |
|---|---|---|
| approve | primary | 同意 |
| return | default | 退回 |
| reject | danger | 拒绝 |
| detail | default | 查看详情 |
| submit | default | 提交 |

multi_url 字段全填（url/pc_url/android_url/ios_url 同值）防桌面端降级。

#### build_feishu_processed_card

决策后转为只读卡片，CLAUDE.md immutability — 不修改入参：

- 浅拷贝 header dict + template 改 grey
- 列表推导生成新 elements（过滤 action 块）
- 追加 note 角标 `✓ 已被 {processed_by} 处理`

测试 `test_processed_card_does_not_mutate_original` 用 `copy.deepcopy` 快照对比验证。

#### build_feishu_supplement_text

补发文本（≤ 200 字）：`f"该审批流程已被 {who_processed} {label}，无需进一步操作。"`

---

### 2. FeishuProvider (providers/feishu.py)

满足 IMProvider Protocol 鸭子类型（`isinstance(provider, IMProvider)` is True）：

```python
class FeishuProvider:
    name = PROVIDER_FEISHU  # "feishu"

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self._client: lark.Client | None = None
        # 启动校验 SDK 版本（不抛错，仅 warning）
        if _resolve_lark_version() != _EXPECTED_LARK_VERSION:
            log.warning(...)

    @property
    def client(self) -> lark.Client:
        if self._client is None:
            self._client = lark.Client.builder().app_id(...).app_secret(...).build()
        return self._client

    async def send_hitl_card(self, *, recipient, ...) -> dict:
        card = build_feishu_hitl_card(...)
        request = CreateMessageRequest.builder().receive_id_type("open_id")....build()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self.client.im.v1.message.create, request)
        if not response.success():
            raise ConnectionError(f"...code={code} msg={msg} log_id={log_id}")
        return {"message_id": response.data.message_id, "raw_response": {...}}

    async def update_card(...) -> None:
        # 234016 (消息已过期 24h 外 patch) → log warning 不抛错
        ...

    async def send_supplement_text(...) -> None:
        # 失败仅 log warning（非关键路径）
        ...

    async def subscribe(self, on_event) -> None:
        raise NotImplementedError(f"{self.name} subscribe 将于 Phase 4.5 实现")

    async def verify_webhook_signature(self, headers, body) -> bool:
        raise NotImplementedError(...)
```

**关键设计点**：

| 决策点 | 选择 | 原因 |
|---|---|---|
| 版本检查方式 | `importlib.metadata.version("lark-oapi")` | `lark.__version__` 属性不存在（reading doc §3） |
| client 初始化时机 | `@property` 延迟构造 | 避免 import 时建网络；测试 monkeypatch 友好 |
| async 集成 | `loop.run_in_executor(None, sync_call, request)` | lark-oapi 1.6.5 是同步 SDK，未公开 AsyncClient |
| 错误包装 | `ConnectionError(...)` | 让 im_jobs.tenacity 3 次重试 (1s/2s/4s) |
| 24h 过期 | `log.warning` + return None | 流程已超时正常，避免无谓重试 |
| supplement_text 失败 | `log.warning` 不抛错 | 非关键路径，主流程已通过 update_card 完成 |

---

### 3. main.py lifespan 集成

在 `backend/app/agent_builder/main.py` 的 `_register_im_providers_if_configured()` 添加：

```python
if mgr.has_feishu():
    try:
        from app.agent_builder.notification.providers.feishu import FeishuProvider
        creds = mgr.feishu()
        provider = FeishuProvider(app_id=creds.app_id, app_secret=creds.app_secret)
        register_provider(provider)
        _logger.info("FeishuProvider 注册成功 app_id=%s", creds.app_id)
    except Exception as exc:
        _logger.warning("FeishuProvider 注册失败（非阻断）: %s", exc)
```

特点：
- 凭据齐全（`FEISHU_APP_ID` + `FEISHU_APP_SECRET`）才注册
- 注册失败 log warning 不阻断启动（与既有 DingTalk 模式一致）

---

### 4. SDK 版本锁定

在 `backend/pyproject.toml` 添加：

```toml
"lark-oapi==1.6.5",
```

CLAUDE.md §3 强制 — 1.6.0/1/2/3 已被 PyPI yanked，必须 pin 1.6.5。

---

## 测试结果（45 测试全绿）

### test_feishu_card_builder.py（26 用例 — 纯函数单元测试）

| # | 测试 | 覆盖点 |
|---|---|---|
| 1 | test_build_card_contains_3_buttons_for_3_deeplinks | 按钮数量 = deeplinks 数量 |
| 2 | test_build_card_approve_button_is_primary_color | approve → primary |
| 3 | test_build_card_reject_button_is_danger_color | reject → danger |
| 4 | test_build_card_return_button_is_default_color | return → default |
| 5 | test_build_card_chinese_labels_correct | 同意/退回/拒绝/查看详情 |
| 6 | test_build_card_unknown_action_keeps_action_name | 未知 action → 原名 + default 颜色 |
| 7 | test_build_card_multi_url_has_all_4_url_fields | url/pc_url/android_url/ios_url 全填 |
| 8 | test_build_card_button_preserves_deeplink_url | 按钮 url 等于 deeplinks 传入值 |
| 9 | test_build_card_header_contains_flow_title | header.title 含"审批待办：流程名" |
| 10 | test_build_card_header_template_is_blue | 新卡片蓝色 template |
| 11 | test_build_card_fields_contain_4_node_details | 节点/申请人/审批人/截止 4 字段 |
| 12 | test_build_card_description_in_separate_div_block | description 独立 div |
| 13 | test_build_card_has_hr_separator | hr 分隔线存在 |
| 14 | test_build_card_wide_screen_mode_enabled | config.wide_screen_mode=True |
| 15 | test_build_card_accepts_tuple_deeplinks | tuple 输入兼容（HitlCardPayload） |
| 16 | test_build_card_empty_deeplinks_produces_empty_actions | 空 deeplinks → 空 actions |
| 17 | test_processed_card_removes_action_block | 决策后移除按钮 |
| 18 | test_processed_card_appends_note_with_processor_name | 追加 note 角标含处理人 |
| 19 | test_processed_card_header_template_is_grey | header 变 grey |
| 20 | test_processed_card_preserves_original_title | header.title 不变 |
| 21 | test_processed_card_does_not_mutate_original | immutability — deepcopy 对比 |
| 22 | test_processed_card_preserves_description_div | 保留 fields + description div |
| 23 | test_supplement_text_includes_processor_and_action | 含处理人 + 中文动作 |
| 24 | test_supplement_text_for_reject_includes_chinese_label | reject → 拒绝 |
| 25 | test_supplement_text_length_under_200 | ≤ 200 字符 |
| 26 | test_action_color_map_contains_4_standard_actions | 4 标准 action 都已映射 |

### test_feishu_provider.py（19 用例 — monkeypatch SDK 单元测试）

| # | 测试 | 覆盖点 |
|---|---|---|
| 1 | test_feishu_provider_satisfies_im_provider_protocol | Protocol 鸭子类型 + name="feishu" |
| 2 | test_provider_client_lazy_initialization | client 延迟初始化（property 触发） |
| 3 | test_resolve_lark_version_returns_installed_version | importlib.metadata 取真实版本 1.6.5 |
| 4 | test_init_warns_when_version_mismatch | 版本不匹配 → warning |
| 5 | test_init_no_warning_when_version_matches | 1.6.5 匹配 → 无 warning |
| 6 | test_send_hitl_card_success_returns_message_id | 成功返回 message_id + raw_response.log_id |
| 7 | test_send_hitl_card_calls_create_with_interactive_msg_type | msg_type="interactive" + receive_id_type="open_id" |
| 8 | test_send_hitl_card_content_is_json_string_not_dict | content 是 json.dumps 字符串 + 解析回卡片 |
| 9 | test_send_hitl_card_raises_connection_error_on_failure | 99991663 → ConnectionError 含 code/msg/log_id |
| 10 | test_send_hitl_card_raises_on_token_expired | 11201 → ConnectionError（tenacity 用尽后写 failed） |
| 11 | test_send_hitl_card_3_deeplinks_become_3_buttons | 端到端：3 deeplinks → 3 action.actions |
| 12 | test_update_card_calls_patch_with_message_id | patch + 正确 message_id |
| 13 | test_update_card_serializes_content_to_json_string | content 是 json.dumps 字符串 |
| 14 | test_update_card_raises_connection_error_on_failure | 99991663 → ConnectionError |
| 15 | test_update_card_skips_when_message_expired | 234016 → log warning 不抛错 |
| 16 | test_send_supplement_text_uses_text_msg_type | msg_type="text" + content={"text":...} |
| 17 | test_send_supplement_text_failure_only_warns_no_raise | 失败仅 log warning |
| 18 | test_subscribe_raises_not_implemented | Phase 4.5 预留 |
| 19 | test_verify_webhook_signature_raises_not_implemented | Phase 4.5 预留 |

**覆盖率**：`providers/feishu.py` 97%（仅 `PackageNotFoundError` 回退路径未覆盖 — 测试环境必定安装 lark-oapi）

---

## Dify / 参考点（CLAUDE.md §2.7）

详见 `docs/reading-im-sdk-04-06-feishu-2026-05-17.md`。

Dify 没有专用 IM Provider 抽象（其多模型接入是 LLM 范式），本 plan 主要参考来源：

| 来源 | 借鉴点 | 应用 |
|---|---|---|
| lark-oapi 官方 README + SDK 源码 | Builder 模式构造 Request；BaseResponse.success/code/msg/get_log_id 接口 | FeishuProvider 直接调用 SDK 模式 |
| 飞书开放平台 Interactive Card 文档 §5 | Card 2.0 JSON schema（config/header/elements） | build_feishu_hitl_card JSON 结构 |
| 飞书开放平台 patch_message 文档 §6 | 24h 时间窗 + content 必须 json string | update_card 234016 跳过处理 |
| Python 标准库 importlib.metadata | 包元数据查询版本 | _resolve_lark_version 取代不存在的 `__version__` |
| 04-05 IMProvider Protocol | name/send_hitl_card/update_card/send_supplement_text 接口签名 | FeishuProvider 鸭子类型实现 |
| 04-05 MockIMProvider 模式 | subscribe/verify_webhook_signature 抛 NotImplementedError + Phase 4.5 提示 | FeishuProvider 一致行为 |

**未复制 Dify 源码**（许可证：AGPL-3.0 vs 本项目 Apache-2.0）。

**hr/offboarding-flow 参考**：04-05 reading doc 已记录接口设计风格借鉴；本 plan 独立实现，无源码复用。

---

## 已知限制 / Deferred

| 项 | 状态 | 何时处理 |
|---|---|---|
| Bot 入站 webhook + Slash 命令 | 未实现 | Phase 4.5 Bot Trigger plan |
| 飞书消息回执监听（已读未读） | 未实现 | Phase 4.5 / Phase 7 可观测性 |
| 卡片 i18n（英文 label） | 未实现 | v2 国际化 |
| AsyncClient 替代 run_in_executor | 未实现 | lark-oapi 1.7+ 公开 AsyncClient 后评估 |
| 飞书消息撤回 API（Phase 4 不需要） | N/A | — |

---

## Deviations from Plan

### 与原 plan context 的差异（小调整）

**1. [Rule 3 - Blocking] 版本校验改用 importlib.metadata 而非 `lark.__version__`**

- **Found during:** Task 0 (lark-oapi SDK 探查)
- **Issue:** plan context 示例 `getattr(lark, "__version__", "unknown")` — 实际验证 `lark.__version__` 属性不存在，永远返回 "unknown" → 启动永远 warning
- **Fix:** 改用标准库 `from importlib.metadata import version; version("lark-oapi")` 取真实包版本
- **Files modified:** providers/feishu.py (新增 `_resolve_lark_version` helper)
- **Reading doc § 3 已记录此陷阱**

**2. [Rule 2 - Critical Feature] update_card 24h 过期 (code=234016) 单独处理**

- **Found during:** Task 0（飞书 patch_message API 文档阅读）
- **Issue:** plan context 未指定 234016 错误的处理方式 — 默认会被包装为 ConnectionError 触发 tenacity 重试 3 次（无意义重试，浪费资源）
- **Fix:** update_card 内显式判断 `response.code == 234016` → log warning 直接 return（流程已超时正常情况，不视为错误）
- **Files modified:** providers/feishu.py
- **测试覆盖:** test_update_card_skips_when_message_expired

**3. [Rule 1 - Improvement] _MockLarkResponse 测试 fixture 完整化**

- **Found during:** Task 2 测试编写
- **Issue:** 原 plan context 仅说 "monkeypatch lark client" — 没具体定义 mock response 结构
- **Fix:** 创建 `_MockLarkResponse` dataclass + `_MockData(message_id)` 完整模拟 `BaseResponse` 接口（success/code/msg/data/get_log_id）
- **Files modified:** tests/test_feishu_provider.py
- **测试覆盖:** 19 测试全部依赖此 fixture

### Race Condition 观察（多 plan 并行执行）

Phase 4 Wave 4（04-06/07/08/09）并行 dispatch 4 个 agent，导致 git index 出现 race：

- Task 0 reading doc 文件被 04-07 commit (3ad60ff) 一并捎带提交
- Task 2 feishu.py + test_feishu_provider.py + main.py + pyproject.toml 被 04-09 commit (9afc5c7) 一并捎带提交
- **文件内容完整无损**，仅 commit 边界与 plan 不严格对齐
- 不影响功能 / 测试 / 依赖关系 — 后续 SUMMARY 提交补全归档

参考 CLAUDE.md §2.1 并行开发优先原则 — 接受 commit 散落代价以换取吞吐。

---

## 关键技术决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 版本检查方式 | `importlib.metadata.version("lark-oapi")` | SDK 不导出 `__version__` 属性 |
| Client 初始化时机 | `@property` 延迟构造 | import 时不建网络 / 测试 monkeypatch 友好 |
| async 集成 | `loop.run_in_executor(None, sync_call, request)` | lark-oapi 1.6.5 是同步 SDK |
| 错误包装层 | `ConnectionError(f"...code={code} msg={msg} log_id={log_id}")` | 触发 im_jobs.tenacity 重试 + 错误信息保留 |
| 234016 处理 | `log.warning + return None` | 流程超时正常情况，避免无谓重试 |
| supplement_text 失败 | `log.warning` 不抛错 | 非关键路径，主流程已通过其他渠道完成 |
| 卡片更新 immutability | `{**original_card, "header": {**...}, "elements": [...]}` | 浅拷贝 + 重组列表，测试 deepcopy 对比验证 |
| 按钮颜色映射 | 模块级 `_ACTION_COLOR_MAP` / `_ACTION_LABEL_MAP` dict | 集中维护 + 测试可断言常量 |
| Provider 注册时机 | FastAPI lifespan startup hook | 与既有 DingTalkProvider 注册模式一致 |
| 测试策略 | monkeypatch `client.im.v1.message.create/patch` | 不依赖飞书真实 API（CLAUDE.md 单元测试） |

---

## Self-Check: PASSED

**文件检查（5 创建 + 2 修改）：**

- FOUND: backend/app/agent_builder/notification/cards/feishu_card.py
- FOUND: backend/app/agent_builder/notification/providers/feishu.py
- FOUND: backend/tests/test_feishu_card_builder.py
- FOUND: backend/tests/test_feishu_provider.py
- FOUND: docs/reading-im-sdk-04-06-feishu-2026-05-17.md
- FOUND (modified): backend/app/agent_builder/main.py
- FOUND (modified): backend/pyproject.toml

**提交检查（3 commits）：**

- FOUND: 3ad60ff (Task 0 reading doc — race-merged with 04-07 commit but content intact)
- FOUND: d35d7a4 (Task 1 feishu_card.py + 26 单元测试)
- FOUND: 9afc5c7 (Task 2 feishu.py + 19 单元测试 + main.py lifespan + pyproject.toml — race-merged with 04-09 commit but content intact)

**测试统计：**

- 45 单元测试全绿（26 card + 19 provider）
- 0 regression（test_im_provider_protocol.py 18 + test_im_credentials_loader.py 15 仍全绿）
- providers/feishu.py 覆盖率 97%（仅 PackageNotFoundError 回退路径未覆盖）

---

*Phase 04-approval-chain-im — Plan 06*
*Completed: 2026-05-17 (Wave 4 并行执行)*
