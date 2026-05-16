/**
 * canvas-node-palette.spec.tsx
 * NodePalette 组件单元测试
 * 覆盖：渲染 5 种节点 / 拖拽事件 / 坐标处理
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NodePalette } from '@/components/agent-builder/canvas/panels/node-palette';
import { useCanvasStore } from '@/lib/stores/canvas-store';

// 重置 canvas store
function resetStore() {
  useCanvasStore.setState({
    workflowId: null,
    workflowName: '新工作流',
    stateSchema: {},
    nodes: [],
    edges: [],
    selectedNodeId: null,
    selectedEdgeId: null,
  });
}

describe('NodePalette', () => {
  beforeEach(() => {
    resetStore();
  });

  it('test_palette_shows_5_node_types：渲染 5 种节点类型卡片', () => {
    render(<NodePalette />);

    // 通过 data-node-type 属性验证 5 个卡片
    expect(screen.getByRole('button', { name: /拖拽 开始 节点/ })).toBeDefined();
    expect(screen.getByRole('button', { name: /拖拽 结束 节点/ })).toBeDefined();
    expect(screen.getByRole('button', { name: /拖拽 LLM 节点/ })).toBeDefined();
    expect(screen.getByRole('button', { name: /拖拽 工具 节点/ })).toBeDefined();
    expect(screen.getByRole('button', { name: /拖拽 条件分支 节点/ })).toBeDefined();
  });

  it('test_drag_node_into_canvas：dragStart 设置正确的 dataTransfer 数据', () => {
    render(<NodePalette />);

    const llmCard = screen.getByRole('button', { name: /拖拽 LLM 节点/ });

    // 构造 dataTransfer mock
    const setDataMock = vi.fn();
    const dataTransfer = {
      setData: setDataMock,
      effectAllowed: 'move',
    };

    fireEvent.dragStart(llmCard, { dataTransfer });

    expect(setDataMock).toHaveBeenCalledWith(
      'application/agent-builder-node',
      'llm',
    );
  });

  it('test_all_node_types_have_draggable_attribute：所有卡片有 draggable 属性', () => {
    render(<NodePalette />);

    const nodeTypes = ['start', 'end', 'llm', 'tool', 'if_else'];
    for (const type of nodeTypes) {
      const cards = document.querySelectorAll(`[data-node-type="${type}"]`);
      expect(cards.length).toBeGreaterThan(0);
      expect(cards[0].getAttribute('draggable')).toBe('true');
    }
  });

  it('test_palette_header_shows_title：面板显示"节点库"标题和说明文字', () => {
    render(<NodePalette />);
    expect(screen.getByText('节点库')).toBeDefined();
    expect(screen.getByText('拖拽节点到画布')).toBeDefined();
  });
});
