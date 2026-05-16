/**
 * IssueList 组件测试
 *
 * 测试：空状态、错误渲染、点击跳转节点、warning/error 样式
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { act } from '@testing-library/react';
import { IssueList } from '@/components/agent-builder/canvas/panels/issue-list';
import { useValidatorStore } from '@/lib/stores/validator-store';
import { useCanvasStore } from '@/lib/stores/canvas-store';
import type { ValidationError } from '@/lib/validator/types';

// 每个测试前重置 store
beforeEach(() => {
  useValidatorStore.getState().clearResults();
  vi.clearAllMocks();
});

describe('IssueList 组件', () => {
  // ─── test_empty_state_when_no_errors ───────────────────────────────────
  it('test_empty_state_when_no_errors: 无错误时显示校验通过', () => {
    render(<IssueList />);
    expect(screen.getByTestId('issue-list-empty')).toBeInTheDocument();
    expect(screen.getByText('DSL 校验通过')).toBeInTheDocument();
  });

  // ─── test_renders_all_errors_with_severity ─────────────────────────────
  it('test_renders_all_errors_with_severity: 有错误时显示所有条目', () => {
    const errors: ValidationError[] = [
      { severity: 'error', code: 'E_CYCLE', message: '检测到成环', node_id: 'llm1' },
      { severity: 'warning', code: 'E_ORPHAN_NODE', message: '孤立节点', node_id: 'tool1' },
    ];

    act(() => {
      useValidatorStore.getState().setResults(errors);
    });

    render(<IssueList />);

    // Issue 列表渲染
    expect(screen.getByTestId('issue-list')).toBeInTheDocument();
    // 显示错误码
    expect(screen.getByText('E_CYCLE')).toBeInTheDocument();
    expect(screen.getByText('E_ORPHAN_NODE')).toBeInTheDocument();
    // 显示错误消息
    expect(screen.getByText('检测到成环')).toBeInTheDocument();
    expect(screen.getByText('孤立节点')).toBeInTheDocument();
  });

  // ─── test_click_issue_selects_node ─────────────────────────────────────
  it('test_click_issue_selects_node: 点击 issue 条目选中对应节点', () => {
    const errors: ValidationError[] = [
      { severity: 'error', code: 'E_INVALID_CONFIG', message: '配置错误', node_id: 'llm1' },
    ];

    act(() => {
      useValidatorStore.getState().setResults(errors);
    });

    render(<IssueList />);

    const item = screen.getByTestId('issue-item-0');
    fireEvent.click(item);

    // 验证 selectedNodeId 已更新
    expect(useCanvasStore.getState().selectedNodeId).toBe('llm1');
  });

  // ─── test_warning_vs_error_styling ─────────────────────────────────────
  it('test_warning_vs_error_styling: error 和 warning 显示不同颜色标识', () => {
    const errors: ValidationError[] = [
      { severity: 'error', code: 'E_CYCLE', message: '成环', node_id: 'n1' },
      { severity: 'warning', code: 'E_ORPHAN_NODE', message: '孤立', node_id: 'n2' },
    ];

    act(() => {
      useValidatorStore.getState().setResults(errors);
    });

    render(<IssueList />);

    // 标题栏显示错误/警告计数
    expect(screen.getByText('1 错误')).toBeInTheDocument();
    expect(screen.getByText('1 警告')).toBeInTheDocument();

    // error 条目显示红色 code
    const cycleCode = screen.getByText('E_CYCLE');
    expect(cycleCode).toHaveClass('text-red-600');

    // warning 条目显示黄色 code
    const orphanCode = screen.getByText('E_ORPHAN_NODE');
    expect(orphanCode).toHaveClass('text-yellow-600');
  });
});
