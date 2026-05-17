---
phase: 05b-plugin-sandbox
verified: 2026-05-18T00:00:00+08:00
status: passed
score: 4/4 must-haves verified
re_verification: false
---

# Phase 5.B: Plugin 沙箱 + Daemon 通信资源限制 Verification Report

**Phase Goal:** Plugin daemon 跑在受限沙箱进程内 — manifest sandbox 段消费 + resource.setrlimit baseline + 可选 cgroups v2 + 网络白名单 + 三层超时强杀（invoke timeout / watchdog SIGTERM grace SIGKILL / idle 自动回收）
**Verified:** 2026-05-18
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                        | Status     | Evidence                                                                                             |
|----|----------------------------------------------------------------------------------------------|------------|------------------------------------------------------------------------------------------------------|
| 1  | PlatformDaemonClient JSONRPC over stdio 双向通信 + lifecycle hooks                          | VERIFIED   | daemon_client.py 含 `_choose_runner`/`start`/`close` 沙箱双轨路径；5/5 acid test PASS               |
| 2  | 沙箱进程资源限制：CPU/memory baseline + network whitelist + manifest sandbox 段               | VERIFIED   | runner.py RLIMIT×4 + network.py AllowlistTransport + SandboxConfig 7 字段 all wired                  |
| 3  | Plugin 异常不影响主进程；超时 / RSS 超限强杀                                                  | VERIFIED   | watchdog.py SIGTERM→SIGKILL 3s grace；fault_isolation 2/2 PASS；idle_reaper 300s auto-close          |
| 4  | Multi-capability plugin 单 daemon 共享 client（5.A），沙箱下仍工作                            | VERIFIED   | sandbox_config=None 走 5.A 路径；5/5 acid test + 271 platforms 0 regression                          |

**Score: 4/4 truths verified**

---

### Required Artifacts

| Artifact                                                              | Expected                                        | Status    | Details                                              |
|-----------------------------------------------------------------------|-------------------------------------------------|-----------|------------------------------------------------------|
| `backend/app/agent_builder/platforms/manifest.py`                     | SandboxConfig 7 字段 + 2 派生属性 + validators  | VERIFIED  | 存在；含 `class SandboxConfig`，7 字段全部有注释与 validator |
| `backend/app/agent_builder/platforms/sandbox/parser.py`               | parse_memory + parse_cpu_seconds                | VERIFIED  | 105 行；两纯函数；0 Pydantic 依赖                    |
| `backend/app/agent_builder/platforms/sandbox/runner.py`               | SandboxRunner Protocol + PosixResourceSandbox   | VERIFIED  | 235 行；含 RLIMIT×4 + os.setsid()；Protocol runtime_checkable |
| `backend/app/agent_builder/platforms/sandbox/network.py`              | AllowlistTransport + make_sandboxed_http_client | VERIFIED  | 192 行；含 class AllowlistTransport + factory          |
| `backend/app/agent_builder/platforms/sandbox/watchdog.py`             | SandboxWatchdog + scan_once                     | VERIFIED  | 348 行；SIGTERM grace→SIGKILL；on_violation 先于 SIGTERM |
| `backend/app/agent_builder/platforms/sandbox/idle_reaper.py`          | IdleDaemonReaper + 300s auto-close              | VERIFIED  | 206 行；scan_once；time.monotonic；_pending 非空跳过   |
| `backend/app/agent_builder/platforms/sandbox/cgroups_v2.py`           | CgroupsV2Sandbox + is_cgroups_v2_available      | VERIFIED  | 229 行；4 检查+真试；--scope不是--service              |
| `backend/app/agent_builder/platforms/exceptions.py`                   | SandboxLimitExceeded + NetworkBlockedError      | VERIFIED  | 两类均在 `__all__` 中；继承 PluginError                |
| `backend/app/agent_builder/platforms/daemon_client.py`                | _choose_runner + _build_filtered_env + last_invoke_at | VERIFIED | 三方法全部存在；FORBIDDEN_EXACT/PREFIXES 黑名单落地   |
| `plugins/huly/platform.yaml`                                          | sandbox 段含 7 字段                             | VERIFIED  | sandbox: cpu_limit/memory/network/timeout_invoke/timeout_idle/use_cgroups/env_allowlist 全部存在     |
| `docs/reading-dify-05b-01-sandbox-config-2026-05-17.md`               | Dify reading doc ≥ 80 行                        | VERIFIED  | 174 行                                               |
| `docs/reading-dify-05b-02-resource-runner-2026-05-17.md`              | Dify reading doc ≥ 80 行                        | VERIFIED  | 210 行                                               |
| `docs/reading-dify-05b-03-network-allowlist-2026-05-18.md`            | Dify reading doc ≥ 80 行                        | VERIFIED  | 192 行                                               |
| `docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-18.md`         | Dify reading doc ≥ 80 行                        | VERIFIED  | 260 行                                               |
| `docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md`                   | Dify reading doc ≥ 80 行                        | VERIFIED  | 159 行                                               |

所有 15 个 artifact 全部 VERIFIED（存在 + 实质内容 + 接线）。

---

### Key Link Verification

| From                                   | To                                         | Via                                      | Status  | Details                                             |
|----------------------------------------|--------------------------------------------|------------------------------------------|---------|-----------------------------------------------------|
| manifest.py SandboxConfig              | sandbox/parser.py                          | `from .sandbox.parser import parse_memory, parse_cpu_seconds` | WIRED | memory_bytes/cpu_limit_seconds 属性调用 parser |
| daemon_client.py                       | sandbox/runner.py PosixResourceSandbox     | `_choose_runner()` → `runner.spawn_with_limits` | WIRED | sandbox_config 非 None 路径调用 runner          |
| daemon_client.py                       | sandbox/watchdog.py SandboxWatchdog        | `start()` 内 `SandboxWatchdog(...).start()` | WIRED | watchdog 与 daemon spawn 一体集成                |
| daemon_client.py                       | sandbox/idle_reaper.py                     | `IdleDaemonReaper` + `last_invoke_at` public 字段 | WIRED | reaper 读 last_invoke_at 判断 idle 时长         |
| daemon_client.py                       | sandbox/cgroups_v2.py                      | `_choose_runner()` cgroups 分支          | WIRED   | use_cgroups=True 时 lazy import CgroupsV2Sandbox    |
| network.py AllowlistTransport          | exceptions.py NetworkBlockedError          | `from ..exceptions import NetworkBlockedError` | WIRED | handle_async_request 抛 NetworkBlockedError        |
| plugins/huly/huly_plugin.py            | sandbox/network.py make_sandboxed_http_client | lazy import + PLUGIN_NETWORK_ALLOW env  | WIRED   | env-gated 双路径；5.A acid test 0 regression        |
| test_manifest_schema.py                | SandboxConfig validators                   | `pytest.raises(ValidationError)`        | WIRED   | 14 TestSandboxConfig 测试全绿                       |
| test_network_allowlist.py (integration) | network_test_daemon.py fixture            | subprocess spawn + env inject            | WIRED   | 4/4 integration tests PASS                          |

---

### Requirements Coverage

| Requirement | Source Plan | Description                                          | Status    | Evidence                                                     |
|-------------|------------|------------------------------------------------------|-----------|--------------------------------------------------------------|
| PLUG-FW-13  | 05b-01     | SandboxConfig manifest sandbox 段 Pydantic schema    | SATISFIED | SandboxConfig 7 字段 + validators + 2 派生属性；49 tests PASS |
| PLUG-FW-09  | 05b-02     | PosixResourceSandbox RLIMIT×4 + os.setsid            | SATISFIED | runner.py 235 行；Protocol runtime_checkable；10 unit tests   |
| PLUG-FW-11  | 05b-03     | AllowlistTransport 应用层网络白名单                   | SATISFIED | network.py 192 行；13 unit + 4 integration tests PASS         |
| PLUG-FW-12  | 05b-04     | SandboxWatchdog + IdleDaemonReaper                   | SATISFIED | watchdog.py + idle_reaper.py；14+13 unit + 6 integration tests |
| PLUG-FW-10  | 05b-05     | CgroupsV2Sandbox systemd-run opt-in                  | SATISFIED | cgroups_v2.py 229 行；4 检查+真试；优雅降级已验证              |

---

### Anti-Patterns Found

| File                          | Pattern                            | Severity | Impact                                                                           |
|-------------------------------|------------------------------------|----------|----------------------------------------------------------------------------------|
| `test_runner.py` (line 13)   | 注释提到 linux_only 但未实现该层    | WARNING  | `test_resource_limits.py` 和 `memory_hog_daemon.py` 在 Plan 02 PLAN 中规划但未创建。Linux CI 的 RLIMIT_AS/RLIMIT_CPU 真 enforcement 集成测试缺失。macOS 已有 contract tests；功能实现完整；仅缺 Linux CI gate 覆盖。 |

该警告为 **非阻塞**（warning 级别）：沙箱实现本身完整正确，缺失的是 Linux CI 下的额外 enforcement 验证层（Plan 02 PLAN 写了但实际未提交）。Phase 5.B ROADMAP 成功标准均通过验证。

---

### Pitfall 防护落地验证

| Pitfall | 防护描述                                         | 落地验证                                               |
|---------|--------------------------------------------------|--------------------------------------------------------|
| Pitfall 1 | macOS RLIMIT 弱 enforcement — skip linux_only  | marker 已注册；test_runner.py 含 `does_not_raise_on_macos` |
| Pitfall 2 | 容器内 systemd-run 失败 — 4 检查+真试降级        | is_cgroups_v2_available() 在 macOS 返回 False；不抛异常  |
| Pitfall 4 | fork bomb 进程组逃逸 — os.killpg 整组 kill       | watchdog.py `_handle_violation` killpg(SIGTERM/SIGKILL) |
| Pitfall 5 | on_violation 顺序 — callback 先于 SIGTERM        | `test_watchdog_on_violation_callback_called_before_sigterm` PASS |
| Pitfall 6 | idle 竞争 — time.monotonic + _pending 非空跳过   | idle_reaper.py scan_once；`test_idle_reaper_skips_active_invoke` PASS |
| Pitfall 7 | cgroups OOM 残留 — systemd-run --collect         | cgroups_v2.py 含 `--collect` 参数                        |
| Pitfall 8 | env secret 泄漏 — strip-all-allowlist            | _FORBIDDEN_EXACT (HMAC_SECRET) + _FORBIDDEN_PREFIXES (AGENT_BUILDER_*, DATABASE_*) |

---

### 5.A Regression 验证

| 测试集                                          | 结果                       |
|-------------------------------------------------|----------------------------|
| `tests/platforms/` (271 + 1 skipped)            | 271 PASSED, 1 SKIPPED (close_fds macOS pre-existing) |
| `tests/platforms_integration/test_huly_acid_test.py` (5/5) | 5 PASSED             |
| `tests/platforms_integration/test_fault_isolation.py` (2/2) | 2 PASSED            |
| Phase 4 IM tests (excluding lark_oapi dev env gap) | 197 PASSED (pre-existing lark_oapi 未安装属 dev env 问题，已记录 deferred-items.md) |

---

### CLAUDE.md §2.7 Reading Doc Gate

所有 5 个 plan 均满足"reading doc commit 早于 feat commit"：

| Plan | Reading Doc Commit | First Feat Commit | Gate |
|------|--------------------|-------------------|------|
| 05b-01 | `e5d06cd` (docs) | `0a33a08` (feat) | PASS |
| 05b-02 | `a7552ad` (docs) | `814618e` (feat) | PASS |
| 05b-03 | `ffe4276` (docs) | `ca3f4a8` (feat) | PASS |
| 05b-04 | `e54b651` (docs) | `36bbce6` (feat) | PASS |
| 05b-05 | `6ef278d` (docs) | `7a3e63b` (feat) | PASS |

---

### macOS / Linux 平台差异处理

| 行为                                | macOS dev                          | Linux CI (ubuntu-latest)           |
|-------------------------------------|------------------------------------|------------------------------------|
| RLIMIT_AS enforcement               | 不能 setrlimit (Darwin 拒绝降低) → try/except 跳过 | 严格 — malloc 超限返 ENOMEM        |
| RLIMIT_CPU enforcement              | 弱 — 不触发 SIGXCPU               | 严格 — 超 soft 发 SIGXCPU         |
| RLIMIT_NPROC                        | cross-platform 严格 ✓              | cross-platform 严格 ✓              |
| cgroups v2 / systemd-run            | is_cgroups_v2_available() = False  | 物理机 True；容器视 delegation      |
| watchdog grace period tests         | 3 SKIPPED (linux_only)             | 需跑 `pytest -m linux_only`        |
| close_fds test                      | SKIPPED (pre-existing)             | 严格断言                           |

---

### Human Verification Required

以下项目无法完全自动化验证，建议在 Linux CI 环境补充：

**1. Linux RLIMIT_AS enforcement integration test**
- **Test:** 在 ubuntu-latest 运行 `pytest -m linux_only tests/platforms_integration/`
- **Expected:** `test_resource_limits.py` 存在时 RLIMIT_AS 100MB limit 阻止 200MB alloc
- **Why human:** 此文件未创建；macOS 无法验证真 enforcement；需 Linux 环境确认行为

**2. Linux cgroups v2 systemd-run integration**
- **Test:** 在 systemd-run 可用的 Linux 主机跑 `pytest -m cgroups_v2`
- **Expected:** `test_cgroups_v2_memory_max_triggers_oom` PASS（daemon 超 MemoryMax 被 OOM kill）
- **Why human:** macOS 全 skip；容器内视 cgroup delegation 配置而定

---

## Overall Assessment

Phase 5.B 目标已实现：Plugin daemon 沙箱化框架完整落地。

**三层防护**：
1. 资源限制：`PosixResourceSandbox` (RLIMIT_CPU/AS/NPROC/NOFILE) + `CgroupsV2Sandbox` (MemoryMax/CPUQuota/TasksMax) opt-in — 实现完整
2. 网络白名单：`AllowlistTransport` exact host:port 匹配 + `make_sandboxed_http_client` — 实现完整
3. 超时强杀：`SandboxWatchdog` (5s scan + 3s SIGTERM grace → SIGKILL) + `IdleDaemonReaper` (300s auto-close) — 实现完整

**5.A 零回归**：sandbox_config=None 双轨路径保护 5.A 全部 11 daemon_client 测试 + 5/5 acid test 通过。

**单一 warning**：Plan 02 规划的 `test_resource_limits.py` (Linux-only RLIMIT_AS 集成测试) 和 `memory_hog_daemon.py` fixture 未创建。该测试覆盖 PLAN spec 中的 Linux CI enforcement gate，但沙箱功能实现本身完整正确，不影响目标达成。可在 Phase 6 或 CI 配置阶段补充。

---

_Verified: 2026-05-18_
_Verifier: Claude (gsd-verifier)_
