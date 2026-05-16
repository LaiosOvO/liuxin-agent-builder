/**
 * records-timeline.spec.tsx — RecordsTimeline 单元测试
 *
 * 覆盖（3 用例）：
 * 1. test_renders_records_in_reverse_chronological_order — 倒序展示
 * 2. test_empty_state_shows_placeholder — 空数据占位
 * 3. test_action_chip_color_correct — 5 种 action 颜色映射
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecordsTimeline } from '@/components/hitl/records-timeline';
import type { HitlRecord } from '@/lib/types/hitl';

describe('RecordsTimeline', () => {
  it('test_renders_records_in_reverse_chronological_order: 倒序展示（最新在上）', () => {
    const records: HitlRecord[] = [
      {
        actor_email: 'alice@example.com',
        action: 'submit',
        ts: '2026-05-15T10:00:00Z',
      },
      {
        actor_email: 'bob@example.com',
        action: 'approve',
        ts: '2026-05-16T12:00:00Z',
        reason: 'looks good',
      },
      {
        actor_email: 'carol@example.com',
        action: 'return',
        ts: '2026-05-17T08:00:00Z',
        reason: '需要补充材料',
      },
    ];

    render(<RecordsTimeline records={records} />);

    const items = screen.getAllByTestId('record-item');
    expect(items.length).toBe(3);
    // 倒序：carol（2026-05-17）→ bob（2026-05-16）→ alice（2026-05-15）
    expect(items[0].textContent).toContain('carol@example.com');
    expect(items[0].textContent).toContain('退回');
    expect(items[0].textContent).toContain('需要补充材料');
    expect(items[1].textContent).toContain('bob@example.com');
    expect(items[1].textContent).toContain('通过');
    expect(items[2].textContent).toContain('alice@example.com');
    expect(items[2].textContent).toContain('提交');
  });

  it('test_empty_state_shows_placeholder: 列表为空显示占位提示', () => {
    render(<RecordsTimeline records={[]} />);
    expect(screen.getByTestId('records-empty')).toBeDefined();
    expect(screen.getByText('暂无历史决策')).toBeDefined();
  });

  it('test_action_chip_color_correct: 5 种 action 颜色映射正确', () => {
    const records: HitlRecord[] = [
      { actor_email: 'a@a', action: 'submit', ts: '2026-05-15T10:00:00Z' },
      { actor_email: 'b@b', action: 'approve', ts: '2026-05-15T11:00:00Z' },
      { actor_email: 'c@c', action: 'return', ts: '2026-05-15T12:00:00Z' },
      { actor_email: 'd@d', action: 'reject', ts: '2026-05-15T13:00:00Z' },
      { actor_email: 'e@e', action: 'escalate', ts: '2026-05-15T14:00:00Z' },
    ];
    render(<RecordsTimeline records={records} />);

    const items = screen.getAllByTestId('record-item');
    // Sorted reverse-chrono: escalate (14:00) -> reject (13:00) -> return (12:00) -> approve (11:00) -> submit (10:00)
    expect(items[0].getAttribute('data-action')).toBe('escalate');
    const chip0 = items[0].querySelector('[data-testid="action-chip"]') as HTMLElement;
    expect(chip0.className).toContain('purple');

    expect(items[1].getAttribute('data-action')).toBe('reject');
    const chip1 = items[1].querySelector('[data-testid="action-chip"]') as HTMLElement;
    expect(chip1.className).toContain('red');

    expect(items[2].getAttribute('data-action')).toBe('return');
    const chip2 = items[2].querySelector('[data-testid="action-chip"]') as HTMLElement;
    expect(chip2.className).toContain('amber');

    expect(items[3].getAttribute('data-action')).toBe('approve');
    const chip3 = items[3].querySelector('[data-testid="action-chip"]') as HTMLElement;
    expect(chip3.className).toContain('emerald');

    expect(items[4].getAttribute('data-action')).toBe('submit');
    const chip4 = items[4].querySelector('[data-testid="action-chip"]') as HTMLElement;
    expect(chip4.className).toContain('blue');
  });
});
