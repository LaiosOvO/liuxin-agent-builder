"""PlatformDaemonClient — JSONRPC over stdio 主进程↔daemon 通信（PLUG-FW-05）。

设计要点（ADR-001 §5 + RESEARCH.md §Pattern 3 + Pitfall 2/8 + reading doc §5 借鉴点）:

- `asyncio.create_subprocess_exec` spawn daemon 子进程（v1 仅 Python；node/go 留 v2）
- `python -u -m <module_entry>` —— `-u` flag 强制 unbuffered stdout，否则 JSONRPC response
  会被 buffer 在 daemon 端不能立即 flush 给主进程（Python 默认 stdout buffer 64KB）
- line-delimited JSON envelope (JSON-RPC 2.0): `{"jsonrpc":"2.0","id":<uuid>,"method":"<cap>.<method>","params":{...}}`
- request_id (UUID4 hex) 关联 `asyncio.Future`；`_read_loop` 按 id 路由响应到对应 future
- daemon 退出（stdout EOF / BrokenPipe）→ 所有 pending future `set_exception(PluginDaemonExitedError)`
  —— **Pitfall 2 关键 fault isolation**：crash 立即失败（< 2s），不许走 30s timeout
- stderr 独立 drain task —— **Pitfall 8 防 buffer 满死锁**（daemon 写 stderr 满 pipe 被 OS block）
- close: terminate → wait 5s → kill；幂等可重复调

JSONRPC 2.0 协议严格遵守:
- jsonrpc: "2.0" 字面字符串
- id: uuid hex string（不用 int 防碰撞）
- method: "<capability>.<method>"（如 "im.send_card"）
- params: dict (kwargs 直接序列化)
- result: any (success path)
- error: {code, message, data?} (error path)
- 错误码约定:
  - -32601: Method not found
  - -32602: Invalid params
  - -32603: Internal error
  - -32000~-32099: plugin 业务错误

Reference: docs/reading-dify-05a-05-daemon-client-2026-05-17.md 5 借鉴点
- 借鉴点 #1: envelope.result 类型化思路（v1 dict 透传）
- 借鉴点 #2: error code/message 双字段（JSONRPC 标准）
- 借鉴点 #3: 简化为 Python 子进程 + stdio（无 HTTP overhead）
- 借鉴点 #4: 同步 invoke（异步 task 留 v2）
- 借鉴点 #5: crash 不自动重启（fault isolation 立即失败 — Pitfall 2）

License: 100% 独立创作，仅借鉴 Dify AGPL-3.0 设计模式，**不拷源代码**。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import TYPE_CHECKING, Any

from .exceptions import (
    PluginDaemonExitedError,
    PluginInvocationError,
)
from .sandbox.runner import PosixResourceSandbox

if TYPE_CHECKING:
    from .manifest import SandboxConfig
    from .sandbox.runner import SandboxRunner
    from .sandbox.watchdog import SandboxWatchdog

_log = logging.getLogger(__name__)

# ── 默认值 ─────────────────────────────────────────────────────────────────────

_DEFAULT_INVOKE_TIMEOUT = 30.0
"""默认 invoke timeout（秒）—— 业务方法通常 < 1s；30s 给足重试容差。"""

_TERMINATE_WAIT = 5.0
"""close 时 terminate 后等待进程退出秒数；超时后 kill -9。"""

# ── env 过滤白名单（Pitfall 8 防 secret 泄漏）────────────────────────────────────

_SAFE_BASE_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
)
"""默认放行的基础 env — daemon Python 解释器启动必需 + 国际化设置。

PATH/HOME 是 OS 进程基础；LANG/LC_ALL/TZ 是国际化（不影响安全）；PYTHONPATH/UNBUFFERED
是 Python 解释器必需（否则 `python -u -m <module>` 找不到 sys.path 或 stdout buffer）。
"""

_FORBIDDEN_PREFIXES = (
    "AGENT_BUILDER_",
    "INTERNAL_",
    "HMAC_",
    "DATABASE_",
    "REDIS_",
    "SMTP_",
)
"""即使 manifest env_allowlist 显式列出，匹配此前缀的 env 也拒绝传给 daemon。

设计理由：plugin 作者**永远不应该**直接读项目内部敏感配置；如果 plugin 需要数据库，
必须走主进程的 capability API（隔离层），不能直接拿 DATABASE_URL 自己连。
"""

_FORBIDDEN_EXACT = (
    "HMAC_SECRET",
    "DATABASE_URL",
    "REDIS_URL",
    "OPENAI_API_KEY",
)
"""精确匹配的 forbidden env — 即使前缀不匹配也强制拒绝（兜底名单）。

例如 OPENAI_API_KEY 不在前缀黑名单内，但绝不允许直接传给第三方 plugin（应该走 LLM
capability proxy 隔离 token 使用计数）。
"""


# ── PlatformDaemonClient ─────────────────────────────────────────────────────


class PlatformDaemonClient:
    """主进程 ↔ daemon JSONRPC over stdio 客户端。

    用法（Plan 06+ HulyPlugin acid test）::

        client = PlatformDaemonClient(
            module_entry="plugins.huly.huly_plugin",
            env={"HULY_ENDPOINT": "http://localhost:18765"},
            invoke_timeout=10.0,
        )
        try:
            result = await client.invoke(
                "im", "send_card",
                recipient={"kind": "channel", "id": "general"},
                card={"title": "...", "body_markdown": "...", "actions": []},
                idempotency_key="k1",
            )
            assert result["plugin_name"] == "huly"
        finally:
            await client.close()

    Attributes:
        _module_entry: 子进程跑 ``python -u -m <module_entry>``；
                       daemon 在 ``__main__`` 写 ``asyncio.run(main())``。
        _env: 注入 daemon 环境变量（如 ``HULY_ENDPOINT``）。
        _invoke_timeout: 每个 invoke 等响应的超时（秒）。
        _proc: 当前 daemon Process（None 表示未启动）。
        _pending: ``{request_id: Future}`` 路由表（_read_loop set_result/set_exception）。
        _reader_task: stdout 读循环 task（spawn 在 start()）。
        _stderr_task: stderr drain task（防 Pitfall 8 pipe 满死锁）。
        _closed: close() 调用过的标志（防 read_loop 重复 set_exception）。
        _lock: start 串行化（防并发首次 invoke 重复 spawn）。
    """

    def __init__(
        self,
        module_entry: str,
        env: dict[str, str] | None = None,
        invoke_timeout: float = _DEFAULT_INVOKE_TIMEOUT,
        cwd: str | None = None,
        sandbox_config: "SandboxConfig | None" = None,
        sandbox_runner: "SandboxRunner | None" = None,
    ) -> None:
        """构造 client（不实际 spawn 进程；首次 invoke 时懒启动）。

        Args:
            module_entry: ``python -u -m <module_entry>`` 形式的模块路径
                          （如 ``"plugins.huly.huly_plugin"`` 或 ``"tests.platforms.fixtures.echo_daemon"``）
            env: 额外环境变量（merge 进 os.environ）— 如 ``{"HULY_ENDPOINT": "http://..."}``
            invoke_timeout: 每个 invoke 等响应的超时（秒）；默认 30.0
                            **重要**：fault isolation test 必须用 ≤ 2.0 验证 crash 立即失败
            cwd: 子进程工作目录；默认 None 表示继承主进程 cwd。
                 Plan 07 acid test 注入项目根目录（让 ``python -m plugins.huly.huly_plugin``
                 能从根目录找到 ``plugins/`` 包，主进程的 pytest 跑在 ``backend/`` 下时
                 必须显式指定 cwd 让 daemon 看见 ``plugins/`` 包）。
            sandbox_config: Wave 3 沙箱配置（默认 None = 走 5.A 兼容路径不沙箱）
                            非 None 时启用：
                            - SandboxRunner spawn_with_limits 注入 RLIMIT（替代 asyncio.create_subprocess_exec）
                            - _build_filtered_env strip-all-allowlist（替代 merge os.environ）
                            - SandboxWatchdog asyncio task 监控 RSS（SIGTERM grace → SIGKILL）
            sandbox_runner: Wave 3 注入 SandboxRunner 实例（默认 None = 自动选 PosixResourceSandbox）
                            主要用于测试 inject MockSandboxRunner；生产路径让 _choose_runner 自动选

        5.A 兼容性约束：
        - sandbox_config=None 时走老路径（asyncio.create_subprocess_exec + dict(os.environ)）
        - 5.A 既有 11 测试不传 sandbox_config → 0 regression
        - 5.A 5/5 acid test 不传 sandbox_config → 0 regression
        """
        self._module_entry = module_entry
        self._env = env
        self._invoke_timeout = invoke_timeout
        self._cwd = cwd
        self._sandbox_config = sandbox_config
        self._sandbox_runner = sandbox_runner

        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._watchdog: "SandboxWatchdog | None" = None
        self._closed = False
        self._lock = asyncio.Lock()

        # public 字段（IdleDaemonReaper 读）— 在 invoke() finally 块更新
        self.last_invoke_at: float = 0.0
        """daemon 最后一次 invoke 完成时间（time.monotonic 时间戳）。

        IdleDaemonReaper 用此字段判断 daemon idle 时长。
        在 invoke() 的 finally 块更新（不是 try 内 — Pitfall 6 保证 exception 也更新）。
        默认 0.0 表示从未 invoke 过。
        """

    # ── 5.B 沙箱 helper（仅 sandbox_config 非 None 时调用）───────────────────

    def _choose_runner(self) -> "SandboxRunner":
        """自动选择 SandboxRunner 实现 — 测试可注入；生产 cgroups opt-in + 优雅降级。

        优先级（Plan 05b-05 升级）：
        1. 显式注入 ``self._sandbox_runner``（测试用 MockSandboxRunner — 优先级最高）
        2. ``sandbox_config.use_cgroups`` + ``is_cgroups_v2_available()`` →
           ``CgroupsV2Sandbox`` (Linux opt-in 路径)
        3. Fallback ``PosixResourceSandbox`` — cross-platform baseline

        **优雅降级（Pitfall 2 — 容器友好）**：
            ``use_cgroups: true`` 但运行环境不支持 cgroups v2 / systemd-run
            （macOS / docker 无 cgroup delegation / 无 systemd-userdbd） →
            **不 fail startup**，log warning + 降级到 PosixResourceSandbox。

        Returns:
            SandboxRunner: 满足 Protocol 的 sandbox 实例（``spawn_with_limits`` 可直接调用）。

        Note:
            ``is_cgroups_v2_available()`` silent-fails（绝不抛异常 — Pitfall 2）；
            本方法所有路径均不抛异常，可在 ``start()`` 同步调用。
            仅在 ``sandbox_config is not None`` 路径调用（5.A 兼容路径不进入此方法）。
        """
        # 1. 显式注入优先（测试 mock）
        if self._sandbox_runner is not None:
            return self._sandbox_runner

        # 2. manifest opt-in 检测 + cgroups v2 available 检测（Plan 05b-05）
        if self._sandbox_config is not None and self._sandbox_config.use_cgroups:
            # 延迟 import 避免无 sandbox_config 场景加载 cgroups_v2 模块
            from .sandbox.cgroups_v2 import (
                CgroupsV2Sandbox,
                is_cgroups_v2_available,
            )

            if is_cgroups_v2_available():
                _log.info("sandbox.runner.selected runner=CgroupsV2Sandbox")
                return CgroupsV2Sandbox()
            # use_cgroups=true 但运行时不可用 — 优雅降级 + warning（不 fail startup）
            _log.warning(
                "sandbox.cgroups_v2.unavailable — falling back to PosixResourceSandbox "
                "(可能原因：非 Linux / 容器无 cgroup delegation / systemd-run 缺失 / "
                "systemd-userdbd 未运行)"
            )

        # 3. cross-platform baseline
        return PosixResourceSandbox()

    def _build_filtered_env(self) -> dict[str, str]:
        """strip-all-allowlist env 过滤（Pitfall 8 防 secret 泄漏）— 仅 sandbox_config 非 None 时调用。

        过滤层级：
        1. base env: PATH/HOME/LANG/LC_ALL/TZ/PYTHONPATH/PYTHONUNBUFFERED 默认放行
           （daemon Python 解释器必需 + 国际化）
        2. manifest env_allowlist opt-in: SandboxConfig.env_allowlist 显式列出的 env 才传
        3. 双层黑名单兜底（即使 manifest 显式 allow 也拒）:
           - _FORBIDDEN_PREFIXES: AGENT_BUILDER_* / INTERNAL_* / HMAC_* / DATABASE_* / REDIS_* / SMTP_*
           - _FORBIDDEN_EXACT: HMAC_SECRET / DATABASE_URL / REDIS_URL / OPENAI_API_KEY
        4. 用户传入 _env override（如 acid test 注入 HULY_ENDPOINT）

        被拒的 env 记 warning log 让运维知道 plugin 作者可能想做不该做的事。

        Returns:
            dict[str, str]: 过滤后的 env，可直接传给 SandboxRunner.spawn_with_limits
        """
        filtered: dict[str, str] = {}

        # 1. base env
        for key in _SAFE_BASE_ENV:
            if key in os.environ:
                filtered[key] = os.environ[key]

        # 2. manifest env_allowlist opt-in
        if self._sandbox_config is not None:
            for key in self._sandbox_config.env_allowlist:
                if key in _FORBIDDEN_EXACT:
                    _log.warning(
                        "env_allowlist refused: %s on FORBIDDEN_EXACT list (module=%s)",
                        key,
                        self._module_entry,
                    )
                    continue
                if any(key.startswith(p) for p in _FORBIDDEN_PREFIXES):
                    _log.warning(
                        "env_allowlist refused: %s matches FORBIDDEN_PREFIXES (module=%s)",
                        key,
                        self._module_entry,
                    )
                    continue
                if key in os.environ:
                    filtered[key] = os.environ[key]

        # 3. 用户传入 env override（acid test 注入路径）
        if self._env:
            filtered.update(self._env)

        return filtered

    # ── 公开 API ───────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """显式 spawn daemon 子进程（首次 invoke 自动调用，亦可手动预热）。

        幂等：若 _proc 已存在（且未 close），直接返回。
        重置：若之前 close 过（_proc 已设回 None），重新允许 spawn。

        子进程参数：
        - ``sys.executable`` 当前 Python 解释器路径（避免 venv 不一致）
        - ``"-u"`` unbuffered stdout/stderr（**关键** — 否则 JSONRPC response buffer 在 daemon）
        - ``"-m" module_entry`` 让 daemon 走标准 module 入口
        - stdin/stdout/stderr 全 PIPE（双向通信）
        - env merge：os.environ + self._env（让 daemon 看见 HULY_ENDPOINT 等）

        启动后:
        - close 标志重置（允许 re-start 场景）
        - 2 个后台 task: _read_loop（路由响应）+ _stderr_drain（防死锁）
        """
        async with self._lock:
            if self._proc is not None:
                return

            # close 后重新 start 场景：重置 closed 标志
            self._closed = False

            cmd = [sys.executable, "-u", "-m", self._module_entry]

            if self._sandbox_config is not None:
                # 5.B 沙箱路径：strip-all-allowlist env + SandboxRunner spawn + watchdog
                env = self._build_filtered_env()
                runner = self._choose_runner()
                self._proc = await runner.spawn_with_limits(
                    cmd,
                    cpu_seconds=self._sandbox_config.cpu_limit_seconds,
                    memory_bytes=self._sandbox_config.memory_bytes,
                    env=env,
                    cwd=self._cwd,
                )
            else:
                # 5.A 兼容路径（不动 5.A 11 测试 + 5/5 acid test）
                merged_env = dict(os.environ)
                if self._env:
                    merged_env.update(self._env)

                self._proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-u",
                    "-m",
                    self._module_entry,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=merged_env,
                    cwd=self._cwd,
                )

            self._reader_task = asyncio.create_task(
                self._read_loop(),
                name=f"daemon-stdout-reader[{self._module_entry}]",
            )
            self._stderr_task = asyncio.create_task(
                self._stderr_drain(),
                name=f"daemon-stderr-drain[{self._module_entry}]",
            )

            # 5.B: 仅在沙箱路径起 watchdog（5.A 老路径 daemon 未设 setsid，killpg 会误杀主进程）
            if self._sandbox_config is not None:
                from .sandbox.watchdog import SandboxWatchdog

                self._watchdog = SandboxWatchdog(
                    pid=self._proc.pid,
                    memory_limit_bytes=self._sandbox_config.memory_bytes,
                    on_violation=self._fail_all_pending,
                )
                self._watchdog.start()

            _log.info(
                "daemon spawned: module=%s pid=%s sandbox=%s",
                self._module_entry,
                self._proc.pid,
                self._sandbox_config is not None,
            )

    async def invoke(
        self,
        capability: str,
        method: str,
        **kwargs: Any,
    ) -> Any:
        """发 JSONRPC request → 等响应（核心 API）。

        Structured log: 埋点 capability/method/latency_ms/outcome（Phase 7 Run Viewer 钩子）

        Args:
            capability: capability 名（"im" / "doc" / "hr" / "identity"）
            method: 方法名（"send_card" / "update_card" / ...）
            **kwargs: 方法参数（直接序列化为 JSONRPC params dict）

        Returns:
            daemon 返回的 result 字段（任意 JSON-serializable 类型）

        Raises:
            PluginInvocationError: daemon 返回 JSONRPC error 业务错（含 code/message）
            PluginDaemonExitedError: daemon 进程在 invoke 期间退出
            asyncio.TimeoutError: invoke_timeout 超时（业务正常路径，非 fault isolation）
        """
        if self._proc is None:
            await self.start()

        # start() 之后 _proc 必有；但 stdin 可能在 close 过程中被关闭
        if self._proc is None or self._proc.stdin is None:
            raise PluginDaemonExitedError(
                f"daemon '{self._module_entry}' failed to start or stdin closed"
            )

        req_id = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = future

        envelope = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": f"{capability}.{method}",
            "params": kwargs,
        }

        start_ts = time.monotonic()

        try:
            line = (json.dumps(envelope) + "\n").encode("utf-8")
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            # daemon stdin 在 write 时已死
            self._pending.pop(req_id, None)
            raise PluginDaemonExitedError(
                f"daemon '{self._module_entry}' stdin broken: {e}"
            ) from e

        try:
            result = await asyncio.wait_for(future, timeout=self._invoke_timeout)
        finally:
            # Future 完成 / 异常 / 超时 都要从 _pending 清理
            self._pending.pop(req_id, None)
            latency_ms = int((time.monotonic() - start_ts) * 1000)

            # Pitfall 6: last_invoke_at 必须在 finally 块更新（不是 try 内）
            # — 写在 try 内 exception 时不会更新，导致 IdleDaemonReaper 误判该 daemon idle
            self.last_invoke_at = time.monotonic()

            # Structured log: Phase 7 Run Viewer 钩子（capability call latency 埋点）
            outcome = (
                "success"
                if not future.cancelled() and future.exception() is None
                else "error"
            )
            _log.info(
                "daemon.invoke capability=%s method=%s latency_ms=%d outcome=%s",
                capability,
                method,
                latency_ms,
                outcome,
            )

        return result

    async def close(self) -> None:
        """关闭 daemon 进程 + 取消后台 task + fail 所有 pending future。

        幂等：可重复调，第二次直接返回。

        步骤:
        1. 标志 _closed = True（防 _read_loop 重复 fail）
        2. terminate() 发 SIGTERM 给 daemon
        3. wait 5s 给 daemon 优雅退出机会
        4. 超时 → kill -9
        5. 取消 reader / stderr task
        6. fail 所有 pending future（PluginDaemonExitedError("daemon closed")）
        7. _proc 设回 None（允许后续 invoke 触发 re-start）
        """
        if self._closed and self._proc is None:
            return

        self._closed = True

        # 5.B: 先 stop watchdog（防 watchdog 在 close 流程中误触发 SIGKILL）
        if self._watchdog is not None:
            self._watchdog.stop()
            self._watchdog = None

        if self._proc is None:
            return

        # SIGTERM
        try:
            self._proc.terminate()
        except ProcessLookupError:
            # 进程已死（如 sys.exit(1) crash）
            pass

        # 等 5s 优雅退出
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=_TERMINATE_WAIT)
        except asyncio.TimeoutError:
            try:
                self._proc.kill()
                await self._proc.wait()
            except ProcessLookupError:
                pass

        # 取消后台 task
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._stderr_task is not None and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass

        # Fail 所有 pending future（虽 _read_loop 应已处理，兜底）
        self._fail_all_pending(
            PluginDaemonExitedError(f"daemon '{self._module_entry}' closed by client")
        )

        self._proc = None
        self._reader_task = None
        self._stderr_task = None

        _log.info("daemon closed: module=%s", self._module_entry)

    # ── 内部：read loop / stderr drain ─────────────────────────────────────────

    async def _read_loop(self) -> None:
        """从 daemon stdout 读响应 → 按 id 路由到 _pending future。

        关键路径：
        - readline() 返回空 bytes → daemon 已 exit → fail 所有 pending future（**Pitfall 2 fault isolation**）
        - 非 JSON 行 → log warn + skip（防 daemon 写 debug 信息污染）
        - 未知 id → log warn + skip（防 daemon 误发 stale response）
        - error 字段 → set_exception(PluginInvocationError)
        - result 字段 → set_result

        异常处理：
        - 任何 _read_loop 异常 → _fail_all_pending + log；不抛给上层
        - Task cancel → 不报错（close 主动取消）
        """
        if self._proc is None or self._proc.stdout is None:
            return

        try:
            while not self._closed:
                line = await self._proc.stdout.readline()
                if not line:
                    # stdout EOF → daemon 已退出（crash / sys.exit）
                    # Pitfall 2 关键：立即 fail 所有 pending future
                    returncode = self._proc.returncode if self._proc else None
                    self._fail_all_pending(
                        PluginDaemonExitedError(
                            f"daemon '{self._module_entry}' stdout closed (returncode={returncode})"
                        )
                    )
                    break

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    _log.warning(
                        "daemon[%s] emitted non-JSON line: %r",
                        self._module_entry,
                        line[:200],
                    )
                    continue

                rid = msg.get("id")
                if rid is None:
                    _log.warning(
                        "daemon[%s] response missing 'id' field: %r",
                        self._module_entry,
                        msg,
                    )
                    continue

                fut = self._pending.pop(rid, None)
                if fut is None:
                    _log.warning(
                        "daemon[%s] response for unknown id %s",
                        self._module_entry,
                        rid,
                    )
                    continue

                if fut.done():
                    # 已被 timeout 等机制设过结果，跳过
                    continue

                if "error" in msg:
                    fut.set_exception(PluginInvocationError(msg["error"]))
                else:
                    fut.set_result(msg.get("result"))

        except asyncio.CancelledError:
            # close 主动 cancel，正常路径
            raise
        except Exception as e:  # noqa: BLE001 — 兜底防 task 静默死
            _log.exception(
                "daemon[%s] read loop crashed: %s",
                self._module_entry,
                e,
            )
            self._fail_all_pending(
                PluginDaemonExitedError(
                    f"daemon '{self._module_entry}' read loop crashed: {e}"
                )
            )

    async def _stderr_drain(self) -> None:
        """持续读 daemon stderr → log forward；**防 pipe buffer 满死锁（Pitfall 8）**。

        daemon 写大量 stderr（如 logger.warning 满负荷）→ pipe buffer 满 →
        daemon 进程被 OS block 在 write() → 整个 plugin 假死。

        本 task 持续 readline drain 防止上述阻塞。
        """
        if self._proc is None or self._proc.stderr is None:
            return

        try:
            while not self._closed:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                _log.info(
                    "[daemon:%s stderr] %s",
                    self._module_entry,
                    line.decode("utf-8", errors="replace").rstrip(),
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — stderr drain 不许影响主流程
            pass

    def _fail_all_pending(self, exc: Exception) -> None:
        """将所有 pending future set_exception；用于 daemon crash / close 场景。

        遍历 list 副本（_pending.items() 可能在 set_exception 触发的回调中改写）。
        """
        for _rid, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    # ── repr 便于调试 / log ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        proc_status = "not_started"
        if self._proc is not None:
            proc_status = (
                f"pid={self._proc.pid}" if self._proc.returncode is None else "exited"
            )
        return (
            f"<PlatformDaemonClient module={self._module_entry!r} "
            f"status={proc_status} pending={len(self._pending)}>"
        )


__all__ = ["PlatformDaemonClient"]
