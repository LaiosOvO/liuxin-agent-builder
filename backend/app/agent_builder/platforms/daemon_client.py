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
from typing import Any

from .exceptions import PluginDaemonExitedError, PluginInvocationError

_log = logging.getLogger(__name__)

# ── 默认值 ─────────────────────────────────────────────────────────────────────

_DEFAULT_INVOKE_TIMEOUT = 30.0
"""默认 invoke timeout（秒）—— 业务方法通常 < 1s；30s 给足重试容差。"""

_TERMINATE_WAIT = 5.0
"""close 时 terminate 后等待进程退出秒数；超时后 kill -9。"""


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
    ) -> None:
        """构造 client（不实际 spawn 进程；首次 invoke 时懒启动）。

        Args:
            module_entry: ``python -u -m <module_entry>`` 形式的模块路径
                          （如 ``"plugins.huly.huly_plugin"`` 或 ``"tests.platforms.fixtures.echo_daemon"``）
            env: 额外环境变量（merge 进 os.environ）— 如 ``{"HULY_ENDPOINT": "http://..."}``
            invoke_timeout: 每个 invoke 等响应的超时（秒）；默认 30.0
                            **重要**：fault isolation test 必须用 ≤ 2.0 验证 crash 立即失败
        """
        self._module_entry = module_entry
        self._env = env
        self._invoke_timeout = invoke_timeout

        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed = False
        self._lock = asyncio.Lock()

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
            )
            self._reader_task = asyncio.create_task(
                self._read_loop(),
                name=f"daemon-stdout-reader[{self._module_entry}]",
            )
            self._stderr_task = asyncio.create_task(
                self._stderr_drain(),
                name=f"daemon-stderr-drain[{self._module_entry}]",
            )

            _log.info(
                "daemon spawned: module=%s pid=%s",
                self._module_entry,
                self._proc.pid,
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
