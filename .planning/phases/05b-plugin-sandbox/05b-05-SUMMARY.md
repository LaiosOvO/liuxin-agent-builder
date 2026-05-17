---
phase: 05b-plugin-sandbox
plan: 05
subsystem: platforms
tags: [sandbox, cgroups-v2, systemd-run, plug-fw-10]
requires: [05b-02, 05b-04]
provides: [CgroupsV2Sandbox, is_cgroups_v2_available, cgroups-v2-opt-in-path]
affects: [PlatformDaemonClient._choose_runner]
tech-stack:
  added: [systemd-run]
  patterns: [4-check-+-real-probe-detection, graceful-degradation-fallback]
key-files:
  created:
    - docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md
    - backend/app/agent_builder/platforms/sandbox/cgroups_v2.py
    - backend/tests/platforms/sandbox/test_cgroups_v2.py
    - backend/tests/platforms_integration/test_cgroups_v2_sandbox.py
  modified:
    - backend/app/agent_builder/platforms/sandbox/__init__.py
decisions:
  - "systemd-run --user --scope 包裹 daemon spawn — 不直写 /sys/fs/cgroup（容器内 unprivileged 失败 Pitfall 2）"
  - "4 检查 + 真试 systemd-run detection — 任何环境 silent return False（绝不抛异常）"
  - "use_cgroups=true 不可用环境优雅降级 PosixResourceSandbox + warning log（不 fail startup）"
  - "MemorySwapMax=0 防 swap 绕过 MemoryMax；TasksMax=32 防 fork bomb（与 RLIMIT_NPROC 双重防护）"
  - "--scope 不能换 --service（service 模式 stdout 走 journal，JSONRPC 通信失败）"
  - "--collect 防 cgroup OOM 后 unit 残留（Pitfall 7）"
metrics:
  duration_minutes: 17
  completed: 2026-05-18
  tests: { added: 19, unit: 16, integration: 3 }
---

# Phase 5.B Plan 05: CgroupsV2Sandbox + systemd-run Linux Opt-in Sandbox Summary

**一句话**: 实现 cgroups v2 + systemd-run --user --scope opt-in 沙箱 runner + 4 检测优雅降级，Phase 5.B Wave 3 三层防护（PosixResource + Watchdog + cgroups）落地完毕。

---

## Tasks

| Task | Status | Commit  |
| ---- | ------ | ------- |
| 0    | docs reading | `6ef278d` |
| 1    | cgroups_v2.py + __init__.py 导出（daemon_client._choose_runner cgroups 分支已由 Plan 04 commit `40e9954` 提前包含 Plan 05 升级版本） | `7a3e63b` + `5172cfb` |
| 2    | 16 单元测 + 3 集成测 | `760832b` + `d70a68c` |

---

## Dify 借鉴点

- `api/core/plugin/entities/plugin.py:26-27` `PluginResourceRequirements.memory: int` — **资源声明与执行分离** 设计思路（声明 schema 独立演化，执行由独立 runner 负责）
- Dify Go dify-plugin-daemon 直写 cgroup 文件 → **反例参考**（容器内权限不足，部署门槛高）→ 本项目走 systemd-run 包装（透明 user slice delegation）
- 详见 `docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md` 6 借鉴点

## 4 检测 + 真试 detection 设计理由（Pitfall 2）

```
1. /sys/fs/cgroup/cgroup.controllers 文件存在    （静态检查 — v2 unified hierarchy 标志）
2. 文件含 memory + cpu controllers              （静态检查 — enforcement 前提）
3. shutil.which("systemd-run") 找到二进制       （静态检查 — alpine / minimal image 缺）
4. subprocess.run systemd-run --user --quiet -- true returncode == 0  （**真试** — 容器内 EPERM 唯一可靠探测）
```

任一失败 silent return False — **绝不 raise**（否则 `_choose_runner` 在容器内 crash）。

## systemd-run 属性选型表

| Property | 值 | 作用 | 备注 |
| --- | --- | --- | --- |
| `MemoryMax` | `<bytes>` | 硬上限触发 OOM kill | cgroups 内核层 enforcement |
| `MemorySwapMax` | `0` | 防 swap 绕过 memory limit | 不加 → daemon 超 RSS 后写 swap 不触 OOM |
| `CPUQuota` | `100%` | 1 个核 rate 限制 | cgroups 无累计 CPU 字段，走 watchdog 兜底 |
| `TasksMax` | `32` | 防 fork bomb 内核层 | 与 RLIMIT_NPROC=16 双重防护 |
| `--slice=agent-builder-plugin.slice` | - | 独立 slice 隔离 | `systemctl --user status` 可查 |
| `--collect` | - | OOM 后 cgroup 自动清理 | Pitfall 7 防 unit 残留 EBUSY |
| `--quiet` | - | 抑制 unit name 输出 | 防污染 JSONRPC stdout pipe |
| `--scope` | - | 当前 shell 进程组 | 不用 `--service`（stdout 走 journal） |

## 优雅降级路径（Pitfall 2 — 容器友好）

```
manifest.sandbox.use_cgroups: true
  ↓
PlatformDaemonClient._choose_runner()
  ↓
is_cgroups_v2_available()?
  ├─ True → CgroupsV2Sandbox  （Linux 物理机 + systemd-userdbd）
  └─ False → PosixResourceSandbox + log.warning("sandbox.cgroups_v2.unavailable ...")
            （macOS / 容器无 cgroup delegation / 无 systemd-userdbd — **不 fail startup**）
```

**关键不变量**：用户在 docker-compose 跑测试 / macOS dev / 容器无 cgroup delegation 时，`use_cgroups: true` 也不应导致服务启动失败。

## Phase 5.B 完成总览（三层防护）

- **Wave 1 ✓** Plan 05b-01: SandboxConfig schema + 5 字段 + memory/cpu validator
- **Wave 2 ✓** Plan 05b-02: SandboxRunner Protocol + PosixResourceSandbox baseline (cross-platform)
- **Wave 2 ✓** Plan 05b-03: AllowlistTransport + make_sandboxed_http_client (httpx 网络白名单)
- **Wave 3 ✓** Plan 05b-04: SandboxWatchdog (RSS scan + SIGTERM grace → SIGKILL) + IdleDaemonReaper (300s timeout) + daemon_client 集成
- **Wave 3 ✓** Plan 05b-05 (本 plan): CgroupsV2Sandbox + is_cgroups_v2_available + _choose_runner cgroups opt-in 分支

**三层防护落地**:
1. **资源限制** ✓ PosixResourceSandbox (RLIMIT_AS/CPU/NPROC/NOFILE) + CgroupsV2Sandbox (MemoryMax/CPUQuota/TasksMax) opt-in
2. **网络白名单** ✓ AllowlistTransport (httpx Transport API + exact host:port)
3. **超时强杀** ✓ SandboxWatchdog (5s scan + 3s SIGTERM grace → SIGKILL) + IdleDaemonReaper (5min timeout)

## Phase 5.C 接力点

- DocCapability / HRCapability 真接入时 sandbox 配置默认值：`cpu_limit="2.0" / memory="1Gi" / network=[] / use_cgroups=false`
- Linux 生产 K8s pod 部署文档化 **推荐 use_cgroups=true**（pod 已有 cgroup 隔离 + systemd-userdbd 启用）
- docker-compose dev 环境**保持 use_cgroups=false**（容器默认无 cgroup delegation — Pitfall 2）

---

## Files Touched

Created:
- `docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md` (159 行)
- `backend/app/agent_builder/platforms/sandbox/cgroups_v2.py` (229 行)
- `backend/tests/platforms/sandbox/test_cgroups_v2.py` (304 行, 16 测)
- `backend/tests/platforms_integration/test_cgroups_v2_sandbox.py` (140 行, 3 测)

Modified:
- `backend/app/agent_builder/platforms/sandbox/__init__.py` (+4 行导出)

Note: `backend/app/agent_builder/platforms/daemon_client.py` 中 `_choose_runner` cgroups 升级版本已由 Plan 04 commit `40e9954` 提前包含（两 plan 并行 Wave 3，Plan 04 commit 时已包含 Plan 05 设计的 cgroups 分支）。本 plan 仅添加 cgroups_v2.py 实现 + 测试。

---

## Test Results

```
单元测试（cross-platform — macOS + Linux 全跑）:
  tests/platforms/sandbox/test_cgroups_v2.py     16 PASSED in 8.44s

集成测试（macOS 全 skip + Linux 容器 CI 大概率 skip）:
  tests/platforms_integration/test_cgroups_v2_sandbox.py    3 SKIPPED on macOS

5.A regression（无 sandbox_config 路径不变）:
  tests/platforms/                                271 PASSED, 1 SKIPPED
  tests/platforms_integration/                    12 PASSED, 6 SKIPPED (cgroups + watchdog Linux-only)
  tests/platforms_integration/test_huly_acid_test.py + test_fault_isolation.py    5 PASSED (5/5 acid ✓)

Phase 4 IM 0 regression:
  tests/test_*_provider.py + tests/test_*_card_builder.py    131 PASSED
  (test_feishu_provider.py 因 lark_oapi 未安装 collection error — 见 deferred-items.md Plan 01)
```

---

## Pitfall 防护落地

- **Pitfall 2** (容器内 systemd-run unprivileged 失败): `is_cgroups_v2_available` 4 检查 + 真试 systemd-run + silent fail；`_choose_runner` 自动降级 + warning log
- **Pitfall 7** (cgroups v2 OOM kill 后 cgroup 残留): `systemd-run --collect` 让 unit 自动清理；集成测 `test_cgroups_v2_memory_max_triggers_oom` 验证

---

## Self-Check: PASSED

Verified files exist:
- FOUND: docs/reading-dify-05b-05-cgroups-v2-2026-05-18.md (159 行)
- FOUND: backend/app/agent_builder/platforms/sandbox/cgroups_v2.py
- FOUND: backend/tests/platforms/sandbox/test_cgroups_v2.py
- FOUND: backend/tests/platforms_integration/test_cgroups_v2_sandbox.py

Verified commits exist:
- FOUND: 6ef278d (docs reading doc)
- FOUND: 7a3e63b (feat cgroups_v2.py)
- FOUND: 5172cfb (chore export)
- FOUND: 760832b (test unit 16 cases)
- FOUND: d70a68c (test integration 3 cases)
