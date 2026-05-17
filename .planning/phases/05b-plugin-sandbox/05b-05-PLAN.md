---
phase: 05b-plugin-sandbox
plan: 05
type: execute
wave: 3
depends_on:
  - "05b-02"
files_modified:
  - docs/reading-dify-05b-05-cgroups-v2-2026-05-17.md
  - backend/app/agent_builder/platforms/sandbox/cgroups_v2.py
  - backend/app/agent_builder/platforms/sandbox/runner.py
  - backend/app/agent_builder/platforms/sandbox/__init__.py
  - backend/app/agent_builder/platforms/daemon_client.py
  - backend/tests/platforms/sandbox/test_cgroups_v2.py
  - backend/tests/platforms_integration/test_cgroups_v2_sandbox.py
autonomous: true
requirements:
  - PLUG-FW-10

must_haves:
  truths:
    - "CgroupsV2Sandbox 实现 SandboxRunner Protocol — 通过 systemd-run --user --scope 包裹 daemon 启动"
    - "is_cgroups_v2_available() 检测 4 条：/sys/fs/cgroup/cgroup.controllers 存在 + memory/cpu controllers + shutil.which('systemd-run') + systemd-run --user 真试一次"
    - "spawn_with_limits 注入 MemoryMax + MemorySwapMax=0 + CPUQuota=100% + TasksMax=32"
    - "use_cgroups: true + 检测可用 → CgroupsV2Sandbox；否则优雅降级到 PosixResourceSandbox + warning 日志"
    - "PlatformDaemonClient._choose_runner 升级：use_cgroups + is_available → CgroupsV2 / 否则 PosixResource"
    - "macOS / 容器内（systemd 不可用）始终降级 — 不 fail startup"
    - "GitHub Actions ubuntu-latest 跑 cgroups_v2_sandbox test 时 skip（容器无 cgroup delegation — Pitfall 2）"
    - "5.A 5/5 acid test + Plan 04 watchdog 集成 0 regression（use_cgroups=false 默认）"
    - "Dify 阅读文档先于代码 commit（CLAUDE.md §2.7 硬性 gate）"
  artifacts:
    - path: "docs/reading-dify-05b-05-cgroups-v2-2026-05-17.md"
      provides: "Dify dify-plugin-daemon Go cgroups v2 实现 → Python systemd-run 借鉴"
      min_lines: 80
    - path: "backend/app/agent_builder/platforms/sandbox/cgroups_v2.py"
      provides: "is_cgroups_v2_available() detector + CgroupsV2Sandbox 实现 + systemd-run cmd 构造"
      contains: "class CgroupsV2Sandbox"
    - path: "backend/app/agent_builder/platforms/daemon_client.py"
      provides: "_choose_runner 升级：use_cgroups + available → CgroupsV2 / fallback PosixResource"
      contains: "is_cgroups_v2_available"
    - path: "backend/tests/platforms_integration/test_cgroups_v2_sandbox.py"
      provides: "Linux + systemd-userdbd 集成测（CI 大概率 skip — 标记 cgroups_v2 marker）"
  key_links:
    - from: "backend/app/agent_builder/platforms/sandbox/cgroups_v2.py"
      to: "backend/app/agent_builder/platforms/sandbox/runner.py"
      via: "CgroupsV2Sandbox 实现 SandboxRunner Protocol contract"
      pattern: "spawn_with_limits"
    - from: "backend/app/agent_builder/platforms/daemon_client.py"
      to: "backend/app/agent_builder/platforms/sandbox/cgroups_v2.py"
      via: "_choose_runner 检测 + 实例化 CgroupsV2Sandbox"
      pattern: "is_cgroups_v2_available\\(\\)"
---

<objective>
实现 `CgroupsV2Sandbox` — Linux 生产可选的 systemd-run --user --scope cgroups v2 包裹 daemon spawn。配套 `is_cgroups_v2_available()` 检测函数（4 条检查 + 真试一次）+ 优雅降级（容器内 / macOS / 不可用时 fallback 到 PosixResourceSandbox + warning log）。最后升级 `PlatformDaemonClient._choose_runner` 让 `use_cgroups: true` + 检测可用时走 CgroupsV2，否则走 Plan 04 默认的 PosixResource。

Purpose: cgroups v2 是 Linux 生产环境的**真实资源限制**（PosixResource RLIMIT 在容器外有效，但 OOM kill / CPU quota 远不如 cgroups 精细）。提供 opt-in 路径让用户在 K8s pod / 物理 Linux 服务器上启用。**v1 默认 use_cgroups: false** —— 避免容器 + Docker compose 部署时启动失败（Pitfall 2）。

Output: 1 个 Dify reading doc + sandbox/cgroups_v2.py（is_available + CgroupsV2Sandbox）+ daemon_client.py _choose_runner 升级 + 单元测（mock systemd-run subprocess）+ cgroups_v2-marked 集成测（CI skip）。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/05b-plugin-sandbox/05b-CONTEXT.md
@.planning/phases/05b-plugin-sandbox/05b-RESEARCH.md
@.planning/phases/05b-plugin-sandbox/05b-01-PLAN.md
@.planning/phases/05b-plugin-sandbox/05b-02-PLAN.md
@backend/app/agent_builder/platforms/sandbox/runner.py
@backend/app/agent_builder/platforms/daemon_client.py
@backend/app/agent_builder/platforms/manifest.py
@CLAUDE.md

<interfaces>
From backend/app/agent_builder/platforms/sandbox/cgroups_v2.py（本 plan 创建）:
```python
import asyncio

def is_cgroups_v2_available() -> bool:
    """检测 cgroups v2 + systemd-run --user 是否可用。

    必须满足：
    1. /sys/fs/cgroup/cgroup.controllers 存在
    2. memory + cpu controllers 在 cgroup.controllers 可用
    3. shutil.which('systemd-run') 不为 None
    4. subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"], timeout=2)
       returncode == 0（真试 — Pitfall 2 防容器内权限不足）
    """

class CgroupsV2Sandbox:
    """实现 SandboxRunner Protocol — systemd-run --user --scope 包裹 daemon spawn."""
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> asyncio.subprocess.Process: ...
```

From backend/app/agent_builder/platforms/daemon_client.py（Plan 04 已扩展，本 plan 升级 _choose_runner）:
```python
def _choose_runner(self) -> SandboxRunner:
    if self._sandbox_runner is not None:
        return self._sandbox_runner
    if (self._sandbox_config is not None
        and self._sandbox_config.use_cgroups
        and is_cgroups_v2_available()):
        return CgroupsV2Sandbox()
    return PosixResourceSandbox()
```

From backend/app/agent_builder/platforms/manifest.py（Plan 01 已加 use_cgroups 字段）:
```python
class SandboxConfig(BaseModel):
    use_cgroups: bool = False  # Linux opt-in 默认 false
    ...
```
</interfaces>
</context>

<reference>
Dify 模块映射（CLAUDE.md §2.7）:
- 后端必读: `api/services/plugin/plugin_service.py` （plugin spawn cgroups / namespace 接入）— grep "cgroup|systemd|namespace|nsenter" 至少 30 行
- 后端参考: dify-plugin-daemon Go 仓库（grep cgroups 用法 — 概念参考不拷代码）
- systemd 官方文档参考: systemd-run(1) man page — `--user --scope --slice=` + `MemoryMax` / `CPUQuota` / `TasksMax` 字段

借鉴重点（reading doc 必含）:
1. Dify dify-plugin-daemon Go 直写 cgroup 文件 vs Python 走 systemd-run（推荐 systemd-run — 不需 root）
2. systemd-run --scope vs --service（scope = 当前 shell 进程组，service = 后台单元）
3. MemorySwapMax=0 防 swap 绕开 memory limit
4. TasksMax=32 防 fork bomb（与 RLIMIT_NPROC 双重防护）
5. v1 不直写 cgroup 文件（容器 unprivileged write 失败 — Pitfall 2）

License: Dify AGPL-3.0 Go 实现不拷代码；systemd-run 是系统标准工具，命令字符串可正常使用。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify reading doc（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05b-05-cgroups-v2-2026-05-17.md</files>
  <action>
    阅读以下 Dify 文件并写阅读笔记（先 commit 此 doc 才能进 Task 1）:

    1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — grep "cgroup|systemd|namespace|resource_limit|MemoryMax|CPUQuota" 至少 30 行
    2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` — grep 同上
    3. （可选 Go 仓库参考）dify-plugin-daemon README — 仅看资源限制 section 概念
    4. （文档参考）systemd-run(1) man page — `--user --scope --slice` + `MemoryMax` / `CPUQuota` / `TasksMax` 字段

    文档结构按 CLAUDE.md §2.7 模板:
    - 项目概述
    - 技术栈对照（Dify Go 直写 cgroup 文件 vs 本项目 Python systemd-run --user --scope）
    - 架构要点（容器 unprivileged 失败场景 → 优雅降级到 PosixResourceSandbox）
    - 可借鉴设计模式 4-6 条（systemd 属性命名 / TasksMax=32 / MemorySwapMax=0 防绕开 / --scope vs --service）
    - 与本项目关系（Pitfall 2 防护 — 4 条检查 + 真试 systemd-run / Plan 04 _choose_runner 升级点）
    - License attribution（systemd 是标准工具命令可用；Dify Go 不拷代码）

    最少 80 行；commit message: `docs(05b-05): add Dify cgroups v2 reading doc`。
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-05-cgroups-v2-2026-05-17.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-05-cgroups-v2-2026-05-17.md | awk '{exit ($1>=80)?0:1}'</automated>
  </verify>
  <done>reading doc 文件存在；≥ 80 行；git log 显示本 doc commit 在 Task 1 之前。</done>
</task>

<task type="auto">
  <name>Task 1: is_cgroups_v2_available 检测 + CgroupsV2Sandbox 实现 + _choose_runner 升级</name>
  <files>
    backend/app/agent_builder/platforms/sandbox/cgroups_v2.py
    backend/app/agent_builder/platforms/sandbox/__init__.py
    backend/app/agent_builder/platforms/daemon_client.py
  </files>
  <action>
    1. 创建 `backend/app/agent_builder/platforms/sandbox/cgroups_v2.py`:

    完整实现（按 RESEARCH §Pattern 2 + Pitfall 2/7）:
    ```python
    """CgroupsV2Sandbox + is_cgroups_v2_available（PLUG-FW-10）。

    设计要点（RESEARCH §Pattern 2 + Pitfall 2/7 + reading doc）:
    - systemd-run --user --scope 包裹 daemon spawn — 资源限制由 systemd 管理（免维护 cgroup 文件）
    - 4 条 detection 检查 + 真试 systemd-run（Pitfall 2 防容器 unprivileged）
    - 不可用时降级到 PosixResourceSandbox + warning log（_choose_runner 处理）
    - MemoryMax + MemorySwapMax=0 + CPUQuota=100% + TasksMax=32 四属性
    - systemd-run --collect --wait 等 cgroup 真释放（Pitfall 7）

    License: 100% 独立创作；systemd-run 是标准工具；不拷 Dify Go 源码。
    """
    from __future__ import annotations

    import asyncio
    import logging
    import os
    import shutil
    import subprocess
    from pathlib import Path

    _log = logging.getLogger(__name__)


    def is_cgroups_v2_available() -> bool:
        """检测 cgroups v2 + systemd-run --user 是否可用（Pitfall 2 完整 4 条 + 真试）."""
        # 1. cgroups v2 统一层级存在
        controllers_path = Path("/sys/fs/cgroup/cgroup.controllers")
        if not controllers_path.exists():
            return False

        # 2. memory + cpu controllers 可用
        try:
            available = controllers_path.read_text().split()
        except (PermissionError, OSError):
            return False
        if "memory" not in available or "cpu" not in available:
            return False

        # 3. systemd-run 在 PATH
        if shutil.which("systemd-run") is None:
            return False

        # 4. 真试一次（Pitfall 2 防 docker container unprivileged 失败）
        try:
            result = subprocess.run(
                ["systemd-run", "--user", "--scope", "--quiet", "--", "true"],
                capture_output=True,
                timeout=2.0,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
        return result.returncode == 0


    class CgroupsV2Sandbox:
        """Linux opt-in cgroups v2 sandbox（systemd-run --user --scope）。

        资源限制走 systemd transient unit:
        - MemoryMax: 硬上限（OOM kill 自动）
        - MemorySwapMax=0: 防 swap 绕开 memory limit
        - CPUQuota=100%: 1 个核（cpu_seconds 通过 watchdog 兜底，cgroups 无总累计 CPU 字段）
        - TasksMax=32: 防 fork bomb（与 RLIMIT_NPROC 双重防护）
        - --slice=agent-builder-plugin.slice: 独立 slice 隔离 + 便于 systemctl 查看
        """

        async def spawn_with_limits(
            self,
            cmd: list[str],
            *,
            cpu_seconds: int,
            memory_bytes: int,
            env: dict[str, str] | None = None,
            cwd: str | None = None,
        ) -> asyncio.subprocess.Process:
            merged_env = dict(os.environ) if env is None else dict(env)

            systemd_cmd = [
                "systemd-run",
                "--user",
                "--scope",
                "--slice=agent-builder-plugin.slice",
                "--quiet",                                       # 不打印 unit name 到 stdout
                "--collect",                                     # 等 cgroup 释放（Pitfall 7）
                f"--property=MemoryMax={memory_bytes}",
                "--property=MemorySwapMax=0",
                "--property=CPUQuota=100%",
                "--property=TasksMax=32",
                "--",
                *cmd,
            ]
            proc = await asyncio.create_subprocess_exec(
                *systemd_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
                cwd=cwd,
            )
            _log.info(
                "sandbox.cgroups_v2.spawned pid=%s memory_bytes=%d cmd=%s",
                proc.pid, memory_bytes, cmd[:2],
            )
            return proc


    __all__ = ["is_cgroups_v2_available", "CgroupsV2Sandbox"]
    ```

    2. 更新 `backend/app/agent_builder/platforms/sandbox/__init__.py` 导出新成员:
    ```python
    from .cgroups_v2 import is_cgroups_v2_available, CgroupsV2Sandbox

    __all__ += ["is_cgroups_v2_available", "CgroupsV2Sandbox"]
    ```

    3. 升级 `backend/app/agent_builder/platforms/daemon_client.py` 的 `_choose_runner`（Plan 04 已添加该方法 baseline）:

    现状（Plan 04 落地）:
    ```python
    def _choose_runner(self) -> SandboxRunner:
        if self._sandbox_runner is not None:
            return self._sandbox_runner
        return PosixResourceSandbox()
    ```

    升级为:
    ```python
    def _choose_runner(self) -> SandboxRunner:
        if self._sandbox_runner is not None:
            return self._sandbox_runner
        if (self._sandbox_config is not None
            and self._sandbox_config.use_cgroups):
            from .sandbox.cgroups_v2 import is_cgroups_v2_available, CgroupsV2Sandbox
            if is_cgroups_v2_available():
                _log.info("sandbox.runner.selected runner=CgroupsV2Sandbox")
                return CgroupsV2Sandbox()
            else:
                _log.warning(
                    "sandbox.cgroups_v2.unavailable — falling back to PosixResourceSandbox "
                    "(可能原因：非 Linux / 容器无 cgroup delegation / systemd-run 缺失)"
                )
        return PosixResourceSandbox()
    ```

    避坑（Pitfall 2/7）:
    - 真试 systemd-run 必须用 `timeout=2.0`（容器内可能 hang）
    - `--quiet` 必须 — 不然 systemd-run 输出 unit name 到 stdout 会污染 daemon JSONRPC pipe
    - `--collect` 必须 — Pitfall 7 防 OOM 后 cgroup 残留
    - `--scope` 不能换成 `--service`（service 模式 daemon 不在当前 shell 进程组，pipe 通信失败）
    - 不直写 /sys/fs/cgroup（unprivileged 写权限是另一个 pitfall — 让 systemd 处理）
    - `is_cgroups_v2_available` 必须**完全 silent fail**（不抛任何异常）— 否则 _choose_runner 在容器内会 crash

    commit messages:
    - `feat(05b-05): add is_cgroups_v2_available detector (4-check + real probe, Pitfall 2)`
    - `feat(05b-05): add CgroupsV2Sandbox (systemd-run --user --scope, PLUG-FW-10)`
    - `feat(05b-05): upgrade _choose_runner to cgroups v2 opt-in path with graceful fallback`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "from app.agent_builder.platforms.sandbox.cgroups_v2 import is_cgroups_v2_available, CgroupsV2Sandbox; from app.agent_builder.platforms.sandbox.runner import SandboxRunner; assert isinstance(CgroupsV2Sandbox(), SandboxRunner), 'CgroupsV2Sandbox must satisfy SandboxRunner Protocol'; avail = is_cgroups_v2_available(); print(f'cgroups_v2_available_on_this_host={avail}')"</automated>
  </verify>
  <done>
    CgroupsV2Sandbox 满足 SandboxRunner Protocol；is_cgroups_v2_available 在任何环境（macOS / 容器 / Linux 物理机）silent return bool；daemon_client._choose_runner 含 cgroups 分支。
  </done>
</task>

<task type="auto">
  <name>Task 2: 单元测 mock systemd-run + 集成测 Linux + systemd（CI skip 兼容） + 5.A regression</name>
  <files>
    backend/tests/platforms/sandbox/test_cgroups_v2.py
    backend/tests/platforms_integration/test_cgroups_v2_sandbox.py
  </files>
  <action>
    1. **单元测试 `backend/tests/platforms/sandbox/test_cgroups_v2.py`** ≥ 8 测（全部用 monkeypatch / mock，不依赖真 systemd-run）:

    - `test_is_cgroups_v2_available_returns_false_when_no_controllers_file`: monkeypatch Path.exists → False → 返回 False
    - `test_is_cgroups_v2_available_returns_false_when_missing_memory_controller`: monkeypatch read_text → "cpu pids"（无 memory）→ False
    - `test_is_cgroups_v2_available_returns_false_when_no_systemd_run_in_path`: monkeypatch shutil.which → None → False
    - `test_is_cgroups_v2_available_returns_false_when_systemd_run_probe_fails`: monkeypatch subprocess.run → returncode=1 → False
    - `test_is_cgroups_v2_available_returns_false_when_systemd_run_times_out`: monkeypatch subprocess.run → raise TimeoutExpired → False
    - `test_is_cgroups_v2_available_silent_on_permission_error`: monkeypatch read_text → raise PermissionError → False（不抛）
    - `test_cgroups_v2_sandbox_builds_correct_systemd_cmd`: 用 monkeypatch asyncio.create_subprocess_exec capture call args → 断言 cmd 含 `systemd-run --user --scope --quiet --collect` + MemoryMax/CPUQuota/TasksMax + `--slice=agent-builder-plugin.slice`
    - `test_cgroups_v2_sandbox_implements_runner_protocol`: `isinstance(CgroupsV2Sandbox(), SandboxRunner) is True`
    - `test_choose_runner_picks_cgroups_when_use_cgroups_true_and_available`: monkeypatch is_cgroups_v2_available → True + sandbox_config(use_cgroups=True) → runner is CgroupsV2Sandbox
    - `test_choose_runner_falls_back_when_cgroups_unavailable`: monkeypatch is_cgroups_v2_available → False + sandbox_config(use_cgroups=True) → runner is PosixResourceSandbox + warning log captured（用 caplog）
    - `test_choose_runner_picks_posix_when_use_cgroups_false`: sandbox_config(use_cgroups=False) → 不调 is_cgroups_v2_available（用 monkeypatch spy） → runner is PosixResourceSandbox

    用 `unittest.mock.patch` + `monkeypatch` + `caplog`（pytest 标准 fixture）。

    2. **集成测 `backend/tests/platforms_integration/test_cgroups_v2_sandbox.py`** ≥ 3 测（@pytest.mark.cgroups_v2 + @pytest.mark.linux_only + skipif not is_cgroups_v2_available()）:

    ```python
    import asyncio
    import sys
    import pytest

    from app.agent_builder.platforms.sandbox.cgroups_v2 import (
        CgroupsV2Sandbox,
        is_cgroups_v2_available,
    )

    pytestmark = [
        pytest.mark.asyncio,
        pytest.mark.linux_only,
        pytest.mark.cgroups_v2,
        pytest.mark.skipif(
            sys.platform == "darwin",
            reason="cgroups v2 是 Linux 专属（Pitfall 2）",
        ),
        pytest.mark.skipif(
            not is_cgroups_v2_available(),
            reason="cgroups v2 / systemd-run --user 不可用（容器 / dev env / CI ubuntu-latest 通常 skip — Pitfall 2）",
        ),
    ]

    async def test_cgroups_v2_smoke_normal_daemon() -> None:
        """smoke: cgroups v2 包裹下 daemon 仍能正常 stdout 通信."""
        sandbox = CgroupsV2Sandbox()
        proc = await sandbox.spawn_with_limits(
            [sys.executable, "-u", "-c", "print('hello cgroups', flush=True)"],
            cpu_seconds=5,
            memory_bytes=100 * 1024 * 1024,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        assert b"hello cgroups" in stdout

    async def test_cgroups_v2_memory_max_triggers_oom() -> None:
        """cgroups MemoryMax=50MB → alloc 200MB 触发 OOM kill (returncode = -SIGKILL = -9 / 137)."""
        sandbox = CgroupsV2Sandbox()
        proc = await sandbox.spawn_with_limits(
            [sys.executable, "-u", "-c",
             "x = b'a' * (200 * 1024 * 1024); print('alloc_unexpected_ok', flush=True)"],
            cpu_seconds=10,
            memory_bytes=50 * 1024 * 1024,    # 50MB 限制
        )
        await asyncio.wait_for(proc.wait(), timeout=15.0)
        # cgroups OOM kill → SIGKILL；returncode = -9 (Python negative for signal) 或 137 (shell convention)
        # Pitfall 7: systemd-run --collect --wait 等 cgroup 释放
        assert proc.returncode != 0, f"200MB alloc 超 50MB MemoryMax 应被 OOM kill；returncode={proc.returncode}"

    async def test_cgroups_v2_tasks_max_blocks_fork_bomb() -> None:
        """cgroups TasksMax=32 → 子进程 fork 超 32 应失败."""
        code = (
            "import subprocess, sys, time\n"
            "children = []\n"
            "for i in range(80):\n"
            "    try:\n"
            "        children.append(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)']))\n"
            "    except (OSError, BlockingIOError) as e:\n"
            "        print(f'fork_failed_at_{i}', flush=True)\n"
            "        break\n"
            "print(f'spawned_{len(children)}', flush=True)\n"
        )
        sandbox = CgroupsV2Sandbox()
        proc = await sandbox.spawn_with_limits(
            [sys.executable, "-u", "-c", code],
            cpu_seconds=10,
            memory_bytes=300 * 1024 * 1024,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        # cgroups TasksMax=32 应在 30 多次 fork 后阻断（含 daemon 自己 + reaper 等系统 task）
        # 容差：可能 fork 失败信号传到 Python 不一致 — 接受 "fork_failed_at_*" 或 "spawned_" 含 < 80
        out = stdout.decode()
        assert "fork_failed_at_" in out or "spawned_" in out, f"输出格式异常：{out}"
        # 如果 spawned_N 则 N < 60（远小于 80）
        for line in out.splitlines():
            if line.startswith("spawned_"):
                n = int(line.split("_")[1])
                assert n < 60, f"TasksMax=32 应阻 fork 超 60 次；实际 spawned={n}"
    ```

    3. **5.A regression** — 必跑:
    - `pytest backend/tests/platforms/ -x` 5.A 162 + 本 phase 前面 plans 全测 0 fail
    - `pytest backend/tests/platforms_integration/test_huly_acid_test.py test_fault_isolation.py -v` 5.A 5/5 acid test 0 fail（本 plan 仅升级 _choose_runner —— sandbox_config=None 时不触发 cgroups 分支）
    - `pytest backend/tests/notification/ -x` Phase 4 81 IM 0 regression

    避坑:
    - GitHub Actions `ubuntu-latest` 通常无 systemd-userdbd 运行 → `is_cgroups_v2_available()` 返回 False → 集成测 skip（不算 fail）
    - macOS local 测试集成测 100% skip（不能 fail）
    - 单元测试 mock subprocess.run 时不能用 default `subprocess.CompletedProcess` —— 必须显式设 returncode
    - 不要 mock `Path.read_text` 全局 — 用 monkeypatch + 限定 scope
    - cgroups detection caplog 验证：Plan 04 `_choose_runner` 用 `_log.warning` → caplog level 设 logging.WARNING

    commit messages:
    - `test(05b-05): add CgroupsV2Sandbox unit tests with mocked systemd-run (≥ 10 cases)`
    - `test(05b-05): add cgroups v2 integration tests (linux_only + cgroups_v2 marked, CI skip-compatible)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/sandbox/test_cgroups_v2.py -v 2>&1 | tail -25</automated>
  </verify>
  <done>
    单元测试 ≥ 10 全 pass；集成测 ≥ 3 在 macOS 全 skip + Linux 容器 CI 通常 skip（cgroups_v2 marker）+ Linux 物理机有 systemd-userdbd 时真跑全绿；5.A 162 + 本 phase 前 plans 全测 0 regression；5/5 acid test 0 regression；Phase 4 81 IM 0 regression。
  </done>
</task>

</tasks>

<verification>
**phase-local checks**:
- `pytest backend/tests/platforms/sandbox/test_cgroups_v2.py -v` ≥ 10 测全绿
- macOS: `pytest backend/tests/platforms_integration/test_cgroups_v2_sandbox.py -v` 输出含 "skipped"
- Linux CI: `pytest -m linux_only backend/tests/platforms_integration/test_cgroups_v2_sandbox.py -v` 大概率 skip（容器无 systemd-userdbd — 这是正确行为）
- Linux 物理机 dev：`pytest -m cgroups_v2 backend/tests/platforms_integration/test_cgroups_v2_sandbox.py -v` 真跑 ≥ 3 测全绿

**5.A regression**:
- `pytest backend/tests/platforms/ -x` 0 fail（5.A 162 + 本 phase 前 plans）
- `pytest backend/tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py -v` 5/5 acid test 0 fail
- `pytest backend/tests/notification/ -x` Phase 4 81 IM 0 regression

**Plan 04 集成 regression**:
- `pytest backend/tests/platforms/test_daemon_client.py -v` Plan 04 ≥ 18 测试 + 本 plan 加的 _choose_runner cgroups 分支 ≥ 3 测试 = 21+ 全绿

**reading doc gate**:
- `git log --oneline -10 | head` docs(05b-05) commit 早于任何 feat(05b-05) commit
</verification>

<success_criteria>
1. **CgroupsV2Sandbox 实现 Protocol**: isinstance(CgroupsV2Sandbox(), SandboxRunner) is True
2. **is_cgroups_v2_available 4 检查完整**: cgroup.controllers 存在 + memory/cpu 可用 + systemd-run in PATH + 真试 returncode 0
3. **Silent fail**: 任何环境（macOS / 容器 / Linux 物理机）调 is_cgroups_v2_available 不抛异常
4. **优雅降级**: use_cgroups=true + 不可用 → fallback to PosixResourceSandbox + warning log（Pitfall 2 / 容器友好）
5. **systemd-run 命令正确**: --user --scope --slice + MemoryMax + MemorySwapMax=0 + CPUQuota=100% + TasksMax=32 + --collect
6. **5.A 兼容**: use_cgroups=false 默认 → 任何 use_cgroups 逻辑都不触发 → 162 platforms + 5/5 acid test 0 regression
7. **测试覆盖**: 单元 ≥ 10（全 mock）+ 集成 ≥ 3（cgroups_v2 marker，CI skip 兼容）
8. **CI 兼容**: GitHub Actions ubuntu-latest 跑全 suite 不 fail（cgroups 测试 skip 不算 fail）
9. **reading doc gate**: docs commit 早于 feat commit（CLAUDE.md §2.7）
</success_criteria>

<output>
After completion, create `.planning/phases/05b-plugin-sandbox/05b-05-SUMMARY.md` 含:
- Dify 借鉴点（Go 直写 cgroup → systemd-run 包裹 的简化映射）
- 4 检查 + 真试 detection 设计理由（Pitfall 2 容器内 silent fail 必要性）
- systemd-run 属性选型表（MemoryMax / MemorySwapMax=0 / CPUQuota=100% / TasksMax=32 / --collect）
- 优雅降级路径（容器内 → PosixResource + warning，不 fail startup）
- Phase 5.B 完成总览（Wave 1 schema / Wave 2 PosixResource+AllowlistTransport / Wave 3 watchdog+cgroups 三层防护落地完毕）
- Phase 5.C 接力点（DocCapability 真接入时 sandbox 配置默认值 + cgroups opt-in 推荐）
</output>
</content>
</invoke>