# Dify 阅读笔记 — Plugin Daemon cgroups v2 资源限制

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> 配套实施 plan: `.planning/phases/05b-plugin-sandbox/05b-05-PLAN.md` (CgroupsV2Sandbox + is_cgroups_v2_available)
> License: Dify AGPL-3.0 — 仅阅读不拷代码；本 plan 100% 独立创作

---

## 项目概述

Dify 在 Python `api/` 主仓库中**只声明** plugin 资源需求（`PluginResourceRequirements.memory: int`），**真实的 cgroups / namespace 隔离实现下沉到 Go 仓库** `dify-plugin-daemon`（独立进程跑在 daemon-host 模式）。本 plan 借鉴**资源声明 → systemd 透传**的简化路径，但走 Python `systemd-run --user --scope` 命令行包装而非 Go 直写 cgroup 文件。

---

## 技术栈对照

| 维度 | Dify（Go dify-plugin-daemon） | 本项目（Python agent-builder） |
| --- | --- | --- |
| 资源限制实现 | Go 直接写 `/sys/fs/cgroup/<slice>/memory.max`（要 root / cgroup delegation） | `systemd-run --user --scope --property=MemoryMax=...` 命令行（透明处理 user slice + delegation） |
| 进程模型 | 独立 daemon-host 进程 fork plugin worker | `asyncio.create_subprocess_exec` spawn 单 plugin daemon |
| 资源声明粒度 | `memory: int` (raw bytes，单字段) | `cpu_limit: str + memory: str + network: list + use_cgroups: bool` (K8s 风格多字段) |
| 容器兼容 | 要求 daemon-host privileged | 优雅降级到 `PosixResourceSandbox`（容器内 systemd-run 失败时不抛错） |
| 部署形态 | daemon 独立部署（解耦） | daemon 嵌入主进程（Phase 5.B v1 简化；Phase 6 marketplace 可拆） |

**核心差异点**：
- Dify 在容器场景下要求 daemon-host privileged，部署门槛高
- 本项目 v1 选择 systemd-run + 检测失败自动降级，**部署友好优先**（用户在 docker-compose / K8s pod / Linux 物理机都能 first-run 成功）

---

## 架构要点

```
manifest.sandbox.use_cgroups: true              manifest.sandbox.use_cgroups: false
              ↓                                                   ↓
PlatformDaemonClient._choose_runner()           PlatformDaemonClient._choose_runner()
              ↓                                                   ↓
is_cgroups_v2_available()?                       PosixResourceSandbox()
   ├─ True: CgroupsV2Sandbox                              ↓
   │       ↓                                  resource.setrlimit (preexec_fn)
   │  systemd-run --user --scope                          ↓
   │       --slice=agent-builder-plugin.slice  asyncio.subprocess.Process
   │       --collect (Pitfall 7)
   │       --property=MemoryMax=<bytes>
   │       --property=MemorySwapMax=0
   │       --property=CPUQuota=100%
   │       --property=TasksMax=32
   │       --quiet
   │       -- <daemon cmd>
   │              ↓
   │     systemd 透明:
   │       - 创建 transient scope unit
   │       - 注入到 user@<uid>.service slice
   │       - 写 cgroup memory.max / pids.max / cpu.max
   │       - OOM kill 自动（cgroups v2 内核）
   │
   └─ False: PosixResourceSandbox + warning log（Pitfall 2）
              "sandbox.cgroups_v2.unavailable — falling back ..."
              （容器内 / macOS / 无 systemd-userdbd 场景）
```

**关键不变量**：`CgroupsV2Sandbox` 与 `PosixResourceSandbox` **同 `SandboxRunner` Protocol**，daemon_client 不感知具体 runner 类型。

---

## 可借鉴的设计模式

### 1. 资源声明与执行分离（来自 `api/core/plugin/entities/plugin.py:26-27`）

Dify `PluginResourceRequirements` 只**声明** `memory: int`，**不**包含 cgroup 写入逻辑。我们的 `SandboxConfig` 同样只声明 `cpu_limit / memory / use_cgroups`，真正的 `setrlimit` / `systemd-run` 由独立 runner 类负责。**关注点分离**让 manifest schema 演化与 runner 实现独立迭代。

### 2. systemd transient unit 包装（systemd-run(1) man page 标准用法）

`systemd-run --user --scope --property=MemoryMax=X` 创建 transient cgroup scope，systemd **透明处理** user slice 创建 + cgroup delegation，**避免**直接 `echo $$ > /sys/fs/cgroup/.../cgroup.procs`（容器内通常 EPERM）。比 Dify Go 直写 cgroup 文件**部署门槛更低**。

### 3. TasksMax=32 防 fork bomb（systemd-run 属性）

`--property=TasksMax=32` 与 PosixResourceSandbox 的 `RLIMIT_NPROC=16` 形成**双重防护**：
- cgroups v2 TasksMax 在内核层强 enforcement（无视 user 权限）
- RLIMIT_NPROC 在 preexec_fn 设定（fallback 路径用）

### 4. MemorySwapMax=0 防 swap 绕过 memory limit（systemd-run 属性）

设 `MemoryMax=512M` 但**不**设 `MemorySwapMax=0` 时，超 RSS 后内核会先写 swap，daemon 可在 swap 容量内继续运行（绕开 OOM kill）。**强制 swap=0 才能保证 MemoryMax 真触发 OOM kill**。

### 5. `--scope` vs `--service` 选择

- `--scope`: 当前 shell 进程组内创建 cgroup（daemon stdin/stdout pipe 直连主进程）✓
- `--service`: 后台 unit（daemon stdout 走 systemd journal，**主进程读不到 stdout** → JSONRPC 通信失败 ✗）

本项目必须用 `--scope`（5.A daemon_client 走 stdio JSONRPC，离不开 pipe）。

### 6. `--collect` flag 防 cgroup OOM 残留（Pitfall 7）

systemd-run 默认 OOM kill daemon 后**保留** scope unit（等用户 `systemctl reset-failed`）。`--collect` 让 unit 自动清理，避免 cgroup tree 残留导致下次 spawn 失败。

---

## 与本项目的关系

### Pitfall 2 防护（4 检查 + 真试）

容器内 `systemd-run --user --scope` 经常返回 `Failed to start transient scope unit: Permission denied`（cgroup namespace 未授权 user slice 创建）。`is_cgroups_v2_available()` 必须做 **4 条检查 + 真试一次**，**任何一条失败都 silent return False**（绝不 raise — 否则 `_choose_runner` 在容器内 crash）：

1. `/sys/fs/cgroup/cgroup.controllers` 文件存在（v2 unified hierarchy）
2. 文件内含 `memory` + `cpu` controllers（启用 enforcement 前提）
3. `shutil.which("systemd-run")` 找到二进制（避免 alpine / minimal image 缺失）
4. `subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "--", "true"], timeout=2)` 真跑一次 returncode == 0（Pitfall 2 容器内 EPERM 场景）

**timeout=2.0** 必要 — 容器内可能 hang 几十秒等 systemd-userdbd 响应；2s 足够本地真机 + 容器 fast-fail。

### Plan 04 `_choose_runner` 升级

Plan 04 baseline:
```python
def _choose_runner(self) -> SandboxRunner:
    if self._sandbox_runner is not None:
        return self._sandbox_runner
    return PosixResourceSandbox()
```

本 plan 升级（保持 Plan 04 既有路径不破坏）:
```python
def _choose_runner(self) -> SandboxRunner:
    if self._sandbox_runner is not None:
        return self._sandbox_runner
    if (self._sandbox_config is not None
        and self._sandbox_config.use_cgroups):
        from .sandbox.cgroups_v2 import is_cgroups_v2_available, CgroupsV2Sandbox
        if is_cgroups_v2_available():
            return CgroupsV2Sandbox()
        # use_cgroups=true 但运行环境不可用 → warning + fallback（不 fail startup）
        _log.warning("sandbox.cgroups_v2.unavailable — falling back to PosixResourceSandbox ...")
    return PosixResourceSandbox()
```

**优雅降级是设计核心**：用户在 docker-compose 跑测试 / macOS dev / 容器无 cgroup delegation 时，`use_cgroups=true` 也不应导致服务启动失败 —— 应自动降级 + 记录 warning。

### 测试策略

- **单元测**（≥ 10）：mock `Path.exists` / `subprocess.run` / `shutil.which` / `asyncio.create_subprocess_exec` — cross-platform 跑（macOS + Linux 都过）
- **集成测**（≥ 3）：`@pytest.mark.cgroups_v2` + `pytest.mark.skipif(not is_cgroups_v2_available())` — macOS / 容器 CI 全 skip；Linux 物理机有 systemd-userdbd 时真跑 (OOM kill / TasksMax fork bomb)
- **5.A regression**：`use_cgroups=false` 默认 → 不触发 cgroups 路径 → 5.A 162 测试 + 5/5 acid test 0 regression

---

## License Attribution

- **systemd-run** 是 systemd 项目标准工具（LGPL-2.1+），命令行字符串属公共领域，可正常使用
- **Dify Go** dify-plugin-daemon (Apache-2.0 / 部分 AGPL-3.0) 的 cgroup 实现**仅读不拷**，本 plan 用 Python systemd-run 是**独立实现**
- 本 plan 100% 独立创作，仅在设计模式层面参考 Dify 资源声明 / 执行分离思路

---

## 总结

Dify Python `PluginResourceRequirements` 给我们**资源声明 schema 的简化范本**；Dify Go daemon 的 cgroup 实现给我们**反例参考**（直写 cgroup 文件部署门槛高）。本 plan 走 systemd-run --user --scope 路径：**部署友好 + 优雅降级 + 4 检查 detection + Pitfall 2/7 全防护**。Phase 5.B Wave 3 三层防护（PosixResource + Watchdog + cgroups）落地完毕后，agent-builder 在 Linux 生产环境可达 Dify Go daemon 的资源隔离强度，但实现复杂度低一个量级（无独立 daemon 进程 + 无 cgroup 直写）。
