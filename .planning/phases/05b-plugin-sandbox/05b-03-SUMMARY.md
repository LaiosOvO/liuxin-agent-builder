---
phase: 05b-plugin-sandbox
plan: 03
subsystem: plugin-sandbox
tags: [httpx, transport-api, allowlist, network-isolation, plugin-framework]

# Dependency graph
requires:
  - phase: 05b-plugin-sandbox
    plan: 02
    provides: NetworkBlockedError 异常占位 (exceptions.py:112)
  - phase: 05b-plugin-sandbox
    plan: 01
    provides: SandboxConfig.network list[str] manifest schema
provides:
  - AllowlistTransport (httpx.AsyncBaseTransport 子类)
  - make_sandboxed_http_client(allow_list) factory
  - NetworkBlockedError 实际消费 (host + port + allowlist 字段)
  - 结构化日志 network.blocked event
  - 集成测 daemon fixture (fixtures/network_test_daemon.py) — Wave 3 plans 可复用
affects:
  - 05b-04 Watchdog/IdleReaper (PlatformDaemonClient._build_filtered_env 转 PLUGIN_NETWORK_ALLOW)
  - Phase 6 marketplace (plugin developer guide 强制要求用 make_sandboxed_http_client)

# Tech tracking
tech-stack:
  added: []  # 0 新依赖 — httpx 5.A 已锁定
  patterns:
    - "httpx.AsyncBaseTransport 子类化 — 注入点最干净 vs socket monkey-patch"
    - "exact (host, port) 匹配 + lowercase + scheme 推断 port"
    - "restrictive baseline: 空 allow = 拒所有出站 (Pitfall 8)"
    - "结构化日志 network.blocked event (host + port + scheme + size)"
    - "env-gated lazy import — 防 5.A acid test daemon spawn 时 ModuleNotFoundError (HIGH-2 fix)"
    - "集成测 fixtures/ 子包模式 — Wave 3 plans 可扩展"

key-files:
  created:
    - docs/reading-dify-05b-03-network-allowlist-2026-05-18.md
    - backend/app/agent_builder/platforms/sandbox/network.py
    - backend/tests/platforms/sandbox/test_network.py
    - backend/tests/platforms_integration/fixtures/__init__.py
    - backend/tests/platforms_integration/fixtures/network_test_daemon.py
    - backend/tests/platforms_integration/test_network_allowlist.py
  modified:
    - plugins/huly/huly_plugin.py

key-decisions:
  - "lazy import 替代顶部 import (HIGH-2 fix) — 防 5.A acid test 子进程 PYTHONPATH 未含 backend/ 时 ModuleNotFoundError"
  - "env-gated 双路径 — PLUGIN_NETWORK_ALLOW 未设走 5.A aiohttp fallback, 设了走 httpx + AllowlistTransport 新路径"
  - "v1 接受 requests/urllib 旁路 — reading doc 明示 trade-off + v2 Phase 6 marketplace 真隔离"
  - "_parse_allow_entry 跳过 malformed entry + warning — 防 plugin 作者笔误静默放行"

requirements-completed: [PLUG-FW-11]

# Metrics
duration: 25min
completed: 2026-05-18
---

# Phase 5.B Plan 05b-03: AllowlistTransport + NetworkBlockedError 集成 Summary

**application-level 网络白名单 v1 闭环 — httpx.AsyncBaseTransport 子类 + restrictive baseline 默认拒所有 + plugin daemon 显式注入 make_sandboxed_http_client; 13 unit + 4 integration tests 全绿, 5.A 162 platforms + 5/5 acid test + Phase 4 card builder 45 测试 0 regression。**

## Performance

- **Duration:** ~25 min (含 reading doc + Dify 5 文件 grep + 测试调试)
- **Tasks:** 3 (Task 0 reading doc + Task 1 network.py + huly 集成 + Task 2 tests)
- **Files:** 7 (1 doc + 1 module + 1 unit test + 1 fixture subpackage + 1 fixture daemon + 1 integration test + 1 modified huly)
- **Commits:** 5 atomic (1 docs + 2 feat + 2 test)

## Task Commits

| # | Type | Hash | Message |
|---|---|---|---|
| 0 | docs | `ffe4276` | `docs(05b-03): add Dify network allowlist reading doc` |
| 1a | feat | `ca3f4a8` | `feat(05b-03): add AllowlistTransport + make_sandboxed_http_client (PLUG-FW-11)` |
| 1b | feat | `6ec4dd4` | `feat(05b-03): integrate sandboxed http client in huly_plugin (env-gated, lazy import)` |
| 2a | test | `c7f1d05` | `test(05b-03): add AllowlistTransport unit tests (13 cases)` |
| 2b | test | `4898743` | `test(05b-03): add network_test_daemon fixture + 4 integration tests` |

CLAUDE.md §2.7 reading-doc-first gate 满足 — `ffe4276` (docs) 早于所有 feat/test commits。

## Dify 参考点

详见 `docs/reading-dify-05b-03-network-allowlist-2026-05-18.md` (192 行)。

**核心发现**: Dify Python 主仓库**没有** application-level 网络白名单 — 它把网络隔离全下沉到独立的 Go daemon (`dify-plugin-daemon` 仓库) 用 Linux network namespace 真隔离。Python 主仓库的 `_httpx_client` (`api/core/plugin/impl/base.py:56`) 仅供主仓库 → Go daemon 自己 RPC 用，不是 per-plugin 网络白名单。

**6 借鉴点**: 池化/显式注入 httpx, `trust_env=False` 切断 PROXY env 旁路, Pydantic v2 Permission BaseModel 嵌套, httpx Transport API 子类化 (BSD-3 公开), 默认 deny + 显式 allowlist, 结构化日志 event。

**显式偏离**: Dify Go daemon namespace 真隔离 vs 本项目 v1 Python httpx Transport 注入 (轻量, cross-platform, 但接受 requests/urllib 旁路 trade-off)。

## Pitfall 防护落地

- **Pitfall 3 (application-level 旁路)**: reading doc + network.py docstring 明示 v1 trade-off — plugin 用 `requests` / `urllib` / 裸 socket 完全绕过；v2 Phase 6 marketplace 上 nsjail / namespace 真隔离修复。
- **Pitfall 8 (restrictive default)**: 空 allow_list = 拒所有出站 (test_allowlist_empty_blocks_everything 验证)；manifest 不显式声明 `sandbox.network: [...]` 即默认禁所有。
- **HIGH-2 (5.A acid test daemon spawn 风险)**: `plugins/huly/huly_plugin.py` 用 lazy import (`_im_send_card_sandboxed` 函数体内 `from app.agent_builder...` import) — env 未设时该函数不被调，import 不执行，5.A acid test 子进程 PYTHONPATH 未含 backend/ 也不会 ModuleNotFoundError。

## 设计取舍

### 匹配规则: exact 而非 glob 通配符 (v1)

- v1 不支持 `*.example.com` 或 CIDR — `_parse_allow_entry` 仅解 `host:port` exact tuple
- 理由: Plan 05b-01 manifest validator 已限定 `^[a-z0-9.-]+:\d+$` 不允许 `*`；plugin 作者必须显式枚举每个 host
- v2 Phase 6 marketplace 上才考虑 glob (附加 plugin 审核 + UI 提示风险)

### port 默认值: scheme 推断 (443/80) + 未知 scheme = 0

- URL 不写显式 port + scheme=https → port=443; http → port=80
- 未知 scheme (如 ftp/ws) → port=0 → 必拒 (安全 baseline — 不识别的协议不放行)
- 旁路验证: `test_allowlist_https_default_port_443` / `test_allowlist_http_default_port_80`

### env-gated 双路径 (5.A 0 regression 关键)

- huly_plugin.py 保留 5.A aiohttp 代码作为 fallback 分支
- 通过 `_parse_network_allow()` 读 `PLUGIN_NETWORK_ALLOW` env
  - 空 → aiohttp (5.A 路径) — acid test 不设 env → 走此路径 → 0 regression
  - 非空 → httpx + AllowlistTransport (新路径) — Plan 05b-03 集成测设 env → 走此路径
- Plan 05b-04 主进程 `_build_filtered_env` 把 manifest `sandbox.network: [...]` 转 env 注入

### 集成测 fixtures/ 子包模式

- `backend/tests/platforms_integration/fixtures/` 子包 — Wave 3 plans (Watchdog / IdleReaper / CgroupsV2) 可在此添加测试 daemon entrypoint
- 命名约定: `{topic}_test_daemon.py` (network/watchdog/idle/cgroups...)
- returncode 编码: 10=blocked, 20=network_error, 30=import_error, 40+=未来扩展

## Test Matrix

### 单元测试 (13 cases, tests/platforms/sandbox/test_network.py)

| 类别 | 测试 | 断言 |
|---|---|---|
| 拒绝 (3) | unlisted_host / empty_allow / port_mismatch | raises NetworkBlockedError, delegate 不被调 |
| 放行 (4) | allowed_host / case-insensitive / https-port-443 / http-port-80 | 返回 200 |
| 边界 (4) | malformed_entry_skipped / aclose_propagates / error_msg / structured_log | 跳过 + warning, aclose delegate, "network.blocked" in log |
| factory (2) | returns_AsyncClient / uses_allowlist | isinstance + 实际 raise |

均用 `httpx.MockTransport` 作 delegate — 不真发 TCP, CI 友好。

### 集成测 (4 cases, tests/platforms_integration/test_network_allowlist.py, @pytest.mark.sandbox_integration)

| 测试 | env | 期望 |
|---|---|---|
| empty_allow_blocks_everything | `PLUGIN_NETWORK_ALLOW=""` | rc=10, stdout 含 `blocked:` |
| target_in_allow_attempts_real_request | `PLUGIN_NETWORK_ALLOW="blocked.example.com:443"` | rc≠10 (放行后真发) |
| target_not_in_allow_is_blocked | `PLUGIN_NETWORK_ALLOW="other-host.com:443"` | rc=10 |
| logs_network_blocked_event_in_stderr | (同上 blocked) | stderr 含 `network.blocked` |

## Regression 验证

- ✅ `tests/platforms/` 215 PASS + 1 SKIPPED (close_fds macOS, 5.A 既有) — **0 regression**
- ✅ `tests/platforms_integration/test_huly_acid_test.py` 3/3 PASS — **5.A acid test 0 regression**
- ✅ `tests/platforms_integration/test_fault_isolation.py` 2/2 PASS — **fault isolation 0 regression**
- ✅ `tests/platforms_integration/test_network_allowlist.py` 4/4 PASS — **新增 Plan 05b-03**
- ✅ Phase 4 IM `test_dingtalk_card_builder + test_feishu_card_builder` 45/45 PASS — **0 regression**
- ⚠️ `lark_oapi` / `wecom` 模块缺失 → Phase 4 部分 IM 测试 collection 失败 — **pre-existing** (已记 deferred-items.md, Plan 05b-01 同 issue)

## Deviations from Plan

None — plan 执行精确按写。Reading doc 写 192 行 (≥ 80 要求); 单元 13 测 (≥ 10 要求); 集成 4 测 (≥ 4 要求); huly_plugin 用 lazy import (HIGH-2 fix per plan critical_rules)。

## Self-Check: PASSED

- [x] `docs/reading-dify-05b-03-network-allowlist-2026-05-18.md` 存在 (192 行 ≥ 80)
- [x] commit `ffe4276` (docs) 早于 `ca3f4a8` / `6ec4dd4` (feat) — CLAUDE.md §2.7 gate ✓
- [x] `backend/app/agent_builder/platforms/sandbox/network.py` 含 `class AllowlistTransport(httpx.AsyncBaseTransport)` + `def make_sandboxed_http_client(allow_list)`
- [x] `plugins/huly/huly_plugin.py` 含 `_parse_network_allow` + `_im_send_card_sandboxed` (lazy import 验证)
- [x] `backend/tests/platforms/sandbox/test_network.py` 13 PASS (无任何 skip)
- [x] `backend/tests/platforms_integration/test_network_allowlist.py` 4 PASS
- [x] 5.A acid test 3/3 PASS (`test_huly_acid_test.py`) — 0 regression
- [x] 5.A platforms 215 PASS (1 skipped pre-existing) — 0 regression
- [x] Phase 4 card builder 45 PASS — 0 regression
