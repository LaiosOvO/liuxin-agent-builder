"""SandboxWatchdog — 进程内资源监控 + SIGTERM grace → SIGKILL（PLUG-FW-12）。

设计要点（RESEARCH §Pattern 4 + Pitfall 4/5 + reading doc §与本项目的关系）:

- **asyncio task 每 5s 扫 RSS** — Linux 读 `/proc/<pid>/status` VmRSS / macOS 用 psutil
  fallback；进程已死直接 return 优雅退出
- **on_violation callback 先于 SIGTERM 触发**（Pitfall 5）— 让主 invoke 立即 raise
  SandboxLimitExceeded 不依赖 race condition；callback 在 SIGTERM 之前**同步**执行
- **os.killpg(pgid, SIGTERM) 整组 kill**（Pitfall 4）— Plan 05b-02 PosixResourceSandbox
  preexec_fn 已 os.setsid 让 daemon 成为新 PGID leader；watchdog kill 整组防 fork 子进程逃逸
- **3s grace → SIGKILL 兜底** — daemon 有 3s 优雅退出窗口（aiohttp/httpx graceful shutdown
  hook 默认 < 1s），仍存活直接 SIGKILL 强杀
- **structured log event** — `sandbox.limit_exceeded` / `sandbox.force_kill` 让运维 grep
  log 重建生命周期（借鉴 Dify install_task 状态追踪思路）
- **不允许 watchdog task crash 误杀主进程** — `_read_rss` 失败 swallow 不 raise，避免
  /proc 临时不可读等场景让整个 watchdog task 死亡

License: 100% 独立创作，借鉴 Dify Go daemon 资源监控设计哲学
        （AGPL-3.0 不拷代码，详见 docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-18.md）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Callable

from ..exceptions import SandboxLimitExceeded

_log = logging.getLogger(__name__)

# ── 默认参数 ──────────────────────────────────────────────────────────────────

_DEFAULT_SCAN_INTERVAL = 5.0
"""每 5s 读一次 RSS — 与 Plan 05b-RESEARCH §Anti-Patterns 对齐.

100 daemon × 5s 扫描 = 20 reads/s（cat /proc/<pid>/status < 1ms）远低于 CPU 占用上限。
不能 < 1s（高频 IO 在大量 daemon 时累积成本）。
"""

_DEFAULT_GRACE_PERIOD = 3.0
"""SIGTERM 后等 3s 给 daemon 优雅退出 — 详见 reading doc §设计参考.

systemd 默认 90s 太宽松；Docker 默认 10s 也偏宽；3s 给 aiohttp/httpx graceful shutdown
hook 足够时间（默认 < 1s）但不让 RSS 持续增长造成主进程 OOM。
"""

_IS_DARWIN = sys.platform == "darwin"


# ── RSS 读取 helper ─────────────────────────────────────────────────────────


def _read_rss_linux(pid: int) -> int | None:
    """Linux: 解析 /proc/<pid>/status VmRSS 行（单位 kB → bytes）。

    Returns:
        RSS bytes（int），或 None（进程已死 / 文件不可读）
    """
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        # 进程已死或权限问题；调用方据此判断 loop 退出
        return None
    except OSError:
        # 其它 IO 错误 — swallow 不 raise（watchdog 不能因临时 IO 错误死）
        return None

    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            # 格式: "VmRSS:	  12345 kB"
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1]) * 1024  # kB → bytes
                except ValueError:
                    return None
    return None


def _read_rss_psutil(pid: int) -> int | None:
    """macOS / fallback: psutil.Process(pid).memory_info().rss.

    Returns:
        RSS bytes（int），或 None（进程已死 / psutil 不可用）
    """
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        _log.warning(
            "psutil not installed — watchdog cannot monitor RSS on macOS. "
            "Install psutil or run on Linux for /proc/<pid>/status path."
        )
        return None

    try:
        return int(psutil.Process(pid).memory_info().rss)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    except Exception:  # noqa: BLE001 — 不能让 watchdog 死
        return None


def _read_rss(pid: int) -> int | None:
    """跨平台 RSS 读取入口 — Linux 走 /proc，其它走 psutil。

    Returns:
        RSS bytes 或 None（进程已死 / 不可读）
    """
    if _IS_DARWIN:
        return _read_rss_psutil(pid)
    return _read_rss_linux(pid)


# ── SandboxWatchdog ─────────────────────────────────────────────────────────


class SandboxWatchdog:
    """asyncio task 监控 daemon RSS — 超 memory_limit_bytes 走 SIGTERM grace → SIGKILL。

    用法（Plan 05b-04 daemon_client 集成）::

        watchdog = SandboxWatchdog(
            pid=proc.pid,
            memory_limit_bytes=sandbox_config.memory_bytes,
            on_violation=lambda msg: client._fail_all_pending(
                SandboxLimitExceeded("memory", limit, actual)
            ),
        )
        watchdog.start()
        # ... daemon 运行 ...
        watchdog.stop()  # close() 时

    生命周期：
    1. `start()` 创建 asyncio task，任务名 `sandbox-watchdog[pid=<pid>]`
    2. `_loop()` 每 scan_interval 秒读 RSS
    3. RSS > memory_limit_bytes → on_violation callback → killpg(SIGTERM) → sleep grace
       → 仍存活 killpg(SIGKILL)
    4. RSS read 返回 None (进程已死) → 优雅退出（return）
    5. `stop()` 设 _stopped=True + task.cancel()

    Attributes:
        _pid: 监控的 daemon PID（必须 setsid 后的 PGID leader）
        _memory_limit_bytes: 触发阈值（bytes）
        _on_violation: 超限回调（同步函数，在 SIGTERM 之前调用）
        _scan_interval: 扫描周期秒数（默认 5.0）
        _grace_period: SIGTERM 后等待秒数（默认 3.0）
        _stopped: stop 标志
        _task: asyncio task handle
    """

    def __init__(
        self,
        pid: int,
        memory_limit_bytes: int,
        on_violation: Callable[[Exception], None] | None = None,
        *,
        scan_interval: float = _DEFAULT_SCAN_INTERVAL,
        grace_period: float = _DEFAULT_GRACE_PERIOD,
    ) -> None:
        """构造 watchdog（不实际启动；调 start() 才 spawn asyncio task）。

        Args:
            pid: 监控的 daemon PID（必须 PosixResourceSandbox spawn 的 PGID leader）
            memory_limit_bytes: 触发阈值（bytes）— SandboxConfig.memory_bytes 派生
            on_violation: 超限回调函数；签名 `Callable[[Exception], None]`
                          回调接收 `SandboxLimitExceeded` 实例；同步执行（不许 await）
                          典型用法：触发 daemon_client._fail_all_pending(exc) 让主 invoke
                          立即 raise 而不是等 daemon 死后 stdout EOF → PluginDaemonExitedError
            scan_interval: 扫描周期秒数（默认 5.0）— 不应 < 1.0（IO 占用）
            grace_period: SIGTERM 后等待秒数（默认 3.0）— 短于 systemd 90s 默认
        """
        self._pid = pid
        self._memory_limit_bytes = memory_limit_bytes
        self._on_violation = on_violation
        self._scan_interval = scan_interval
        self._grace_period = grace_period

        self._stopped = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """spawn asyncio task — 必须在 asyncio event loop 内调用。

        幂等：若 task 已存在且未 done，直接返回。
        """
        if self._task is not None and not self._task.done():
            return
        self._stopped = False
        self._task = asyncio.create_task(
            self._loop(), name=f"sandbox-watchdog[pid={self._pid}]"
        )
        _log.debug(
            "sandbox.watchdog.started pid=%s memory_limit=%d",
            self._pid,
            self._memory_limit_bytes,
        )

    def stop(self) -> None:
        """设 _stopped + cancel task — 幂等。

        不 await task；调用方需自行处理 task cancellation（典型在 daemon_client.close 内）。
        """
        self._stopped = True
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def scan_once(self) -> bool:
        """公共方法：执行一次扫描，返回是否检测到超限（仅用于测试）.

        Returns:
            True if RSS > memory_limit_bytes（已触发 on_violation + SIGTERM 序列），
            False if 未超限 or 进程已死。

        HIGH-4 fix：让单元测试可直接调用扫描逻辑，无需等待 asyncio sleep。
        """
        rss = _read_rss(self._pid)
        if rss is None:
            # 进程已死 — 不算超限
            return False
        if rss > self._memory_limit_bytes:
            await self._handle_violation(rss)
            return True
        return False

    async def _loop(self) -> None:
        """asyncio task 主循环 — 每 scan_interval 秒扫一次 RSS。

        退出条件：
        - _stopped 被 set（外部 stop 调用）
        - rss read 返回 None（进程已死）
        - 超限走完 SIGTERM → SIGKILL 路径后 break

        异常处理：
        - asyncio.CancelledError → re-raise（标准 task cancel 行为）
        - 其它 Exception → log warning + break（不让 task 静默死）
        """
        try:
            while not self._stopped:
                triggered = await self.scan_once()
                if triggered:
                    break  # 超限后退出循环（daemon 已 kill）
                # 检查进程是否已死
                if _read_rss(self._pid) is None:
                    _log.debug(
                        "sandbox.watchdog.process_exited pid=%s — watchdog exit", self._pid
                    )
                    break
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — 不让 task 静默死
            _log.warning(
                "sandbox.watchdog.crashed pid=%s err=%s — watchdog exit",
                self._pid,
                e,
            )

    async def _handle_violation(self, actual_rss: int) -> None:
        """检测到超限的处理流程：on_violation → SIGTERM → grace → SIGKILL.

        Steps:
        1. structured log `sandbox.limit_exceeded`
        2. on_violation callback（Pitfall 5：先于 SIGTERM 让主 invoke 立即 raise）
        3. os.killpg(pgid, SIGTERM)（Pitfall 4：整组 kill 防 fork 逃逸）
        4. await sleep(grace_period)
        5. 探活 os.kill(pid, 0)；ProcessLookupError → 优雅退出
        6. os.killpg(pgid, SIGKILL) 强杀 + structured log `sandbox.force_kill`

        Args:
            actual_rss: 触发的实际 RSS（bytes）— 用于 log + SandboxLimitExceeded
        """
        _log.warning(
            "sandbox.limit_exceeded pid=%s kind=memory limit_bytes=%d actual_bytes=%d",
            self._pid,
            self._memory_limit_bytes,
            actual_rss,
        )

        # Step 1: on_violation 先执行（Pitfall 5）— 让主 invoke 立即 raise
        if self._on_violation is not None:
            try:
                exc = SandboxLimitExceeded(
                    kind="memory",
                    limit=self._memory_limit_bytes,
                    actual=actual_rss,
                )
                self._on_violation(exc)
            except Exception as e:  # noqa: BLE001 — callback 不能阻塞 kill 路径
                _log.warning(
                    "sandbox.watchdog.on_violation_callback_failed pid=%s err=%s",
                    self._pid,
                    e,
                )

        # Step 2: killpg(SIGTERM) 整组（Pitfall 4）
        try:
            pgid = os.getpgid(self._pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError) as e:
            _log.debug(
                "sandbox.watchdog.sigterm_skipped pid=%s err=%s（进程可能已死）",
                self._pid,
                e,
            )
            return  # 进程已死，无需 SIGKILL

        # Step 3: grace 等待
        await asyncio.sleep(self._grace_period)

        # Step 4: 探活
        try:
            os.kill(self._pid, 0)  # signal 0 = 仅探活，不发实际信号
        except ProcessLookupError:
            _log.debug(
                "sandbox.watchdog.sigterm_succeeded pid=%s（grace 内退出）", self._pid
            )
            return  # 已死，无需 SIGKILL

        # Step 5: 仍存活，SIGKILL 强杀
        try:
            pgid = os.getpgid(self._pid)
            os.killpg(pgid, signal.SIGKILL)
            _log.warning(
                "sandbox.force_kill pid=%s grace_period=%.1fs — daemon ignored SIGTERM",
                self._pid,
                self._grace_period,
            )
        except (ProcessLookupError, PermissionError) as e:
            _log.debug(
                "sandbox.watchdog.sigkill_skipped pid=%s err=%s（进程可能刚死）",
                self._pid,
                e,
            )


__all__ = [
    "SandboxWatchdog",
    "_read_rss",
    "_read_rss_linux",
    "_read_rss_psutil",
    "_DEFAULT_SCAN_INTERVAL",
    "_DEFAULT_GRACE_PERIOD",
]
