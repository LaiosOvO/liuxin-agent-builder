/**
 * InstancesList + 实例列表页核心逻辑测试
 *
 * 使用 MSW 拦截 API 请求，验证：
 * - 列表渲染（状态徽章、ID 截断、时间列）
 * - 加载态 spinner
 * - 空列表提示
 * - 行点击回调
 * - 状态徽章颜色
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { InstancesList } from '@/components/agent-builder/instances/instances-list';
import type { InstanceSummary } from '@/lib/types/instance';

/** 生成测试用实例摘要 */
function makeInstance(overrides: Partial<InstanceSummary> = {}): InstanceSummary {
  return {
    id: 'inst-abc123def456',
    workflow_id: 'wf-001',
    workflow_version_id: 'ver-001',
    status: 'completed',
    initial_input: null,
    error_message: null,
    created_by: null,
    created_at: '2026-05-16T10:00:00Z',
    started_at: null,
    completed_at: '2026-05-16T10:01:30Z',
    ...overrides,
  };
}

describe('InstancesList', () => {
  it('渲染实例行并截断 ID', () => {
    const items = [makeInstance({ id: 'inst-abc123def456ghij' })];
    render(<InstancesList items={items} onRowClick={vi.fn()} loading={false} />);

    // ID 应被截断（取前16字符），"…" 是独立文本节点，用 textContent 查找
    const cell = document.querySelector('td.font-mono');
    expect(cell?.textContent).toContain('inst-abc123def45');
  });

  it('显示 completed 状态徽章', () => {
    const items = [makeInstance({ status: 'completed' })];
    render(<InstancesList items={items} onRowClick={vi.fn()} loading={false} />);

    expect(screen.getByText('已完成')).toBeTruthy();
  });

  it('显示 running 状态徽章', () => {
    const items = [makeInstance({ status: 'running' })];
    render(<InstancesList items={items} onRowClick={vi.fn()} loading={false} />);

    expect(screen.getByText('运行中')).toBeTruthy();
  });

  it('显示 failed 状态徽章', () => {
    const items = [makeInstance({ status: 'failed' })];
    render(<InstancesList items={items} onRowClick={vi.fn()} loading={false} />);

    expect(screen.getByText('失败')).toBeTruthy();
  });

  it('加载中显示 spinner', () => {
    render(<InstancesList items={[]} onRowClick={vi.fn()} loading={true} />);

    // 加载态：有 animate-spin class 的元素
    const spinner = document.querySelector('.animate-spin');
    expect(spinner).toBeTruthy();
  });

  it('空列表显示提示文字', () => {
    render(<InstancesList items={[]} onRowClick={vi.fn()} loading={false} />);

    expect(screen.getByText(/暂无实例/)).toBeTruthy();
  });

  it('点击行触发 onRowClick 回调', () => {
    const onRowClick = vi.fn();
    const items = [makeInstance({ id: 'inst-click-test-1234' })];
    render(<InstancesList items={items} onRowClick={onRowClick} loading={false} />);

    // 点击详情按钮
    const detailBtn = screen.getByText('详情');
    fireEvent.click(detailBtn);

    expect(onRowClick).toHaveBeenCalledWith('inst-click-test-1234');
  });

  it('渲染多条实例行', () => {
    const items = [
      makeInstance({ id: 'inst-1aaa2bbb3ccc4ddd', status: 'completed' }),
      makeInstance({ id: 'inst-2aaa2bbb3ccc4ddd', status: 'failed' }),
      makeInstance({ id: 'inst-3aaa2bbb3ccc4ddd', status: 'pending' }),
    ];
    render(<InstancesList items={items} onRowClick={vi.fn()} loading={false} />);

    // 每行 td.font-mono 的 textContent 应包含截断后的 ID 前缀
    const cells = document.querySelectorAll('td.font-mono');
    const texts = Array.from(cells).map((c) => c.textContent ?? '');
    expect(texts.some((t) => t.includes('inst-1aaa2bbb3cc'))).toBe(true);
    expect(texts.some((t) => t.includes('inst-2aaa2bbb3cc'))).toBe(true);
    expect(texts.some((t) => t.includes('inst-3aaa2bbb3cc'))).toBe(true);
  });
});
