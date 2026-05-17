---
phase: 05a-platform-plugin-framework
plan: 03
subsystem: platforms/capabilities
tags: [platform, plugin, capability, protocol, runtime_checkable, hr, identity, trigger, tool, dify-reference, async-generator]
provides:
  - HRCapability Protocol（8 method + 5 值对象，含 resolve_department_members 接口为 Phase 5.D dept: 表达式预留）
  - IdentityCapability Protocol（3 method + is_source_of_truth flag + watch_user_changes async generator）
  - TriggerCapability v1.1 骨架（subscribe_events async generator + verify_event_signature）
  - ToolCapability v1.1 骨架（list_tools + invoke_tool + ToolSpec/ToolInvocationResult）
  - 完整 capabilities/__init__.py 含 24 exports（6 capability + 18 值对象）
requires:
  - phase: 05a-platform-plugin-framework Plan 01
    provides: WorkspacePluginInstallation 表 + tests/platforms 测试目录骨架 + conftest fixture
  - phase: 05a-platform-plugin-framework Plan 02
    provides: platforms/__init__.py + exceptions.py + IMCapability + DocCapability（并行 wave 2）
affects:
  - 05a-04 PlatformPluginRegistry（用本 plan 6 Capability Protocols 做 isinstance check + per-workspace 路由）
  - 05a-05 LegacyIMProviderAdapter（实现 IMCapability 由 Plan 02 提供，本 plan 不直接影响）
  - 05a-06 PlatformDaemonClient + Mock（MockPlatformPlugin 实现 6 capability 子集）
  - 05a-07 HulyPlugin acid test（4 facade IM/Doc/HR/Identity 来自本 plan 与 Plan 02）
  - Phase 5.D dept:研发部 表达式（HRCapability.resolve_department_members）
  - Phase 5.D Huly user 反向 sync（IdentityCapability.is_source_of_truth + watch_user_changes）
  - Phase 5.D+ Trigger 节点真实接入（TriggerCapability v1.1 骨架）
  - Phase 5.D+ LLM Tool 节点真实接入（ToolCapability v1.1 骨架）
tech-stack:
  added: []  # 全用 Phase 1-4 已锁定 stdlib + Phase 4 IMProvider 风格
  patterns:
    - runtime_checkable Protocol + 鸭子类型（沿用 Phase 4 IMProvider 模式）
    - dataclass(frozen=True) 值对象（CLAUDE.md immutability）
    - is_source_of_truth flag 区分 SoT vs non-SoT plugin（决定 sync 方向）
    - async generator pull 模式（subscribe_events / watch_user_changes — 比 webhook push 简化）
    - inspect.isasyncgenfunction 静态断言（防 `if False: yield` 模式被误写）
    - try/except ImportError 处理并行 plan 文件冲突（capabilities/__init__.py 条件 re-export）
    - JSON Schema dict 透传不强类型化（借鉴 Dify ToolEntity.parameters）
key-files:
  created:
    - docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md
    - backend/app/agent_builder/platforms/capabilities/hr.py
    - backend/app/agent_builder/platforms/capabilities/identity.py
    - backend/app/agent_builder/platforms/capabilities/trigger.py
    - backend/app/agent_builder/platforms/capabilities/tool.py
    - backend/tests/platforms/test_capabilities_hr.py
    - backend/tests/platforms/test_capabilities_identity.py
    - backend/tests/platforms/test_capabilities_trigger_tool.py
    - .planning/phases/05a-platform-plugin-framework/deferred-items.md
  modified:
    - backend/app/agent_builder/platforms/capabilities/__init__.py（重写为完整 24 exports 含条件 import）
key-decisions:
  - "HRCapability `resolve_department_members(expression: str) -> list[EmployeeRef]` 为 Phase 5.D dept: 表达式预留接口（IM-05 节点 assignee 解析核心）"
  - "IdentityCapability.is_source_of_truth: bool 区分 Huly (True) vs Phase 4 IM provider (False) — 决定 sync 方向：True 时 watch_user_changes 真推送；False 时 raise NotImplementedError"
  - "HRCapability.create_leave_request 仅 source_of_truth=True plugin 实现；非权威 plugin 第一行检查 raise NotImplementedError"
  - "Trigger / Tool v1.1 仅 Protocol 骨架（subscribe_events / verify_event_signature / list_tools / invoke_tool）— 实现留 Phase 5.D+（CONTEXT.md §Deferred Ideas 明确）"
  - "subscribe_events 用 async generator pull 模式（比 Dify webhook + Flask route 注册简化）"
  - "ToolSpec.input_schema / output_schema 用 dict[str, Any] 透传 JSON Schema（不强类型化 — 借鉴 Dify ToolEntity.parameters 模式让 plugin 自由）"
  - "ToolInvocationResult success/error 互斥 envelope（result vs error_message 二选一 — 借鉴 Dify PluginDaemonBasicResponse 简化无泛型）"
  - "capabilities/__init__.py 用 try/except ImportError 处理 Plan 02 并行执行边界（doc.py 可能尚未存在时 __all__ 动态构建）"
  - "Department.member_ids 用 tuple[str, ...]（不可变） — Phase 5.D dept: 表达式解析直接读此字段展开（无 N+1 查询）"
patterns-established:
  - "Pattern: is_source_of_truth flag + raise NotImplementedError gate — Identity / HR capability 区分权威与非权威 plugin 的运行时分流"
  - "Pattern: inspect.isasyncgenfunction 静态断言（High 5 防 `if False: yield {}` 模式被误写）"
  - "Pattern: 双 Mock plugin 测试覆盖（SourceOfTruth + NonSourceOfTruth） — 验证 runtime_checkable + 业务语义同时"
  - "Pattern: dataclass frozen=True + tuple/dict default_factory 不可变值对象（CLAUDE.md immutability 全栈贯穿）"
  - "Pattern: 条件 __init__.py（try/except ImportError + 动态 __all__） — 处理并行 wave 内多 plan 共享 __init__ 的执行边界"
requirements-completed:
  - PLUG-FW-01
metrics:
  duration: 15min
  tasks_completed: 3
  files_created: 9
  files_modified: 1
  tests_added: 41
  tests_passing: 41
  capability_coverage_percent: 98
  phase4_im_regression: 0
  completed_date: "2026-05-17"
---

# Phase 5.A Plan 03: HR + Identity + Trigger + Tool Capability Protocols Summary

**HRCapability（8 method 含 dept: 表达式预留）+ IdentityCapability（is_source_of_truth flag + watch_user_changes async generator）+ Trigger/Tool v1.1 骨架 + 完整 capabilities/__init__.py（24 exports），覆盖率 98.01%（≥80% 硬性要求），41 测试 0 regression**

## Performance

- **Duration:** 15 min（19:55 → 20:10 UTC+8）
- **Started:** 2026-05-17T11:55:11Z
- **Completed:** 2026-05-17T12:10:00Z
- **Tasks:** 3（Task 0 reading doc / Task 1 HR+Identity / Task 2 Trigger+Tool+__init__）
- **Files created:** 9
- **Files modified:** 1（capabilities/__init__.py 重写）

## Accomplishments

- **HRCapability + 5 值对象**（EmployeeRef / Employee / Department / LeaveRequest / EmployeeFilter）— 8 method 含 `resolve_department_members(expression)` 为 Phase 5.D `dept:研发部` 表达式接口预留
- **IdentityCapability + 2 值对象**（UserPrincipal / UserChangeEvent）— `is_source_of_truth: bool` flag 解决 Huly acid test §6 反向 sync 设计问题（区分 sync 方向）
- **TriggerCapability + ToolCapability v1.1 骨架** — Protocol 已就位，实现留 Phase 5.D+（CONTEXT.md §Deferred Ideas 明确）
- **完整 capabilities/__init__.py**（24 exports：6 capability + 18 值对象）使用 try/except ImportError 模式处理 Plan 02 并行执行边界
- **41 单测全 pass + 98.01% capability 覆盖率**（pytest --cov=app/agent_builder/platforms/capabilities --cov-fail-under=80）
- **3 个 isasyncgenfunction 静态断言**（identity.watch_user_changes / trigger.subscribe_events / im.subscribe_events 已在 Plan 02 测试）— High 5 防 `if False: yield {}` 模式被误写
- **Phase 4 IM 51 测试 0 regression**（feishu_provider 跳过 — pre-existing lark_oapi env 缺失，已记入 deferred-items.md）

## Task Commits

每个 task 独立 atomically 提交：

1. **Task 0: Dify HR/Identity/Trigger/Tool 阅读文档** — `6fbc840` (docs)
   - 248 行阅读文档（≥60 硬性 gate）
   - 6 借鉴点指回 5.A Plan 03 module（PluginCategory enum / PluginToolProviderEntity 三段式 / TriggerProviderEntity / ToolEntity.parameters dict / PluginDaemonBasicResponse envelope / HR/Identity 完全新疆域）
   - License attribution: Dify AGPL-3.0 vs 本项目 Apache-2.0
   - **CLAUDE.md §2.7 硬性 gate**：reading doc 是 Plan 03 第一个 commit ✓

2. **Task 1: HRCapability + IdentityCapability + 24 单测** — `b0353c0` (feat)
   - hr.py 191 行（≥100）
   - identity.py 131 行（≥60）
   - 24 测试 pass：13 HR + 11 Identity
   - 包含 `inspect.isasyncgenfunction(SoTMockIdentity.watch_user_changes)` 静态断言（High 5）
   - 注：本 commit 同时引入 Plan 02 未提交的 im.py / __init__.py / exceptions.py / test_capabilities_im.py（因 `git add` 触发整个 platforms/ 子树跟踪）— Plan 02 reading doc 已先提交 `1eaaea6`，本提交将 Plan 02 工程文件一并入库

3. **Task 2: TriggerCapability + ToolCapability + 完整 __init__.py + 17 单测** — `748f6ac` (feat)
   - trigger.py 117 行（≥40）
   - tool.py 136 行（≥40）
   - capabilities/__init__.py 重写为完整 24 exports 含条件 import
   - 17 测试 pass：Trigger 6 + Tool 11
   - 包含 `inspect.isasyncgenfunction(MockTrigger.subscribe_events)` 静态断言（High 5）

**Plan metadata commit** (本 commit): SUMMARY.md + STATE.md + ROADMAP.md + deferred-items.md

## Files Created/Modified

### 新增（9 文件）

- `docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md`（248 行）— Dify 阅读文档（CLAUDE.md §2.7 硬性 gate）
- `backend/app/agent_builder/platforms/capabilities/hr.py`（191 行）— HRCapability + 5 值对象
- `backend/app/agent_builder/platforms/capabilities/identity.py`（131 行）— IdentityCapability + 2 值对象
- `backend/app/agent_builder/platforms/capabilities/trigger.py`（117 行）— TriggerCapability v1.1 骨架
- `backend/app/agent_builder/platforms/capabilities/tool.py`（136 行）— ToolCapability v1.1 骨架
- `backend/tests/platforms/test_capabilities_hr.py`（13 tests, 322 行）
- `backend/tests/platforms/test_capabilities_identity.py`（11 tests, 255 行）
- `backend/tests/platforms/test_capabilities_trigger_tool.py`（17 tests, ~280 行）
- `.planning/phases/05a-platform-plugin-framework/deferred-items.md`

### 修改（1 文件）

- `backend/app/agent_builder/platforms/capabilities/__init__.py` — 重写为完整 24 exports（6 capability + 18 值对象），使用 try/except ImportError 处理 Plan 02 并行执行边界

## Decisions Made

- **HRCapability.resolve_department_members(expression)** — Phase 5.D `dept:研发部` 表达式解析的核心接口。表达式语法（5.D 落地）：`dept:<部门名>` / `role:<角色名>` / `id:<employee_id>` / `user:<email>` / `manager_of:<employee_id>` / 逗号分隔多条件
- **IdentityCapability.is_source_of_truth: bool** — 解决 Huly acid test §6 反向 sync 设计问题（区分 Huly=True vs Phase 4 IM=False，决定 sync 方向）
- **HRCapability.create_leave_request + IdentityCapability.watch_user_changes** — 双重 source_of_truth gate：非权威 plugin 第一行 raise NotImplementedError；watch_user_changes 即使 raise 也要含 `if False: yield ...` 让 Python 标记为 asyncgenfunction
- **Trigger / Tool v1.1 仅 Protocol 骨架** — 实现留 Phase 5.D+（CONTEXT.md §Deferred Ideas 明确 — "TriggerCapability / ToolCapability / WorkflowCapability 完整接口（v1.1 仅留 Protocol 骨架，真实接入留 Phase 5.D+）"）
- **subscribe_events 用 async generator pull 模式** — 比 Dify webhook + Flask route 注册简化一层（调用方 `async for event in cap.subscribe_events(...)` 自然 backpressure）
- **ToolSpec.input_schema / output_schema 用 dict[str, Any] 透传** — 借鉴 Dify ToolEntity.parameters 模式不强类型化 — 让 plugin 自由选 OpenAPI / JSON Schema / 自定义格式
- **ToolInvocationResult success/error 互斥** — 借鉴 Dify PluginDaemonBasicResponse 简化无泛型；success=True 时 result 有值，success=False 时 error_message 有值
- **capabilities/__init__.py 用 try/except ImportError** — 处理 Plan 02 doc.py 可能尚未存在的并行执行边界（__all__ 字段动态构建）；Plan 02 提交后 import 成功 → __all__ 自动追加 IM/Doc exports
- **Department.member_ids 用 tuple[str, ...]** — Phase 5.D dept: 表达式解析直接读此字段展开成员列表（不可变 + 无 N+1 查询）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 处理 Plan 02 并行执行 doc.py 可能尚未存在的情景**

- **Found during:** Task 2 （写 capabilities/__init__.py 时 Plan 02 仅提交 reading doc / IM，doc.py 尚未提交）
- **Issue:** Plan 03 PLAN.md 假设 Plan 02 先写 IM/Doc，但实际执行时 Plan 02 doc.py 后于本 plan Task 1 commit 才出现
- **Fix:** capabilities/__init__.py 使用 `try / except ImportError` 模式条件 re-export IM/Doc，`__all__` 字段动态构建
- **Files modified:** backend/app/agent_builder/platforms/capabilities/__init__.py
- **Verification:** import 时即使 doc.py 缺失也不 raise；当 Plan 02 提交后 import 成功 → __all__ 自动追加 6 个 Doc exports
- **Committed in:** `748f6ac`

**2. [Rule 3 - Blocking] Plan 02 未提交 platforms/__init__.py / exceptions.py / im.py 被本 plan Task 1 commit 自动 staged**

- **Found during:** Task 1 commit（git add 触发整个 platforms/ 子树跟踪）
- **Issue:** Plan 02 写了文件但仅提交了 reading doc；本 plan `git add backend/app/agent_builder/platforms/capabilities/hr.py ...` 时 Git 也 stage 了 platforms/ 整个新目录的所有未跟踪文件
- **Fix:** 接受现状（这些文件本就是 Plan 02 产物，需要 Plan 03 import 它们）— 后续 Plan 02 执行时已无需 commit 这些 file（已入库）
- **Files modified:** backend/app/agent_builder/platforms/__init__.py + exceptions.py + capabilities/im.py + tests/platforms/test_capabilities_im.py（这些都是 Plan 02 内容，但成为 Plan 03 提交 b0353c0 的一部分）
- **Verification:** Plan 02 后续 `git status` 仅显示 doc.py + test_capabilities_doc.py 待提交；Plan 02 已成功提交 `0eba676`
- **Committed in:** `b0353c0`

---

**Total deviations:** 2 auto-fixed（2 blocking — 均处理并行 plan 执行边界问题）
**Impact on plan:** 两条 deviation 均不引入功能 / scope creep，仅工程边界处理。__init__.py 条件 import 模式实际更鲁棒（未来类似并行 plan 场景可复用）。

## Issues Encountered

**1. `lark_oapi` 模块缺失（pre-existing 环境问题）**

- 触发时机：跑 `pytest tests/test_feishu_provider.py` 时 `ModuleNotFoundError: No module named 'lark_oapi'`
- 来源：pyproject.toml 含 `lark-oapi==1.6.5` 但当前 venv 未安装
- 处理：跳过该测试文件，跑 `test_im_provider_protocol.py + test_im_credentials_loader.py + test_dingtalk_provider.py`（51 测试 0 regression）
- scope_boundary 判定：Plan 03 仅新增 capabilities/ 文件，未触碰 feishu provider — out-of-scope
- 已记入 `.planning/phases/05a-platform-plugin-framework/deferred-items.md`

## User Setup Required

None — 本 plan 仅纯 Python typing.Protocol + dataclass，无外部服务依赖。

## Next Phase Readiness

### Plan 03 直接解锁

- **Plan 04 PlatformPluginRegistry**：所有 6 Capability Protocols 已就位，Registry 可做 `isinstance(plugin, IMCapability)` 等检查
- **Plan 05 LegacyIMProviderAdapter**：IMCapability 由 Plan 02 提供，本 plan 不直接影响（HR/Identity 留给 Plan 05 之后的 plan）
- **Plan 06 PlatformDaemonClient + Mock**：MockPlatformPlugin 可实现 6 capability 任意子集 — 当前 Protocol 签名稳定
- **Plan 07 HulyPlugin acid test**：4 facade（IM/Doc/HR/Identity）来自本 plan 与 Plan 02

### Phase 5.D（未来）

- `dept:研发部` 表达式解析 — `HRCapability.resolve_department_members` 接口已就位（IM-05 节点 assignee 解析的钩子）
- Huly user 反向 sync — `IdentityCapability.is_source_of_truth=True` + `watch_user_changes` 已设计好
- HR 离职预置模板（Phase 7 success criteria） — `HRCapability.list_employees + list_leave_requests` 已就位
- Trigger 节点 v1.1 真实接入 — `TriggerCapability.subscribe_events + verify_event_signature` 骨架已定，待 plugin 实现
- LLM Tool 节点 v1.1 真实接入 — `ToolCapability.list_tools + invoke_tool` 骨架已定

### 无 blocker

Plan 03 100% 完成 `PLUG-FW-01` requirement。

---

## Dify 参考点（详见 reading doc）

每条借鉴点对应 reading doc 章节锚点：

| # | 借鉴点 | Reading doc 锚点 | 本 plan 应用 |
| - | --- | --- | --- |
| 1 | PluginCategory StrEnum → capabilities Literal 枚举 | `### 1. PluginCategory 枚举 → 5.A capabilities` | `capabilities/__init__.py` re-export 6 capability；manifest.yaml `capabilities` 字段（Plan 03 后 Plan 04 manifest schema 设计时用 Literal["im","doc","hr","identity","trigger","tool"]） |
| 2 | PluginToolProviderEntity 三段式（provider + declaration + invocation） → list_tools + invoke_tool 双 API 分离 | `### 2. PluginToolProviderEntity 三段式` | `tool.py` ToolCapability.list_tools 返回 declaration（ToolSpec 列表），invoke_tool 执行 |
| 3 | TriggerProviderEntity subscription + events → async generator pull 模式 | `### 3. TriggerProviderEntity` | `trigger.py` subscribe_events 用 AsyncIterator pull（比 Dify webhook + Flask route 简化） |
| 4 | ToolEntity.parameters JSON Schema dict 直传 不强类型化 | `### 4. ToolEntity JSON Schema dict 直传` | `tool.py` ToolSpec.input_schema: dict[str, Any]（Plan 03 实现） |
| 5 | PluginDaemonBasicResponse 错误码 envelope → success/error 字段 | `### 5. PluginDaemonBasicResponse envelope` | `tool.py` ToolInvocationResult.success/error_message 简化 envelope（无泛型 YAGNI） |
| 6 | Dify 无 HR / Identity 抽象 → 完全新疆域 | `### 6. Dify 无 HR/Identity（新疆域）` | `hr.py` + `identity.py` 参考 Huly platform spike `docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md` §4 / §6 设计 |

---

## Huly Acid Test Gap → Plan 03 解决映射

| Huly acid test gap | Plan 03 解决 |
|---|---|
| **Gap #3: HRProvider 不存在** | HRCapability 完整 8 method（含 resolve_department_members / create_leave_request）— Phase 5.D Huly HR plugin 实现 |
| **Gap #5: 身份反向 sync 设计未明** | IdentityCapability.is_source_of_truth + watch_user_changes async generator — Phase 5.D Huly Identity plugin 真推送 |

---

## 测试结果

### Plan 03 直接覆盖

```
$ pytest tests/platforms/test_capabilities_hr.py tests/platforms/test_capabilities_identity.py tests/platforms/test_capabilities_trigger_tool.py -o "addopts=" --cov=app/agent_builder/platforms/capabilities --cov-fail-under=80
============================== 41 passed in 11.91s ==============================
TOTAL                                                    201      4    98%
Required test coverage of 80% reached. Total coverage: 98.01%
```

### 全 capabilities 覆盖（Plan 02 + Plan 03 累积）

```
Name                                                   Stmts   Miss  Cover
--------------------------------------------------------------------------
app/agent_builder/platforms/capabilities/__init__.py      20      4    80%
app/agent_builder/platforms/capabilities/doc.py           40      0   100%
app/agent_builder/platforms/capabilities/hr.py            47      0   100%
app/agent_builder/platforms/capabilities/identity.py      25      0   100%
app/agent_builder/platforms/capabilities/im.py            33      0   100%
app/agent_builder/platforms/capabilities/tool.py          21      0   100%
app/agent_builder/platforms/capabilities/trigger.py       15      0   100%
--------------------------------------------------------------------------
TOTAL (capabilities/)                                    201      4    98%
```

### Phase 4 IM Regression

```
$ pytest tests/test_im_provider_protocol.py tests/test_im_credentials_loader.py tests/test_dingtalk_provider.py
============================== 51 passed in 21.85s ==============================
```

0 regression（feishu_provider 因 pre-existing lark_oapi env 缺失跳过，详 deferred-items.md）。

---

## Self-Check: PASSED

**Files created (9):**
- ✓ docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md（248 行 ≥ 60）
- ✓ backend/app/agent_builder/platforms/capabilities/hr.py（191 行 ≥ 100）
- ✓ backend/app/agent_builder/platforms/capabilities/identity.py（131 行 ≥ 60）
- ✓ backend/app/agent_builder/platforms/capabilities/trigger.py（117 行 ≥ 40）
- ✓ backend/app/agent_builder/platforms/capabilities/tool.py（136 行 ≥ 40）
- ✓ backend/tests/platforms/test_capabilities_hr.py（13 tests）
- ✓ backend/tests/platforms/test_capabilities_identity.py（11 tests）
- ✓ backend/tests/platforms/test_capabilities_trigger_tool.py（17 tests）
- ✓ .planning/phases/05a-platform-plugin-framework/deferred-items.md

**Files modified (1):**
- ✓ backend/app/agent_builder/platforms/capabilities/__init__.py（重写为 24 exports）

**Commits exist:**
- ✓ 6fbc840 (Task 0 Dify HR/Identity/Trigger/Tool reading doc)
- ✓ b0353c0 (Task 1 HR + Identity Protocol + 24 单测)
- ✓ 748f6ac (Task 2 Trigger + Tool + 完整 __init__.py + 17 单测)

**Tests pass:**
- ✓ 41 Plan 03 capability tests pass（13 HR + 11 Identity + 17 Trigger/Tool）
- ✓ 58 全 capability tests pass（含 Plan 02 IM 8 + Doc 9）
- ✓ pytest --cov=app/agent_builder/platforms/capabilities **98.01%** ≥ 80% 硬性
- ✓ Phase 4 IM 51 测试 0 regression

**Reading doc gate:**
- ✓ Reading doc commit 6fbc840 早于 Task 1 commit b0353c0 ✓
- ✓ License attribution（Dify AGPL-3.0 vs 本项目 Apache-2.0）✓
- ✓ 6 借鉴点指回 5.A Plan 03 module ✓

**Capability acceptance:**
- ✓ 6 Capability Protocol 文件全部存在
- ✓ HRCapability.resolve_department_members 接口为 Phase 5.D dept: 表达式预留 ✓
- ✓ IdentityCapability.is_source_of_truth 解决 Huly acid test §6 反向 sync 设计 ✓
- ✓ TriggerCapability / ToolCapability v1.1 骨架 ✓
- ✓ inspect.isasyncgenfunction 静态断言（identity.watch_user_changes / trigger.subscribe_events）✓

**Requirements covered:**
- ✓ PLUG-FW-01（PlatformPlugin 顶层抽象类 + 6 Capability Protocols 完整定义 — Plan 03 完成 4/6，Plan 02 完成 IM+Doc 2/6 = 6/6）

---

*Phase: 05a-platform-plugin-framework*
*Plan: 03*
*Completed: 2026-05-17*
