/**
 * deadline-countdown.spec.tsx — DeadlineCountdown 单元测试
 *
 * 覆盖（3 用例）：
 * 1. test_displays_remaining_time_correctly — 渲染剩余时间
 * 2. test_displays_overdue_state_when_past_deadline — 超时后红色 + "已超时"
 * 3. test_calls_onTimeout_callback_when_deadline_crossed — 触发 onTimeout
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { DeadlineCountdown } from '@/components/hitl/deadline-countdown';

describe('DeadlineCountdown', () => {
  beforeEach(() => {
    // 用假定时器 + 固定 "now"，确保 setInterval 可控
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-05-17T10:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('test_displays_remaining_time_correctly: 倒计时显示剩余时间', () => {
    // deadline = now + 2h 30min
    const deadline = new Date('2026-05-17T12:30:00Z').toISOString();
    render(<DeadlineCountdown deadlineAt={deadline} />);

    // useEffect 触发后 nowMs 更新 — 立即推进 timers 让 effect 跑
    act(() => {
      vi.advanceTimersByTime(0);
    });

    const node = screen.getByTestId('countdown-text');
    expect(node.textContent).toContain('剩余');
    expect(node.textContent).toContain('2 小时');
    expect(node.textContent).toContain('30 分钟');

    // 非超时
    const root = screen.getByTestId('deadline-countdown');
    expect(root.getAttribute('data-overdue')).toBe('false');
  });

  it('test_displays_overdue_state_when_past_deadline: 已超时显示红色 + "已超时"', () => {
    // deadline = now - 1h（已过期）
    const deadline = new Date('2026-05-17T09:00:00Z').toISOString();
    render(<DeadlineCountdown deadlineAt={deadline} />);

    act(() => {
      vi.advanceTimersByTime(0);
    });

    const node = screen.getByTestId('countdown-text');
    expect(node.textContent).toContain('已超时');

    const root = screen.getByTestId('deadline-countdown');
    expect(root.getAttribute('data-overdue')).toBe('true');
    // 红色文本（Tailwind class）
    expect(root.className).toContain('red');
  });

  it('test_calls_onTimeout_callback_when_deadline_crossed: 跨越 deadline 触发 onTimeout', () => {
    // deadline = now + 3s
    const deadline = new Date('2026-05-17T10:00:03Z').toISOString();
    const onTimeout = vi.fn();

    render(
      <DeadlineCountdown deadlineAt={deadline} onTimeout={onTimeout} />,
    );

    // 初始仍未超时
    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(onTimeout).not.toHaveBeenCalled();

    // 推进 5 秒 → 跨越 deadline
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    // 至少触发一次（可能因 React useEffect 触发多次，但 ≥1 即可）
    expect(onTimeout).toHaveBeenCalled();
    expect(onTimeout.mock.calls.length).toBeGreaterThanOrEqual(1);

    // UI 也应切换到已超时
    const node = screen.getByTestId('countdown-text');
    expect(node.textContent).toContain('已超时');
  });
});
