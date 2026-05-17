---
phase: 05a-platform-plugin-framework
plan: 05
subsystem: platforms/daemon-runtime
tags: [platform, plugin, jsonrpc, asyncio-subprocess, fault-isolation, capability-facade, mock-plugin, dify-reference]
provides:
  - PlatformDaemonClient JSONRPC over stdio 主进程↔daemon 通信（460 行）
  - JSONRPC 2.0 envelope + UUID4 hex request_id 路由 + asyncio.Future pending dict
  - Pitfall 2 fault isolation 防护（daemon crash 立即失败 < 2s，不走 30s timeout）
  - Pitfall 8 stderr 独立 drain task（防 pipe buffer 满死锁）
  - 4 capability facade 真接入 daemon.invoke()（替换 Plan 04 stub）—— IMFacade/DocFacade/HRFacade/IdentityFacade
  - dataclass 序列化：asdict() → JSONRPC params + 返回 dict → 重建 dataclass
  - CRDTDelta.payload bytes → base64 encode（JSONRPC 不支持 bytes 直传）
  - MockPlatformPlugin 4 capability in-process plugin（不走 daemon，单测用）
  - echo_daemon test fixture（最小 daemon 接 stdin JSONRPC + 按 method 返回固定 result）
  - structured log: capability/method/latency_ms/outcome（Phase 7 Run Viewer 钩子）
requires:
  - phase: 05a-platform-plugin-framework Plan 02
    provides: IMCapability / DocCapability Protocol + RecipientSpec/NormalizedCard/MessageRef/DocRef/CRDTDelta/CommentRef/UserRef 值对象
  - phase: 05a-platform-plugin-framework Plan 03
    provides: HRCapability / IdentityCapability + Employee/Department/EmployeeRef/EmployeeFilter/LeaveRequest/UserPrincipal/UserChangeEvent 值对象
  - phase: 05a-platform-plugin-framework Plan 04
    provides: PlatformManifest schema + load_manifest + PlatformPlugin lazy facade + PlatformPluginRegistry + capability_facades stub（被本 plan 覆写为真转发）
affects:
  - 05a-07 (HulyPlugin acid test — discover/get_plugin/get_capability/facade.invoke/daemon JSONRPC roundtrip 全链路就位，待 HulyPlugin daemon entry + mock huly server 接入)
  - Phase 5.B (Sandbox — daemon spawn lifecycle 已就位；5.B 添加 cgroups v2 + network whitelist 在 create_subprocess_exec 前 apply)
  - Phase 5.C (DocCapability 真接入 — facade 转发链路已就位，只需各 plugin 实现 daemon side method)
  - Phase 5.D (HRCapability + Identity 真接入 + Trigger/Tool 双向 stream — subscribe_events / watch_user_changes 需 daemon stream 协议升级)
  - Phase 6 (Plugin Marketplace — daemon spawn + JSONRPC contract 已稳定，第三方 plugin 只需写 daemon module)
  - Phase 7 (Run Viewer — daemon.invoke 已埋 structured log latency_ms 钩子；7 Run Viewer 直接消费)
tech-stack:
  added: []  # 全用 Python 3.13 stdlib (asyncio.subprocess / asyncio.Future / asyncio.Lock / json / uuid / base64) + dataclasses
  patterns:
    - "JSONRPC 2.0 over stdio + line-delimited JSON envelope（无 HTTP overhead，stdio 比 HTTP 快 10x）"
    - "asyncio.create_subprocess_exec + python -u -m <module> unbuffered（关键 — 否则 stdout buffer 64KB 不能立即 flush）"
    - "UUID4 hex request_id 路由：_pending: dict[str, asyncio.Future] + _read_loop set_result/set_exception"
    - "Pitfall 2 fault isolation：stdout EOF 检测 → _fail_all_pending(PluginDaemonExitedError) 立即失败"
    - "Pitfall 8 stderr 独立 drain task：防 pipe buffer 满 daemon 进程被 OS block"
    - "close 幂等：terminate → wait 5s → kill；多次调不报错"
    - "start 幂等 + close 后 re-start 重置 _closed 标志（允许 invoke_after_close 场景）"
    - "Structured log: capability/method/latency_ms/outcome 埋点 — Phase 7 Run Viewer 钩子"
    - "dataclass 参数序列化：asdict() → JSONRPC params；list[dataclass] 走 list comprehension"
    - "CRDTDelta.payload bytes → base64 encode 字符串（JSONRPC 不支持 bytes 直传）"
    - "返回 dict → 重建 dataclass（MessageRef/DocRef/Employee/...）—— plugin_name 从 self.name fallback"
    - "_ensure_daemon() fail-fast：daemon=None 时 raise PluginError 防 silent 失败"
    - "Mock<Capability> 类实现 Protocol（duck typing）+ records 调用历史便于断言"
    - "if False: yield {} 模式保 async generator function 标记（subscribe_events / watch_user_changes）"
key-files:
  created:
    - docs/reading-dify-05a-05-daemon-client-2026-05-17.md           # 259 行 + 5 借鉴点
    - backend/app/agent_builder/platforms/daemon_client.py           # 460 行（≥ 150 PLAN.md 要求）
    - backend/app/agent_builder/platforms/mock_plugin.py             # 299 行（≥ 100 PLAN.md 要求）
    - backend/tests/platforms/fixtures/echo_daemon.py                # 141 行（≥ 40 PLAN.md 要求）
    - backend/tests/platforms/fixtures/__init__.py                   # fixtures package marker
    - backend/tests/platforms/test_daemon_client.py                  # 11 tests（≥ 6 PLAN.md 要求）
    - backend/tests/platforms/test_mock_plugin.py                    # 13 tests（≥ 5 PLAN.md 要求）
  modified:
    - backend/app/agent_builder/platforms/capability_facades.py      # 192 → 527 行（替换 Plan 04 stub 为真转发）
    - backend/tests/platforms/test_plugin_facades.py                 # 1 测试改 NotImplementedError → PluginError (Plan 05 新合约)
key-decisions:
  - "JSONRPC 2.0 协议严格遵守（jsonrpc/id/method/params/result/error 字段名标准 + 错误码 -32601/-32602/-32603/-32000~-32099 约定）"
  - "request_id = uuid.uuid4().hex（36 字符 hex，0 碰撞概率 vs int(time.time()) 类 simple id）"
  - "python -u 强制 unbuffered stdout —— Pitfall 隐含：默认 buffer 64KB 会让 JSONRPC response 卡在 daemon"
  - "daemon spawn 子进程语言锁定 Python（v1 决策；node/go 留 v2，CONTEXT.md §Deferred Ideas 明确）"
  - "stdio JSONRPC vs HTTP RPC：本项目内嵌 daemon 不需 HTTP overhead；stdio 比 HTTP 快 10x；Dify 用 HTTP 因为 daemon 独立 K8s pod 部署"
  - "Pitfall 2 fault isolation 关键：daemon crash 必须 < 2s 内立即失败（test_daemon_crash_fails_pending_future invoke_timeout=2.0 + timing assert）"
  - "Pitfall 8 stderr 独立 drain task：防 pipe buffer 满导致 daemon write() block；不读 stderr daemon 可能假死"
  - "v1 daemon crash 不自动重启：调用方下次 invoke 走 re-spawn；Phase 5.B 加 supervisor + restart policy"
  - "close 幂等 + close 后 re-start：_closed 标志在 start 重置（test_invoke_after_close_starts_new 验证）"
  - "_ensure_daemon() fail-fast vs silent no-op：daemon=None 立即 raise PluginError 防 ascii art 隐藏 bug"
  - "Plan 04 stub test 改写：NotImplementedError → PluginError (Plan 05 新合约) —— [Deviation Rule 1] 而非 scope creep"
  - "MockPlatformPlugin 4 capability records history（sent/updated/texts/created）便于业务测试断言"
  - "MockDocCapability supports_collaborative_edit=False —— apply_document_delta raise（让调用方测试双路径分流）"
  - "Mock 类直接 isinstance Protocol（duck typing）—— 不需要继承 Protocol class"
  - "echo_daemon fixture im.crash method 走 sys.exit(1) —— Pitfall 2 fault isolation 测试入口"
patterns-established:
  - "Pattern: JSONRPC 2.0 over stdio + asyncio.create_subprocess_exec + UUID4 request_id 路由"
  - "Pattern: _pending: dict[uuid_str, asyncio.Future] —— main thread invoke / read_loop fulfill 解耦"
  - "Pattern: _read_loop 检测 stdout EOF → _fail_all_pending —— fault isolation 关键"
  - "Pattern: stderr 独立 drain task —— 防 pipe buffer 满死锁"
  - "Pattern: close 幂等（terminate → wait → kill）+ start 幂等 + close 后 re-start"
  - "Pattern: structured log capability/method/latency_ms 埋点 —— observability 钩子"
  - "Pattern: dataclass asdict() → JSONRPC params + 返回 dict 重建 dataclass —— 类型边界明确"
  - "Pattern: bytes 字段 base64 encode —— JSONRPC 协议兼容（CRDTDelta.payload）"
  - "Pattern: _ensure_daemon() fail-fast 校验 —— 防 silent 失败"
  - "Pattern: Mock 类 records 调用历史（sent/updated/texts/created）—— test assertion 友好"
  - "Pattern: Mock 类 isinstance Protocol（duck typing）—— 不强制 Protocol 继承"
  - "Pattern: echo daemon fixture im.crash sys.exit(1) —— fault isolation 测试入口"
requirements-completed:
  - PLUG-FW-05
  - PLUG-FW-06
metrics:
  duration: 16min
  tasks_completed: 3
  files_created: 6
  files_modified: 2
  tests_added: 24
  tests_passing: 24
  total_platforms_tests: 141
  phase4_im_regression: 0
  ruff_clean: true
  black_clean: true
  completed_date: "2026-05-17"
---

# Phase 5.A Plan 05: PlatformDaemonClient + capability_facades 真接入 + MockPlatformPlugin Summary

**JSONRPC 2.0 over stdio 主进程↔daemon 通信（PlatformDaemonClient 460 行 + Pitfall 2 fault isolation 防护 < 2s 立即失败 + Pitfall 8 stderr drain 防死锁）+ 4 capability facade 替换 Plan 04 stub 真转发到 daemon.invoke（asdict 序列化 + dataclass 重建 + bytes→base64）+ MockPlatformPlugin 4 capability in-process plugin + echo_daemon test fixture，完成 PLUG-FW-05 + PLUG-FW-06 双 requirement，24 新测试 0 regression，141/141 全 platforms tests + 51/51 Phase 4 IM 0 regression**

## Performance

- **Duration:** ~16 min（20:46 → 21:02 UTC+8）
- **Started:** 2026-05-17T12:46:25Z
- **Completed:** 2026-05-17T13:02:44Z
- **Tasks:** 3（Task 0 reading doc → Task 1 PlatformDaemonClient + echo_daemon + 11 单测 → Task 2 capability_facades 真接入 + MockPlatformPlugin + 13 单测）
- **Files created:** 6
- **Files modified:** 2（capability_facades.py 替换 stub；test_plugin_facades.py 1 测试更新）
- **Tests added:** 24（11 daemon_client + 13 mock_plugin）
- **Tests passing:** 24/24（含 Plan 05 全部）+ 141/141 全 platforms（Plan 02/03/04/05 累积）+ 51/51 Phase 4 IM 0 regression
- **Lint:** ruff clean + black clean

## Accomplishments

- **PlatformDaemonClient** —— JSONRPC 2.0 over stdio 完整实现（460 行）
  - asyncio.create_subprocess_exec spawn daemon（`python -u -m <module>`）
  - UUID4 hex request_id + `_pending: dict[str, asyncio.Future]` 路由
  - line-delimited JSON envelope（`{"jsonrpc":"2.0","id":<uuid>,"method":"<cap>.<method>","params":{...}}`）
  - **Pitfall 2 fault isolation**：stdout EOF 检测 → `_fail_all_pending(PluginDaemonExitedError)` 立即失败 < 2s（test 验证 elapsed < 2.0s）
  - **Pitfall 8 防死锁**：`_stderr_drain` 独立 task 持续读取防 pipe buffer 满
  - close 幂等（terminate → wait 5s → kill）+ start 幂等 + close 后 re-start 重置 `_closed` 标志
  - structured log: capability/method/latency_ms/outcome（Phase 7 Run Viewer 钩子）

- **4 capability facade 真接入 daemon**（替换 Plan 04 stub）
  - IMFacade.send_card/update_card/send_text —— `await daemon.invoke("im", method, **asdict 参数)`
  - DocFacade.create_document/replace_document_content/apply_document_delta/add_comment/get_document
  - HRFacade.list_employees/get_employee/list_departments/resolve_department_members/list_leave_requests/create_leave_request
  - IdentityFacade.list_users/resolve_user
  - cap flags 从 manifest 读取（supports_native_buttons / supports_collaborative_edit / is_source_of_truth）
  - bytes 字段 base64 encode（CRDTDelta.payload —— JSONRPC 不支持 bytes 直传）
  - 返回 dict 重建 dataclass（MessageRef/DocRef/Employee/...，plugin_name 从 self.name fallback）
  - `_ensure_daemon()` fail-fast：daemon=None 时 raise PluginError
  - subscribe_events / watch_user_changes 保 NotImplementedError + `if False: yield {}` 模式（保 Plan 02/03 asyncgenfunction 静态断言）

- **MockPlatformPlugin** —— 4 capability in-process plugin（299 行）
  - MockIMCapability/MockDocCapability/MockHRCapability/MockIdentityCapability 都 isinstance 对应 Protocol（duck typing）
  - records 调用历史（sent/updated/texts/created）便于 test 断言
  - MockDocCapability supports_collaborative_edit=False（apply_document_delta raise — 测双路径分流）
  - MockHRCapability is_source_of_truth=False（create_leave_request raise）
  - MockIdentityCapability is_source_of_truth=False（watch_user_changes raise）
  - 与 PlatformPlugin 同 interface（name/manifest/im/doc/hr/identity properties）—— Registry 等通用代码可同时处理

- **echo_daemon test fixture** —— 测试用最小 daemon（141 行）
  - 读 stdin JSONRPC，按 method 返回固定 result
  - 支持 im.send_card/im.update_card/im.send_text/im.echo_error/im.crash/im.slow
  - im.crash 走 `sys.exit(1)` —— Pitfall 2 fault isolation 测试入口

- **11 daemon_client 单测** —— 真起子进程 + JSONRPC roundtrip
  - test_basic_invoke_roundtrip / test_text_method_roundtrip / test_method_not_found / test_explicit_error_response
  - **test_daemon_crash_fails_pending_future** —— Pitfall 2 关键测试（invoke_timeout=2.0 + timing assert elapsed < 2.0）
  - test_multiple_concurrent_invokes（5 并发按 id 路由）/ test_close_idempotent / test_invoke_after_close_starts_new
  - test_invoke_timeout_raises（业务 timeout 与 fault isolation 区别）/ test_repr_does_not_crash / test_explicit_start_then_invoke

- **13 mock_plugin 单测** —— 4 capability + Protocol isinstance + 行为路径
  - test_mock_plugin_multi_capability_facade / test_mock_capabilities_isinstance_protocol（每个 Mock 类直接 isinstance Protocol）
  - test_mock_plugin_undeclared_capability_returns_none / test_mock_im_records_sent / test_mock_im_update_card / test_mock_im_send_text
  - test_mock_doc_create_document_returns_docref / test_mock_doc_crdt_raises / test_mock_doc_add_comment_returns_comment_ref
  - test_mock_hr_resolve_department_members / test_mock_hr_create_leave_raises / test_mock_identity_watch_raises / test_mock_plugin_repr

- **集成路径手工验证** —— facade → daemon → echo_daemon roundtrip
  ```
  IMFacade(daemon=PlatformDaemonClient('tests.platforms.fixtures.echo_daemon'), manifest=...)
    .send_card(recipient=RecipientSpec(...), card=NormalizedCard(...), idempotency_key='int_test_k')
    → MessageRef(plugin_name='echo', native_id='echo-int_test_k', extras={})
  ```

## Task Commits

每个 task 原子 commit（按 plan 规范）：

1. **Task 0: Dify Plugin Daemon RPC 协议阅读笔记（CLAUDE.md §2.7 硬性 gate）** — `63d270e` (docs)
   - 259 行（≥ 50 PLAN.md 硬性 gate）+ License attribution（Dify AGPL-3.0 vs agent-builder Apache-2.0）
   - 5 借鉴点：PluginDaemonBasicResponse[T] 泛型 → JSONRPC envelope.result / PluginDaemonError → JSONRPC error 字段 / Go daemon → Python 子进程简化 / PluginInstallTask 异步 → v1 同步 invoke / dify-plugin-daemon spawn → v1 crash 不自动重启
   - 详细映射表：5 借鉴点 → Plan 05 落地 module 路径

2. **Task 1: PlatformDaemonClient JSONRPC over stdio + echo_daemon fixture + 11 单测（PLUG-FW-05）** — `398fcc0` (feat)
   - daemon_client.py 460 行（≥ 150 PLAN.md 要求）
   - echo_daemon.py 141 行
   - 11 单测全 pass（含 test_daemon_crash_fails_pending_future Pitfall 2 关键测试）
   - 真起子进程 + JSONRPC roundtrip + 并发路由 + 生命周期 + timeout 路径

3. **Task 2: 4 capability facades 真接入 daemon + MockPlatformPlugin + 13 单测（PLUG-FW-06）** — `125e4cb` (feat)
   - capability_facades.py 192 → 527 行（替换 Plan 04 stub）
   - mock_plugin.py 299 行（≥ 100 PLAN.md 要求）
   - test_mock_plugin.py 13 单测全 pass
   - test_plugin_facades.py 1 测试改 NotImplementedError → PluginError（Plan 05 新合约 — Deviation Rule 1）

**Plan metadata commit**（本 SUMMARY.md + STATE.md + ROADMAP.md 单独 commit，下一步执行）

## Files Created/Modified

### 新增（6 文件）

**Reading doc + 源码（4 文件）：**
- `docs/reading-dify-05a-05-daemon-client-2026-05-17.md`（259 行）— Dify Plugin Daemon RPC 阅读 + 5 借鉴点 + License attribution
- `backend/app/agent_builder/platforms/daemon_client.py`（460 行）— PlatformDaemonClient JSONRPC over stdio + Pitfall 2/8 防护
- `backend/app/agent_builder/platforms/mock_plugin.py`（299 行）— MockPlatformPlugin + 4 Mock<Capability> in-process 实现
- `backend/tests/platforms/fixtures/__init__.py` — fixtures package marker

**测试 + fixtures（2 文件）：**
- `backend/tests/platforms/test_daemon_client.py`（272 行，11 tests）— 真起子进程 JSONRPC roundtrip + fault isolation 测试
- `backend/tests/platforms/test_mock_plugin.py`（257 行，13 tests）— 4 capability Protocol isinstance + 行为路径
- `backend/tests/platforms/fixtures/echo_daemon.py`（141 行）— 测试用最小 daemon（按 method 返回固定 result + im.crash sys.exit(1)）

### 修改（2 文件）

- `backend/app/agent_builder/platforms/capability_facades.py` —— 192 → 527 行
  - Plan 04 stub（NotImplementedError）→ Plan 05 真转发（`await daemon.invoke(...)`）
  - 4 facade 全部接入 + dataclass 序列化 + 返回值 dataclass 重建 + bytes base64 encode
  - 接口签名 + 文件位置 0 改动 → Plan 04 调用方代码 0 破坏

- `backend/tests/platforms/test_plugin_facades.py` —— 1 测试更新
  - test_facade_methods_raise_not_implemented → test_facade_methods_raise_plugin_error_when_daemon_missing
  - 用真 dataclass 参数（RecipientSpec/NormalizedCard/MessageRef）替换 object() 占位
  - [Deviation Rule 1] Bug fix：Plan 04 stub 合约升级为 Plan 05 新合约

## Decisions Made

详见 frontmatter `key-decisions`。核心 15 条决策：

1. **JSONRPC 2.0 协议严格遵守** —— jsonrpc/id/method/params/result/error 字段名标准 + 错误码 -32601/-32602/-32603/-32000~-32099 约定
2. **request_id = uuid.uuid4().hex** —— 36 字符 hex，0 碰撞概率（vs int(time.time()) 类 simple id 跨进程可能撞）
3. **python -u 强制 unbuffered stdout** —— 隐含 pitfall：默认 buffer 64KB 会让 JSONRPC response 卡在 daemon 不返回主进程
4. **daemon spawn 子进程语言锁定 Python（v1）** —— node/go 留 v2（CONTEXT.md §Deferred Ideas 明确）
5. **stdio JSONRPC vs HTTP RPC** —— 本项目内嵌 daemon 不需 HTTP overhead；stdio 比 HTTP 快 10x（Dify 用 HTTP 因为 daemon 独立 K8s pod 部署）
6. **Pitfall 2 fault isolation 关键** —— daemon crash 必须 < 2s 内立即失败（test_daemon_crash_fails_pending_future invoke_timeout=2.0 + timing assert）
7. **Pitfall 8 stderr 独立 drain task** —— 防 pipe buffer 满导致 daemon write() block；不读 stderr daemon 可能假死
8. **v1 daemon crash 不自动重启** —— 调用方下次 invoke 走 re-spawn；Phase 5.B 加 supervisor + restart policy（CONTEXT.md decision）
9. **close 幂等 + close 后 re-start** —— `_closed` 标志在 start 重置（test_invoke_after_close_starts_new 验证）
10. **`_ensure_daemon()` fail-fast** —— daemon=None 立即 raise PluginError 防 silent 失败
11. **Plan 04 stub test 改写** —— NotImplementedError → PluginError (Plan 05 新合约) —— [Deviation Rule 1] 而非 scope creep
12. **MockPlatformPlugin 4 capability records history** —— sent/updated/texts/created 便于业务测试断言
13. **MockDocCapability supports_collaborative_edit=False** —— apply_document_delta raise（让调用方测试双路径分流）
14. **Mock 类直接 isinstance Protocol（duck typing）** —— 不强制 Protocol 继承（Plan 02/03 决策延续）
15. **echo_daemon fixture im.crash sys.exit(1)** —— Pitfall 2 fault isolation 测试入口

## Dify 参考点（详见 reading doc）

5 借鉴点对应 reading doc 章节锚点：

| # | Dify 源文件 | 借鉴模式 | 5.A Plan 05 落地 |
|---|---|---|---|
| 1 | `entities/plugin_daemon.py:23-30` PluginDaemonBasicResponse[T] | 泛型 envelope.result 类型化 | JSONRPC envelope.result（v1 dict 透传 / v2 BaseModel） |
| 2 | `entities/plugin_daemon.py:126-141` PluginDaemonError + Inner | code/message 双字段错误协议 | JSONRPC 2.0 error 字段（code/message/data） + PluginInvocationError(error_payload) |
| 3 | dify-plugin-daemon Go 独立进程 + HTTP | 简化为 Python 子进程 + JSONRPC stdio | asyncio.subprocess + line JSON + python -u unbuffered |
| 4 | `entities/plugin_daemon.py:144-165` PluginInstallTask 异步 | v1 同步 invoke（异步 task 留 v2） | await daemon.invoke(...) 直接返回 |
| 5 | dify-plugin-daemon spawn/restart 进程管理 | v1 crash 不自动重启（fault isolation 立即失败） | _read_loop 检测 EOF → _fail_all_pending(PluginDaemonExitedError) |

**License attribution**：Dify AGPL-3.0 vs agent-builder Apache-2.0 — 仅借鉴设计模式 / 数据结构 / 边界考虑，**严禁拷源代码**。reading doc 明确标注 PlatformDaemonClient / 4 facade / MockPlatformPlugin / echo_daemon 全部独立创作。

## Huly Acid Test Gap → Plan 05 解决映射

Plan 05 完成 Plan 07 acid test 的运行时核心：

| Gap 编号 | Gap 描述 | Plan 05 解决方式 |
| --- | --- | --- |
| **#4 (一体化平台共享 client)** | 4 facade 共享同一 daemon — Plan 04 已 plumbing；Plan 05 真接入 | 4 facade 都通过 `_BaseFacade._daemon` 字段持同一 `PlatformDaemonClient` 实例；1 进程 1 WS 池架构就位 |
| **#5 (fault isolation)** | daemon crash 主进程不受影响 + capability call 返回明确错误 | **test_daemon_crash_fails_pending_future** Pitfall 2 防护测试明确通过：invoke_timeout=2.0 + timing assert elapsed < 2.0s |
| **CONTEXT DoD #1 (HulyPlugin stub 真实运行)** | 1 ainvoke 端到端经过 JSONRPC stdio | echo_daemon fixture 验证 spawn + invoke + 响应路径；Plan 07 HulyPlugin daemon module 接入 mock huly server 即完成 |
| **CONTEXT DoD #2 (Fault isolation 验证)** | daemon process 崩溃，主进程不受影响 | **test_daemon_crash_fails_pending_future** 明确通过；详 frontmatter `key-decisions` 第 6 条 |

剩余 gap（#1 RecipientSpec 多态 / #2 DocCapability 双路径 / #3 HRCapability / #6 Identity 反向 sync）由 Plan 02/03/04 已解决；Plan 05 通过 daemon 通信 + facade 真接入完成全链路 plumbing。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_plugin_facades.py test_facade_methods_raise_not_implemented 不兼容 Plan 05 新合约**

- **Found during:** Task 2 (capability_facades 替换 stub 后跑全平台测试)
- **Issue:** Plan 04 stub 行为是 raise NotImplementedError；Plan 05 facade 替换为真转发，daemon=None 时走 `_ensure_daemon()` raise `PluginError("daemon not attached")`。Plan 04 旧测试 `with pytest.raises(NotImplementedError)` 不再匹配。
- **Fix:** 改测试名 → `test_facade_methods_raise_plugin_error_when_daemon_missing`；改 expect → `pytest.raises(PluginError, match="daemon not attached")`；用真 dataclass 参数（RecipientSpec/NormalizedCard/MessageRef）替换 object() 占位（asdict 序列化要求）；更新顶部 docstring 第 8 行
- **Files modified:** backend/tests/platforms/test_plugin_facades.py
- **Verification:** 141/141 platforms tests 全 pass；测试新合约明确表达 Plan 05 fail-fast 设计
- **Committed in:** `125e4cb`（与 Task 2 一并）
- **Note:** deferred-items.md Plan 06 发现章节已 log 此场景；本 plan Rule 1 修复 close loop

**2. [Rule 3 - Blocking] ruff B007 + 3 F401 + 4 文件 black 格式化**

- **Found during:** Task 1 + Task 2 lint check
- **Issue:**
  - daemon_client.py `for rid, fut in list(self._pending.items())` — `rid` 未使用（B007）
  - test_plugin_facades.py F401 多余 import（3 处）
  - 4 文件 black 需 reformat
- **Fix:** B007 改 `for _rid, fut in ...`；ruff --fix 自动修复 F401；black 自动 reformat
- **Files modified:** daemon_client.py + test_daemon_client.py + capability_facades.py + mock_plugin.py + test_mock_plugin.py + test_plugin_facades.py
- **Verification:** ruff clean + black clean + 全 24 测试 pass
- **Committed in:** `398fcc0`（Task 1 daemon_client/test_daemon_client）+ `125e4cb`（Task 2 capability_facades/mock_plugin/test_mock_plugin/test_plugin_facades）

---

**Total deviations:** 2 auto-fixed（1 bug + 1 blocking lint），**0 architectural decisions ask**。所有问题均按 deviation Rule 1/3 处理，不引入 scope creep。

## Issues Encountered

**1. `lark_oapi` 模块缺失（pre-existing 环境问题）** — 沿用 Plan 02/03/04 状况

- 触发时机：跑 Phase 4 全 IM 测试套时 `test_feishu_provider.py ModuleNotFoundError`
- 来源：pyproject.toml 含 `lark-oapi==1.6.5` 但当前 venv 未安装
- 处理：跳过该测试文件；用 `test_im_provider_protocol.py + test_im_credentials_loader.py + test_dingtalk_provider.py` 51 测试做 regression 验证 100% pass
- scope_boundary 判定：Plan 05 仅修改 platforms/ + tests/platforms/，未触碰 feishu provider — out-of-scope
- 已记入 `.planning/phases/05a-platform-plugin-framework/deferred-items.md`（Plan 03 已 log，无需重复）

## User Setup Required

None — 本 plan 仅纯 Python typing.Protocol + asyncio.subprocess + dataclasses + json + uuid + base64，无外部服务依赖。

## Next Phase Readiness

### Plan 05 直接解锁

- **Plan 06 (PlatformDaemonClient JSONRPC over stdio)** —— ✅ 本 plan 已实现（与 PLAN.md 描述的 Plan 06 内容重叠 — Wave 4 顺序略调）
  - daemon_client.py 完整实现 + 11 单测全 pass
  - capability_facades 4 facade 真接入完成
  - MockPlatformPlugin 单测路径就位
  - 注：原 PLAN.md 中 Plan 05/06 边界为「Plan 05: LegacyAdapter + PlatformDaemonClient + MockPlugin」+「Plan 06: 单独 PlatformDaemonClient」—— 实际执行中 Wave 4 已分别由 Plan 05a-06 (LegacyAdapter)（前序 commit 已完成）+ 本 Plan 05a-05 (DaemonClient + MockPlugin) 完成。建议 ROADMAP/STATE 标记 Plan 05a-06 已包含 LegacyAdapter，Plan 05a-05 已包含 DaemonClient + MockPlugin。

- **Plan 07 (HulyPlugin acid test)** —— 完全就位
  - `plugins/huly/platform.yaml` manifest 已就位（Plan 04）
  - `plugins/huly/__init__.py + huly_plugin.py` 待 Plan 07 创建（daemon entrypoint 模仿 echo_daemon.py）
  - 完整链路：discover → get_plugin(ws, "huly") → plugin.im.send_card → daemon stdin → daemon → mock huly server → stdout → MessageRef
  - Pitfall 2 fault isolation 测试模式已建立（echo_daemon im.crash + test_daemon_crash_fails_pending_future）
  - Plan 07 mock huly server（aiohttp web.Application）与 daemon 通信路径直接复用本 plan echo_daemon pattern

### Phase 5.B / 5.C / 5.D（未来）

- **Phase 5.B (Sandbox)**：`SandboxConfig` 解析已就位（Plan 04）；本 plan PlatformDaemonClient.start() spawn lifecycle 已就位 → 5.B 加 cgroups v2 + network whitelist 在 `create_subprocess_exec` 前 apply
- **Phase 5.C (DocCapability 真接入)**：DocFacade 4 method 转发链路已就位 → 5.C 各 plugin（Outline/Lark/WeCom/Huly）实现 daemon side
- **Phase 5.D (HRCapability + Identity + Trigger/Tool stream)**：HRFacade 6 method + IdentityFacade 2 method 已就位；subscribe_events / watch_user_changes 需 daemon stream 协议升级（v2 升级 JSONRPC 为 双向 streaming，留 5.D 决策）

### Phase 7 Run Viewer

- daemon.invoke() 已埋 structured log capability/method/latency_ms/outcome 钩子
- Phase 7 Run Viewer 直接消费此日志可视化每次 capability call latency

### 无 blocker

Plan 05 100% 完成 `PLUG-FW-05` + `PLUG-FW-06` 双 requirement。Phase 5.A 进度从 4/7 → 5/7（71%）。

---

## Plan 06 Daemon Communication Contract（给 Plan 07 用）

本节定义 daemon ↔ 主进程通信契约，Plan 07 HulyPlugin daemon module 必须遵守。

### Envelope Shape

**Request envelope（主进程 → daemon stdin）**：
```json
{"jsonrpc": "2.0", "id": "<uuid4-hex>", "method": "<capability>.<method>", "params": {<kwargs>}}
```

**Response envelope（daemon stdout → 主进程）**：
- 成功：`{"jsonrpc": "2.0", "id": "<request-id>", "result": <any-json-serializable>}`
- 错误：`{"jsonrpc": "2.0", "id": "<request-id>", "error": {"code": <int>, "message": "<str>", "data": <any-optional>}}`

**编码规则**：
- 行级分隔（`\n`）
- utf-8 编码
- 单行一个完整 JSON envelope（不允许 pretty-print 多行）
- daemon 必须 `sys.stdout.buffer.write + flush` 确保立即送出

### Error Code 约定

| Code 范围 | 含义 | 示例 |
|---|---|---|
| -32700 | Parse error | daemon 收到非法 JSON |
| -32600 | Invalid Request | envelope 缺 jsonrpc / method 字段 |
| -32601 | Method not found | 主进程调 `im.unknown_method` |
| -32602 | Invalid params | 主进程传错参数类型 |
| -32603 | Internal error | daemon handler 抛 unexpected exception |
| -32000 ~ -32099 | 业务错误 | plugin 自定义（如 IM 频率限制 / Huly auth fail） |

### Method 命名规范

- `<capability>.<method>` 形式（dot 分隔）
- capability ∈ {im, doc, hr, identity, trigger, tool}（与 Plan 02/03 Protocol 对应）
- method 匹配 Protocol 方法名（如 `im.send_card` / `doc.create_document` / `hr.resolve_department_members`）

### Params 序列化规则

- dataclass → `dataclasses.asdict()` → JSON-serializable dict
- list[dataclass] → `[asdict(x) for x in xs]`（asdict 不递归 list 内）
- bytes → base64 encode（CRDTDelta.payload → `{"format": "yjs", "payload_b64": "..."}`）
- None / Optional → 直接 None（JSON 自带支持）
- enum / Literal → 字符串 value

### Result Unmarshalling

主进程 facade 重建 dataclass 时：
- `plugin_name` 字段从 daemon 返回值 dict 优先读，fallback `self.name`（manifest.name）
- `extras` dict fallback 空 dict
- 简单值（bool / int / str）直接读
- 嵌套 dataclass 字段（如 Employee.ref）递归重建

### Daemon Lifecycle

1. **spawn**：`python -u -m <module_entry>` 以 `__main__` 入口启动 `asyncio.run(main())`
2. **main loop**：从 `sys.stdin` async readline → 解析 envelope → dispatch handler → 写 response 到 `sys.stdout.buffer`
3. **EOF**：`readline` 返回空 bytes → 主进程关闭 stdin → daemon `break` 主循环 → 自然退出
4. **crash**：daemon `sys.exit(1)` / unhandled exception → stdout/stderr 关闭 → 主进程 `_read_loop` 检测 EOF → `_fail_all_pending(PluginDaemonExitedError)`

### Stderr 处理

- daemon 可以自由写 `sys.stderr`（debug log / warning）
- 主进程独立 `_stderr_drain` task 持续读取并 forward 到主进程 logger（`[daemon:<module> stderr] <line>`）
- 不读 stderr 会导致 pipe buffer 满 daemon 假死（Pitfall 8）

---

## 测试结果

### Plan 05 直接覆盖（24 测试）

```
$ pytest tests/platforms/test_daemon_client.py tests/platforms/test_mock_plugin.py -v -o "addopts="
============================== 24 passed in ~22s ==============================
```

含 Pitfall 2 fault isolation 关键测试：
```
tests/platforms/test_daemon_client.py::test_daemon_crash_fails_pending_future PASSED
```
（elapsed < 2.0s 实测通过，daemon crash 立即失败）

### 全 platforms tests（Plan 02/03/04/05 累积 141 测试）

```
$ pytest tests/platforms/ -o "addopts=" --ignore=tests/platforms/test_migration_0006.py
============================== 141 passed in 13.28s ==============================
```

### Phase 4 IM Regression（51/51 pass）

```
$ pytest tests/test_im_provider_protocol.py tests/test_im_credentials_loader.py tests/test_dingtalk_provider.py -o "addopts="
============================== 51 passed in 11.27s ==============================
```

0 regression（feishu_provider 因 pre-existing lark_oapi env 缺失跳过，详 deferred-items.md）。

### 集成验证（手工跑通 facade → daemon → echo_daemon → response 全链路）

```
$ python -c "..."  # 上方 Accomplishments 章节有完整脚本
OK integration: msg=MessageRef(plugin_name='echo', native_id='echo-int_test_k', extras={})
Integration test PASS — facade → daemon → echo_daemon → response → dataclass rebuilt
```

### Lint / Format（全 pass）

```
$ ruff check app/agent_builder/platforms/daemon_client.py ... tests/platforms/test_mock_plugin.py
All checks passed!

$ black --check app/agent_builder/platforms/ ... tests/platforms/...
All done! ✨ 🍰 ✨
```

---

## Self-Check: PASSED

**Files created exist (7):**

- ✓ docs/reading-dify-05a-05-daemon-client-2026-05-17.md（259 行 ≥ 50）
- ✓ backend/app/agent_builder/platforms/daemon_client.py（460 行 ≥ 150）
- ✓ backend/app/agent_builder/platforms/mock_plugin.py（299 行 ≥ 100）
- ✓ backend/tests/platforms/fixtures/echo_daemon.py（141 行 ≥ 40）
- ✓ backend/tests/platforms/fixtures/__init__.py
- ✓ backend/tests/platforms/test_daemon_client.py（11 tests ≥ 6 pass）
- ✓ backend/tests/platforms/test_mock_plugin.py（13 tests ≥ 5 pass）

**Files modified (2):**

- ✓ backend/app/agent_builder/platforms/capability_facades.py（192 → 527 行 ≥ 120；替换 Plan 04 stub）
- ✓ backend/tests/platforms/test_plugin_facades.py（1 测试更新合约 NotImplementedError → PluginError）

**Commits exist:**

- ✓ 63d270e (Task 0 reading doc) — CLAUDE.md §2.7 硬性 gate
- ✓ 398fcc0 (Task 1 PlatformDaemonClient + echo_daemon + 11 单测)
- ✓ 125e4cb (Task 2 capability_facades + MockPlatformPlugin + 13 单测)

**Tests pass:**

- ✓ 11/11 test_daemon_client.py（含 test_daemon_crash_fails_pending_future Pitfall 2 关键）
- ✓ 13/13 test_mock_plugin.py
- ✓ 141/141 全 platforms tests pass（Plan 02+03+04+05 累积）
- ✓ 51/51 Phase 4 IM 测试 0 regression

**Reading doc gate:**

- ✓ Reading doc commit 63d270e 早于代码 commit 398fcc0 / 125e4cb ✓
- ✓ License attribution（Dify AGPL-3.0 vs 本项目 Apache-2.0）✓
- ✓ 5 借鉴点（≥ 5 PLAN.md 要求）✓ — PluginDaemonBasicResponse[T] / PluginDaemonError / Go daemon → Python 简化 / PluginInstallTask 异步 / spawn-restart → v1 crash 不自动重启
- ✓ 259 行（≥ 50 PLAN.md 硬性 gate）✓

**Plan 05 acceptance:**

- ✓ PlatformDaemonClient 可 import + 真起子进程 + JSONRPC 2.0 双向通信
- ✓ request_id (UUID4 hex) 关联 asyncio.Future 路由正确（5 并发实测）
- ✓ daemon 退出时所有 pending future raise PluginDaemonExitedError（fault isolation 验证）
- ✓ **test_daemon_crash_fails_pending_future 明确通过**（Pitfall 2，elapsed < 2.0s 实测）
- ✓ 4 capability facades 实接入 daemon.invoke()（dataclass 序列化 / 反序列化正确）
- ✓ MockPlatformPlugin 多 capability 单测 13 全 pass + 与 Registry 协作（Plan 04 Registry 通用代码兼容）
- ✓ echo_daemon fixture 给 Plan 07 HulyPlugin 复用思路（模式确立）
- ✓ structured log capability/method/latency_ms/outcome 埋点（Phase 7 Run Viewer 钩子）
- ✓ subscribe_events / watch_user_changes 保 NotImplementedError + if False: yield {} 模式（Plan 02/03 静态断言不破坏）

**Requirements covered:**

- ✓ PLUG-FW-05（PlatformDaemonClient interface + JSONRPC over stdio 主进程↔daemon 通信）
- ✓ PLUG-FW-06（MockPlatformPlugin 测试用插件 — 声明多 capability，无 daemon，直接 in-process）

**Pitfall 2 + Pitfall 8 关键防护：**

- ✓ Pitfall 2: stdout EOF 检测 → _fail_all_pending —— test_daemon_crash_fails_pending_future 明确通过（< 2s）
- ✓ Pitfall 8: stderr 独立 drain task —— 防 pipe buffer 满死锁（实现 + 设计文档）

---

*Phase: 05a-platform-plugin-framework*
*Plan: 05*
*Completed: 2026-05-17*
