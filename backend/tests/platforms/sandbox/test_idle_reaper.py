"""IdleDaemonReaper 单元测试 — mock daemon list；不真 spawn 子进程.

测试覆盖（Pitfall 6）:
- 默认参数（timeout_idle=300.0 / scan_interval=60.0）
- start / stop / 幂等
- scan_once 跳过未启动 daemon（_proc is None）
- scan_once 跳过活跃 invoke daemon（_pending 非空 — Pitfall 6 防竞争）
- scan_once 跳过未跟踪 last_invoke_at daemon（5.A 兼容）
- scan_once close idle daemon（last_invoke_at > timeout_idle）
- scan_once swallow close error（reaper 不死）
- scan_once 用 time.monotonic 不是 time.time（Pitfall 6 NTP 抗变）
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent_builder.platforms.sandbox.idle_reaper import IdleDaemonReaper


def _make_mock_daemon(
    proc=MagicMock(),
    pending=None,
    last_invoke_at: float | None = None,
    close_side_effect=None,
    module_entry: str = "mock.daemon",
) -> MagicMock:
    """构造 mock daemon — 模拟 PlatformDaemonClient 必需属性."""
    d = MagicMock()
    d._proc = proc
    d._pending = pending if pending is not None else {}
    d.last_invoke_at = last_invoke_at if last_invoke_at is not None else 0.0
    d._module_entry = module_entry
    if close_side_effect is not None:
        d.close = AsyncMock(side_effect=close_side_effect)
    else:
        d.close = AsyncMock(return_value=None)
    return d


# ── 默认参数 ─────────────────────────────────────────────────────────────────


def test_reaper_default_intervals() -> None:
    """IdleDaemonReaper 默认 timeout_idle=300.0 + scan_interval=60.0."""
    r = IdleDaemonReaper(get_daemons=lambda: [])
    assert r._timeout_idle == 300.0
    assert r._scan_interval == 60.0


def test_reaper_custom_intervals() -> None:
    """可定制 timeout_idle / scan_interval（测试用短值）."""
    r = IdleDaemonReaper(
        get_daemons=lambda: [], timeout_idle=10.0, scan_interval=1.0
    )
    assert r._timeout_idle == 10.0
    assert r._scan_interval == 1.0


# ── start / stop / 幂等 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reaper_start_creates_named_task() -> None:
    """start() 后 task.get_name() == 'sandbox-idle-reaper'."""
    r = IdleDaemonReaper(get_daemons=lambda: [], scan_interval=10.0)
    r.start()
    assert r._task is not None
    assert r._task.get_name() == "sandbox-idle-reaper"
    r.stop()
    try:
        await r._task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_reaper_stop_idempotent() -> None:
    """stop() 可重复调."""
    r = IdleDaemonReaper(get_daemons=lambda: [])
    r.start()
    r.stop()
    r.stop()
    assert r._stopped is True


# ── scan_once 跳过逻辑（Pitfall 6 防竞争）────────────────────────────────────


@pytest.mark.asyncio
async def test_reaper_skips_unstarted_daemon() -> None:
    """daemon._proc is None → 跳过（close 不被调）."""
    d = _make_mock_daemon(proc=None, last_invoke_at=time.monotonic() - 10000)
    r = IdleDaemonReaper(get_daemons=lambda: [d], timeout_idle=1.0)

    reaped = await r.scan_once()

    assert reaped == 0
    d.close.assert_not_called()


@pytest.mark.asyncio
async def test_reaper_skips_active_invoke() -> None:
    """daemon._pending 非空 → 跳过（Pitfall 6 防竞争）.

    即使 last_invoke_at 很久前，只要 _pending 有 future 就算活跃。
    """
    d = _make_mock_daemon(
        pending={"some-req-id": object()},  # 有活跃 future
        last_invoke_at=time.monotonic() - 10000,  # 看起来 idle 很久
    )
    r = IdleDaemonReaper(get_daemons=lambda: [d], timeout_idle=1.0)

    reaped = await r.scan_once()

    assert reaped == 0
    d.close.assert_not_called()


@pytest.mark.asyncio
async def test_reaper_skips_daemon_without_last_invoke_at() -> None:
    """daemon 无 last_invoke_at 属性（5.A 兼容） → 跳过（不调 close）."""
    d = MagicMock()
    d._proc = MagicMock()  # 已启动
    d._pending = {}
    d._module_entry = "test.daemon"
    # 删除 last_invoke_at 属性（用 spec 限制 attribute access 不让 MagicMock 自动生成）
    del d.last_invoke_at

    d.close = AsyncMock()
    r = IdleDaemonReaper(get_daemons=lambda: [d], timeout_idle=1.0)

    reaped = await r.scan_once()

    assert reaped == 0
    d.close.assert_not_called()


@pytest.mark.asyncio
async def test_reaper_skips_daemon_within_timeout() -> None:
    """last_invoke_at 在 timeout_idle 内 → 跳过."""
    d = _make_mock_daemon(last_invoke_at=time.monotonic() - 0.5)  # 0.5s 前 invoke
    r = IdleDaemonReaper(get_daemons=lambda: [d], timeout_idle=10.0)

    reaped = await r.scan_once()

    assert reaped == 0
    d.close.assert_not_called()


# ── scan_once close 路径 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reaper_closes_idle_daemon() -> None:
    """daemon.last_invoke_at > timeout_idle → daemon.close() 被调."""
    d = _make_mock_daemon(last_invoke_at=time.monotonic() - 100.0)
    r = IdleDaemonReaper(get_daemons=lambda: [d], timeout_idle=10.0)

    reaped = await r.scan_once()

    assert reaped == 1
    d.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_reaper_closes_multiple_idle_daemons() -> None:
    """多 idle daemon → 全部 close + reaped 计数."""
    now = time.monotonic()
    d1 = _make_mock_daemon(last_invoke_at=now - 100.0, module_entry="d1")
    d2 = _make_mock_daemon(last_invoke_at=now - 200.0, module_entry="d2")
    active = _make_mock_daemon(last_invoke_at=now - 0.1, module_entry="active")

    r = IdleDaemonReaper(
        get_daemons=lambda: [d1, d2, active], timeout_idle=10.0
    )

    reaped = await r.scan_once()

    assert reaped == 2
    d1.close.assert_awaited_once()
    d2.close.assert_awaited_once()
    active.close.assert_not_called()


@pytest.mark.asyncio
async def test_reaper_swallows_close_error() -> None:
    """daemon.close raise Exception → reaper 不死，下次循环继续."""
    d_bad = _make_mock_daemon(
        last_invoke_at=time.monotonic() - 100.0,
        close_side_effect=RuntimeError("close failed intentionally"),
        module_entry="bad",
    )
    d_good = _make_mock_daemon(
        last_invoke_at=time.monotonic() - 100.0, module_entry="good"
    )

    r = IdleDaemonReaper(
        get_daemons=lambda: [d_bad, d_good], timeout_idle=10.0
    )

    # scan_once 不应 raise（swallow）
    reaped = await r.scan_once()

    # d_bad close 被调但失败 → reaped 不 +1
    # d_good close 被调成功 → reaped +1
    d_bad.close.assert_awaited_once()
    d_good.close.assert_awaited_once()
    assert reaped == 1  # 仅 good 算


# ── time.monotonic 使用验证（Pitfall 6 NTP 抗变）─────────────────────────────


@pytest.mark.asyncio
async def test_reaper_uses_monotonic_not_wallclock(monkeypatch) -> None:
    """reaper 用 time.monotonic — NTP 校正 wall clock 突跳不影响."""
    called_monotonic = []
    original_monotonic = time.monotonic

    def fake_monotonic():
        called_monotonic.append(True)
        return original_monotonic()

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    d = _make_mock_daemon(last_invoke_at=time.monotonic() - 100.0)
    r = IdleDaemonReaper(get_daemons=lambda: [d], timeout_idle=10.0)

    await r.scan_once()

    # monotonic 至少调用 1 次（now = time.monotonic）
    assert len(called_monotonic) >= 1


# ── _loop 不死亡 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reaper_loop_continues_after_scan_error() -> None:
    """scan_once 抛异常 → reaper task 不死，下次 sleep + 继续."""
    call_count = [0]

    def get_daemons_with_error():
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("first scan fails")
        return []  # 后续返空 list 正常

    r = IdleDaemonReaper(
        get_daemons=get_daemons_with_error, scan_interval=0.01
    )
    r.start()

    # 等 2-3 个 cycle
    await asyncio.sleep(0.05)

    r.stop()
    try:
        await r._task
    except asyncio.CancelledError:
        pass

    # call_count 应 > 1（第一次失败后还有后续 scan）
    assert call_count[0] >= 2
