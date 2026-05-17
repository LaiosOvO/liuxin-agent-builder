---
phase: 04-approval-chain-im
plan: "05"
subsystem: notification-im
tags: [im-provider, registry, mock, credentials, im-jobs, abstraction]
dependency_graph:
  requires:
    - 04-01 (chain payload + ChainAdvanceResult)
    - 03-04 (email_jobs.py 模板 + _build_deeplink)
    - 03-01 (notifications 表 ORM)
  provides:
    - IMProvider Protocol（鸭子类型 + Phase 4.5 预留 subscribe/verify_webhook_signature）
    - ProviderRegistry（register / get / list / clear_providers）
    - MockIMProvider（测试 + E2E 用 + fail_count 支持 tenacity 重试场景）
    - IMCredentialsManager（5 家 frozen dataclass + .env 加载）
    - im_jobs.send_hitl_card_job（克隆 email_jobs 模板 + 结构化日志）
    - 5 家 provider name 常量（PROVIDER_FEISHU / WECOM / DINGTALK / SLACK / MATTERMOST）
    - CardBuilder Protocol + HitlCardPayload frozen dataclass（卡片构造抽象基类）
  affects:
    - Wave 4 plan 04-06/07/08/09（4 家 Provider 并行实现 — 全部 import 本 plan 抽象层）
    - Wave 5 plan 04-10（多通道 fan-out 调用 notif.channel 路由）
tech-stack:
  added: []
  patterns:
    - typing.Protocol + runtime_checkable（鸭子类型 + isinstance 校验）
    - 模块级 Registry dict + factory function（无 DI 框架）
    - @dataclass(frozen=True) 凭据 + 调用记录（CLAUDE.md immutability）
    - tenacity AsyncRetrying 1s/2s/4s 指数退避（与 email_jobs 一致）
    - 结构化日志 logger.info('im.card.send', extra={...})
    - audit_log action='im.send_failed' 显式可观测（NOTI-10）
key-files:
  created:
    - backend/app/agent_builder/notification/__init__.py
    - backend/app/agent_builder/notification/providers/__init__.py
    - backend/app/agent_builder/notification/providers/base.py (190 行)
    - backend/app/agent_builder/notification/providers/mock.py (172 行)
    - backend/app/agent_builder/notification/cards/__init__.py
    - backend/app/agent_builder/notification/cards/base.py (68 行)
    - backend/app/agent_builder/core/__init__.py
    - backend/app/agent_builder/core/im_credentials.py (252 行)
    - backend/app/jobs/im_jobs.py (215 行)
    - backend/tests/test_im_provider_protocol.py (327 行, 18 测试)
    - backend/tests/test_im_credentials_loader.py (305 行, 15 测试)
    - backend/tests/test_im_jobs_skeleton.py (433 行, 10 集成测试)
    - docs/reading-im-sdk-04-05-providers-2026-05-17.md (257 行)
  modified: []
decisions:
  - "[Phase 04-05] Protocol over ABC：用 typing.Protocol + runtime_checkable 不用 abc.ABC（CLAUDE.md python/patterns.md 推荐 + MockIMProvider 无需继承基类即可满足鸭子类型）"
  - "[Phase 04-05] 模块级 Registry dict + factory function（不用 FastAPI Depends — provider 应在 startup 一次注册而非每请求初始化）"
  - "[Phase 04-05] [Rule 3 - Blocking] runtime_checkable Protocol 校验依赖方法存在性 → MockIMProvider 必须实现 subscribe/verify_webhook_signature 抛 NotImplementedError（Protocol body NotImplementedError 默认行为不会被自动继承到鸭子类型 instance）"
  - "[Phase 04-05] 5 家 frozen dataclass per provider credentials（vs 通用 dict[str,str] — 类型清晰 + immutable）"
  - "[Phase 04-05] env 缺失 warn 不抛错（按需配置 — 用户可能只用 2-3 家）；getter 调用时缺失抛 RuntimeError + 提示需要的环境变量名"
  - "[Phase 04-05] env strip + 空字符串视为未配置（防 .env 文件意外引号 / 空格）"
  - "[Phase 04-05] register_provider 校验 name 必须在 KNOWN_PROVIDERS 集合（typo 防护，FakeProvider 抛 ValueError）"
  - "[Phase 04-05] get_provider 抛 KeyError 时携带已注册列表（便于排查）"
  - "[Phase 04-05] im_jobs 克隆 email_jobs 状态机（pending→sending→sent/failed + tenacity 3 次 1s/2s/4s + audit_log 失败可观测）"
  - "[Phase 04-05] im_jobs payload['im_message_id'] 写回（供后续 update_card；新 dict immutable 模式不修改既有 dict）"
  - "[Phase 04-05] 结构化日志 logger.info('im.card.send', extra={provider, recipient, status, latency_ms, notification_id, message_id}) — Phase 7 ELK / Loki 友好"
  - "[Phase 04-05] [Rule 1 - Bug] unknown provider 路径 audit_log 在 commit 之后调 → 移到 commit 之前一次性 commit（否则 audit_log 仅 buffered 不 flush）"
  - "[Phase 04-05] 不引入新 IM SDK 依赖（lark-oapi / wechatpy / 等留 04-06+ Provider 实现 plan 单独 import）"
  - "[Phase 04-05] backend/app/agent_builder/core/ 独立目录（不动 flock app/core/ — CLAUDE.md §2.3 Fork discipline）"
  - "[Phase 04-05] CardBuilder 用 Protocol 不用基类（各 Provider plan 自实现 build_hitl_card / build_supplement_text）"
  - "[Phase 04-05] HitlCardPayload 用 tuple[dict[str,str], ...] 而非 list（frozen dataclass + 不可变集合双重防修改）"
metrics:
  duration: "25min"
  completed_date: "2026-05-17"
---

# Phase 4 Plan 05: IMProvider Protocol + Registry + MockIMProvider + IMCredentialsManager + im_jobs.py Summary

**一句话**: Phase 4 IM 通知**抽象层基础设施** — IMProvider Protocol（鸭子类型 + Phase 4.5 入站接口预留）+ 模块级 Registry + MockIMProvider（测试用）+ IMCredentialsManager（5 家 .env 加载 + frozen dataclass）+ im_jobs.send_hitl_card_job（克隆 email_jobs 模板 + tenacity 重试 + 结构化日志），43 单元/集成测试全绿，Wave 4 04-06..09 四家具体 Provider plan 可并行启动。

---

## 完成的工作

### 1. notification 模块骨架

新增 `backend/app/agent_builder/notification/` 目录：
- `providers/` — IMProvider Protocol + Registry + 5 家 Provider 实现存放处
- `cards/` — 卡片构造抽象（各 Provider 自实现 build_*_card）

与 `backend/app/services/notification_service.py`（Phase 3 邮件入队）解耦：
- Phase 3 邮件 service 保留原位（向后兼容）
- Phase 4 IM 抽象走新 module，Wave 5 04-10 multichannel fan-out 时再扩展 notification_service

### 2. IMProvider Protocol（providers/base.py）

```python
@runtime_checkable
class IMProvider(Protocol):
    name: str
    async def send_hitl_card(*, recipient, flow_title, node_title, applicant_name,
                              actor_name, deadline_at, description, deeplinks) -> dict: ...
    async def update_card(*, message_id, new_content) -> None: ...
    async def send_supplement_text(*, recipient, text) -> None: ...
    # Phase 4.5 预留（默认 NotImplementedError）
    async def subscribe(on_event) -> None: ...
    async def verify_webhook_signature(headers, body) -> bool: ...
```

**5 家 provider name 常量**：
- `PROVIDER_FEISHU` / `PROVIDER_WECOM` / `PROVIDER_DINGTALK` / `PROVIDER_SLACK` / `PROVIDER_MATTERMOST`
- `KNOWN_PROVIDERS: frozenset` 防 typo（register_provider 校验）

**ProviderRegistry**：
```python
_PROVIDERS: dict[str, IMProvider] = {}
def register_provider(provider) -> None  # startup 注册 + KNOWN_PROVIDERS 校验
def get_provider(name) -> IMProvider     # 未注册抛 KeyError + 提示已注册列表
def list_providers() -> list[str]        # sorted 稳定顺序
def clear_providers() -> None            # 测试 fixture 用
```

### 3. MockIMProvider（providers/mock.py）

测试 + E2E 用 Provider — **不发真实 IM 请求，仅记录 calls 列表**：

```python
mock = MockIMProvider(name=PROVIDER_FEISHU)
register_provider(mock)
# ... 触发投递 ...
assert mock.calls[0].method == 'send_hitl_card'
assert mock.calls[0].recipient == 'ou_xyz'
```

**错误模拟**：
- `fail_send_hitl_card=True` — 所有 send_hitl_card 抛 ConnectionError
- `fail_count=2` — 前 2 次抛错，第 3 次成功（**测 tenacity 重试场景**）

**MockCallRecord**：`@dataclass(frozen=True)` 记录创建后不可修改。

### 4. IMCredentialsManager（core/im_credentials.py）

5 家凭据 frozen dataclass：
- `FeishuCredentials(app_id, app_secret)`
- `WeComCredentials(corp_id, agent_id, secret)`
- `DingTalkCredentials(app_key, app_secret)`
- `SlackCredentials(bot_token)`
- `MattermostCredentials(base_url, bot_token)`

`IMCredentialsManager`：
- `__init__` 调 `_load_from_env` 一次性加载所有
- `feishu() / wecom() / ...` getter — 未配置抛 RuntimeError + 提示 env 名
- `has_feishu() / ...` 检查 — 不抛错
- `list_configured()` — sorted 已配置 name 列表

**env 处理**：
- whitespace strip（防 .env 文件意外空格）
- 空字符串视为未配置
- 缺失 warn 不抛错（按需配置）

### 5. im_jobs.send_hitl_card_job（jobs/im_jobs.py）

克隆 `email_jobs.send_hitl_email_job` 状态机：

```
1. SELECT notifications WHERE id=:id
2. 幂等：if status=='sent' 跳过
3. status='sending' + commit
4. provider = get_provider(notif.channel)  # 未注册→fail+audit_log
5. 渲染 deeplinks（复用 email_jobs._build_deeplink — DRY）
6. tenacity 3 次 1s/2s/4s 指数退避调 provider.send_hitl_card
7. 成功 → status='sent' + sent_at + payload['im_message_id']（供 update_card）
8. 失败 → status='failed' + error_message + audit_log action='im.send_failed'
9. 结构化日志 logger.info('im.card.send', extra={provider, recipient, status,
                          latency_ms, notification_id, message_id})
```

**重试触发**：`(ConnectionError, TimeoutError, OSError)` — 业务错误不重试。

### 6. CardBuilder Protocol（cards/base.py）

各 Provider plan 实现自己的 build_*_card：

```python
@dataclass(frozen=True)
class HitlCardPayload:
    flow_title: str
    node_title: str
    applicant_name: str
    actor_name: str
    deadline_at: str
    description: str
    deeplinks: tuple[dict[str, str], ...]  # tuple 双重不可变

class CardBuilder(Protocol):
    provider_name: str
    def build_hitl_card(payload: HitlCardPayload) -> dict[str, Any]: ...
    def build_supplement_text(*, who_processed: str, action: str) -> str: ...
```

---

## 测试结果（43 测试全绿）

### test_im_provider_protocol.py（18 用例）

| 测试 | 覆盖点 |
|---|---|
| test_mock_provider_satisfies_protocol | runtime_checkable isinstance 校验 |
| test_known_providers_frozenset_contains_5 | 5 家常量 + frozenset 不可变 |
| test_register_and_get_provider | Registry CRUD 正确路径 |
| test_get_unknown_provider_raises_keyerror | 未注册抛 KeyError + 携带已注册列表 |
| test_register_provider_with_invalid_name_raises | typo 防护（不在 KNOWN_PROVIDERS） |
| test_list_providers_returns_registered_names | sorted 稳定顺序 |
| test_clear_providers_for_test_isolation | fixture 隔离 |
| test_subscribe_raises_not_implemented | Phase 4.5 预留接口 |
| test_verify_webhook_signature_raises_not_implemented | Phase 4.5 预留接口 |
| test_mock_records_send_hitl_card_call | calls 列表填充 + message_id 返回 |
| test_mock_records_update_card_and_supplement_text | 3 method 都记录 |
| test_mock_fail_send_hitl_card_raises_connection_error | 错误模拟开关 |
| test_mock_fail_count_simulates_intermittent_failure | tenacity 重试场景 |
| test_mock_call_record_is_frozen | MockCallRecord immutable |
| test_mock_reset_clears_calls_and_attempts | fixture 复用支持 |
| test_hitl_card_payload_is_frozen | HitlCardPayload immutable |
| test_hitl_card_payload_default_deeplinks_is_empty_tuple | tuple 默认 |
| test_card_builder_protocol_is_runtime_checkable_optional | CardBuilder 鸭子类型 |

### test_im_credentials_loader.py（15 用例）

| 测试 | 覆盖点 |
|---|---|
| test_load_with_feishu_env_creates_credentials | 单家 env 加载 |
| test_load_without_feishu_env_returns_none_until_getter_raises | getter 抛 RuntimeError |
| test_load_5_providers_independently | 5 家独立配置 |
| test_credentials_are_frozen | 5 个 dataclass(frozen=True) |
| test_load_warns_on_missing | caplog 5 条 warning |
| test_load_no_warning_when_all_configured | 全配置 → 无 warning |
| test_has_provider_returns_correct_bool | has_* 检查 |
| test_list_configured_returns_sorted_names | sorted 列表 |
| test_list_configured_empty_when_none | 空配置返回空列表 |
| test_partial_wecom_env_does_not_create_credentials | 企微 3 字段缺 1 → 不创建 |
| test_partial_mattermost_env_does_not_create_credentials | Mattermost 缺 token → 不创建 |
| test_whitespace_in_env_is_stripped | env 两端空白被 strip |
| test_empty_string_env_treated_as_missing | "" + 仅空白 → 视为未配置 |
| test_feishu_credentials_dataclass_equality | 相同字段相等 |
| test_all_5_credentials_have_distinct_types | 5 个独立类 |

### test_im_jobs_skeleton.py（10 集成测试 — 真实 PG + MockIMProvider）

| 测试 | 覆盖点 |
|---|---|
| test_send_hitl_card_job_success | mock 调用 + status='sent' + im_message_id 写回 payload |
| test_send_hitl_card_job_idempotent_skip_sent | status='sent' → 不重发 |
| test_send_hitl_card_job_retries_on_connection_error | fail_count=2 → 第 3 次成功 |
| test_send_hitl_card_job_fails_after_3_retries | fail_count=10 → status='failed' + audit_log |
| test_send_hitl_card_job_unknown_provider_fails | channel='nonexistent' → fail + audit_log |
| test_send_hitl_card_job_structured_log_emitted | caplog 'im.card.send' + extra 字段 |
| test_send_hitl_card_job_provider_receives_correct_args | 7 个入参 + deeplinks 完整 |
| test_send_hitl_card_job_writes_im_message_id_to_payload | payload['im_message_id'] 写入 |
| test_send_hitl_card_job_missing_notification_no_op | 不存在 ID → log.error 不抛 |
| test_send_hitl_card_job_failure_log_extra_fields | 失败 caplog status='failed' + error |

---

## 5 家 .env 凭据字段映射表

| Provider   | .env 变量名                                          | dataclass 字段                  |
|------------|------------------------------------------------------|---------------------------------|
| feishu     | FEISHU_APP_ID, FEISHU_APP_SECRET                     | app_id, app_secret              |
| wecom      | WECOM_CORP_ID, WECOM_AGENT_ID, WECOM_SECRET          | corp_id, agent_id, secret       |
| dingtalk   | DINGTALK_APP_KEY, DINGTALK_APP_SECRET                | app_key, app_secret             |
| slack      | SLACK_BOT_TOKEN                                      | bot_token                       |
| mattermost | MATTERMOST_URL, MATTERMOST_BOT_TOKEN                 | base_url, bot_token             |

---

## send_hitl_card_job 状态机 + 结构化日志 schema

### 状态机

```
pending ─┐
         ├─→ sending ─→ sent (provider.send_hitl_card 成功)
         │             ↓
         │             payload['im_message_id'] 写回 + sent_at + commit
         │
         └─→ sending ─→ failed (3 次 tenacity 重试均失败 / unknown provider)
                       ↓
                       error_message + audit_log action='im.send_failed' + commit

sent → 二次调用：log.info 跳过（幂等）
```

### 结构化日志 schema

```python
logger.info("im.card.send", extra={
    "provider": str,           # PROVIDER_FEISHU / ...
    "recipient": str,          # IM user_id
    "status": str,             # 'sent' / 'failed'
    "latency_ms": int,         # 从 job 开始到结束总耗时
    "notification_id": int,    # BIGSERIAL
    "message_id": str | None,  # provider 返回的消息 ID（成功时）
    "error": str | None,       # 失败时错误摘要（≤ 200 字符）
})
```

Phase 7 ELK / Loki 查询友好：
- `provider:feishu AND status:failed`
- `latency_ms:>1000`（慢调用告警）

---

## Phase 4.5 预留接口（subscribe / verify_webhook_signature）

Protocol 一次定义完整，各 Provider Phase 4 仅实现 NotImplementedError stub：

```python
async def subscribe(self, on_event: Any) -> None:
    raise NotImplementedError(f"{self.name} subscribe 将于 Phase 4.5 实现")

async def verify_webhook_signature(self, headers, body) -> bool:
    raise NotImplementedError(f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现")
```

**Phase 4.5 Bot Trigger plan** 各 Provider 实现真实 webhook 接收 + dispatch；不需要改 Protocol，仅在各 Provider class 添加方法即可（向后兼容）。

---

## Dify 参考点

详见 `docs/reading-im-sdk-04-05-providers-2026-05-17.md`。

Dify **没有 IM Provider 抽象**（仅 LLM API 多厂商接入）；本 plan 借鉴的是 Dify
`api/core/model_runtime/model_providers/` 的**多 provider 抽象设计**：

| Dify 模式 | 本项目对应 |
|---|---|
| `ModelProvider` 基类 + 厂商 plugin/yaml | `IMProvider` Protocol + Registry register_provider |
| `model_provider_factory.get_provider_schema()` | `get_provider(name)` 工厂函数 |
| Provider yaml credential schema | `IMCredentialsManager` + per-provider `frozen dataclass` |
| Provider lifecycle (init/cleanup) | FastAPI lifespan 注入 + clear_providers fixture |

**关键差异**：
- 本项目用 `typing.Protocol` 鸭子类型，不用 `abc.ABC`（CLAUDE.md python/patterns.md 推荐）
- 凭据用 5 家独立 frozen dataclass，不用通用 dict（类型清晰 + immutable）

**hr/offboarding-flow 参考点**：仅借鉴 IMProvider 接口设计风格（send_message / update_message），**不复制源码**（hr 项目独立，许可证不同）。

---

## Wave 4 下游依赖（04-06..09 4 plans 可并行）

| Plan | 内容 | import 本 plan 的什么 |
|------|------|----------------------|
| 04-06 | FeishuProvider（lark-oapi 1.6.5 + Interactive Card 2.0） | IMProvider + register_provider + IMCredentialsManager.feishu() |
| 04-07 | WeComProvider（wechatpy 1.8.18 + spike templated card） | IMProvider + IMCredentialsManager.wecom() |
| 04-08 | DingTalkProvider（dingtalk-stream 0.24.3 + ActionCard） | IMProvider + IMCredentialsManager.dingtalk() |
| 04-09 | SlackProvider + MattermostProvider（slack-bolt + httpx 直调） | IMProvider + IMCredentialsManager.slack() / mattermost() |

每 plan 仅添加 1 个 Provider 文件 + 注册到 lifespan + 单元测试（mock SDK 调用），互不冲突可并行。

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] MockIMProvider 必须实际实现 subscribe/verify_webhook_signature**

- **Found during:** Task 1（test_mock_provider_satisfies_protocol 失败）
- **Issue:** `runtime_checkable` Protocol 校验依赖 instance 上方法存在性；Protocol 内 `raise NotImplementedError` 默认实现不会被自动继承到鸭子类型 instance（不像 ABC 那样）。`isinstance(mock, IMProvider)` 返回 False
- **Fix:** MockIMProvider 显式实现这两个方法（同样抛 NotImplementedError），与 Protocol 默认行为保持一致；这也是 Phase 4 各真实 Provider 的预期模式（Phase 4.5 实现时各自覆盖）
- **Files modified:** backend/app/agent_builder/notification/providers/mock.py
- **Commit:** 88c5ee9

**2. [Rule 1 - Bug] unknown provider 路径 audit_log commit 顺序**

- **Found during:** Task 3（test_send_hitl_card_job_unknown_provider_fails 失败 — audit_logs 行数 0）
- **Issue:** 原代码先 `await db.commit()` 提交 notif.status='failed'，再调 `_write_audit_log_failure`，audit_log 只 buffered 不 flush
- **Fix:** 调换顺序 — 先 `_write_audit_log_failure(db, notif, ...)` buffer audit_log，再一次性 `await db.commit()` 提交 notif.status 改动 + audit_log
- **Files modified:** backend/app/jobs/im_jobs.py
- **Commit:** 2e1eb05

### Architectural Decisions

无 Rule 4 架构变更。

---

## 关键技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Provider 抽象 | `typing.Protocol + runtime_checkable` | CLAUDE.md python/patterns.md 推荐；MockIMProvider 无需继承基类即可满足鸭子类型 |
| Registry | 模块级 dict + factory function | provider 应在 startup 一次注册（vs FastAPI Depends 每请求初始化） |
| 凭据存储 | 5 家独立 frozen dataclass | 类型清晰（vs 通用 dict[str,str]） + immutable（防外部修改） |
| env 缺失策略 | warn 不抛错；getter 抛 RuntimeError | 按需配置（用户可能只用 2-3 家） + 调用时清晰提示 |
| im_jobs 重试 | tenacity 3 次 1s/2s/4s + ConnectionError/TimeoutError/OSError | 与 email_jobs 完全一致（运维一致性） |
| 结构化日志 | `logger.info('im.card.send', extra={...})` | Phase 7 ELK/Loki 查询友好；vs 字符串拼接 |
| im_message_id 写回 | 成功后 `payload['im_message_id']`（新 dict immutable 模式） | 供 04-10 update_card 用 |
| CardBuilder | `Protocol` 不是基类 | 与 IMProvider 设计一致；各 Provider plan 自实现 |
| 目录隔离 | `backend/app/agent_builder/core/` 独立 | CLAUDE.md §2.3 Fork discipline：不动 flock `app/core/` |

---

## Self-Check: PASSED

文件检查（4 个新建 + 8 个核心 file）：
- FOUND: backend/app/agent_builder/notification/__init__.py
- FOUND: backend/app/agent_builder/notification/providers/__init__.py
- FOUND: backend/app/agent_builder/notification/providers/base.py
- FOUND: backend/app/agent_builder/notification/providers/mock.py
- FOUND: backend/app/agent_builder/notification/cards/__init__.py
- FOUND: backend/app/agent_builder/notification/cards/base.py
- FOUND: backend/app/agent_builder/core/__init__.py
- FOUND: backend/app/agent_builder/core/im_credentials.py
- FOUND: backend/app/jobs/im_jobs.py
- FOUND: backend/tests/test_im_provider_protocol.py
- FOUND: backend/tests/test_im_credentials_loader.py
- FOUND: backend/tests/test_im_jobs_skeleton.py
- FOUND: docs/reading-im-sdk-04-05-providers-2026-05-17.md

提交检查（4 个 commit hash）：
- FOUND: f29162e (Task 0 reading doc)
- FOUND: 88c5ee9 (Task 1 Protocol + Registry + Mock + cards)
- FOUND: 5b11ba8 (Task 2 IMCredentialsManager)
- FOUND: 2e1eb05 (Task 3 im_jobs.send_hitl_card_job)

测试统计：
- 43 单元/集成测试全绿（18 + 15 + 10）
- 0 regression（email_jobs 8 测试仍全绿）
- Total 51 tests pass in 14.55s

---

*Phase 04-approval-chain-im — Plan 05*
*Completed: 2026-05-17*
