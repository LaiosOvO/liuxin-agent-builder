---
phase: 05b-plugin-sandbox
plan: 04
type: execute
wave: 3
depends_on:
  - "05b-02"
  - "05b-03"
files_modified:
  - docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-17.md
  - backend/app/agent_builder/platforms/sandbox/watchdog.py
  - backend/app/agent_builder/platforms/sandbox/idle_reaper.py
  - backend/app/agent_builder/platforms/sandbox/__init__.py
  - backend/app/agent_builder/platforms/daemon_client.py
  - backend/tests/platforms/sandbox/test_watchdog.py
  - backend/tests/platforms/sandbox/test_idle_reaper.py
  - backend/tests/platforms_integration/test_watchdog_grace_period.py
  - backend/tests/platforms_integration/test_idle_reaper.py
  - backend/tests/platforms_integration/fixtures/sigterm_ignoring_daemon.py
  - backend/tests/platforms/test_daemon_client.py
autonomous: true
requirements:
  - PLUG-FW-12

must_haves:
  truths:
    - "SandboxWatchdog 独立 asyncio task — 每 5s 读 /proc/<pid>/status VmRSS（Linux）或 psutil fallback（macOS）"
    - "RSS 超 memory_limit_bytes → on_violation callback → killpg(SIGTERM) → 等 3s grace → 仍存活 killpg(SIGKILL)"
    - "Watchdog on_violation 集成 daemon._fail_all_pending(SandboxLimitExceeded)（Pitfall 5 避免 error 类型竞态）"
    - "IdleDaemonReaper 独立 asyncio task — 每 60s 扫所有 active daemon，last_invoke_at > timeout_idle 调 daemon.close()"
    - "last_invoke_at 在 invoke() finally 块更新（Pitfall 6 避免 reaper 与 active invoke 竞争）"
    - "PlatformDaemonClient 构造接受 sandbox_config 可选参数；start() 时走 SandboxRunner.spawn_with_limits + 起 watchdog"
    - "_build_filtered_env strip 全部环境变量，仅留 PATH/HOME/LANG/TZ + manifest env_allowlist（Pitfall 8 防 secret 泄漏）"
    - "AGENT_BUILDER_* / INTERNAL_* / HMAC_SECRET / DATABASE_URL 前缀变量永远 strip（不允许 env_allowlist override）"
    - "5.A daemon_client 既有 11 测试 + 5/5 acid test 0 regression（sandbox_config 默认 None 时走 5.A 路径）"
    - "Dify 阅读文档先于代码 commit（CLAUDE.md §2.7 硬性 gate）"
  artifacts:
    - path: "docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-17.md"
      provides: "Dify plugin lifecycle / watchdog / idle reap 借鉴点"
      min_lines: 80
    - path: "backend/app/agent_builder/platforms/sandbox/watchdog.py"
      provides: "SandboxWatchdog asyncio task + SIGTERM grace 3s → SIGKILL（Pitfall 4/5）"
      contains: "class SandboxWatchdog"
    - path: "backend/app/agent_builder/platforms/sandbox/idle_reaper.py"
      provides: "IdleDaemonReaper 60s 扫 + 300s timeout auto-close"
      contains: "class IdleDaemonReaper"
    - path: "backend/app/agent_builder/platforms/daemon_client.py"
      provides: "5.A daemon_client.py 扩展 — sandbox_config 注入 + _choose_runner + _build_filtered_env + last_invoke_at + watchdog 集成"
      contains: "_build_filtered_env"
    - path: "backend/tests/platforms_integration/test_watchdog_grace_period.py"
      provides: "watchdog SIGTERM grace → SIGKILL 集成测（Linux only）"
    - path: "backend/tests/platforms_integration/fixtures/sigterm_ignoring_daemon.py"
      provides: "测试 daemon 故意忽略 SIGTERM 验证 grace → SIGKILL 路径"
  key_links:
    - from: "backend/app/agent_builder/platforms/sandbox/watchdog.py"
      to: "backend/app/agent_builder/platforms/exceptions.py"
      via: "on_violation callback raise SandboxLimitExceeded（Plan 05b-02 已定义）"
      pattern: "SandboxLimitExceeded"
    - from: "backend/app/agent_builder/platforms/daemon_client.py"
      to: "backend/app/agent_builder/platforms/sandbox/runner.py"
      via: "_choose_runner 返回 PosixResourceSandbox 实例；spawn_with_limits 替代 asyncio.create_subprocess_exec"
      pattern: "PosixResourceSandbox\\(\\)"
    - from: "backend/app/agent_builder/platforms/daemon_client.py"
      to: "backend/app/agent_builder/platforms/sandbox/watchdog.py"
      via: "start() 内 self._watchdog = SandboxWatchdog(...).start()"
      pattern: "SandboxWatchdog\\("
---

<objective>
完成三层超时强杀防护的 Wave 3 集成 —— 实现 `SandboxWatchdog`（每 5s 扫 RSS / cgroup memory.current；超限走 SIGTERM 3s grace → SIGKILL）+ `IdleDaemonReaper`（每 60s 扫 last_invoke_at；> 300s 自动 close）+ `PlatformDaemonClient` 集成（sandbox_config 注入、_choose_runner、_build_filtered_env strip-all-allowlist、last_invoke_at finally 块更新、watchdog spawn/stop 生命周期）。

Purpose: 这是 Phase 5.B 的核心集成 plan — 把 Wave 2 已就绪的 PosixResourceSandbox + AllowlistTransport 真正接入 5.A daemon_client，让 manifest sandbox 段从"声明"变成"生效"。同时实现 strip-all env allowlist（Pitfall 8 secret 防泄漏）。

Output: 1 个 Dify reading doc + watchdog.py + idle_reaper.py + daemon_client.py 扩展（保留 5.A 11 测试 + 5/5 acid test 0 regression）+ 单元测试 + Linux-only 集成测试（grace period 真行为验证）+ 5.A daemon_client 测试扩展（sandbox_config 默认 None 路径）。
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
@.planning/phases/05b-plugin-sandbox/05b-03-PLAN.md
@backend/app/agent_builder/platforms/daemon_client.py
@backend/app/agent_builder/platforms/sandbox/runner.py
@backend/app/agent_builder/platforms/sandbox/network.py
@backend/app/agent_builder/platforms/manifest.py
@backend/app/agent_builder/platforms/exceptions.py
@backend/tests/platforms/test_daemon_client.py
@CLAUDE.md

<interfaces>
From backend/app/agent_builder/platforms/sandbox/watchdog.py（本 plan 创建）:
```python
from typing import Callable

class SandboxWatchdog:
    def __init__(
        self,
        pid: int,
        memory_limit_bytes: int,
        on_violation: Callable[[str], None] | None = None,
        *,
        scan_interval: float = 5.0,
        grace_period: float = 3.0,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
```

From backend/app/agent_builder/platforms/sandbox/idle_reaper.py（本 plan 创建）:
```python
from typing import Callable

class IdleDaemonReaper:
    def __init__(
        self,
        get_daemons: Callable[[], list["PlatformDaemonClient"]],
        timeout_idle: float = 300.0,
        scan_interval: float = 60.0,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
```

From backend/app/agent_builder/platforms/daemon_client.py（5.A 已有 460 行，本 plan 扩展）:
```python
# 新加 __init__ 参数:
class PlatformDaemonClient:
    def __init__(
        self,
        module_entry: str,
        env: dict[str, str] | None = None,
        invoke_timeout: float = _DEFAULT_INVOKE_TIMEOUT,
        cwd: str | None = None,
        sandbox_config: SandboxConfig | None = None,  # NEW Wave 3
        sandbox_runner: SandboxRunner | None = None,  # NEW Wave 3 — injectable for testing
    ) -> None: ...

    last_invoke_at: float  # NEW Wave 3 — reaper 读

    def _choose_runner(self) -> SandboxRunner: ...  # NEW Wave 3
    def _build_filtered_env(self) -> dict[str, str]: ...  # NEW Wave 3 — strip-all-allowlist
```

5.A 兼容性约束:
- sandbox_config=None 时 → 走 5.A 老路径（asyncio.create_subprocess_exec 直接 spawn，无 watchdog）
- 5.A 11 个 test_daemon_client.py 测试不传 sandbox_config → 0 regression
- 5.A 5/5 acid test 不传 sandbox_config → 0 regression
</interfaces>
</context>

<reference>
Dify 模块映射（CLAUDE.md §2.7）:
- 后端必读: `api/services/plugin/plugin_service.py` （plugin lifecycle / kill / cleanup — grep "watchdog|monitor|kill|terminate|cleanup|reap" 至少 30 行）
- 后端必读: `api/core/plugin/manager.py` （plugin 进程管理 / idle close 策略）
- 后端参考: dify-plugin-daemon Go 仓库 watchdog 思路（仅概念）

借鉴重点（reading doc 必含）:
1. Dify daemon 是否有 watchdog 监控资源使用？什么周期（5s / 30s / 60s）
2. Dify 是否有 idle plugin 自动关闭机制？timeout 默认值
3. SIGTERM grace 时间（systemd 默认 3s / docker 默认 10s）
4. 进程组 kill (killpg) vs 单进程 kill 选型理由（Pitfall 4 fork bomb）
5. /proc/<pid>/status VmRSS vs psutil.memory_info() 跨平台选型

License: Dify AGPL-3.0 不拷代码；borrowed 设计概念允许（grace period 数值 / scan interval 选型）。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify reading doc（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-17.md</files>
  <action>
    阅读以下 Dify 文件并写阅读笔记（先 commit 此 doc 才能进 Task 1）:

    1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — grep "watchdog|monitor|kill|terminate|cleanup|reap|idle" 至少 30 行
    2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` — grep 同上 + "lifecycle|spawn|close" 至少 30 行
    3. （可选）systemd man pages KillSignal / TimeoutStopSec 默认值（资料参考；不需 Read 工具）

    文档结构按 CLAUDE.md §2.7 模板:
    - 项目概述
    - 技术栈对照（Dify 进程管理策略 vs 本项目 asyncio task watchdog）
    - 架构要点（三层防护层级：invoke timeout / watchdog grace / idle reap）
    - 可借鉴设计模式 4-6 条（grace 时间 / scan 频率 / kill 进程组 vs 单进程）
    - 与本项目关系（Pitfall 4 进程组 / Pitfall 5 error 竞态 / Pitfall 6 active invoke 竞争）
    - License attribution

    最少 80 行；commit message: `docs(05b-04): add Dify watchdog/idle reaper reading doc`。
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-17.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-17.md | awk '{exit ($1>=80)?0:1}'</automated>
  </verify>
  <done>reading doc 文件存在；≥ 80 行；git log 显示本 doc commit 在 Task 1 之前。</done>
</task>

<task type="auto">
  <name>Task 1: SandboxWatchdog + IdleDaemonReaper（独立模块，Pitfall 4/5/6 防护）</name>
  <files>
    backend/app/agent_builder/platforms/sandbox/watchdog.py
    backend/app/agent_builder/platforms/sandbox/idle_reaper.py
    backend/app/agent_builder/platforms/sandbox/__init__.py
  </files>
  <action>
    1. 创建 `backend/app/agent_builder/platforms/sandbox/watchdog.py`:

    完整实现（按 RESEARCH §Pattern 4）:
    - `SandboxWatchdog.__init__` 接受 pid + memory_limit_bytes + on_violation callback + scan_interval (默认 5.0) + grace_period (默认 3.0)
    - `start()` 起 asyncio.create_task(self._loop(), name=f"sandbox-watchdog[pid={pid}]")
    - `_loop()` 每 scan_interval 秒读 RSS:
      - Linux: `Path(f"/proc/{pid}/status").read_text()` parse VmRSS 行
      - macOS / fallback: try import psutil 用 `psutil.Process(pid).memory_info().rss`
      - 进程已死: read_rss 返回 None → loop 自然 return
    - 超 memory_limit_bytes:
      1. 先调 on_violation(reason) callback（让 daemon_client._fail_all_pending(SandboxLimitExceeded) — Pitfall 5）
      2. `os.killpg(os.getpgid(pid), signal.SIGTERM)`（Pitfall 4 整组 kill）
      3. `await asyncio.sleep(grace_period)`
      4. `os.kill(pid, 0)` 探活；ProcessLookupError → 优雅退出 return
      5. `os.killpg(os.getpgid(pid), signal.SIGKILL)` 强杀
    - `stop()` 设 _stopped=True + task.cancel()
    - structured log: `sandbox.limit_exceeded` / `sandbox.force_kill` 用 logger.warning extra=dict(...)

    避坑（Pitfall 4/5）:
    - 必须 `os.killpg(os.getpgid(pid), sig)` 不是 `os.kill(pid, sig)`（防 fork 子进程逃逸）
    - on_violation callback **先于** SIGTERM 发送（让主 invoke 立刻 raise SandboxLimitExceeded 不依赖 race condition）
    - `_read_rss` 失败 swallow 不 raise（避免 watchdog task crash 误杀整个主进程）
    - asyncio task name 必须含 pid（debugging 多 daemon 场景）
    - 不要 watchdog 频率 < 1s（RESEARCH §Anti-Patterns 100 daemon 场景 CPU 占用）

    2. 创建 `backend/app/agent_builder/platforms/sandbox/idle_reaper.py`:

    完整实现（按 RESEARCH §Pattern 5）:
    - `IdleDaemonReaper.__init__` 接受 get_daemons callable + timeout_idle (默认 300) + scan_interval (默认 60)
    - `_loop()` while not _stopped:
      - `now = time.monotonic()`（Pitfall 6 不能用 time.time wall clock）
      - for daemon in get_daemons():
        - `last = getattr(daemon, "last_invoke_at", None)`
        - 跳过 `daemon._proc is None`（未启动）或 `daemon._pending`（活跃 invoke — Pitfall 6 防竞争）
        - `if last is not None and now - last > timeout_idle`: 
          - structured log `sandbox.idle_reaped` daemon name + idle_secs
          - try `await daemon.close()` 不阻塞主进程；except 记 warning
      - await asyncio.sleep(scan_interval)
    - `start()` / `stop()` 同 watchdog

    避坑（Pitfall 6）:
    - 必须 `time.monotonic()` 不能 `time.time()`（NTP 误判）
    - 跳过 `daemon._pending` 长度 > 0（活跃 invoke 不算 idle）
    - `daemon._proc` 用 5.A 已有属性（不能改 5.A 字段）
    - close 失败 swallow 不 raise（reaper 不能因单 daemon 死亡而停）

    3. 更新 `backend/app/agent_builder/platforms/sandbox/__init__.py` 导出新类:
    ```python
    """Phase 5.B sandbox runtime: resource limits / network allowlist / watchdog / cgroups."""
    from .runner import SandboxRunner, PosixResourceSandbox
    from .network import AllowlistTransport, make_sandboxed_http_client
    from .watchdog import SandboxWatchdog
    from .idle_reaper import IdleDaemonReaper
    from .parser import parse_memory, parse_cpu_seconds

    __all__ = [
        "SandboxRunner", "PosixResourceSandbox",
        "AllowlistTransport", "make_sandboxed_http_client",
        "SandboxWatchdog", "IdleDaemonReaper",
        "parse_memory", "parse_cpu_seconds",
    ]
    ```

    commit messages:
    - `feat(05b-04): add SandboxWatchdog (SIGTERM grace 3s → SIGKILL, Pitfall 4/5)`
    - `feat(05b-04): add IdleDaemonReaper (300s timeout, Pitfall 6 active invoke skip)`
    - `chore(05b-04): export sandbox runtime classes from __init__`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "from app.agent_builder.platforms.sandbox import SandboxWatchdog, IdleDaemonReaper; w = SandboxWatchdog(pid=99999, memory_limit_bytes=1024**3); assert w._scan_interval == 5.0; assert w._grace_period == 3.0; r = IdleDaemonReaper(get_daemons=lambda: []); assert r._timeout_idle == 300.0"</automated>
  </verify>
  <done>SandboxWatchdog + IdleDaemonReaper 类已定义；默认值 5s / 3s / 300s / 60s 正确；__init__ 导出。</done>
</task>

<task type="auto">
  <name>Task 2: PlatformDaemonClient 集成 sandbox runner + env_allowlist + watchdog 生命周期</name>
  <files>
    backend/app/agent_builder/platforms/daemon_client.py
    backend/tests/platforms/test_daemon_client.py
  </files>
  <action>
    1. 修改 `backend/app/agent_builder/platforms/daemon_client.py`（5.A 460 行 → 5.B 扩展约 80 行）:

    **`__init__` 新增参数**:
    - `sandbox_config: SandboxConfig | None = None`
    - `sandbox_runner: SandboxRunner | None = None`（injectable for testing）
    - 设置 `self._sandbox_config = sandbox_config`
    - 设置 `self._sandbox_runner = sandbox_runner`（None 表示未启用沙箱）
    - 设置 `self._watchdog: SandboxWatchdog | None = None`
    - 设置 `self.last_invoke_at: float = 0.0`（reaper 读，public 属性）

    **`_choose_runner` 方法**:
    ```python
    def _choose_runner(self) -> SandboxRunner:
        """自动选择 runner — Plan 05 提供 cgroups detection 时升级."""
        if self._sandbox_runner is not None:
            return self._sandbox_runner  # injected
        # use_cgroups + Linux + cgroups available → Plan 05 加 CgroupsV2Sandbox 分支
        # 本 plan 仅 PosixResourceSandbox baseline
        return PosixResourceSandbox()
    ```

    **`_build_filtered_env` 方法（Pitfall 8 防 secret 泄漏）**:
    ```python
    _SAFE_BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "PYTHONPATH", "PYTHONUNBUFFERED")
    _FORBIDDEN_PREFIXES = ("AGENT_BUILDER_", "INTERNAL_", "HMAC_", "DATABASE_", "REDIS_", "SMTP_")
    _FORBIDDEN_EXACT = ("HMAC_SECRET", "DATABASE_URL", "REDIS_URL", "OPENAI_API_KEY")

    def _build_filtered_env(self) -> dict[str, str]:
        """strip-all-allowlist — 默认仅传 safe base env；manifest env_allowlist opt-in。

        即使 manifest 显式 allow AGENT_BUILDER_* 也拒绝（FORBIDDEN_PREFIXES）。
        """
        filtered: dict[str, str] = {}
        # 1. base env
        for k in self._SAFE_BASE_ENV:
            if k in os.environ:
                filtered[k] = os.environ[k]
        # 2. manifest env_allowlist opt-in
        if self._sandbox_config is not None:
            for k in self._sandbox_config.env_allowlist:
                if k in self._FORBIDDEN_EXACT:
                    _log.warning("env_allowlist refused: %s is on FORBIDDEN_EXACT list", k)
                    continue
                if any(k.startswith(p) for p in self._FORBIDDEN_PREFIXES):
                    _log.warning("env_allowlist refused: %s matches FORBIDDEN_PREFIXES", k)
                    continue
                if k in os.environ:
                    filtered[k] = os.environ[k]
        # 3. 用户传入 env override（如 acid test 传 HULY_ENDPOINT）
        if self._env:
            filtered.update(self._env)
        return filtered
    ```

    **`start()` 方法修改** — 沙箱化分支:
    ```python
    async def start(self) -> None:
        async with self._lock:
            if self._proc is not None:
                return
            self._closed = False

            env = self._build_filtered_env() if self._sandbox_config else (
                {**os.environ, **self._env} if self._env else dict(os.environ)
            )

            if self._sandbox_config is not None:
                # 5.B 沙箱路径
                runner = self._choose_runner()
                self._proc = await runner.spawn_with_limits(
                    [sys.executable, "-u", "-m", self._module_entry],
                    cpu_seconds=self._sandbox_config.cpu_limit_seconds,
                    memory_bytes=self._sandbox_config.memory_bytes,
                    env=env,
                    cwd=self._cwd,
                )
            else:
                # 5.A 兼容路径（不动 5.A 11 测试）
                self._proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-u", "-m", self._module_entry,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=self._cwd,
                )

            # ... 5.A 既有 reader_task / stderr_task spawn ...

            # 5.B: 仅在沙箱路径起 watchdog
            if self._sandbox_config is not None:
                from .sandbox.watchdog import SandboxWatchdog
                self._watchdog = SandboxWatchdog(
                    pid=self._proc.pid,
                    memory_limit_bytes=self._sandbox_config.memory_bytes,
                    on_violation=lambda msg: self._fail_all_pending(
                        SandboxLimitExceeded(msg)
                    ),
                )
                self._watchdog.start()
    ```

    **`invoke()` 方法修改** — last_invoke_at finally 更新（Pitfall 6）:
    ```python
    async def invoke(self, ...) -> Any:
        await self.start()
        try:
            # ... 5.A 既有 send + wait_for response 逻辑 ...
            return result
        finally:
            self.last_invoke_at = time.monotonic()  # 5.B: finally 块更新
    ```

    **`close()` 方法修改** — stop watchdog:
    ```python
    async def close(self) -> None:
        if self._watchdog is not None:
            self._watchdog.stop()
            self._watchdog = None
        # ... 5.A 既有 close 逻辑 ...
    ```

    **import** 加: `from .sandbox.runner import SandboxRunner, PosixResourceSandbox` + `from .exceptions import SandboxLimitExceeded`

    2. **更新 `backend/tests/platforms/test_daemon_client.py`** — 加 7+ 测试覆盖新行为:
    
    - `test_sandbox_config_none_uses_legacy_spawn_path`: sandbox_config=None → 走 asyncio.create_subprocess_exec 路径（5.A 兼容）
    - `test_sandbox_config_set_uses_sandbox_runner`: 传 sandbox_config + injected mock SandboxRunner → start() 调 runner.spawn_with_limits
    - `test_build_filtered_env_strips_secrets_by_default`: 设 HMAC_SECRET / DATABASE_URL → _build_filtered_env 结果不含
    - `test_build_filtered_env_allows_safe_base`: PATH / HOME / LANG 默认在 filtered env 中
    - `test_build_filtered_env_respects_env_allowlist`: sandbox_config(env_allowlist=["FOO"])+ env FOO=bar → filtered 含 FOO
    - `test_build_filtered_env_forbidden_prefix_always_rejected`: 即使 env_allowlist=["AGENT_BUILDER_X"] 也被 reject + 警告日志
    - `test_last_invoke_at_updates_on_invoke_finally`: 调 invoke() → last_invoke_at > 0.0
    - `test_close_stops_watchdog_if_present`: sandbox_config 启动后调 close → watchdog._stopped 为 True

    5.A 11 既有测试**不修改任何断言** — 它们都不传 sandbox_config → 仍走 5.A 路径 → 0 regression。

    避坑:
    - sandbox_config=None 时 **绝不能** 启动 watchdog（不然 5.A daemon 没设 RLIMIT/setsid，watchdog killpg 可能误杀整个主进程）
    - 不要把 watchdog start 放到 5.A 既有 start() 路径里（保持双轨清晰）
    - `last_invoke_at` finally 块更新 — 写在 try 内会因 exception 不更新（Pitfall 6）
    - `_FORBIDDEN_PREFIXES` 是 prefix match 不是 exact match
    - `_SAFE_BASE_ENV` 之外的所有 env 默认 strip — 即使 manifest 想 allow 也要 explicit 列出

    commit messages:
    - `feat(05b-04): integrate sandbox runner + watchdog in PlatformDaemonClient (5.A backward compat)`
    - `feat(05b-04): add _build_filtered_env strip-all-allowlist (Pitfall 8 secret leak)`
    - `test(05b-04): add daemon_client sandbox integration tests (≥ 7 new)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_daemon_client.py -v 2>&1 | tail -25</automated>
  </verify>
  <done>
    daemon_client.py 新增 _choose_runner / _build_filtered_env / last_invoke_at / watchdog 生命周期；test_daemon_client.py 新增 ≥ 7 测试全 pass；5.A 既有 11 测试 0 regression；5/5 acid test 0 regression（pytest tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py）。
  </done>
</task>

<task type="auto">
  <name>Task 3: 单元 + 集成测 — watchdog grace period + idle reaper 真行为</name>
  <files>
    backend/tests/platforms/sandbox/test_watchdog.py
    backend/tests/platforms/sandbox/test_idle_reaper.py
    backend/tests/platforms_integration/test_watchdog_grace_period.py
    backend/tests/platforms_integration/test_idle_reaper.py
    backend/tests/platforms_integration/fixtures/sigterm_ignoring_daemon.py
  </files>
  <action>
    1. **单元测试 `test_watchdog.py`** ≥ 6 测（mock pid / on_violation; 不真 spawn 子进程）:
    
    - `test_watchdog_default_intervals`: SandboxWatchdog(pid=1, memory_limit_bytes=...) 默认 scan=5.0 grace=3.0
    - `test_watchdog_start_creates_named_task`: start() 后 task.get_name() 含 "sandbox-watchdog[pid="
    - `test_watchdog_stop_cancels_task`: start → stop → task.cancelled() == True
    - `test_watchdog_read_rss_returns_none_for_dead_pid`: pid=999999 不存在 → _read_rss 返回 None（FileNotFoundError swallow）
    - `test_watchdog_on_violation_callback_called_before_signals`: 用 monkeypatch _read_rss 强制返回 limit+1 → on_violation 至少调 1 次（async loop sleep + advance 验证）
    - `test_watchdog_no_violation_callback_not_called`: _read_rss 返回 limit-1 → on_violation 不调（loop 1 cycle）

    用 `pytest-asyncio` + `asyncio.sleep(0)` advance event loop 测 _loop 第一轮行为。

    2. **单元测试 `test_idle_reaper.py`** ≥ 6 测:
    
    - `test_reaper_default_intervals`: IdleDaemonReaper(get_daemons=...) 默认 timeout=300 scan=60
    - `test_reaper_skips_unstarted_daemon`: daemon._proc is None → 跳过（close 不被调）
    - `test_reaper_skips_active_invoke`: daemon._pending = {"k": Future()} → 跳过（Pitfall 6 防竞争）
    - `test_reaper_closes_idle_daemon`: daemon.last_invoke_at = now - 400.0 → daemon.close() 被调
    - `test_reaper_swallows_close_error`: daemon.close raise Exception → reaper task 不死，下次循环继续
    - `test_reaper_uses_monotonic_not_wallclock`: monkeypatch time.monotonic → 验证用 monotonic（Pitfall 6 NTP 抗变）

    3. **集成测 fixture `backend/tests/platforms_integration/fixtures/sigterm_ignoring_daemon.py`**:
    ```python
    """fixture daemon — 故意忽略 SIGTERM 触发 watchdog grace period 测试."""
    import asyncio
    import json
    import signal
    import sys

    async def main() -> None:
        # 忽略 SIGTERM — 让 watchdog SIGTERM 失败 → 3s grace 后 SIGKILL
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        # JSONRPC stdio loop（最简版本，仅响应 alloc_200mb method）
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        big_buffer = []  # 持续分配（让 RSS 真涨）

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                req = json.loads(line.decode())
                method = req.get("method", "")
                req_id = req.get("id")
                if method.endswith("alloc_200mb"):
                    # 持续分配 200MB（触发 watchdog memory_limit_bytes 检测）
                    big_buffer.append(b'a' * (200 * 1024 * 1024))
                    resp = {"jsonrpc": "2.0", "id": req_id, "result": {"alloc": True}}
                else:
                    resp = {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}}
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()

    if __name__ == "__main__":
        asyncio.run(main())
    ```

    4. **集成测 `test_watchdog_grace_period.py`** ≥ 3 测（Linux only @pytest.mark.linux_only @pytest.mark.sandbox_integration）:
    
    - `test_watchdog_sigterm_then_sigkill_after_grace`: 起 sigterm_ignoring_daemon + sandbox_config(memory="50Mi", timeout_invoke=10) → invoke alloc_200mb → watchdog 检测超 50MB → SIGTERM (被忽略) → 3s grace → SIGKILL → daemon.returncode == -SIGKILL (-9) + invoke raise SandboxLimitExceeded + elapsed < 9.0s
    - `test_watchdog_normal_daemon_no_violation`: 起 echo_daemon（5.A 已有 fixture，不超内存）+ sandbox_config(memory="500Mi") → invoke 多次成功 + watchdog 任务存活 + 无 SandboxLimitExceeded
    - `test_watchdog_on_violation_fails_pending_invoke_immediately`: invoke alloc_200mb 用 invoke_timeout=30 → watchdog 超限 → 主 invoke 立即 raise SandboxLimitExceeded（不是 30s 后 TimeoutError）→ elapsed < 10s

    5. **集成测 `test_idle_reaper.py`** ≥ 2 测（@pytest.mark.sandbox_integration）:
    
    - `test_idle_reaper_closes_idle_daemon`: 起 echo_daemon + sandbox_config(timeout_idle=1, ...) → invoke 一次 → 等待 2s → reaper scan_interval 设短(0.5s) 手动触发一次 → daemon._proc 应 None 或 returncode 已设
    - `test_idle_reaper_skips_active_invoke`: daemon 在长 invoke 中（_pending 非空）→ reaper 即使 last_invoke_at 很久前也不 close

    6. **5.A regression check** — 必跑:
    - `pytest backend/tests/platforms/ -x` 5.A 162 + 本 plan 新增 ≥ 12 = 174+ 全绿
    - `pytest backend/tests/platforms_integration/test_huly_acid_test.py test_fault_isolation.py -v` 5/5 acid test 0 regression
    - `pytest backend/tests/notification/ -x` Phase 4 81 IM 0 regression

    避坑:
    - `signal.signal(SIGTERM, SIG_IGN)` 在 daemon 内必须**先于** stdin loop（否则 watchdog 提前 SIGTERM 被默认 handler 处理）
    - `os.killpg(getpgid(pid), SIGTERM)` 必须 daemon 走 PosixResourceSandbox（os.setsid 已设）— sandbox_config 必须传
    - 集成测 elapsed assertion 用 `<9.0` 给余量（scan_interval 5s + grace 3s + jitter）
    - macOS skipif：`@pytest.mark.skipif(sys.platform == "darwin", reason="RLIMIT 弱 enforcement + setsid 行为差异")` 加 Linux-only 集成测
    - reaper 测试用很短 timeout_idle=1.0 + scan_interval=0.5（不等真正 60s）

    commit messages:
    - `test(05b-04): add watchdog + idle_reaper unit tests (≥ 12 new)`
    - `test(05b-04): add sigterm_ignoring_daemon fixture + grace period integration test`
    - `test(05b-04): add idle reaper integration tests`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/sandbox/test_watchdog.py tests/platforms/sandbox/test_idle_reaper.py -v 2>&1 | tail -20</automated>
  </verify>
  <done>
    单元测试 ≥ 12 全 pass；Linux-only 集成测 ≥ 5 全绿（macOS skip）；5.A 162 + 本 plan 新增 ≥ 19 = 181+ 全绿；5/5 acid test 0 regression；Phase 4 81 IM 0 regression。
  </done>
</task>

</tasks>

<verification>
**phase-local checks**:
- `pytest backend/tests/platforms/sandbox/ -v` 含 ≥ 19 新测全绿
- `pytest backend/tests/platforms/test_daemon_client.py -v` 含 ≥ 7 新测全绿（+ 5.A 11 = 18+）
- Linux CI: `pytest -m linux_only backend/tests/platforms_integration/test_watchdog_grace_period.py -v` ≥ 3 全绿

**5.A regression**:
- `pytest backend/tests/platforms/ -x` 0 fail（5.A 162 + 本 plan 新增）
- `pytest backend/tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py -v` 5/5 acid test 0 fail
- `pytest backend/tests/notification/ -x` Phase 4 81 IM 0 regression

**reading doc gate**:
- `git log --oneline -10 | head` docs(05b-04) commit 早于任何 feat(05b-04) commit
</verification>

<success_criteria>
1. **三层防护完整**: invoke timeout (5.A) + watchdog grace 3s → SIGKILL (新) + idle reaper 300s (新)
2. **Pitfall 4 防护**: os.killpg 整组 kill；setsid 让 daemon 成为 pgid leader（Plan 05b-02 已落）
3. **Pitfall 5 防护**: on_violation callback 先于 SIGTERM 让主 invoke 立即 raise SandboxLimitExceeded（不依赖 race）
4. **Pitfall 6 防护**: last_invoke_at finally 块更新；reaper 跳过 _pending 非空 daemon
5. **Pitfall 8 防护**: _build_filtered_env strip-all-allowlist；FORBIDDEN_PREFIXES 拒绝 AGENT_BUILDER_*/HMAC_*
6. **5.A 兼容性**: sandbox_config=None 时走老路径；11 既有 test + 5/5 acid test 0 regression
7. **Linux CI gate**: grace period 真行为验证（sigterm_ignoring_daemon fixture）
8. **测试覆盖**: 单元 ≥ 12 + 集成 ≥ 5 + daemon_client 新增 ≥ 7
9. **reading doc gate**: docs commit 早于 feat commit（CLAUDE.md §2.7）
</success_criteria>

<output>
After completion, create `.planning/phases/05b-plugin-sandbox/05b-04-SUMMARY.md` 含:
- Dify 借鉴点（grace 时间 3s 对照 systemd 默认 / scan 5s 选型理由 / kill 进程组思路）
- 三层防护层级图（invoke timeout / watchdog grace / idle reaper 互不阻塞）
- Pitfall 4/5/6/8 防护具体实现位置（killpg / on_violation 顺序 / _pending skip / FORBIDDEN_PREFIXES）
- 5.A 兼容性策略（sandbox_config=None 走老路径，0 regression）
- Plan 05 接入点（CgroupsV2Sandbox 替换 _choose_runner 返回值）
</output>
</content>
</invoke>