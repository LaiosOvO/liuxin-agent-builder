---
phase: 05b-plugin-sandbox
plan: 02
type: execute
wave: 2
depends_on:
  - "05b-01"
files_modified:
  - docs/reading-dify-05b-02-resource-runner-2026-05-17.md
  - backend/app/agent_builder/platforms/sandbox/runner.py
  - backend/app/agent_builder/platforms/exceptions.py
  - backend/tests/platforms/sandbox/test_runner.py
  - backend/tests/platforms_integration/test_resource_limits.py
  - backend/tests/platforms_integration/fixtures/__init__.py
  - backend/tests/platforms_integration/fixtures/memory_hog_daemon.py
  - backend/pyproject.toml
autonomous: true
requirements:
  - PLUG-FW-09

must_haves:
  truths:
    - "SandboxRunner Protocol 提供统一 spawn_with_limits 接口（cpu_seconds / memory_bytes / env / cwd）"
    - "PosixResourceSandbox 通过 preexec_fn 在 fork 后 exec 前调用 resource.setrlimit 注入 CPU/AS/NPROC/NOFILE 4 类 RLIMIT"
    - "PosixResourceSandbox 启动时 os.setsid() 让 daemon 成为新进程组 leader（Pitfall 4 防 fork 子进程逃逸）"
    - "spawn_with_limits 返回的 asyncio.subprocess.Process 可正常 stdin/stdout/stderr 通信（pipe 不受 setsid 影响）"
    - "SandboxLimitExceeded 异常类已定义（Wave 3 watchdog 引用）"
    - "Linux CI 真跑 enforcement test（RLIMIT_AS 限 100MB 时 alloc 200MB 子进程 returncode != 0）"
    - "macOS contract test 跳过 enforcement（@pytest.mark.skipif sys.platform == 'darwin'）"
    - "Dify 阅读文档先于代码 commit（CLAUDE.md §2.7 硬性 gate）"
  artifacts:
    - path: "docs/reading-dify-05b-02-resource-runner-2026-05-17.md"
      provides: "Dify plugin daemon 资源限制 Go 实现思路 → Python preexec_fn 借鉴点"
      min_lines: 80
    - path: "backend/app/agent_builder/platforms/sandbox/runner.py"
      provides: "SandboxRunner Protocol + PosixResourceSandbox + _apply_posix_limits preexec_fn"
      contains: "class PosixResourceSandbox"
    - path: "backend/app/agent_builder/platforms/exceptions.py"
      provides: "SandboxLimitExceeded + NetworkBlockedError 异常占位（Wave 3 + Plan 05b-03 引用）"
      contains: "class SandboxLimitExceeded"
    - path: "backend/tests/platforms/sandbox/test_runner.py"
      provides: "SandboxRunner contract test（macOS smoke + 全平台 API 正确性）"
    - path: "backend/tests/platforms_integration/test_resource_limits.py"
      provides: "Linux-only RLIMIT_AS / RLIMIT_CPU enforcement test"
    - path: "backend/pyproject.toml"
      provides: "pytest markers: linux_only / sandbox_integration"
  key_links:
    - from: "backend/app/agent_builder/platforms/sandbox/runner.py"
      to: "backend/app/agent_builder/platforms/sandbox/parser.py"
      via: "PosixResourceSandbox 接受 memory_bytes int（parser 已在 Plan 05b-01 完成）"
      pattern: "memory_bytes: int"
    - from: "backend/tests/platforms_integration/test_resource_limits.py"
      to: "backend/tests/platforms_integration/fixtures/memory_hog_daemon.py"
      via: "fixture daemon 子进程 alloc 大块内存触发 RLIMIT_AS"
      pattern: "module_entry.*memory_hog"
---

<objective>
建立 sandbox runner 抽象层 —— `SandboxRunner` Protocol 定义 + `PosixResourceSandbox` 跨平台 baseline 实现（通过 `resource.setrlimit` + `preexec_fn` 注入 CPU/AS/NPROC/NOFILE 限制 + `os.setsid()` 进程组隔离）。同时定义 `SandboxLimitExceeded` 异常类（Wave 3 watchdog 引用）+ Linux-only enforcement 集成测试（macOS skip）。

Purpose: PosixResourceSandbox 是**所有 plugin daemon spawn 的唯一入口**——Wave 3 watchdog + cgroups 集成时通过 Protocol 注入即可不修改 daemon_client 逻辑（5.A daemon_client 在 Wave 3 才接入 sandbox runner）。

Output: 1 个 Dify reading doc + sandbox/runner.py（含 Protocol + PosixResourceSandbox） + exceptions.py 扩展 + 单元测试（macOS 全平台 contract test） + Linux-only 集成测试（GitHub Actions ubuntu-latest 跑真 enforcement）+ pytest markers 配置。
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
@backend/app/agent_builder/platforms/daemon_client.py
@backend/app/agent_builder/platforms/exceptions.py
@backend/app/agent_builder/platforms/sandbox/parser.py
@CLAUDE.md

<interfaces>
<!-- 本 plan 创建的接口（Wave 3 Plan 04/05 依赖此契约）-->

From backend/app/agent_builder/platforms/sandbox/runner.py（本 plan 创建）:
```python
from typing import Protocol

class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> asyncio.subprocess.Process: ...

class PosixResourceSandbox:
    """实现 SandboxRunner Protocol — resource.setrlimit baseline (macOS + Linux)."""
    async def spawn_with_limits(self, ...) -> asyncio.subprocess.Process: ...
```

From backend/app/agent_builder/platforms/exceptions.py（本 plan 扩展）:
```python
class SandboxLimitExceeded(Exception):
    """资源超限 — watchdog 检测时 raise（Wave 3 引用）。"""
    pass

class NetworkBlockedError(Exception):
    """网络白名单拦截 — AllowlistTransport raise（Plan 05b-03 引用）。"""
    pass
```

Wave 2 Plan 03（AllowlistTransport）会引用 NetworkBlockedError；Wave 3 Plan 04（watchdog）会引用 SandboxLimitExceeded —— 故本 plan 一并定义占位。

From backend/app/agent_builder/platforms/sandbox/parser.py（Plan 05b-01 已完成，本 plan 消费）:
```python
def parse_memory(value: str) -> int: ...
def parse_cpu_seconds(value: str) -> int: ...
```

5.A daemon_client.py 当前 spawn 实现（本 plan 不修改，Wave 3 才修改）:
```python
self._proc = await asyncio.create_subprocess_exec(
    sys.executable, "-u", "-m", self._module_entry,
    stdin=PIPE, stdout=PIPE, stderr=PIPE,
    env=merged_env, cwd=self._cwd,
)
```
</interfaces>
</context>

<reference>
Dify 模块映射（CLAUDE.md §2.7）:
- 后端必读: `api/services/plugin/plugin_service.py` (plugin spawn / resource 注入入口) — grep "subprocess\|spawn\|resource\|limit" 至少 30 行
- 后端参考: `dify-plugin-daemon` Go 仓库（独立 repo）— 仅查看资源限制相关 Go cgroups 调用作为概念参考（**不拷代码**）
- 后端参考: `api/core/plugin/manager.py` (plugin 生命周期 — fork / spawn / kill 模式)

借鉴重点（reading doc 必含）:
1. Dify 采用 Go + cgroups 直写 — Python 对应方案是 resource.setrlimit + preexec_fn
2. Dify plugin spawn 是同步还是异步？我们用 asyncio.loop.subprocess_exec 包装 preexec_fn
3. Dify 是否处理 fork bomb？我们用 RLIMIT_NPROC + setsid 进程组隔离
4. Dify 跨平台支持？我们 macOS dev + Linux prod 双轨（macOS 弱 enforcement 文档化）
5. Dify env 注入策略？对照本 plan strip-all + manifest allowlist 默认安全

License: Dify AGPL-3.0 + Go 实现 vs agent-builder Apache-2.0 + Python — 严禁拷代码，仅借鉴设计模式与字段命名。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify reading doc（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05b-02-resource-runner-2026-05-17.md</files>
  <action>
    阅读以下 Dify 文件并写阅读笔记（**先 commit 此 doc 才能进 Task 1**）:

    1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — plugin spawn 入口（grep "subprocess\|spawn\|Popen\|create_subprocess" 至少 30 行上下文）
    2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` — plugin 生命周期 fork/kill（grep "kill\|terminate\|preexec\|setsid" 至少 30 行）
    3. （可选）web 端 plugin sandbox UI: `/Users/admin/ai/ref/dify/repo/web/app/components/plugins/` — 资源用量展示视角（与本 plan 后端无关，但可了解最终 UX）

    文档结构按 CLAUDE.md §2.7 模板:
    ```
    # Dify 阅读笔记 — Plan 05b-02 SandboxRunner Protocol + PosixResourceSandbox
    > 日期: 2026-05-17
    > 仓库: https://github.com/langgenius/dify (commit ${LOCAL_HEAD}, /Users/admin/ai/ref/dify/repo/)
    > 同时参考: dify-plugin-daemon Go 仓库（仅概念，不拷代码）

    ## 项目概述（一句话）
    ## 技术栈对照（Dify Go + cgroups vs 本项目 Python + resource.setrlimit）
    ## 架构要点（plugin spawn 链路简图 / preexec_fn 注入点）
    ## 可借鉴的设计模式（4-6 条，每条 [Dify 路径:行号] + Python 实现思路）
    ## 与本项目的关系（Phase 5.B PosixResourceSandbox 字段命名 + RLIMIT 选型 + 默认值如何对齐 / 偏离）
    ## License 与 attribution（Dify AGPL-3.0 + Go vs Apache-2.0 + Python — 100% 独立创作）
    ```

    最少 80 行；commit message: `docs(05b-02): add Dify resource runner reading doc`。
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-02-resource-runner-2026-05-17.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-02-resource-runner-2026-05-17.md | awk '{exit ($1>=80)?0:1}'</automated>
  </verify>
  <done>reading doc 文件存在；≥ 80 行；git log 显示本 doc commit 在 Task 1 之前。</done>
</task>

<task type="auto">
  <name>Task 1: SandboxRunner Protocol + PosixResourceSandbox + 异常占位</name>
  <files>
    backend/app/agent_builder/platforms/sandbox/runner.py
    backend/app/agent_builder/platforms/exceptions.py
    backend/pyproject.toml
  </files>
  <action>
    1. **扩展 `backend/app/agent_builder/platforms/exceptions.py`** — 加 2 个异常类（**仅占位定义**，Wave 3 / Plan 03 才真 raise）:
       ```python
       class SandboxLimitExceeded(Exception):
           """sandbox 资源超限（CPU/memory）— watchdog 检测时 raise（Wave 3）。"""
           pass

       class NetworkBlockedError(Exception):
           """非白名单 host 出站 — AllowlistTransport raise（Plan 05b-03）。"""
           pass
       ```
       同时在 `__all__` list 加这两个名字。

    2. **创建 `backend/app/agent_builder/platforms/sandbox/runner.py`**:

       ```python
       """SandboxRunner Protocol + PosixResourceSandbox（PLUG-FW-09）。

       设计要点（RESEARCH §Pattern 1 + Pitfall 1/4 + reading doc 借鉴点）:
       - SandboxRunner Protocol 让 Wave 3 watchdog 与 Plan 05 cgroups 通过同一接口注入
       - PosixResourceSandbox 用 asyncio loop.subprocess_exec + preexec_fn 注入 4 类 RLIMIT
       - os.setsid() 让 daemon 成为新进程组 leader（Pitfall 4 fork bomb / kill 整组）
       - macOS RLIMIT_AS/CPU 弱 enforcement — Linux CI 才跑真实限制（Pitfall 1）

       License: 100% 独立创作，借鉴 Dify Go 实现的设计概念（AGPL-3.0 不拷代码）。
       """
       from __future__ import annotations
       import asyncio
       import logging
       import os
       import resource
       import subprocess
       from functools import partial
       from typing import Protocol, runtime_checkable

       _log = logging.getLogger(__name__)

       _DEFAULT_NPROC_LIMIT = 16    # daemon 不能 fork 超 16 子进程
       _DEFAULT_NOFILE_LIMIT = 256  # daemon 文件描述符上限


       def _apply_posix_limits(cpu_seconds: int, memory_bytes: int) -> None:
           """preexec_fn — fork 后 / exec 前在子进程上下文跑。

           必须无阻塞 + 无 async（fork 后 event loop 不可用）。
           macOS RLIMIT_AS/CPU 弱 enforcement（Pitfall 1）；Linux 严格。
           """
           # RLIMIT_CPU: 累积 CPU 秒数 — Linux 严格（超 SIGXCPU）/ macOS 弱
           resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
           # RLIMIT_AS: 虚拟内存上限 — Linux 严格 / macOS advisory
           resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
           # RLIMIT_NPROC: 子进程数（防 fork bomb）— cross-platform 严格
           resource.setrlimit(resource.RLIMIT_NPROC, (_DEFAULT_NPROC_LIMIT, _DEFAULT_NPROC_LIMIT))
           # RLIMIT_NOFILE: 文件描述符上限（防句柄泄漏）— cross-platform 严格
           resource.setrlimit(resource.RLIMIT_NOFILE, (_DEFAULT_NOFILE_LIMIT, _DEFAULT_NOFILE_LIMIT))
           # 新进程组 leader — 让 SIGTERM 能 killpg 整棵进程树（Pitfall 4）
           os.setsid()


       @runtime_checkable
       class SandboxRunner(Protocol):
           """统一沙箱 spawn 接口 — PosixResourceSandbox / CgroupsV2Sandbox 共实现。"""

           async def spawn_with_limits(
               self,
               cmd: list[str],
               *,
               cpu_seconds: int,
               memory_bytes: int,
               env: dict[str, str] | None = None,
               cwd: str | None = None,
           ) -> asyncio.subprocess.Process: ...


       class PosixResourceSandbox:
           """resource.setrlimit baseline — cross-platform（macOS dev + Linux prod）。

           实现要点:
           - asyncio loop.subprocess_exec 直接接收 preexec_fn（async_create_subprocess_exec 不接受）
           - SubprocessStreamProtocol + Process wrapper 让返回值与 5.A daemon_client API 一致
           - close_fds=True 防 fd 从父进程泄漏

           macOS dev: contract test only（API 不抛 + 默认值正确）
           Linux CI: enforcement test（真 OOM / SIGXCPU）
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
               loop = asyncio.get_event_loop()
               merged_env = dict(os.environ) if env is None else dict(env)
               # 注：env 默认 merge os.environ 是为了让 cross-platform smoke test 简单
               # 真正的 env_allowlist 过滤在 Wave 3 daemon_client._build_filtered_env 做

               preexec = partial(_apply_posix_limits, cpu_seconds, memory_bytes)

               transport, protocol = await loop.subprocess_exec(
                   asyncio.subprocess.SubprocessStreamProtocol,
                   *cmd,
                   stdin=subprocess.PIPE,
                   stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE,
                   env=merged_env,
                   cwd=cwd,
                   preexec_fn=preexec,
                   close_fds=True,
               )
               proc = asyncio.subprocess.Process(transport, protocol, loop)
               _log.info(
                   "sandbox.spawned pid=%s cpu_seconds=%d memory_bytes=%d cmd=%s",
                   proc.pid, cpu_seconds, memory_bytes, cmd[:2],
               )
               return proc


       __all__ = ["SandboxRunner", "PosixResourceSandbox", "_apply_posix_limits"]
       ```

    3. **`backend/pyproject.toml` 加 pytest markers**:
       在 `[tool.pytest.ini_options]` 段（若不存在则新建）加:
       ```toml
       markers = [
           "linux_only: 仅 Linux 跑（macOS skipped — RLIMIT 弱 enforcement, Pitfall 1）",
           "sandbox_integration: Phase 5.B sandbox 集成测试（spawn 真子进程）",
           "cgroups_v2: cgroups v2 测试（需 systemd-run + cgroup v2 内核）",
       ]
       ```
       如果该段已有 markers 列表则 append 不要覆盖。

    **避坑**:
    - `loop.subprocess_exec` 返回 `(transport, protocol)` tuple 必须 unpack 后用 `Process(transport, protocol, loop)` 包装（不能直接 `await loop.subprocess_exec()` 取 Process）
    - `preexec_fn` 是 POSIX only — 但本项目仅 Linux/macOS（CLAUDE.md §3 锁定）— 安全
    - 不要在 `_apply_posix_limits` 里加 logging（fork 后 logger handler fd 状态不确定，可能死锁）
    - `os.setsid()` 必须放最后（前面 setrlimit 失败 raise 会被 preexec_fn 上传到 OSError, asyncio 报错；setsid 后任何错误都难以传回）
    - 不要默认 `env={}` 而 merge `os.environ`（一致 — 让 contract test 不爆 PATH 找不到 python3）
    - SandboxLimitExceeded / NetworkBlockedError 不要在本 plan 真 raise — 仅占位定义（Wave 3 / Plan 03 才用）

    commit messages（拆 3 个 commit）:
    - `feat(05b-02): add SandboxLimitExceeded + NetworkBlockedError placeholders`
    - `feat(05b-02): add SandboxRunner Protocol + PosixResourceSandbox (PLUG-FW-09)`
    - `chore(05b-02): add pytest markers linux_only/sandbox_integration/cgroups_v2`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "from app.agent_builder.platforms.sandbox.runner import SandboxRunner, PosixResourceSandbox; from app.agent_builder.platforms.exceptions import SandboxLimitExceeded, NetworkBlockedError; assert isinstance(PosixResourceSandbox(), SandboxRunner), 'PosixResourceSandbox must satisfy SandboxRunner Protocol'"</automated>
  </verify>
  <done>SandboxRunner Protocol 可 runtime_checkable; PosixResourceSandbox 实例满足 Protocol; 2 个异常类已定义且 exceptions __all__ 含；pyproject.toml 含 linux_only/sandbox_integration/cgroups_v2 markers。</done>
</task>

<task type="auto">
  <name>Task 2: 单元测试 contract + 集成测 Linux-only enforcement</name>
  <files>
    backend/tests/platforms/sandbox/test_runner.py
    backend/tests/platforms_integration/test_resource_limits.py
    backend/tests/platforms_integration/fixtures/__init__.py
    backend/tests/platforms_integration/fixtures/memory_hog_daemon.py
  </files>
  <action>
    1. **单元测试 `backend/tests/platforms/sandbox/test_runner.py`**（macOS + Linux 都跑，contract test，≥ 8 测）:

       - `test_sandbox_runner_is_protocol`: `from typing import Protocol`; assert SandboxRunner in PosixResourceSandbox.__mro__ if runtime_checkable ELSE isinstance(PosixResourceSandbox(), SandboxRunner)
       - `test_posix_sandbox_spawn_returns_process`: 起 `python -c 'print("ok")'` 子进程 → assert isinstance(proc, asyncio.subprocess.Process) + await proc.communicate() == (b"ok\n", b"")
       - `test_posix_sandbox_stdin_pipe_works`: 起 `python -c 'import sys; print(sys.stdin.read())'` → proc.stdin.write(b"hello\n") + close stdin → await communicate() 含 "hello"
       - `test_posix_sandbox_env_injection`: 起 `python -c 'import os; print(os.environ.get("FOO"))'` env={"FOO": "bar"} → 输出含 "bar"
       - `test_posix_sandbox_cwd_set`: 起 `python -c 'import os; print(os.getcwd())'` cwd="/tmp" → 输出 "/tmp"
       - `test_posix_sandbox_setsid_new_session`: 起 `python -c 'import os; print(os.getpid()==os.getsid(0))'` → 输出 "True"（setsid 后 sid == pid）
       - `test_posix_sandbox_close_fds_no_leak`: 起 `python -c 'import os; print(len(os.listdir("/proc/self/fd")) if os.path.exists("/proc/self/fd") else 3)'` → assert 输出整数 ≤ 6（stdin/stdout/stderr + 少量 internal — Linux only check）；macOS 时断言 `os.listdir 不存在` 走兜底 == 3
       - `test_posix_sandbox_rlimit_nproc_set`: 起 `python -c 'import resource; print(resource.getrlimit(resource.RLIMIT_NPROC))'` → 输出包含 "(16, 16)"（cross-platform 严格）

       所有测试都用 `@pytest.mark.asyncio` + 用临时事件循环，确保 cleanup。

    2. **集成测 fixture `backend/tests/platforms_integration/fixtures/__init__.py`** 空文件（pytest package marker）

    3. **集成测 fixture `backend/tests/platforms_integration/fixtures/memory_hog_daemon.py`** — 一个会尝试 alloc 200MB 的 daemon entrypoint:
       ```python
       """fixture daemon — 启动后立即尝试 alloc 大块内存触发 RLIMIT_AS（Plan 05b-02 集成测用）."""
       import sys
       def main() -> int:
           try:
               x = b'a' * (200 * 1024 * 1024)  # 200MB
               print("alloc_ok", flush=True)
               return 0
           except MemoryError:
               print("alloc_failed_memory_error", flush=True)
               return 1
           except Exception as e:
               print(f"alloc_failed_other:{type(e).__name__}", flush=True)
               return 2

       if __name__ == "__main__":
           sys.exit(main())
       ```

    4. **集成测 `backend/tests/platforms_integration/test_resource_limits.py`**（Linux only，≥ 5 测）:

       ```python
       import asyncio
       import signal
       import sys
       import pytest

       from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox

       pytestmark = [
           pytest.mark.asyncio,
           pytest.mark.linux_only,
           pytest.mark.sandbox_integration,
           pytest.mark.skipif(
               sys.platform == "darwin",
               reason="macOS RLIMIT_AS/CPU 弱 enforcement — Pitfall 1，仅 Linux CI 跑严格 enforcement",
           ),
       ]

       async def test_rlimit_as_enforces_memory_cap() -> None:
           """Linux: 子进程 alloc 200MB 超 100MB RLIMIT_AS → 必失败."""
           sandbox = PosixResourceSandbox()
           proc = await sandbox.spawn_with_limits(
               [sys.executable, "-u", "-m", "tests.platforms_integration.fixtures.memory_hog_daemon"],
               cpu_seconds=10,
               memory_bytes=100 * 1024 * 1024,
           )
           await asyncio.wait_for(proc.wait(), timeout=5.0)
           assert proc.returncode != 0, f"200MB alloc 应超 100MB limit；returncode={proc.returncode}"

       async def test_rlimit_cpu_triggers_sigxcpu() -> None:
           """RLIMIT_CPU 1s + busy loop → returncode 负值（信号杀）."""
           sandbox = PosixResourceSandbox()
           proc = await sandbox.spawn_with_limits(
               [sys.executable, "-u", "-c", "while True: pass"],
               cpu_seconds=1,
               memory_bytes=100 * 1024 * 1024,
           )
           await asyncio.wait_for(proc.wait(), timeout=10.0)
           # Linux SIGXCPU = 24; returncode = -24 或 -SIGKILL = -9
           assert proc.returncode is not None and proc.returncode < 0, \
               f"busy loop 超 RLIMIT_CPU 1s 应被信号杀；returncode={proc.returncode}"

       async def test_rlimit_nproc_blocks_fork_bomb() -> None:
           """RLIMIT_NPROC=16: subprocess 内 fork 超 16 应失败."""
           # 用 daemon 内 os.fork() 循环测；用 Popen 起多个 sleep 子进程也行
           code = (
               "import subprocess, sys\n"
               "children = []\n"
               "for i in range(50):\n"
               "    try:\n"
               "        children.append(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']))\n"
               "    except (BlockingIOError, OSError) as e:\n"
               "        print(f'failed_at_{i}:{e}', flush=True)\n"
               "        break\n"
               "print(f'spawned_{len(children)}', flush=True)\n"
           )
           sandbox = PosixResourceSandbox()
           proc = await sandbox.spawn_with_limits(
               [sys.executable, "-u", "-c", code],
               cpu_seconds=5,
               memory_bytes=200 * 1024 * 1024,
           )
           stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
           out = stdout.decode()
           assert "failed_at_" in out, f"NPROC=16 应在 16-20 次 fork 后失败；out={out}"

       async def test_setsid_pgid_equals_pid() -> None:
           """setsid 后 daemon 的 pgid 应等于 pid（验证 Pitfall 4 修复）."""
           sandbox = PosixResourceSandbox()
           proc = await sandbox.spawn_with_limits(
               [sys.executable, "-u", "-c", "import os; print(os.getpid()==os.getpgid(0), flush=True)"],
               cpu_seconds=5,
               memory_bytes=50 * 1024 * 1024,
           )
           stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
           assert stdout.decode().strip() == "True", f"daemon pgid 应等于 pid (setsid)；stdout={stdout}"

       async def test_smoke_normal_daemon_works() -> None:
           """smoke: 资源限制下 normal daemon 仍能正常通信 stdout."""
           sandbox = PosixResourceSandbox()
           proc = await sandbox.spawn_with_limits(
               [sys.executable, "-u", "-c", "print('hello sandbox', flush=True)"],
               cpu_seconds=5,
               memory_bytes=50 * 1024 * 1024,
           )
           stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
           assert stdout == b"hello sandbox\n"
       ```

    5. **5.A regression**:
       - 运行 `pytest backend/tests/platforms/ -x` 5.A 162 测试 0 fail
       - 运行 `pytest backend/tests/platforms_integration/ -x` 5.A 5/5 acid test 0 fail（本 plan 未修改 daemon_client.py，should be safe）

    避坑:
    - macOS local 跑 `pytest backend/tests/platforms_integration/test_resource_limits.py -v` 应全 skip（output 含 "5 skipped"）—— 不能 fail
    - Linux CI 真跑时 `test_rlimit_cpu_triggers_sigxcpu` 可能因 OS 调度差异返回 -SIGKILL 而非 -SIGXCPU —— 断言 `< 0` 即可
    - `cwd=` 用 backend/ 让 `tests.platforms_integration.fixtures.memory_hog_daemon` 可 import — 但用 `-m` flag 时 cwd 必须在 backend/ 下

    commit messages:
    - `test(05b-02): add PosixResourceSandbox contract unit tests (≥ 8)`
    - `test(05b-02): add Linux-only resource limit enforcement integration tests`
    - `test(05b-02): add memory_hog_daemon fixture for RLIMIT_AS testing`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/sandbox/test_runner.py -v 2>&1 | tail -15</automated>
  </verify>
  <done>
    contract test ≥ 8 全 pass（macOS + Linux）；Linux-only test 在 macOS 全 skip（不 fail）；fixture daemon 可被 -m flag import；5.A 162 platforms + 5/5 acid test 0 regression。
  </done>
</task>

</tasks>

<verification>
**phase-local checks**:
- `pytest backend/tests/platforms/sandbox/test_runner.py -v` 8+ contract test 全绿
- macOS: `pytest backend/tests/platforms_integration/test_resource_limits.py -v` 输出含 "skipped"（Pitfall 1 验证）
- Linux CI (GitHub Actions ubuntu-latest): `pytest -m linux_only backend/tests/platforms_integration/test_resource_limits.py -v` 5+ 全绿

**5.A regression**:
- `pytest backend/tests/platforms/ -x` 0 fail（5.A 162 测试）
- `pytest backend/tests/platforms_integration/ -x` 0 fail（5.A 5/5 acid test）

**Phase 4 regression**:
- `pytest backend/tests/notification/ -x` Phase 4 81 IM 0 regression

**reading doc gate**:
- `git log --oneline -10 | head` docs(05b-02) commit 早于任何 feat(05b-02) commit
</verification>

<success_criteria>
1. **抽象层完整**: SandboxRunner Protocol runtime_checkable + PosixResourceSandbox 满足
2. **4 类 RLIMIT 全部注入**: CPU / AS / NPROC (16) / NOFILE (256)
3. **setsid 进程组隔离**: 集成测显式断言 pgid == pid（Pitfall 4 防护）
4. **macOS dev contract test 全绿**: 不依赖 enforcement，验 API 正确性
5. **Linux CI enforcement test**: RLIMIT_AS 真 OOM / RLIMIT_NPROC 真阻 fork bomb
6. **异常占位定义**: SandboxLimitExceeded + NetworkBlockedError（不真 raise，给 Wave 3 / Plan 03 用）
7. **5.A regression**: 162 platforms + 5/5 acid test + 81 IM 0 regression
8. **reading doc gate**: docs commit 早于 feat commit（CLAUDE.md §2.7）
</success_criteria>

<output>
After completion, create `.planning/phases/05b-plugin-sandbox/05b-02-SUMMARY.md` 含:
- Dify 借鉴点（Go cgroups → Python resource.setrlimit 的映射 + 字段命名对齐）
- 4 类 RLIMIT 选型理由（为何选 NPROC=16 / NOFILE=256）
- macOS vs Linux enforcement 行为对照表
- Wave 3 plans 接入点（_choose_runner 在 daemon_client.py 修改时引用 PosixResourceSandbox）
</output>
</content>
</invoke>