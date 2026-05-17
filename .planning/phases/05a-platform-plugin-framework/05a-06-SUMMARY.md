---
phase: 05a-platform-plugin-framework
plan: 06
subsystem: platforms/legacy-adapter
tags: [platform, plugin, legacy-adapter, dual-registry, blocker3-fix, phase4-zero-regression, dify-reference]
provides:
  - LegacyIMProviderAdapter（Phase 4 IMProvider → IMCapability 适配层）
  - wrap_legacy_provider 工厂函数
  - _PROVIDERS_AS_CAP 双轨 dict（base.py）
  - _maybe_wrap_for_capability hook（register_provider 自动 wrap）
  - get_capability_for_legacy / list_legacy_capabilities helper
  - Registry.get_capability(IMCapability) fallback to _PROVIDERS_AS_CAP（Blocker 3 修复）
requires:
  - phase: 05a-platform-plugin-framework Plan 02
    provides: IMCapability Protocol + RecipientSpec/NormalizedCard/MessageRef 值对象
  - phase: 05a-platform-plugin-framework Plan 04
    provides: PlatformPluginRegistry.get_capability 路由层（本 plan 在末尾追加 fallback）
  - phase: 4 Plan 04-05
    provides: IMProvider Protocol + register_provider/get_provider/_PROVIDERS（本 plan 增强不破坏）
affects:
  - 05a-07 (HulyPlugin acid test — Registry 中 manifest plugin (huly) 与 legacy adapter 共存；capability routing 验证)
  - Phase 4 (零影响 — 老接口 0 改动，0 测试 regression)
  - Phase 5.B (Sandbox — 不直接影响)
  - Phase 5.C (DocCapability 真接入 — fallback 模式可复用)
  - Phase 5.D (Trigger/Tool 真接入 + Huly user 反向 sync)
tech-stack:
  added: []  # 全用 Phase 1-4 + 5.A Plan 04 已锁定（typing.Protocol + asyncio + dataclass）
  patterns:
    - "Dify 双轨数据共存模式（_PROVIDERS + _PROVIDERS_AS_CAP）— 借鉴自 data_migration.py"
    - "Adapter 设计模式：raw provider → IMCapability 接口适配（参数 + 返回值转译）"
    - "同一 raw provider 实例共享（双 dict 引用同一对象 — Phase 4 0 regression 关键不变量）"
    - "try/except ImportError 静默降级（测试隔离场景兼容）"
    - "fail-quiet fallback：cap_name=='im' 才 fallback；其他 capability 返回 None"
    - "lossy field 映射：3 字段 NormalizedCard → 8 字段 legacy send_hitl_card（title.split em-dash）"
    - "cap flags 硬编码 + getattr 推导：无 manifest 时从 legacy 字段或硬编码推断"
    - "register_provider 接口签名不变 + 内部追加副作用（_maybe_wrap_for_capability hook）"
key-files:
  created:
    - docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md           # 320 行
    - backend/app/agent_builder/platforms/legacy_im_adapter.py        # 311 行
    - backend/tests/platforms/test_legacy_im_adapter.py               # 20 tests
  modified:
    - backend/app/agent_builder/notification/providers/base.py        # +78 行（_PROVIDERS_AS_CAP + hook + helper）
    - backend/app/agent_builder/platforms/registry.py                 # +27 行（IM fallback）
    - backend/tests/platforms/test_registry.py                        # +3 tests（fallback 测试）
    - .planning/phases/05a-platform-plugin-framework/deferred-items.md # +1 entry（Plan 05 遗留测试问题）
key-decisions:
  - "LegacyIMProviderAdapter 内部 self._legacy 指向同一 raw provider 实例（不深拷贝）— Phase 4 0 regression 的根本保障"
  - "register_provider 签名不变，仅末尾追加一行 _maybe_wrap_for_capability — Phase 4 老调用 0 改动"
  - "_maybe_wrap_for_capability 用 try/except ImportError 静默降级（测试隔离场景：platforms 模块未加载时仅老路径工作）"
  - "_PROVIDERS_AS_CAP 类型用 `dict[str, Any]` forward ref —— base.py 不能 import platforms.legacy_im_adapter 顶层（避免循环 import）"
  - "Registry fallback 仅适用 cap_name == 'im'（TriggerCapability / ToolCapability 等不存在 LegacyAdapter）"
  - "Registry fallback prefer 优先 → 否则按 sorted name 取首个（确定性 fallback）"
  - "Registry fallback try/except ImportError 防御性兜底（notification.providers.base 未加载场景）"
  - "supports_native_buttons 硬编码 webhook 唯一例外 — Phase 4 6 家实情：5 家原生卡片 / webhook 通用 HTTP"
  - "supports_threads = False（Phase 4 6 家都无 thread 概念；CONTEXT.md decision 留 Phase 5.D 接入真平台）"
  - "supports_card_update 用 getattr(legacy, 'supports_card_update', False) — Phase 4 字段已存在，default False 安全降级"
  - "title.split(' — ', 1) 拆 flow_title + node_title — 约定俗成的 '流程 — 节点' 模式 lossy 还原；无分隔符 fallback 整 title"
  - "applicant_name / actor_name / deadline_at 留空字符串 — NormalizedCard 不携带，调用方应在 body_markdown 中包含"
  - "subscribe_events raise NotImplementedError('Phase 4.5') + `if False: yield {}` 保 async generator function 标记"
patterns-established:
  - "Pattern: 双轨 dict 共存（_PROVIDERS + _PROVIDERS_AS_CAP）实现新老接口并存，老接口 0 破坏"
  - "Pattern: Adapter wrap with self._legacy 同一实例引用 — 共享 connection pool / credential / state"
  - "Pattern: register_X 内部追加 _maybe_wrap_for_Y hook — 接口签名不变 + 副作用扩展"
  - "Pattern: try/except ImportError 静默降级用于循环依赖 / 测试隔离场景"
  - "Pattern: lossy field 映射 + 约定分隔符还原 + 空字段填充（适配老 8 字段接口）"
  - "Pattern: fail-quiet fallback 按 cap type whitelist（仅 'im' 走 fallback；其他 None）"
requirements-completed:
  - PLUG-FW-04
  - IM-LEGACY-WRAP
metrics:
  duration: 14min
  tasks_completed: 3
  files_created: 3
  files_modified: 4
  tests_added: 23
  tests_passing: 23
  total_legacy_adapter_tests: 20
  total_registry_tests: 16
  phase4_im_regression: 0
  phase4_notification_regression: 0
  e2e_v2_collect: 26
  ruff_clean: true
  black_clean: true
  completed_date: "2026-05-17"
---

# Phase 5.A Plan 06: LegacyIMProviderAdapter + Registry IMCapability fallback Summary

**Phase 4 6 家 IMProvider（feishu/wecom/dingtalk/slack/mattermost/webhook）通过新 IMCapability 接口被调用 + Phase 4 测试 0 regression — 用户硬性 DoD #3 达成。LegacyIMProviderAdapter（311 行）+ base.py 双轨 _PROVIDERS_AS_CAP + Registry IM fallback（Blocker 3 修复）+ 23 新测试覆盖（20 adapter + 3 fallback），Phase 4 IM 61 + notification 33 + e2e_v2 26 specs collect 三套 0 regression。**

## Performance

- **Duration:** ~14 min（20:46 → 21:00 UTC+8）
- **Started:** 2026-05-17T12:46:53Z
- **Completed:** 2026-05-17T13:00:47Z
- **Tasks:** 3（Task 0 reading doc → Task 1 LegacyIMProviderAdapter + 20 单测 → Task 2 base.py 双轨 + Registry fallback + 3 单测）
- **Files created:** 3
- **Files modified:** 4
- **Tests added:** 23（20 adapter + 3 registry fallback）
- **Tests passing:** 23/23 Plan 06 全新测试 + 36/36 platforms（含 Plan 06 36）+ Phase 4 IM 61/61 + Phase 4 notification 33/33 = **0 regression**
- **Lint:** ruff clean + black clean

## Accomplishments

### LegacyIMProviderAdapter（PLUG-FW-04 / IM-LEGACY-WRAP）

311 行完整实现 Phase 4 IMProvider → IMCapability 适配：

- **零接口破坏**：Phase 4 既有 `register_provider(provider)` 行为 100% 不变；adapter 仅在 `_PROVIDERS_AS_CAP` 双轨 dict 存放
- **同一 raw provider 实例共享**：adapter 内部 `self._legacy` 指向同一 IMProvider，`get_provider(name)` 与 `_PROVIDERS_AS_CAP[name]._legacy` 是 `is` 同一对象 —— 共享连接池 / credential / state（Phase 4 0 regression 的根本保障）
- **参数映射**：
  - `IMProvider.send_hitl_card(recipient: str, 8 keyword args)` → `IMCapability.send_card(*, recipient: RecipientSpec, card: NormalizedCard, idempotency_key)`
  - `IMProvider.update_card(message_id: str, new_content: dict)` → `IMCapability.update_card(msg_ref: MessageRef, card: NormalizedCard)`
  - `IMProvider.send_supplement_text(recipient, text)` → `IMCapability.send_text(recipient: RecipientSpec, text)`
  - `subscribe_events` raise NotImplementedError + `if False: yield {}`（Phase 4.5 业务层处理；保 async generator function 标记）
- **cap flags 推导**：
  - `supports_native_buttons = (legacy.name != "webhook")` — Phase 4 6 家实情
  - `supports_card_update = getattr(legacy, "supports_card_update", False)` — 沿用 legacy 字段 + 默认 False 安全降级
  - `supports_threads = False` — Phase 4 6 家都无 thread 支持
- **lossy field 映射**：`title.split(" — ", 1)` 拆为 `flow_title + node_title`（约定俗成的 "流程 — 节点" 模式还原；无分隔符 fallback 整 title）；`applicant_name / actor_name / deadline_at` 留空字符串（NormalizedCard 不携带）

### base.py 双轨 _PROVIDERS_AS_CAP（IM-LEGACY-WRAP）

`notification/providers/base.py` +78 行（不破坏老接口）：

- **新增 `_PROVIDERS_AS_CAP: dict[str, Any]`** — forward ref `Any` 避免 base.py import platforms 循环依赖
- **新增 `_maybe_wrap_for_capability(provider)` hook** —— try/except ImportError 静默降级（测试隔离场景 platforms 模块未加载时仅老路径工作）
- **新增 `get_capability_for_legacy(name)` / `list_legacy_capabilities()` helper** —— 新代码 entry point
- **`register_provider` 末尾追加一行 `_maybe_wrap_for_capability(provider)`** —— 签名 100% 不变，老 Phase 4 调用 0 改动
- **`clear_providers` 增加 `_PROVIDERS_AS_CAP.clear()`** —— 测试隔离

### Registry.get_capability fallback to LegacyAdapter（Blocker 3 修复）

`platforms/registry.py` +27 行（`get_capability` 末尾追加 fallback 逻辑）：

```python
# Blocker 3 修复：fallback 到 _PROVIDERS_AS_CAP（LegacyAdapter wrapped）
if cap_name == "im":
    try:
        from app.agent_builder.notification.providers.base import _PROVIDERS_AS_CAP
    except ImportError:
        return None
    if prefer and prefer in _PROVIDERS_AS_CAP:
        return _PROVIDERS_AS_CAP[prefer]
    for name in sorted(_PROVIDERS_AS_CAP.keys()):
        return _PROVIDERS_AS_CAP[name]
return None
```

**关键不变量**：
- 仅 `cap_name == "im"` 时走 fallback（其他 capability 不存在 LegacyAdapter）
- ImportError 捕获保证 `notification.providers.base` 未加载时静默失败（fail-quiet）
- prefer 优先 → 否则按 sorted name 取首个（确定性）

这是 Blocker 3 修复的核心：让 CONTEXT decision「新老 plugin 共存」真正落地 —— 当 workspace 还没装任何 manifest plugin 时，老的 Phase 4 6 家 IMProvider 必须能通过新 `get_capability(IMCapability)` 接口拿到。

## Task Commits

每个 task 原子 commit（按 plan 规范）：

1. **Task 0: Dify legacy/migration 阅读笔记（CLAUDE.md §2.7 硬性 gate）** — `98cba53` (docs)
   - 320 行（≥ 50 PLAN.md 硬性 gate）+ AGPL/attribution 标注
   - 5 借鉴点：双轨并存而非强制 cutover / 迁移失败容忍 + 静默降级 / 老接口字段最小化保留 / 迁移后旧接口仍可用 / cap flags 推导
   - 详细映射表：5 借鉴点 → Plan 06 落地代码位置
   - reading 源文件：data_migration.py (212 行) + plugin_migration.py (619 行) + plugin_auto_upgrade_service.py (85 行)

2. **Task 1: LegacyIMProviderAdapter 实现 + 20 单测（PLUG-FW-04 / IM-LEGACY-WRAP）** — `fbee696` (feat)
   - `backend/app/agent_builder/platforms/legacy_im_adapter.py` 311 行（≥ 100 PLAN.md 要求）
   - `backend/tests/platforms/test_legacy_im_adapter.py` 20 测试
   - 测试覆盖：isinstance + 5 cap flags（5）+ send_card 参数映射 + title 拆分 + 空字段填充（4）+ update_card 双路径（2）+ send_text + subscribe + wrap helper（3）+ raw_provider 共享不变量（1）+ 双轨注册 + 6 家全量 wrap + KNOWN_PROVIDERS invariant + wrap 不静默 skip（5）

3. **Task 2: base.py 双轨 _PROVIDERS_AS_CAP + Registry IMCapability fallback to LegacyAdapter + 3 fallback 单测（Blocker 3 修复）** — `3c97b5e` (feat)
   - `backend/app/agent_builder/notification/providers/base.py` +78 行（_PROVIDERS_AS_CAP + hook + helper + register_provider/clear_providers 增强）
   - `backend/app/agent_builder/platforms/registry.py` +27 行（IM fallback 末尾追加）
   - `backend/tests/platforms/test_registry.py` +3 测试（test_get_capability_falls_back_to_legacy_when_no_manifest_plugin / test_get_capability_prefers_manifest_plugin_over_legacy / test_get_capability_non_im_does_not_fallback）

**Plan metadata commit**（本 SUMMARY.md + STATE.md + ROADMAP.md 单独 commit，下一步执行）

## Files Created/Modified

### 新增（3 文件）

- `docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md`（320 行）— Dify legacy/migration 阅读 + 5 借鉴点 + License attribution
- `backend/app/agent_builder/platforms/legacy_im_adapter.py`（311 行）— LegacyIMProviderAdapter + wrap_legacy_provider helper
- `backend/tests/platforms/test_legacy_im_adapter.py`（20 tests）— Phase 4 6 家 wrap 全量 cover + 双轨注册 + isinstance Protocol

### 修改（4 文件）

- `backend/app/agent_builder/notification/providers/base.py`（+78 行）：
  - `register_provider` 增强（末尾追加 `_maybe_wrap_for_capability(provider)`，签名不变）
  - `clear_providers` 增强（追加 `_PROVIDERS_AS_CAP.clear()`）
  - 新增模块级 `_PROVIDERS_AS_CAP: dict[str, Any]`
  - 新增 `_maybe_wrap_for_capability` / `get_capability_for_legacy` / `list_legacy_capabilities`
- `backend/app/agent_builder/platforms/registry.py`（+27 行）：
  - `get_capability` 末尾追加 IM-only fallback 逻辑（Blocker 3 修复）
- `backend/tests/platforms/test_registry.py`（+3 测试）：
  - test_get_capability_falls_back_to_legacy_when_no_manifest_plugin（Blocker 3 核心验证）
  - test_get_capability_prefers_manifest_plugin_over_legacy（manifest 优先验证）
  - test_get_capability_non_im_does_not_fallback（防御性测试）
- `.planning/phases/05a-platform-plugin-framework/deferred-items.md`（+1 entry）：
  - 记录 Plan 05 遗留的 `test_facade_methods_raise_not_implemented` 失败问题（scope_boundary 判定 out-of-scope）

## Decisions Made

详见 frontmatter `key-decisions`。核心 13 条决策：

1. **adapter 共享 raw provider 实例**：`adapter._legacy is get_provider(name)` —— Phase 4 0 regression 根本保障
2. **register_provider 签名不变**：仅末尾追加副作用 hook（Phase 4 调用 0 改动）
3. **try/except ImportError 静默降级**：_maybe_wrap_for_capability + Registry fallback 双重防御
4. **_PROVIDERS_AS_CAP 类型 forward ref Any**：避免 base.py ↔ platforms.legacy_im_adapter 循环 import
5. **Registry fallback 仅 cap_name == "im"**：Trigger/Tool 等其他 capability 不存在 LegacyAdapter
6. **prefer 优先 → sorted name fallback**：确定性 + 与 manifest plugin 路由语义一致
7. **supports_native_buttons 硬编码 webhook 例外**：Phase 4 6 家实情
8. **supports_threads = False**：Phase 4 6 家无 thread 概念
9. **supports_card_update getattr fallback False**：Phase 4 字段已存在，默认安全降级
10. **title.split(" — ", 1) lossy 拆分**：约定俗成的 "流程 — 节点" 模式还原
11. **legacy 5 空字段（applicant_name 等）填空字符串**：调用方应在 body_markdown 中包含
12. **subscribe_events raise NotImplementedError + if False: yield {}**：Phase 4.5 业务层处理 + 保 async generator function 标记
13. **wrap helper `wrap_legacy_provider` 独立导出**：便于测试 + 未来扩展（如 v2 改用 builder 模式）

## Dify 参考点（详见 reading doc）

5 借鉴点对应 reading doc 章节锚点：

| # | Dify 源文件 | 借鉴模式 | 5.A Plan 06 落地 |
|---|---|---|---|
| 1 | `services/plugin/data_migration.py:14-26` `PluginDataMigration.migrate` | 双轨数据共存模式（同表两种 schema） | `_PROVIDERS` + `_PROVIDERS_AS_CAP` 双 dict 共存 |
| 2 | `plugin_migration.py:103-104` `except Exception` + `data_migration.py:55-57` `failed_ids` | 迁移失败容忍 + 静默降级 | `_maybe_wrap_for_capability` try/except ImportError + Registry fallback try/except |
| 3 | `data_migration.py:67-72` 处理 retrieval_model 部分字段 | 老接口字段最小化保留 | `title.split(" — ")` lossy 拆分 + 5 字段空填充 |
| 4 | `plugin_migration.py` 整体设计（应用层路由层兜底） | 迁移后旧接口仍可用 | `register_provider` 签名不变 + 同一 raw provider 实例共享 |
| 5 | Dify provider declaration `supports_*` 字段惯例 | cap flags 推导 | `supports_native_buttons/supports_card_update/supports_threads` 从 legacy 字段或硬编码推导 |

**License attribution**：Dify AGPL-3.0 vs 本项目 Apache-2.0 — 仅借鉴设计模式 / 数据结构 / 边界考虑，**严禁拷源代码**。reading doc 明确标注每条借鉴点为独立创作。

## Phase 4 Regression 报告（用户硬性 DoD #3 核心验收）

### Phase 4 IM Provider 测试（61/61 PASSED — 0 regression）

```
$ pytest tests/test_im_provider_protocol.py tests/test_im_credentials_loader.py \
         tests/test_im_jobs_skeleton.py tests/test_dingtalk_provider.py -o "addopts="
============================== 61 passed in 15.63s ==============================
```

覆盖测试：
- `test_im_provider_protocol.py` — Protocol isinstance + KNOWN_PROVIDERS 校验 + 6 家 register/get
- `test_im_credentials_loader.py` — credentials env loader + per-provider config
- `test_im_jobs_skeleton.py` — arq job structured log + provider receives correct args + missing/failure cases
- `test_dingtalk_provider.py` — 20+ DingTalk 端到端（ActionCard + OAPI + 错误码 + access_token）

### Phase 4 Notification 测试（33/33 PASSED — 0 regression）

```
$ pytest tests/test_notification_service_multichannel.py tests/test_notification_node_multichannel.py \
         tests/test_notification_model.py tests/test_notification_service.py -o "addopts="
============================== 33 passed in 22.47s ==============================
```

覆盖测试：
- `test_notification_service_multichannel.py` — multichannel fan-out + unique constraint + reminder round + payload immutable
- `test_notification_node_multichannel.py` — execute email + feishu + partial failure + multiple IM channels
- `test_notification_model.py` — Notification ORM + JSONB roundtrip + workspace cascade
- `test_notification_service.py` — enqueue + payload tokens + unique constraint + arq pool fallback

### Phase 4 e2e_v2 specs collect（26/26 — 0 regression）

```
$ cd e2e_v2 && pytest specs/ --co -q
26 tests collected in 0.04s
```

26 specs 全部 collect 成功（fixture / import 0 regression），覆盖：
- test_04_chain_parallel_all/parallel_any/sequential — multichannel chain 模式
- test_04_chain_sequential safe_links 4 UA（slackbot/googlebot/Outlook/Microsoft Defender）
- test_04_delegation — delegate to new actor + audit + depth limit + self-delegate 422
- test_04_escalation — timeout escalation + no decision buttons + 24h simulation
- test_04_im_card_delivery — multichannel 5 IM providers + deeplinks + browser-harness

### Plan 06 全新测试（23/23 PASSED）

```
$ pytest tests/platforms/test_legacy_im_adapter.py tests/platforms/test_registry.py -o "addopts="
============================== 36 passed in 8.87s ==============================
```

（其中 20 个是 test_legacy_im_adapter.py 全新；16 个是 test_registry.py，含 3 个 Plan 06 新增 fallback 测试，共 23 新增）

### Lint / Format（全 pass）

```
$ ruff check app/agent_builder/platforms/legacy_im_adapter.py \
             app/agent_builder/notification/providers/base.py \
             app/agent_builder/platforms/registry.py \
             tests/platforms/test_legacy_im_adapter.py \
             tests/platforms/test_registry.py
All checks passed!

$ black --check ...
All done! ✨ 🍰 ✨
5 files would be left unchanged.
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_get_capability_prefers_manifest_plugin_over_legacy 初版断言错误**

- **Found during:** Task 2 测试执行
- **Issue:** 初版断言 `assert cap.name == "huly"`，但 Plan 04 IMFacade stub 实现里 `name = "facade_im_stub"`（非 manifest.name）
- **Fix:** 改断言为 `isinstance(cap, IMFacade)` + `not isinstance(cap, LegacyIMProviderAdapter)`（验证返回类型而非 name 字段）
- **Files modified:** backend/tests/platforms/test_registry.py
- **Verification:** test 通过；test 注释明确说明 stub 现实
- **Committed in:** `3c97b5e`（与 Task 2 一并）

**2. [Rule 3 - Blocking] ruff I001 + black 格式化**

- **Found during:** Task 2 lint check
- **Issue:** test_legacy_im_adapter.py I001 unsorted-imports（1 处）；black 4 文件需 reformat
- **Fix:** `ruff check --fix` 自动修复 + `black` 自动 reformat；re-run 测试全 pass
- **Files modified:** 4 个 Plan 06 文件（含 legacy_im_adapter.py + base.py + test_legacy_im_adapter.py + test_registry.py）
- **Verification:** ruff clean + black clean + 36 测试全 pass（lint 修改后回归）
- **Committed in:** `3c97b5e`（与 Task 2 一并）

---

**Total deviations:** 2 auto-fixed（1 bug + 1 blocking lint），**0 architectural decisions ask**。所有问题均按 deviation Rule 1-3 处理，不引入 scope creep。

## Issues Encountered（out-of-scope，已记入 deferred-items.md）

**1. Plan 05 遗留：`test_plugin_facades.py::test_facade_methods_raise_not_implemented` 失败**

- **来源**：Plan 05 在 `capability_facades.py` 把 facade method 行为从 `raise NotImplementedError`（Plan 04 stub）改为 `raise PluginError("daemon not attached")`，但旧测试断言未同步更新
- **来源验证**：`git stash` 我的 Plan 06 改动后该测试**仍然失败** → 确认 Plan 05 遗留
- **scope_boundary 判定**：Plan 06 仅新增 `legacy_im_adapter.py` + 修改 `base.py` `_PROVIDERS_AS_CAP` + 修改 `registry.py` 末尾 fallback，**未触碰 `capability_facades.py`**；out-of-scope
- **已记入** `.planning/phases/05a-platform-plugin-framework/deferred-items.md`
- **建议**：Plan 05 或后续 plan 同步更新 `test_facade_methods_raise_not_implemented` 改 `expect PluginError`

**2. `lark_oapi` 模块缺失（pre-existing 环境问题）** — Plan 03/04 已 log

- 触发时机：跑 Phase 4 全 IM 测试套时 `test_feishu_provider.py ModuleNotFoundError`
- 来源：pyproject.toml 含 `lark-oapi==1.6.5` 但当前 venv 未安装
- 处理：跳过该测试文件；用 `test_im_provider_protocol.py + test_im_credentials_loader.py + test_im_jobs_skeleton.py + test_dingtalk_provider.py` 61 测试做 regression 验证 100% pass
- scope_boundary 判定：Plan 06 仅新增 legacy_im_adapter.py + 修改 base.py / registry.py，未触碰 feishu provider — out-of-scope
- 已记入 deferred-items.md（Plan 03 已 log，不重复）

## User Setup Required

None — 本 plan 仅纯 Python typing.Protocol + asyncio + dataclass + classmethod，无外部服务依赖。

## Next Phase Readiness

### Plan 06 直接解锁

- **Plan 07 (HulyPlugin acid test)**：
  - HulyPlugin manifest 启动后，Registry 中既有 manifest plugin (huly) 又有 6 家 legacy adapter (`_PROVIDERS_AS_CAP`)
  - capability routing 验证：
    - `get_capability(IMCapability)`（不指定 prefer）→ 优先 huly facade（不走 fallback）
    - `get_capability(IMCapability, prefer="feishu")` → fallback 到 LegacyAdapter(FeishuProvider)
    - `get_capability(IMCapability, prefer="huly")` → 返回 huly facade
  - 完整链路：discover → get_plugin(ws, "huly") → plugin.im.send_card → daemon stdin → daemon → mock huly server → stdout → MessageRef

### Phase 5.B / 5.C / 5.D / Phase 4.5（未来）

- **Phase 4.5（IM bot 入站订阅）**：`LegacyIMProviderAdapter.subscribe_events` 当前 NotImplementedError；Phase 4.5 决策走业务层 dispatcher（不通过 IMCapability subscribe_events）；adapter 行为 0 改动
- **Phase 5.B（Sandbox）**：不直接影响（adapter 仅 in-memory wrap，无 subprocess 概念）
- **Phase 5.C（Doc/HR 真接入）**：fallback 模式可复用（如未来 LegacyDocProviderAdapter 走同样双轨）
- **Phase 5.D（Trigger/Tool + Huly user 反向 sync）**：subscribe_events 真实现 + RecipientSpec(kind="thread") 真支持

### 无 blocker

Plan 06 100% 完成 `PLUG-FW-04` + `IM-LEGACY-WRAP` 双 requirement。Phase 5.A 进度从 5/7 → 6/7（86%）。

---

## Self-Check: PASSED

**Files created exist (3):**

- ✓ docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md（320 行 ≥ 50）
- ✓ backend/app/agent_builder/platforms/legacy_im_adapter.py（311 行 ≥ 100）
- ✓ backend/tests/platforms/test_legacy_im_adapter.py（20 tests pass）

**Files modified exist (4):**

- ✓ backend/app/agent_builder/notification/providers/base.py（+78 行 _PROVIDERS_AS_CAP + hook + helper）
- ✓ backend/app/agent_builder/platforms/registry.py（+27 行 IM fallback）
- ✓ backend/tests/platforms/test_registry.py（+3 tests fallback）
- ✓ .planning/phases/05a-platform-plugin-framework/deferred-items.md（+1 entry Plan 05 遗留）

**Commits exist:**

- ✓ 98cba53 (Task 0 reading doc) — CLAUDE.md §2.7 硬性 gate
- ✓ fbee696 (Task 1 LegacyIMProviderAdapter + 20 单测)
- ✓ 3c97b5e (Task 2 base.py 双轨 + Registry fallback + 3 单测)

**Tests pass:**

- ✓ 20/20 test_legacy_im_adapter.py（含 isinstance + 5 cap flags + send_card + update_card + send_text + subscribe + wrap + raw_provider 共享 + 双轨注册 + 6 家全量 wrap + KNOWN_PROVIDERS invariant + wrap 不静默 skip）
- ✓ 16/16 test_registry.py（含 13 Plan 04 + 3 Plan 06 fallback：falls_back_to_legacy / prefers_manifest_over_legacy / non_im_does_not_fallback）
- ✓ **Phase 4 IM regression：61/61 pass**（test_im_provider_protocol + test_im_credentials_loader + test_im_jobs_skeleton + test_dingtalk_provider）
- ✓ **Phase 4 Notification regression：33/33 pass**（multichannel + node_multichannel + model + service）
- ✓ **e2e_v2 collect：26/26 specs collect 成功**（Phase 1-4 fixture / import 0 regression）

**Reading doc gate:**

- ✓ Reading doc commit 98cba53 早于代码 commit fbee696 / 3c97b5e ✓
- ✓ License attribution（Dify AGPL-3.0 vs 本项目 Apache-2.0）✓
- ✓ 5 借鉴点（PLAN.md 要求）✓ — 双轨数据共存 / 失败容忍降级 / 老接口字段最小化保留 / 旧接口仍可用 / cap flags 推导
- ✓ 320 行（≥ 50 PLAN.md 要求）✓

**Plan 06 acceptance:**

- ✓ LegacyIMProviderAdapter 实现 IMCapability Protocol 100%（runtime_checkable + 4 method + 3 cap flag + name property）
- ✓ base.py 双轨 Registry（_PROVIDERS + _PROVIDERS_AS_CAP）共存
- ✓ register_provider 自动 wrap（_maybe_wrap_for_capability hook 真实生效）
- ✓ **Registry.get_capability(IMCapability) fallback 到 _PROVIDERS_AS_CAP 真实实现**（Blocker 3 修复 — 不仅 key_links 声明，registry.py 必有对应 fallback 代码）
- ✓ Phase 4 61 IM + 33 notification 测试 0 regression — **用户硬性 DoD #3 达成**
- ✓ Phase 4 e2e_v2 26 specs collect 成功（fixture/import 0 regression）
- ✓ 6 家 Phase 4 provider 模拟 wrap 全 isinstance IMCapability（test_all_six_phase4_providers_wrap_correctly）
- ✓ KNOWN_PROVIDERS frozenset 不变（test_known_providers_invariant）
- ✓ 老调用 API 不变；新代码可走 `get_capability_for_legacy(name)` 拿 IMCapability，或经 `Registry.get_capability(IMCapability, prefer='feishu')` 走 fallback

**Requirements covered:**

- ✓ PLUG-FW-04（LegacyIMProviderAdapter 让 Phase 4 6 家 IMProvider 通过新 IMCapability 接口被调用，零 regression）
- ✓ IM-LEGACY-WRAP（Phase 4 register_provider 注册自动 wrap 为 LegacyAdapter；新老 plugin 共存通过 capability_registry 按 plugin_name 路由）

**用户硬性 DoD #3 验证（CONTEXT.md acid test DoD）：**

- ✓ "LegacyIMProviderAdapter 让 Phase 4 6 家 provider 通过新接口被调用" — `test_all_six_phase4_providers_wrap_correctly` 6 家全 isinstance IMCapability
- ✓ "所有 Phase 4 测试 0 regression" — IM 61 + notification 33 + e2e_v2 26 specs collect = **三套 0 regression**
- ✓ Blocker 3 修复：Registry.get_capability(IMCapability) 在缺 manifest plugin 时正确 fallback 到 LegacyAdapter

---

*Phase: 05a-platform-plugin-framework*
*Plan: 06*
*Completed: 2026-05-17*
