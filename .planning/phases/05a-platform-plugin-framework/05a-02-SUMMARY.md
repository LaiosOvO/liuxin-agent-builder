---
phase: 05a-platform-plugin-framework
plan: 02
subsystem: platforms/capabilities
tags: [platform, plugin, protocol, dataclass-frozen, runtime-checkable, im, doc, crdt, dify-reference]
requires:
  - phase: 04-im-channels
    provides: IMProvider Protocol pattern + 6 家 Provider 实战
  - phase: 05a-platform-plugin-framework
    plan: 01
    provides: tests/platforms/conftest.py 共享 fixture + workspace_plugin_installations ORM
provides:
  - PluginError 异常家族（5 异常类集中定义）
  - IMCapability Protocol + RecipientSpec/NormalizedCard/MessageRef 值对象
  - DocCapability Protocol + DocRef/DocInfo/CRDTDelta/CommentRef/UserRef 值对象
  - 双路径设计（replace_document_content vs apply_document_delta）— 解决 Huly acid test gap #2
  - 多态 RecipientSpec — 解决 Huly acid test gap #a
affects:
  - Plan 03 (HR/Identity capabilities — 已在并行 commit b0353c0 完成)
  - Plan 04 (PluginRegistry get_capability(IMCapability, ...) 路由)
  - Plan 05 (LegacyIMProviderAdapter wrap Phase 4 IMProvider → IMCapability)
  - Plan 06 (PlatformDaemonClient + MockPlatformPlugin)
  - Plan 07 (HulyPlugin acid test — IMCapability.send_card 端到端)
tech-stack:
  added: []
  patterns:
    - "@runtime_checkable Protocol — 鸭子类型 + isinstance 双保险（Phase 4 IMProvider 沿用）"
    - "dataclass(frozen=True) — 不可变值对象（CLAUDE.md immutability）"
    - "Literal[...] 字面值类型 — 替代 StrEnum 轻量约束"
    - "async generator pattern — subscribe_events 用 `if False: yield {}` 让方法成为 async generator function"
    - "双路径 cap flag — supports_collaborative_edit 决定走 replace vs apply_delta（CRDT vs 全量替换互斥）"
key-files:
  created:
    - docs/reading-dify-05a-02-capability-protocols-2026-05-17.md
    - backend/app/agent_builder/platforms/__init__.py
    - backend/app/agent_builder/platforms/exceptions.py
    - backend/app/agent_builder/platforms/capabilities/im.py
    - backend/app/agent_builder/platforms/capabilities/doc.py
    - backend/tests/platforms/test_capabilities_im.py
    - backend/tests/platforms/test_capabilities_doc.py
  modified: []
key-decisions:
  - "Plan 02 不写 capabilities/__init__.py 完整 exports — 由 Plan 03 独占（避免并行写冲突；Plan 02 tests 用直接子模块 import）"
  - "Plan 02 创建空的 capabilities/__init__.py 仅让 Python import resolution 工作（实际由并行 Plan 03 commit b0353c0 一并提交并改为完整 exports）"
  - "subscribe_events 用 `async def f(...): if False: yield {}` pattern + `inspect.isasyncgenfunction` 静态断言测试（runtime_checkable 不检查方法类型）"
  - "双路径方法 replace_document_content / apply_document_delta 分离 — 调错路径 raise NotImplementedError（明确语义，避免运行时混淆）"
  - "DocInfo.content_markdown 设为 Optional —— 支持 Huly 二跳 fetchMarkup 风格的 plugin（避免 N+1 调用强制返回）"
  - "PluginInvocationError 携带 error_payload dict（含 code/message） — 便于上层 except 后获取 daemon 原始错误码"
  - "Plan 02 commit hash 实际分布：Task 0 单独 1eaaea6 / Task 1 被并行 Plan 03 commit b0353c0 一并 bundled / Task 2 独立 0eba676（git 文件状态完整可追溯）"
patterns-established:
  - "Capability Protocol 文件组织：每 capability 一 file（capabilities/{im,doc,hr,identity,trigger,tool}.py）"
  - "值对象命名：[Domain]Ref（MessageRef/DocRef/UserRef/CommentRef）+ [Domain]Info（DocInfo）+ [Domain]Spec（RecipientSpec/EmployeeFilter）"
  - "异常集中定义：platforms/exceptions.py 含全部 PluginError 家族（不分散各 capability file）"
  - "Plan 内 reading doc 5 借鉴点必须指回具体 5.A 模块（CLAUDE.md §2.7 硬性 gate）"
requirements-completed:
  - PLUG-FW-01
duration: 14min
completed: 2026-05-17
---

# Phase 5.A Plan 02: IMCapability + DocCapability Protocols Summary

**IMCapability（多态 RecipientSpec + 3 cap flags + async generator subscribe_events）+ DocCapability（双路径 replace/apply_delta + CRDT 互斥设计）+ exceptions 模块（5 异常类）— 解决 Huly acid test gap #a/#2，PLUG-FW-01 推进 2/6 capability**

## Performance

- **Duration:** ~14 min（含 Task 0 reading doc + Task 1 IM + Task 2 Doc）
- **Started:** 2026-05-17T11:54:14Z
- **Completed:** 2026-05-17T12:08:30Z
- **Tasks:** 3
- **Files created:** 7（1 reading doc + 4 source + 2 test）
- **Tests added:** 17（8 IM + 9 Doc）
- **Tests passing:** 17/17（含 Plan 01-03 合计 74/74）

## Accomplishments

- **IMCapability Protocol** 完整定义：3 cap flags（supports_native_buttons / supports_card_update / supports_threads）+ 4 method（send_card / update_card / send_text / subscribe_events）
- **RecipientSpec 多态化** —— 解决 Huly acid test gap #a（kind: Literal["channel","dm_user","thread"] 三场景统一）
- **DocCapability 双路径设计** —— 解决 Huly acid test gap #2（supports_collaborative_edit cap flag + replace_document_content / apply_document_delta 互斥 raise NotImplementedError）
- **6 值对象全部 frozen=True** —— RecipientSpec / MessageRef / NormalizedCard / DocRef / DocInfo / CRDTDelta / CommentRef / UserRef（CLAUDE.md immutability 100%）
- **静态断言测试** `inspect.isasyncgenfunction(subscribe_events)` —— High 5 关键 pattern，runtime_checkable 不检查方法类型，必须显式断言
- **Negative case 覆盖** —— 缺方法的 mock 类正确返回 isinstance False（runtime_checkable 行为校验）
- **Phase 4 IM Protocol 0 regression** —— 33/33 phase 4 测试 pass（test_im_provider_protocol + test_im_credentials_loader；test_feishu_provider 因预存 lark_oapi 模块缺失跳过，与本 plan 无关）

## Task Commits

每 task 原子 commit（按 plan 规范）：

1. **Task 0: Dify capability + endpoint 阅读文档（Task 0 硬性 gate）** — `1eaaea6` (docs)
2. **Task 1: exceptions 模块 + IMCapability Protocol + 值对象** — `b0353c0` (feat) — 注：本 commit 由并行执行的 Plan 03 一并提交（含 5.A `platforms/__init__.py` + Plan 02 文件 `exceptions.py` + `capabilities/im.py` + tests + Plan 03 自己的 hr.py / identity.py 文件）
3. **Task 2: DocCapability Protocol + 双路径 replace/apply_delta + 单测** — `0eba676` (feat)

**Plan 元数据**：本 SUMMARY.md + STATE.md + ROADMAP.md 更新会在最后单独 commit

_Note: Task 1 文件归属正确（git 追溯可见每文件作者），仅 commit message 归属到 Plan 03。后续 Plan 03 SUMMARY 不应再次声明已被 Plan 02 拥有的文件_

## Files Created/Modified

### Created（7 个）

- `docs/reading-dify-05a-02-capability-protocols-2026-05-17.md` — Dify endpoint/plugin/plugin_daemon 三 entity 阅读 + 5 借鉴点指回 5.A 模块（216 行）
- `backend/app/agent_builder/platforms/__init__.py` — Phase 5.A 包入口（标 ADR-001 + 后续 plan map）
- `backend/app/agent_builder/platforms/exceptions.py` — 5 异常类（PluginError / ManifestValidationError / CapabilityMissingError / PluginDaemonExitedError / PluginInvocationError）
- `backend/app/agent_builder/platforms/capabilities/__init__.py` — 空 placeholder（注明 Plan 03 独占写完整 exports）
- `backend/app/agent_builder/platforms/capabilities/im.py` — IMCapability Protocol + 3 值对象（206 行）
- `backend/app/agent_builder/platforms/capabilities/doc.py` — DocCapability Protocol + 5 值对象（247 行）
- `backend/tests/platforms/test_capabilities_im.py` — 8 单测（isinstance + 不可变 + Literal 枚举 + isasyncgenfunction + negative case）
- `backend/tests/platforms/test_capabilities_doc.py` — 9 单测（双 plugin 风格 isinstance + 5 值对象 + 双路径互斥 + negative case）

### Modified（0 个）

无 — Plan 02 仅新增文件，未修改既有 Phase 1-4 代码。

## Decisions Made

详见 frontmatter `key-decisions`。核心：

1. **不写 `capabilities/__init__.py` 完整 exports** — Plan 03 独占（避免并行写冲突）；Plan 02 tests 用直接子模块 import `from app.agent_builder.platforms.capabilities.im import ...`
2. **空 `capabilities/__init__.py`** 仅让 Python import resolution 工作 — Plan 02 写注释 placeholder，实际由并行 Plan 03 commit b0353c0 改为完整 exports
3. **subscribe_events `if False: yield {}` pattern** + `inspect.isasyncgenfunction` 静态断言测试 — runtime_checkable 不检查方法类型（仅检查名字 + 属性），必须显式断言 async generator 语义
4. **双路径互斥 raise NotImplementedError** — 调错路径明确 raise（不静默兼容），让调用方按 supports_collaborative_edit cap flag 显式选路径

## Dify 参考点

5 借鉴点（详见 `docs/reading-dify-05a-02-capability-protocols-2026-05-17.md` 第 47-130 行）：

| # | Dify 源文件 | 借鉴模式 | 5.A target | Status |
| - | --- | --- | --- | --- |
| 1 | `plugin.py:61-67` (PluginCategory) | StrEnum 单选 → `capabilities: list[Literal[...]]` 多选（一 plugin 多 capability 关键差异） | 留 Plan 03 manifest 消费 | ⏸ Plan 03 |
| 2 | `endpoint.py:11-18` (EndpointDeclaration.method) | method 字段字符串 → Python Protocol async 方法签名（类型安全） | `IMCapability.send_card` / `DocCapability.apply_document_delta` 等 | ✅ 本 plan |
| 3 | `plugin_daemon.py:47-67` (PluginToolProviderEntity 等) | 每 capability 一个 Entity 子类 → 每 capability 一 file 组织 | `capabilities/im.py` / `capabilities/doc.py` | ✅ 本 plan |
| 4 | `plugin.py:143-154` (PluginInstallation) | 凭据 + runtime 字段流转 → workspace_plugin_installations.credentials_json（Plan 01 已建）+ 各 capability 实现持 closure | 留 Plan 04+ Registry 消费 | ⏸ Plan 04 |
| 5 | `plugin.py:70-141` + `plugin_daemon.py:47-67` (PluginDeclaration vs PluginEntity) | Declaration 静态层 vs Runtime 实例层 → manifest 声明 vs Capability instance | `@runtime_checkable Protocol`（允许 mock 不继承） | ✅ 本 plan |

**License attribution**：Dify AGPL-3.0 vs 本项目 Apache-2.0 — 仅借鉴设计模式 / 数据结构思路，严禁拷贝源代码（reading doc 明确标注每条借鉴点为独立创作）。

## Huly Acid Test Gap 解决映射

Plan 02 解决的 acid test gap（详见 `docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md`）：

| Gap 编号 | Gap 描述 | Plan 02 解决方式 |
| --- | --- | --- |
| **#1 (RecipientSpec)** | Phase 4 IMProvider 仅支持 `recipient: str` 单一形式，Huly 等一体化平台需 channel post / DM / thread reply 三场景 | `RecipientSpec(kind: Literal["channel","dm_user","thread"], id: str, extras: dict)` 多态值对象 + Literal 类型约束 |
| **#2 (DocProvider CRDT 30% fit)** | 之前 DocProvider 单一 `update_document` 含糊语义，对 Huly Y.js CRDT 全量替换会破坏一致性 | `DocCapability` 拆 `replace_document_content` + `apply_document_delta` 双方法 + `supports_collaborative_edit` cap flag 调用方决策 + 调错路径 raise NotImplementedError |
| **#b (IM cap flag)** | Phase 4 仅有 `supports_card_update` 单 flag | `IMCapability` 升级为 3 flag：`supports_native_buttons` / `supports_card_update` / `supports_threads`（按钮渲染 / 卡片更新 / 线程回复独立协商） |

剩余 gap（#3 HR / #4 一体化共享 client / #5 身份反向 sync）由 Plan 03（HR + Identity capabilities）+ Plan 07（HulyPlugin acid test）解决。

## Deviations from Plan

**None** — 本 plan 完全按 PLAN.md 执行：

- Task 0 reading doc 先 commit ✓（hash 1eaaea6 早于任何代码 commit）
- Task 1 exceptions + IMCapability + 8 单测（plan 要求 ≥ 6，实交 8）
- Task 2 DocCapability 双路径 + 9 单测（plan 要求 ≥ 6，实交 9）

**唯一过程性观察**：Task 1 文件（`platforms/__init__.py` + `exceptions.py` + `capabilities/im.py` + test_capabilities_im.py + 空 `capabilities/__init__.py`）被并行执行的 Plan 03 agent 一并 commit 到 `b0353c0`。这是**良性的 git 行为**（并行 agent 都加了未 staged 的所有新文件就 commit），文件作者 / 路径 / 内容均正确，仅 commit message 归属到 Plan 03。git log 可追溯每文件首次出现的 commit，但内容归属 Plan 02 (PlatformManifest spec / IMCapability spec 等 100% 按 Plan 02 PLAN.md 设计)。

**对未来 plan 的影响**：无影响 — 文件存在、可 import、测试 pass、行数达标。Plan 03 SUMMARY 应不重复声明本 Plan 02 的产出。

## Issues Encountered

1. **Parallel agent commit interleaving** — Plan 03 并行 agent 在 Plan 02 Task 1 准备 commit 前先 commit，把 Plan 02 的所有 staged 文件一并打包到自己的 commit `b0353c0`。处理：检查 git ls-tree 确认所有 Plan 02 文件确已入库（按内容、按路径，均符合 PLAN.md 规范），后续 Task 2 commit 正常推进，无返工。
2. **Pre-existing `lark_oapi` 模块缺失** — Phase 4 `test_feishu_provider.py` 因 conda env 缺 `lark_oapi` 包无法 collect。**out of scope per RULE SCOPE BOUNDARY**（与 Plan 02 无关，是预存环境问题）；改用 `test_im_provider_protocol.py + test_im_credentials_loader.py` 33 测试做 regression 验证 100% pass。

## Self-Check

**Files created exist:**
- ✓ docs/reading-dify-05a-02-capability-protocols-2026-05-17.md（216 行 / ≥ 60 / 3 attribution mentions）
- ✓ backend/app/agent_builder/platforms/__init__.py
- ✓ backend/app/agent_builder/platforms/exceptions.py
- ✓ backend/app/agent_builder/platforms/capabilities/__init__.py（空 placeholder — 已被 Plan 03 overwrite 为完整 exports）
- ✓ backend/app/agent_builder/platforms/capabilities/im.py（206 行 / ≥ 90）
- ✓ backend/app/agent_builder/platforms/capabilities/doc.py（247 行 / ≥ 90）
- ✓ backend/tests/platforms/test_capabilities_im.py（8 测试 全 pass）
- ✓ backend/tests/platforms/test_capabilities_doc.py（9 测试 全 pass）

**Commits exist:**
- ✓ 1eaaea6 (Task 0 reading doc)
- ✓ b0353c0 (Task 1 — bundled by parallel Plan 03 agent，Plan 02 文件均在其中)
- ✓ 0eba676 (Task 2 DocCapability)

**Tests pass:**
- ✓ 8/8 IM tests pass
- ✓ 9/9 Doc tests pass
- ✓ 74/74 tests/platforms/ 全集 pass（含 Plan 01-03）
- ✓ 33/33 Phase 4 IM Protocol 测试 0 regression

**Success criteria：**
- ✓ Reading doc commit 在前
- ✓ `from app.agent_builder.platforms.capabilities.im import IMCapability, RecipientSpec, NormalizedCard, MessageRef` 直接子模块 import 工作
- ✓ `from app.agent_builder.platforms.capabilities.doc import DocCapability, DocRef, CRDTDelta, DocInfo` 直接子模块 import 工作
- ✓ test_subscribe_events_is_async_generator 静态断言 pass（inspect.isasyncgenfunction 验证）
- ✓ ≥ 15 tests pass（实交 17）
- ✓ 双路径互斥（Outline apply_delta raise / Huly replace_content raise）通过 test_dual_path_mutual_exclusion 验证
- ✓ exceptions 模块 5 异常类集中定义可 import
- ✓ ruff check + black format 全 pass

## Self-Check: PASSED

## Next Plan Readiness

Plan 02 完成 PLUG-FW-01 的 2/6 capability（IM + Doc）；剩余 4 capability（HR / Identity / Trigger / Tool）由并行 Plan 03 commit b0353c0 完成（已 PASS 74/74 tests）。

下一步：
- Plan 04 (PluginRegistry) 可使用 `IMCapability` / `DocCapability` 做 `get_capability` 类型路由
- Plan 05 (LegacyIMProviderAdapter) 可 wrap Phase 4 IMProvider 为 IMCapability 实例
- Plan 07 (HulyPlugin acid test) 可基于 IMCapability.send_card 跑端到端

无 blocker 或 concern。

---

*Phase: 05a-platform-plugin-framework*
*Plan: 02*
*Completed: 2026-05-17*
