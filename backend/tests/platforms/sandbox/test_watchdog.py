"""SandboxWatchdog 单元测试 — mock pid + on_violation callback；不真 spawn 子进程.

测试覆盖（Pitfall 4/5）:
- 默认参数（scan_interval=5.0 / grace_period=3.0）
- start() 创建 named asyncio task（含 pid）
- stop() 取消 task + 幂等
- _read_rss 死 pid 返 None（FileNotFoundError swallow）
- scan_once 检测超限 → on_violation 调用 + SIGTERM 发送（验证调用顺序 Pitfall 5）
- scan_once 未超限 → on_violation 不调

注意：本测试不真 spawn 受限子进程（Linux only enforcement 在 integration test 跑）；
仅验证 SandboxWatchdog 控制流（callback 顺序 / API 形态 / async lifecycle）。
"""

from __future__ import annotations

import asyncio
import os
import signal
from unittest.mock import MagicMock, patch

import pytest

from app.agent_builder.platforms.exceptions import SandboxLimitExceeded
from app.agent_builder.platforms.sandbox.watchdog import (
    SandboxWatchdog,
    _read_rss,
    _read_rss_linux,
)


# ── 默认参数 ─────────────────────────────────────────────────────────────────


def test_watchdog_default_intervals() -> None:
    """SandboxWatchdog 默认 scan_interval=5.0 + grace_period=3.0."""
    w = SandboxWatchdog(pid=1, memory_limit_bytes=1024**3)
    assert w._scan_interval == 5.0
    assert w._grace_period == 3.0


def test_watchdog_custom_intervals() -> None:
    """可定制 scan_interval / grace_period（测试用短值）."""
    w = SandboxWatchdog(
        pid=1, memory_limit_bytes=1024**3, scan_interval=0.1, grace_period=0.2
    )
    assert w._scan_interval == 0.1
    assert w._grace_period == 0.2


# ── start / stop / task lifecycle ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_watchdog_start_creates_named_task() -> None:
    """start() 后 task.get_name() 含 'sandbox-watchdog[pid='."""
    w = SandboxWatchdog(pid=12345, memory_limit_bytes=1024**3, scan_interval=0.05)
    w.start()
    assert w._task is not None
    name = w._task.get_name()
    assert "sandbox-watchdog[pid=12345]" in name, (
        f"task name should contain pid, got {name}"
    )
    w.stop()
    # 等 cancel 完成
    try:
        await w._task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_watchdog_stop_cancels_task() -> None:
    """start → stop → task.cancelled() == True (or task.done())."""
    w = SandboxWatchdog(pid=12345, memory_limit_bytes=1024**3, scan_interval=10.0)
    w.start()
    await asyncio.sleep(0.01)  # 让 task 启动
    w.stop()
    await asyncio.sleep(0.05)  # 让 cancel 生效
    assert w._task is not None
    assert w._task.cancelled() or w._task.done()


@pytest.mark.asyncio
async def test_watchdog_stop_idempotent() -> None:
    """stop() 可重复调，无副作用."""
    w = SandboxWatchdog(pid=12345, memory_limit_bytes=1024**3)
    w.start()
    w.stop()
    w.stop()  # 第二次不报错
    assert w._stopped is True


@pytest.mark.asyncio
async def test_watchdog_start_idempotent() -> None:
    """start() 可重复调，不重复 spawn task."""
    w = SandboxWatchdog(pid=12345, memory_limit_bytes=1024**3, scan_interval=10.0)
    w.start()
    task1 = w._task
    w.start()  # 第二次 — 应该返回不重复
    task2 = w._task
    assert task1 is task2  # 同一个 task
    w.stop()
    try:
        await w._task
    except asyncio.CancelledError:
        pass


# ── _read_rss 死 pid 返 None ─────────────────────────────────────────────────


def test_watchdog_read_rss_returns_none_for_dead_pid() -> None:
    """pid=999999 不存在 → _read_rss 返回 None（FileNotFoundError swallow）."""
    # 用一个肯定不存在的 pid（Linux PID_MAX 通常 ≤ 4M）
    result = _read_rss(999999999)
    assert result is None


def test_watchdog_read_rss_linux_returns_none_for_dead_pid() -> None:
    """Linux 路径：_read_rss_linux(dead_pid) 返 None（不 raise）."""
    result = _read_rss_linux(999999999)
    assert result is None


# ── scan_once：超限 → on_violation + SIGTERM 顺序（Pitfall 5）─────────────────


@pytest.mark.asyncio
async def test_watchdog_scan_once_no_violation_when_under_limit() -> None:
    """scan_once: RSS < limit → on_violation 不调，返 False."""
    callback_calls = []

    def callback(exc):
        callback_calls.append(exc)

    w = SandboxWatchdog(
        pid=12345,
        memory_limit_bytes=1024 * 1024 * 100,  # 100MB
        on_violation=callback,
    )

    # mock _read_rss 返 50MB（低于 limit）
    with patch(
        "app.agent_builder.platforms.sandbox.watchdog._read_rss",
        return_value=50 * 1024 * 1024,
    ):
        triggered = await w.scan_once()

    assert triggered is False
    assert callback_calls == []


@pytest.mark.asyncio
async def test_watchdog_scan_once_returns_false_when_pid_dead() -> None:
    """scan_once: _read_rss 返 None（进程已死） → 返 False + on_violation 不调."""
    callback_calls = []

    def callback(exc):
        callback_calls.append(exc)

    w = SandboxWatchdog(pid=12345, memory_limit_bytes=1024**3, on_violation=callback)

    with patch(
        "app.agent_builder.platforms.sandbox.watchdog._read_rss", return_value=None
    ):
        triggered = await w.scan_once()

    assert triggered is False
    assert callback_calls == []


@pytest.mark.asyncio
async def test_watchdog_on_violation_callback_called_before_sigterm() -> None:
    """**Pitfall 5 关键**：on_violation callback 先于 SIGTERM 触发.

    验证顺序：callback 在 killpg(SIGTERM) 之前被调用，让主 invoke 立即 raise
    SandboxLimitExceeded 而不依赖 race condition。
    """
    call_order = []

    def callback(exc):
        assert isinstance(exc, SandboxLimitExceeded)
        assert exc.kind == "memory"
        assert exc.actual == 200 * 1024 * 1024  # 200MB
        assert exc.limit == 100 * 1024 * 1024  # 100MB limit
        call_order.append("callback")

    w = SandboxWatchdog(
        pid=12345,
        memory_limit_bytes=100 * 1024 * 1024,
        on_violation=callback,
        grace_period=0.01,  # 让测试快
    )

    # mock：_read_rss 返超限值 + killpg/os.kill 拦截不真发信号
    with (
        patch(
            "app.agent_builder.platforms.sandbox.watchdog._read_rss",
            return_value=200 * 1024 * 1024,
        ),
        patch("os.killpg") as mock_killpg,
        patch("os.getpgid", return_value=12345),
        patch("os.kill", side_effect=ProcessLookupError),  # 模拟 grace 后进程已死
    ):
        triggered = await w.scan_once()

    # callback 应该被调过（先于 SIGTERM）
    assert call_order == ["callback"]
    assert triggered is True
    # killpg 应被调（SIGTERM）— callback 之后
    assert mock_killpg.call_count >= 1
    # 第一次 killpg 应是 SIGTERM
    first_call = mock_killpg.call_args_list[0]
    assert first_call[0][1] == signal.SIGTERM


@pytest.mark.asyncio
async def test_watchdog_sigkill_after_grace_when_sigterm_ignored() -> None:
    """SIGTERM 后探活仍存活 → SIGKILL 强杀.

    模拟 daemon 忽略 SIGTERM 场景。
    """
    w = SandboxWatchdog(
        pid=12345,
        memory_limit_bytes=100 * 1024 * 1024,
        grace_period=0.01,
    )

    with (
        patch(
            "app.agent_builder.platforms.sandbox.watchdog._read_rss",
            return_value=200 * 1024 * 1024,
        ),
        patch("os.killpg") as mock_killpg,
        patch("os.getpgid", return_value=12345),
        patch("os.kill", return_value=None),  # 探活成功 — 进程还活着
    ):
        await w.scan_once()

    # killpg 至少 2 次：SIGTERM + SIGKILL
    assert mock_killpg.call_count == 2
    signals = [call[0][1] for call in mock_killpg.call_args_list]
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals


@pytest.mark.asyncio
async def test_watchdog_callback_exception_does_not_block_kill() -> None:
    """on_violation callback raise 异常 → 不阻塞 SIGTERM 路径."""

    def failing_callback(exc):
        raise RuntimeError("callback intentionally fails")

    w = SandboxWatchdog(
        pid=12345,
        memory_limit_bytes=100 * 1024 * 1024,
        on_violation=failing_callback,
        grace_period=0.01,
    )

    with (
        patch(
            "app.agent_builder.platforms.sandbox.watchdog._read_rss",
            return_value=200 * 1024 * 1024,
        ),
        patch("os.killpg") as mock_killpg,
        patch("os.getpgid", return_value=12345),
        patch("os.kill", side_effect=ProcessLookupError),
    ):
        # 不应 raise — callback 异常 swallow
        triggered = await w.scan_once()

    assert triggered is True
    assert mock_killpg.call_count >= 1


# ── _loop 退出条件 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_watchdog_loop_exits_when_process_dead() -> None:
    """_loop 检测进程已死（_read_rss 返 None）→ 优雅 break + task done."""
    w = SandboxWatchdog(pid=99999999, memory_limit_bytes=1024**3, scan_interval=0.01)
    w.start()
    # 等 scan 几次 + 检测死 pid 退出
    await asyncio.sleep(0.1)
    assert w._task is not None
    assert w._task.done()
    # task 应正常 return（不是 cancelled）
    assert not w._task.cancelled()
