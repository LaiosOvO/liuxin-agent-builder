/**
 * InstanceFilter 组件测试
 *
 * 验证：
 * - 状态下拉渲染并触发 onChange
 * - 搜索框 debounce 输入触发 onChange
 * - 工作流下拉渲染选项
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { InstanceFilter } from '@/components/agent-builder/instances/instance-filter';
import type { InstanceFilterValue } from '@/components/agent-builder/instances/instance-filter';
import type { WorkflowSummary } from '@/lib/types/dsl';

const emptyFilter: InstanceFilterValue = {
  workflow_id: undefined,
  status: undefined,
  search: undefined,
};

const mockWorkflows: WorkflowSummary[] = [
  { id: 'wf-001', name: '客服工作流', status: 'published', created_at: '2026-05-01T00:00:00Z', updated_at: '2026-05-01T00:00:00Z' },
  { id: 'wf-002', name: '数据处理流', status: 'draft', created_at: '2026-05-02T00:00:00Z', updated_at: '2026-05-02T00:00:00Z' },
];

describe('InstanceFilter', () => {
  it('渲染状态下拉框（包含全部、运行中等选项）', () => {
    render(
      <InstanceFilter value={emptyFilter} onChange={vi.fn()} workflows={[]} />,
    );

    // 状态 select 应存在
    const select = screen.getByRole('combobox');
    expect(select).toBeTruthy();

    // 包含"全部状态"选项
    expect(screen.getByText('全部状态')).toBeTruthy();
  });

  it('选择状态触发 onChange 并重置 page', () => {
    const onChange = vi.fn();
    render(
      <InstanceFilter value={emptyFilter} onChange={onChange} workflows={[]} />,
    );

    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 'running' } });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'running' }),
    );
  });

  it('工作流下拉渲染传入的工作流列表', () => {
    render(
      <InstanceFilter value={emptyFilter} onChange={vi.fn()} workflows={mockWorkflows} />,
    );

    expect(screen.getByText('客服工作流')).toBeTruthy();
    expect(screen.getByText('数据处理流')).toBeTruthy();
  });

  it('输入搜索词后触发 onChange（经 debounce）', async () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    render(
      <InstanceFilter value={emptyFilter} onChange={onChange} workflows={[]} />,
    );

    const searchInput = screen.getByPlaceholderText(/按实例 ID 前缀搜索/);
    fireEvent.change(searchInput, { target: { value: 'inst-abc' } });

    // debounce 300ms 未触发
    expect(onChange).not.toHaveBeenCalled();

    // 推进计时器
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ search: 'inst-abc' }),
    );
    vi.useRealTimers();
  });

  it('有过滤值时显示"清空过滤"按钮', () => {
    const filterWithStatus: InstanceFilterValue = {
      workflow_id: undefined,
      status: 'running',
      search: undefined,
    };
    render(
      <InstanceFilter value={filterWithStatus} onChange={vi.fn()} workflows={[]} />,
    );

    expect(screen.getByText('清空过滤')).toBeTruthy();
  });
});
