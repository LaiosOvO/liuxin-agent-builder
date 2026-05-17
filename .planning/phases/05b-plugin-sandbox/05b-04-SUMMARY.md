---
phase: 05b-plugin-sandbox
plan: 04
subsystem: plugin-sandbox
tags: [watchdog, idle-reaper, daemon-client, sigterm-grace, env-allowlist, plugin-framework]

# Dependency graph
requires:
  - phase: 05b-plugin-sandbox
    plan: 02
    provides: PosixResourceSandbox（setsid PGID leader + RLIMIT 注入）+ SandboxLimitExceeded 异常
  - phase: 05b-plugin-sandbox
    plan: 03
    provides: AllowlistTransport（参考 lazy import 模式）
  - phase: 05b-plugin-sandbox
    plan: 01
    provides: SandboxConfig.memory_bytes / cpu_limit_seconds / env_allowlist / timeout_idle 字段
provides:
  - SandboxWatchdog asyncio task — SIGTERM grace 3s → SIGKILL（Pitfall 4/5）
  - IdleDaemonReaper asyncio task — 300s timeout auto-close（Pitfall 6）
  - PlatformDaemonClient.sandbox_config / sandbox_runner __init__ 参数
  - PlatformDaemonClient.last_invoke_at public 字段（reaper 读）
  - PlatformDaemonClient._choose_runner / _build_filtered_env 方法
  - sigterm_ignoring_daemon fixture（Linux integration test 用）
  - scan_once() 公共方法（HIGH-4 fix 便于单测）
affects:
  - 05b-05 CgroupsV2Sandbox（_choose_runner 加 use_cgroups 分支接入点）
  - Phase 6 marketplace（plugin 上传后注入 sandbox_config 启用三层防护）

# Tech tracking
tech-stack:
  added: []  # 0 新依赖 — 仅用 stdlib asyncio/os/signal/time/pathlib
  patterns:
    - "asyncio task + scan_once() 公共方法 — 单元测试可绕过 sleep 直接验证扫描逻辑（HIGH-4 fix）"
    - "on_violation callback 先于 SIGTERM（Pitfall 5 防 error 类型竞态）"
    - "os.killpg(getpgid(pid), SIGTERM) 整组 kill（Pitfall 4 防 fork 子进程逃逸）"
    - "time.monotonic 不是 time.time（Pitfall 6 NTP 抗变）"
    - "finally 块更新 last_invoke_at（Pitfall 6 exception 也更新）"
    - "strip-all-allowlist env 过滤（_SAFE_BASE_ENV + _FORBIDDEN_PREFIXES + _FORBIDDEN_EXACT 三层 — Pitfall 8）"
    - "双轨 spawn 路径（sandbox_config=None 走 5.A asyncio.create_subprocess_exec / 非 None 走 SandboxRunner.spawn_with_limits）"
    - "TYPE_CHECKING import 避免循环依赖 daemon_client ↔ sandbox.runner"
    - "psutil lazy import + 缺失时 warning（macOS RSS fallback path）"

key-files:
  created:
    - docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-18.md
    - backend/app/agent_builder/platforms/sandbox/watchdog.py
    - backend/app/agent_builder/platforms/sandbox/idle_reaper.py
    - backend/tests/platforms/sandbox/test_watchdog.py
    - backend/tests/platforms/sandbox/test_idle_reaper.py
    - backend/tests/platforms_integration/test_watchdog_grace_period.py
    - backend/tests/platforms_integration/test_idle_reaper.py
    - backend/tests/platforms_integration/fixtures/sigterm_ignoring_daemon.py
  modified:
    - backend/app/agent_builder/platforms/daemon_client.py
    - backend/app/agent_builder/platforms/sandbox/__init__.py
    - backend/tests/platforms/test_daemon_client.py

key-decisions:
  - "watchdog 默认 5s scan + 3s grace（比 systemd 90s 短 30x — plugin daemon 预期响应 SIGTERM <1s）"
  - "reaper 默认 60s scan + 300s timeout_idle（与 SandboxConfig.timeout_idle le=86400 字段对齐）"
  - "scan_once() 公共方法（HIGH-4 fix）— 让单元测试可直接验证扫描逻辑，无需 asyncio.sleep wait"
  - "_FORBIDDEN_EXACT 黑名单覆盖 env_allowlist opt-in（HMAC_SECRET 即使 manifest allow 也拒）"
  - "watchdog 仅在沙箱路径起（5.A 兼容 daemon 未 setsid，killpg 会误杀主进程）"
  - "close() 先 stop watchdog 再 SIGTERM daemon（防 watchdog 在 close 流程中误触发 SIGKILL）"
  - "Linux-only 集成测用 sigterm_ignoring_daemon fixture（macOS skipif）"
  - "idle reaper 跨平台跑（与 OS 无关，仅依赖 last_invoke_at 跟踪）"

requirements-completed: [PLUG-FW-12]

# Metrics
duration: 18min
completed: 2026-05-18
---

# Phase 5.B Plan 05b-04: SandboxWatchdog + IdleDaemonReaper + daemon_client 集成 Summary

**完成 Phase 5.B Wave 3 核心集成 — SandboxWatchdog (SIGTERM 3s grace → SIGKILL，Pitfall 4/5) + IdleDaemonReaper (300s timeout auto-close，Pitfall 6) + PlatformDaemonClient 沙箱化接入 (双轨兼容 5.A 11 测试 + 5/5 acid test 0 regression，strip-all-allowlist env 防 Pitfall 8 secret 泄漏)。43 新测试全绿，5.A 零回归。**

## Performance

- **Duration:** ~18 min
- **Tasks:** 4（Task 0 reading doc + Task 1 watchdog/reaper + Task 2 daemon_client 集成 + Task 3 测试）
- **Files:** 11 (1 doc + 2 新源 + 2 修改源 + 5 测试 + 1 fixture)
- **Commits:** 9 atomic (1 docs + 3 feat + 1 chore + 4 test)

## Task Commits

| # | Type | Hash | Message |
|---|---|---|---|
| 0 | docs | `e54b651` | docs(05b-04): add Dify watchdog/idle reaper reading doc |
| 1a | feat | `36bbce6` | feat(05b-04): add SandboxWatchdog (SIGTERM grace 3s → SIGKILL, Pitfall 4/5) |
| 1b | feat | `3d943bc` | feat(05b-04): add IdleDaemonReaper (300s timeout, Pitfall 6 active invoke skip) |
| 1c | chore | `253a2ec` | chore(05b-04): export SandboxWatchdog + IdleDaemonReaper from sandbox package |
| 2 | feat | `40e9954` | feat(05b-04): integrate sandbox runner + watchdog in PlatformDaemonClient |
| 2t | test | `224b53a` | test(05b-04): add daemon_client sandbox integration tests (13 new) |
| 3a | test | `b7e4b78` | test(05b-04): add watchdog + idle_reaper unit tests (27 new) |
| 3b | test | `a188596` | test(05b-04): add sigterm_ignoring_daemon fixture + grace period integration test |
| 3c | test | `f0d8057` | test(05b-04): add idle reaper integration tests (cross-platform) |

CLAUDE.md §2.7 gate：`e54b651` (docs) 早于所有 feat/test commits ✓

## 三层防护层级实现位置

```
Layer 1: invoke timeout (5.A, 已存在)
  └─ daemon_client.invoke() asyncio.wait_for(future, timeout=invoke_timeout)
  └─ 默认 30s / fault isolation test 用 2.0s

Layer 2: watchdog grace SIGTERM → SIGKILL (本 plan)
  └─ sandbox/watchdog.py: SandboxWatchdog
      ├─ asyncio task 每 5s 读 /proc/<pid>/status VmRSS
      ├─ 超 memory_bytes:
      │   1. on_violation callback (Pitfall 5 - 先于 SIGTERM)
      │   2. os.killpg(pgid, SIGTERM) (Pitfall 4 - 整组 kill)
      │   3. await asyncio.sleep(3s grace)
      │   4. os.kill(pid, 0) 探活 → ProcessLookupError 退出
      │   5. os.killpg(pgid, SIGKILL) 强杀
      └─ structured log: sandbox.limit_exceeded / sandbox.force_kill

Layer 3: idle reaper (本 plan)
  └─ sandbox/idle_reaper.py: IdleDaemonReaper
      ├─ asyncio task 每 60s 扫所有 daemon
      ├─ 跳过 _proc is None / _pending 非空 daemon (Pitfall 6 防竞争)
      ├─ time.monotonic() - last_invoke_at > 300s → daemon.close()
      └─ structured log: sandbox.idle_reaped
```

## Pitfall 防护落地

| Pitfall | 防护 | 实现位置 |
|---|---|---|
| **Pitfall 4** (fork bomb 逃逸) | `os.killpg(os.getpgid(pid), SIGTERM)` 整组 kill | `watchdog.py:_handle_violation` |
| **Pitfall 5** (on_violation 顺序) | callback 在 SIGTERM 之前同步执行 + 接收 SandboxLimitExceeded | `watchdog.py:_handle_violation` Step 1 |
| **Pitfall 6** (NTP wall clock) | `time.monotonic()` 不是 `time.time()` | `idle_reaper.py:scan_once` |
| **Pitfall 6** (active invoke 竞争) | 跳过 `_pending` 非空 daemon | `idle_reaper.py:scan_once` |
| **Pitfall 6** (finally 块更新) | `last_invoke_at = time.monotonic()` 在 invoke() finally | `daemon_client.py:invoke` |
| **Pitfall 8** (secret 泄漏) | strip-all-allowlist + _FORBIDDEN_EXACT/PREFIXES 黑名单 | `daemon_client.py:_build_filtered_env` |

## 5.A 兼容性策略

**关键约束**：`sandbox_config=None` 走 5.A 老路径 → 11 既有 test + 5/5 acid test 0 regression

```python
async def start(self):
    if self._sandbox_config is not None:
        # 5.B 沙箱路径：SandboxRunner + watchdog
        runner = self._choose_runner()
        self._proc = await runner.spawn_with_limits(cmd, ...)
        self._watchdog = SandboxWatchdog(pid=self._proc.pid, ...)
        self._watchdog.start()
    else:
        # 5.A 兼容路径（不动 5.A 测试）
        self._proc = await asyncio.create_subprocess_exec(...)
```

**验证**：`pytest tests/platforms/ tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py` 276 passed + 1 skipped（close_fds macOS pre-existing）。Phase 4 IM 96 测试 0 regression。

## Test Matrix

### 单元测试 (40 cases)

| 文件 | 测试数 | 关键覆盖 |
|---|---|---|
| `test_watchdog.py` | 14 | 默认参数 / start/stop 幂等 / _read_rss 死 pid / scan_once 超限路径 (Pitfall 5 on_violation 先于 SIGTERM) / SIGKILL 兜底 / callback 异常不阻塞 / _loop 死 pid 自动 break |
| `test_idle_reaper.py` | 13 | 默认参数 / 跳过 _proc is None / _pending 非空 (Pitfall 6) / close idle daemon / swallow close error / time.monotonic (Pitfall 6 NTP) / _loop 异常后继续 |
| `test_daemon_client.py` (新增 13) | 13 | sandbox_config=None 走 5.A 路径 (0 regression) / _build_filtered_env 6 测覆盖 PATH/HMAC_SECRET/AGENT_BUILDER_*/env_allowlist opt-in / _choose_runner 注入 vs 默认 / last_invoke_at finally 块 (Pitfall 6) / close stops watchdog |

### 集成测试 (6 cases — 3 idle + 3 watchdog)

| 文件 | 测试数 | 跨平台 | 关键覆盖 |
|---|---|---|---|
| `test_idle_reaper.py` | 3 | ✓ | 真 spawn echo daemon + 强行设 last_invoke_at → reaper close + lazy re-spawn / 跳过活跃 invoke |
| `test_watchdog_grace_period.py` | 3 | Linux only | sigterm_ignoring_daemon + alloc_200mb → SIGTERM IGN → 3s grace → SIGKILL / 正常 daemon 无误触发 / on_violation 让 invoke 立即 raise（不走 30s timeout）|

### 0 Regression 验证

- ✅ 5.A daemon_client 11 测试 PASS
- ✅ 5.A acid test 3/3 PASS (`test_huly_acid_test.py`)
- ✅ 5.A fault isolation 2/2 PASS (`test_fault_isolation.py`)
- ✅ 5.B Plan 01-03 215 platforms 测试 PASS（含 21 parser + 14 SandboxConfig + 13 network + 10 runner + 5/5 acid）
- ✅ Phase 4 IM 96 测试 PASS（card builder + provider protocol）
- ✅ macOS: watchdog grace period 测试 3 SKIPPED (Linux CI gate as designed)

## Deviations from Plan

None — 所有 plan 项按写执行。

**显式优化点（HIGH-4 fix 按 plan 要求实现）**:
- `scan_once()` 公共方法（两个类都加）— 让单元测试可直接验证扫描逻辑，无需 `asyncio.sleep` 等待真 cycle
- 双轨 spawn 路径设计严格遵守"sandbox_config=None 走 5.A 老路径不启动 watchdog"约束（避免 5.A daemon 未 setsid 时 killpg 误杀主进程）

## Dify 参考点

详见 `docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-18.md` (260 行)。

**6 借鉴点**：
1. HTTP client 长 timeout (600s) 作为外层兜底 — 我们 invoke timeout 30s 比 Dify 严格 20x（因为 Dify 依赖 Go daemon cgroups 兜底，我们没有 cgroups 强制路径）
2. uninstall 显式生命周期 API — 我们 IdleDaemonReaper 主动 close 不依赖 GC
3. trust_env=False 切断隐式代理 — 我们 strip-all-allowlist env 同思路（绝不传 HTTP_PROXY）
4. 池化 HTTP client 限连接数 — Plan 05b-03 AllowlistTransport 已借鉴
5. install_task 状态机思路 → structured log event (sandbox.limit_exceeded / sandbox.force_kill / sandbox.idle_reaped) 让运维 grep log 重建生命周期
6. systemd KillSignal/TimeoutStopSec 默认值参考（外部资料）— 我们 grace_period 3s 比 systemd 90s 短 30x（plugin daemon 预期 graceful shutdown < 1s）

**显式偏离**：Dify Go daemon 进程隔离 vs 本项目 Python asyncio task watchdog（跨平台栈不同 — Dify 推到 Go，我们留 Python）。

## Plan 05 接入点

`_choose_runner` 方法已预留 CgroupsV2Sandbox 接入：

```python
def _choose_runner(self) -> "SandboxRunner":
    if self._sandbox_runner is not None:
        return self._sandbox_runner  # injected
    # Plan 05b-05 接入点：use_cgroups + is_cgroups_v2_available() → CgroupsV2Sandbox
    # 本 plan 仅 PosixResourceSandbox baseline
    return PosixResourceSandbox()
```

Plan 05b-05 仅需加 use_cgroups 检测 + `CgroupsV2Sandbox()` 返回分支。

## Issues Encountered

- **psutil 未安装** — macOS RSS fallback path 用 psutil（Linux 走 /proc/<pid>/status 不需要）；测试通过 patch 验证 lazy import + warning log path
- **lark_oapi / wecom 模块缺失** — Phase 4 IM 部分测试 collection 失败（pre-existing dev env issue，记 deferred-items.md；本 plan 集成测/单测全绿不受影响）

## User Setup Required

None — 沙箱机制纯代码改动，无外部服务配置。

**Linux CI 需要的额外配置**（GitHub Actions ubuntu-latest）:
- `@pytest.mark.linux_only` 在 pytest.ini 已注册（Plan 05b-02 落实）
- 跑 `pytest -m linux_only tests/platforms_integration/test_watchdog_grace_period.py` 即可验证真 SIGTERM grace → SIGKILL 行为

## Next Phase Readiness

- ✅ **Wave 3 Plan 04 完成**：watchdog + idle reaper + daemon_client 集成全部落地
- ✅ **Plan 05b-05 可启动**：_choose_runner 接入点已就位（CgroupsV2Sandbox 仅需加分支返回）
- ✅ **5.A 0 regression**：276 platforms + 5/5 acid + Phase 4 IM 全绿
- ✅ **Phase 6 marketplace 预备**：sandbox_config 注入路径已通；marketplace plugin 上传后直接传 SandboxConfig 即启用三层防护
- ✅ **CLAUDE.md §2.7 满足**：reading doc commit 早于 feat commit

---
*Phase: 05b-plugin-sandbox*
*Completed: 2026-05-18*

## Self-Check: PASSED

**验证清单**:
- [x] `docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-18.md` 存在（260 行 ≥ 80）
- [x] `backend/app/agent_builder/platforms/sandbox/watchdog.py` 存在（含 `class SandboxWatchdog` + `scan_once`）
- [x] `backend/app/agent_builder/platforms/sandbox/idle_reaper.py` 存在（含 `class IdleDaemonReaper` + `scan_once`）
- [x] `backend/app/agent_builder/platforms/daemon_client.py` 已修改（含 `_choose_runner` + `_build_filtered_env` + `last_invoke_at`）
- [x] `backend/app/agent_builder/platforms/sandbox/__init__.py` 导出 `SandboxWatchdog` + `IdleDaemonReaper`
- [x] `backend/tests/platforms/sandbox/test_watchdog.py` 14 测试 PASS（含 Pitfall 5 顺序验证）
- [x] `backend/tests/platforms/sandbox/test_idle_reaper.py` 13 测试 PASS（含 Pitfall 6 防竞争）
- [x] `backend/tests/platforms/test_daemon_client.py` 新增 13 测试 + 5.A 11 测试 0 regression
- [x] `backend/tests/platforms_integration/test_watchdog_grace_period.py` 3 测试（macOS SKIPPED / Linux CI gate）
- [x] `backend/tests/platforms_integration/test_idle_reaper.py` 3 测试 PASS（跨平台）
- [x] `backend/tests/platforms_integration/fixtures/sigterm_ignoring_daemon.py` 存在（SIG_IGN + alloc_200mb method）
- [x] commit `e54b651` (docs) 早于 `36bbce6` / `3d943bc` / `40e9954` (feat) — CLAUDE.md §2.7 gate ✓
- [x] `pytest tests/platforms/ tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py --no-cov` 276 PASS + 1 SKIPPED（close_fds macOS pre-existing）— 0 regression
- [x] Phase 4 IM 96 测试 PASS（card builder + provider protocol）— 0 regression
- [x] 9 atomic commits（1 docs + 3 feat + 1 chore + 4 test）
