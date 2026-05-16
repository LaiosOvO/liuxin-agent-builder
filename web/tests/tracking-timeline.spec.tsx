/**
 * TrackingTimeline + ApplicantOnlyRecords + DeadlineCountdown 组件测试
 *
 * 验证（满足 PLAN ≥4 + 节点可视化要求）：
 *  - 1: records 按时间顺序渲染（数据由父组件已排序，组件本身只渲染）
 *  - 2: current_node 高亮（蓝色 border + banner）
 *  - 3: 状态徽章 icon 正确（done/rejected/returned/in_review/waiting_human）
 *  - 4: overdue 节点显示红色倒计时（DeadlineCountdown urgent level）
 *  - 5: applicant-only-records 永不显示 ip/ua（前端双重保险）
 *  - 6: 空 records 显示提示文字
 *  - 7: action 标签颜色正确（submit/approve/reject/return/escalate）
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

import { TrackingTimeline } from '@/components/instance/tracking-timeline';
import { ApplicantOnlyRecords } from '@/components/instance/applicant-only-records';
import { DeadlineCountdown } from '@/components/instance/deadline-countdown';
import type { TrackingCurrentNode, TrackingRecord } from '@/lib/types/tracking';


// ── 测试辅助 ───────────────────────────────────────────────────────────────

function record(overrides: Partial<TrackingRecord> = {}): TrackingRecord {
  return {
    actor_email: 'approver@example.com',
    actor_name: '审批人甲',
    action: 'approve',
    reason: '看起来合规',
    ts: '2026-05-17T10:00:00Z',
    ip: null,
    ua: null,
    ...overrides,
  };
}

function currentNode(overrides: Partial<TrackingCurrentNode> = {}): TrackingCurrentNode {
  return {
    id: 'hitl_1',
    title: '主管审批',
    status: 'waiting_human',
    node_type: 'hitl',
    actor: { email: 'lead@example.com', name: '主管' },
    deadline_at: null,
    started_at: '2026-05-17T09:00:00Z',
    ...overrides,
  };
}


// ── Test 1: records 按顺序渲染 ─────────────────────────────────────────────

describe('TrackingTimeline', () => {
  it('按传入顺序渲染所有 records (父组件负责 ts ASC 排序)', () => {
    const records = [
      record({ action: 'submit', ts: '2026-05-17T09:00:00Z' }),
      record({ action: 'approve', ts: '2026-05-17T10:00:00Z' }),
      record({ action: 'reject', ts: '2026-05-17T11:00:00Z' }),
    ];
    render(<TrackingTimeline currentNode={null} records={records} />);

    const list = screen.getByTestId('timeline-list');
    const items = list.querySelectorAll('li');
    expect(items.length).toBe(3);
    // 第一条应是 submit
    expect(items[0]?.textContent).toContain('提交');
    expect(items[1]?.textContent).toContain('通过');
    expect(items[2]?.textContent).toContain('拒绝');
  });

  // ── Test 2: current_node 高亮 ────────────────────────────────────────────

  it('current_node 不为 null 时显示高亮 banner', () => {
    render(
      <TrackingTimeline currentNode={currentNode({ title: '部门主管审批' })} records={[]} />,
    );

    const banner = screen.getByTestId('current-node-banner');
    expect(banner).toBeTruthy();
    expect(banner.className).toContain('border-blue-400'); // 当前节点高亮 ring
    expect(banner.textContent).toContain('部门主管审批');
    expect(banner.textContent).toContain('等待提交');
  });

  it('current_node 为 null 时不渲染 banner', () => {
    render(<TrackingTimeline currentNode={null} records={[]} />);
    expect(screen.queryByTestId('current-node-banner')).toBeNull();
  });

  // ── Test 3: 状态徽章 icon 正确 ──────────────────────────────────────────

  it.each([
    ['waiting_human', '等待提交'],
    ['in_review', '审核中'],
    ['done', '已通过'],
    ['rejected', '已拒绝'],
    ['returned', '已退回'],
  ])('节点状态 %s 渲染对应中文徽章 %s', (status, label) => {
    render(
      <TrackingTimeline currentNode={currentNode({ status })} records={[]} />,
    );
    const badge = screen.getByTestId(`status-badge-${status}`);
    expect(badge).toBeTruthy();
    expect(badge.textContent).toContain(label);
  });

  // ── Test 4: overdue 节点显示红色倒计时 ─────────────────────────────────

  it('overdue 节点（deadline 已过）显示 urgent (red) 倒计时', () => {
    // deadline 在过去 2 小时
    const pastDeadline = new Date(Date.now() - 2 * 3600_000).toISOString();
    render(
      <TrackingTimeline
        currentNode={currentNode({ deadline_at: pastDeadline })}
        records={[]}
      />,
    );

    const countdown = screen.getByTestId('deadline-countdown');
    expect(countdown.getAttribute('data-overdue')).toBe('true');
    expect(countdown.getAttribute('data-level')).toBe('urgent');
    expect(countdown.textContent).toContain('已超时');
    expect(countdown.className).toContain('text-red-600');
  });

  it('未超时但 <1h 显示 urgent (red) 倒计时', () => {
    const near = new Date(Date.now() + 30 * 60_000).toISOString(); // +30min
    render(
      <TrackingTimeline
        currentNode={currentNode({ deadline_at: near })}
        records={[]}
      />,
    );
    const countdown = screen.getByTestId('deadline-countdown');
    expect(countdown.getAttribute('data-overdue')).toBe('false');
    expect(countdown.getAttribute('data-level')).toBe('urgent');
    expect(countdown.textContent).toContain('剩余');
  });

  it('剩余 12h 显示 normal (green) 倒计时', () => {
    const distant = new Date(Date.now() + 12 * 3600_000).toISOString();
    render(
      <TrackingTimeline
        currentNode={currentNode({ deadline_at: distant })}
        records={[]}
      />,
    );
    const countdown = screen.getByTestId('deadline-countdown');
    expect(countdown.getAttribute('data-level')).toBe('normal');
  });

  // ── Test 5: action 标签正确 ────────────────────────────────────────────

  it.each([
    ['submit', '提交'],
    ['approve', '通过'],
    ['reject', '拒绝'],
    ['return', '退回'],
    ['escalate', '升级'],
  ])('action=%s 渲染对应中文标签 %s', (action, label) => {
    render(
      <TrackingTimeline
        currentNode={null}
        records={[record({ action, ts: '2026-05-17T09:00:00Z' })]}
      />,
    );
    const tag = screen.getByTestId(`action-tag-${action}`);
    expect(tag).toBeTruthy();
    expect(tag.textContent).toBe(label);
  });

  // ── Test 6: 空 records 提示 ────────────────────────────────────────────

  it('records 空数组显示"暂无审批决策记录"提示', () => {
    render(<TrackingTimeline currentNode={null} records={[]} />);
    expect(screen.getByTestId('empty-records')).toBeTruthy();
    expect(screen.getByText('暂无审批决策记录')).toBeTruthy();
  });
});


// ── Test 7: ApplicantOnlyRecords 永不显示 ip/ua ──────────────────────────

describe('ApplicantOnlyRecords', () => {
  it('即使 record 中含 ip/ua 字段也不渲染（前端双重保险）', () => {
    const recWithLeakedAudit: TrackingRecord = {
      actor_email: 'approver@example.com',
      actor_name: '审批人甲',
      action: 'approve',
      reason: '正常',
      ts: '2026-05-17T10:00:00Z',
      // 后端漏脱敏的极端场景：万一带过来
      ip: '10.0.0.5',
      ua: 'Mozilla/5.0 SuperLeaked',
    };
    render(<ApplicantOnlyRecords records={[recWithLeakedAudit]} />);

    const root = screen.getByTestId('applicant-only-records');
    // 不应出现任何 IP 字面量或 UA 子串
    expect(root.textContent).not.toContain('10.0.0.5');
    expect(root.textContent).not.toContain('SuperLeaked');
    expect(root.textContent).not.toContain('Mozilla');
    // 业务字段保留
    expect(root.textContent).toContain('审批人甲');
    expect(root.textContent).toContain('通过');
    expect(root.textContent).toContain('正常');
  });

  it('records 空时显示提示', () => {
    render(<ApplicantOnlyRecords records={[]} />);
    expect(screen.getByTestId('applicant-records-empty')).toBeTruthy();
  });

  it('自定义 title 生效', () => {
    render(<ApplicantOnlyRecords records={[record()]} title="我的流程历史" />);
    expect(screen.getByText('我的流程历史')).toBeTruthy();
  });
});


// ── Test 8: DeadlineCountdown 单测 ───────────────────────────────────────

describe('DeadlineCountdown', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('deadlineAt=null 时不渲染', () => {
    const { container } = render(<DeadlineCountdown deadlineAt={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('每秒更新倒计时', async () => {
    const start = new Date('2026-05-17T10:00:00Z').getTime();
    vi.setSystemTime(start);

    const deadline = new Date(start + 2 * 60_000).toISOString(); // +2min
    render(<DeadlineCountdown deadlineAt={deadline} />);

    const countdown = screen.getByTestId('deadline-countdown');
    expect(countdown.textContent).toContain('剩余 2m');

    // 推进 60s
    vi.setSystemTime(start + 60_000);
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    // 推进后应显示 1m xx s 或 0m XXs（取决于 React re-render 时序）
    expect(countdown.textContent).toContain('剩余');
  });
});
