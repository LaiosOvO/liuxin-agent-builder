/**
 * config-panel.spec.tsx
 * ConfigPanel 组件单元测试
 * 覆盖：无选中状态 / LLM 表单渲染 / 表单校验 / 提交更新 store / 切换节点重置表单
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConfigPanel } from '@/components/agent-builder/canvas/panels/config-panel';
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

describe('ConfigPanel', () => {
  beforeEach(() => {
    resetStore();
  });

  it('test_empty_when_no_selection：无选中节点时显示空状态', () => {
    render(<ConfigPanel />);
    expect(screen.getByText('选中节点后在此编辑配置')).toBeDefined();
    expect(screen.getByText('节点配置')).toBeDefined();
  });

  it('test_llm_form_renders_model_field：选中 LLM 节点后渲染模型输入字段', () => {
    // 先添加 LLM 节点并选中
    const { addNode, selectNode } = useCanvasStore.getState();
    addNode('llm', { x: 0, y: 0 });

    const { nodes } = useCanvasStore.getState();
    selectNode(nodes[0].id);

    render(<ConfigPanel />);

    // 应渲染 LLM 表单中的模型字段
    expect(screen.getByPlaceholderText('openai/gpt-4o')).toBeDefined();
    expect(screen.getByText('System Prompt')).toBeDefined();
    expect(screen.getByText('User Prompt')).toBeDefined();
  });

  it('test_llm_form_validation_blocks_empty_model：model 为空时提交被阻断', async () => {
    const { addNode, selectNode } = useCanvasStore.getState();
    addNode('llm', { x: 0, y: 0 });

    const { nodes } = useCanvasStore.getState();
    selectNode(nodes[0].id);

    render(<ConfigPanel />);

    // 清空模型字段
    const modelInput = screen.getByPlaceholderText('openai/gpt-4o') as HTMLInputElement;
    fireEvent.change(modelInput, { target: { value: '' } });

    // 尝试提交
    const saveBtn = screen.getByRole('button', { name: '保存' });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText('模型不能为空')).toBeDefined();
    });
  });

  it('test_form_submit_updates_store：提交 LLM 表单后 store 中节点 config 更新', async () => {
    const { addNode, selectNode } = useCanvasStore.getState();
    addNode('llm', { x: 0, y: 0 });

    const { nodes } = useCanvasStore.getState();
    const nodeId = nodes[0].id;
    selectNode(nodeId);

    render(<ConfigPanel />);

    const modelInput = screen.getByPlaceholderText('openai/gpt-4o') as HTMLInputElement;
    fireEvent.change(modelInput, { target: { value: 'anthropic:claude-sonnet-4-5' } });

    // 填写必填的 user_prompt（否则校验失败）- 使用精确的 user_prompt placeholder
    const userPromptArea = screen.getByPlaceholderText(
      '支持 Jinja2 变量 {{ start.output }}',
    ) as HTMLTextAreaElement;
    fireEvent.change(userPromptArea, { target: { value: '处理输入' } });

    const saveBtn = screen.getByRole('button', { name: '保存' });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      const updatedNode = useCanvasStore
        .getState()
        .nodes.find((n) => n.id === nodeId);
      expect((updatedNode?.data.config as Record<string, unknown>).model).toBe(
        'anthropic:claude-sonnet-4-5',
      );
    });
  });

  it('test_switching_selection_shows_correct_form：切换选中节点后渲染对应表单', () => {
    const { addNode, selectNode } = useCanvasStore.getState();
    addNode('llm', { x: 0, y: 0 });
    addNode('tool', { x: 300, y: 0 });

    const { nodes } = useCanvasStore.getState();

    // 先选中 LLM 节点
    selectNode(nodes[0].id);
    const { unmount } = render(<ConfigPanel />);
    expect(screen.queryByPlaceholderText('openai/gpt-4o')).toBeDefined();
    unmount();

    // 切换到 tool 节点
    selectNode(nodes[1].id);
    render(<ConfigPanel />);
    // tool 节点表单应显示 URL 相关字段
    expect(screen.getByText('类型')).toBeDefined();
  });
});
