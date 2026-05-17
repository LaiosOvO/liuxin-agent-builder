"""IdleDaemonReaper — 后台 asyncio task 扫描 idle daemon 自动 close（PLUG-FW-12）。

设计要点（RESEARCH §Pattern 5 + Pitfall 6 + reading doc §与本项目的关系）:

- **asyncio task 每 60s 扫所有 active daemon** — `get_daemons` callback 返回当前 daemon list
- **time.monotonic 不是 time.time**（Pitfall 6）— NTP 校正会让 wall clock 突跳，monotonic
  保证单调递增，不会让 last_invoke_at 突然变小误判 idle
- **跳过 _pending 非空 daemon**（Pitfall 6 防竞争）— 活跃 invoke 进行中不算 idle；
  即使 last_invoke_at 很久前，只要还有 pending future 就跳过
- **跳过 _proc is None daemon** — 未启动 daemon（已 close 重置）不需 close
- **close 失败 swallow** — 单 daemon 死掉不能让 reaper task 死；下次循环继续扫
- **structured log event** `sandbox.idle_reaped` 让运维 grep log 重建生命周期（借鉴 Dify
  install_task 状态追踪思路）

为什么不用 apscheduler / Celery beat：
- 20 行 asyncio.sleep + while 循环即可；apscheduler 800KB 大头依赖
- 主进程 event loop 内 task 与 daemon 生命周期对齐（主进程死，reaper 自动死）
- 不需要分布式调度（idle reaper 本地状态）

License: 100% 独立创作，借鉴 Dify uninstall 显式生命周期 API 设计哲学
        （AGPL-3.0 不拷代码，详见 docs/reading-dify-05b-04-watchdog-idle-reaper-2026-05-18.md）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..daemon_client import PlatformDaemonClient

_log = logging.getLogger(__name__)

# ── 默认参数 ──────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT_IDLE = 300.0
"""daemon idle 超 300s (5min) 自动 close — 与 RESEARCH 决策对齐.

与 SandboxConfig.timeout_idle 字段一致（默认 300, le=86400）。
manifest 可覆盖：实例化 reaper 时传 timeout_idle=sandbox_config.timeout_idle。
"""

_DEFAULT_SCAN_INTERVAL = 60.0
"""每 60s 扫一次所有 daemon — 与 RESEARCH 决策对齐.

100 daemon × 60s 扫描 = 1.67 scans/s（list 遍历 < 1ms）远低于 CPU 占用上限。
比 watchdog (5s) 宽 12x — idle 检测不需要高频。
"""


class IdleDaemonReaper:
    """asyncio task 扫描所有 daemon — last_invoke_at > timeout_idle 自动 close。

    用法（Plan 05b-04 daemon_client 集成或更高层 plugin manager 启动时）::

        reaper = IdleDaemonReaper(
            get_daemons=lambda: list(plugin_manager.active_daemons.values()),
            timeout_idle=300.0,
            scan_interval=60.0,
        )
        reaper.start()
        # ... 主进程运行 ...
        reaper.stop()  # shutdown 时

    生命周期：
    1. `start()` 创建 asyncio task，任务名 `sandbox-idle-reaper`
    2. `_loop()` 每 scan_interval 秒扫一次 get_daemons() 返回列表
    3. 跳过未启动（`_proc is None`）/ 活跃 invoke（`_pending` 非空）daemon
    4. `time.monotonic() - daemon.last_invoke_at > timeout_idle` → `await daemon.close()`
    5. close 失败 swallow log warning，不让 task 死
    6. `stop()` 设 _stopped + task.cancel()

    Attributes:
        _get_daemons: 返回当前所有 daemon 实例的 callback
        _timeout_idle: idle 阈值秒数（默认 300.0）
        _scan_interval: 扫描周期秒数（默认 60.0）
        _stopped: stop 标志
        _task: asyncio task handle
    """

    def __init__(
        self,
        get_daemons: Callable[[], list["PlatformDaemonClient"]],
        timeout_idle: float = _DEFAULT_TIMEOUT_IDLE,
        scan_interval: float = _DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """构造 reaper（不实际启动；调 start() 才 spawn asyncio task）。

        Args:
            get_daemons: 返回当前所有 daemon 实例列表的 callback
                         典型实现：`lambda: list(plugin_manager.daemons.values())`
                         调用时机：每次扫描循环开始时调一次（避免 reaper 维护自己的 list）
            timeout_idle: idle 阈值秒数（默认 300.0）— manifest sandbox.timeout_idle 派生
            scan_interval: 扫描周期秒数（默认 60.0）— 比 watchdog 5s 宽 12x
        """
        self._get_daemons = get_daemons
        self._timeout_idle = timeout_idle
        self._scan_interval = scan_interval

        self._stopped = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """spawn asyncio task — 必须在 asyncio event loop 内调用。

        幂等：若 task 已存在且未 done，直接返回。
        """
        if self._task is not None and not self._task.done():
            return
        self._stopped = False
        self._task = asyncio.create_task(self._loop(), name="sandbox-idle-reaper")
        _log.debug(
            "sandbox.idle_reaper.started timeout_idle=%.1fs scan_interval=%.1fs",
            self._timeout_idle,
            self._scan_interval,
        )

    def stop(self) -> None:
        """设 _stopped + cancel task — 幂等。

        不 await task；调用方需自行处理 cancellation（典型在 app shutdown handler）。
        """
        self._stopped = True
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def scan_once(self) -> int:
        """公共方法：执行一次扫描，返回 close 掉的 daemon 数量（仅用于测试）.

        Returns:
            被 close 的 daemon 数量（0 表示没有 idle daemon）

        HIGH-4 fix：让单元测试可直接调用扫描逻辑，无需等待 asyncio sleep 60s。
        """
        now = time.monotonic()
        reaped = 0

        daemons = self._get_daemons()
        for daemon in daemons:
            # 跳过未启动 daemon
            if getattr(daemon, "_proc", None) is None:
                continue

            # 跳过活跃 invoke（Pitfall 6 防竞争）
            pending = getattr(daemon, "_pending", None)
            if pending:
                continue

            last = getattr(daemon, "last_invoke_at", None)
            if last is None:
                # 未跟踪 last_invoke_at 的 daemon（5.A 兼容路径），跳过
                continue

            if now - last <= self._timeout_idle:
                continue

            # 触发 close
            idle_secs = now - last
            module = getattr(daemon, "_module_entry", "<unknown>")
            _log.info(
                "sandbox.idle_reaped daemon=%s idle_secs=%.1f timeout=%.1f",
                module,
                idle_secs,
                self._timeout_idle,
            )

            try:
                await daemon.close()
                reaped += 1
            except Exception as e:  # noqa: BLE001 — 单 daemon 死掉不让 reaper 死
                _log.warning(
                    "sandbox.idle_reaper.close_failed daemon=%s err=%s",
                    module,
                    e,
                )

        return reaped

    async def _loop(self) -> None:
        """asyncio task 主循环 — 每 scan_interval 秒扫一次所有 daemon。

        异常处理：
        - asyncio.CancelledError → re-raise（标准 task cancel 行为）
        - 其它 Exception → log warning + continue（reaper 不许因单次循环错误死）
        """
        try:
            while not self._stopped:
                try:
                    await self.scan_once()
                except Exception as e:  # noqa: BLE001 — reaper 不死
                    _log.warning(
                        "sandbox.idle_reaper.scan_failed err=%s — continue next cycle",
                        e,
                    )
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            raise


__all__ = [
    "IdleDaemonReaper",
    "_DEFAULT_TIMEOUT_IDLE",
    "_DEFAULT_SCAN_INTERVAL",
]
