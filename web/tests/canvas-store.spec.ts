/**
 * canvas-store.spec.ts
 * Zustand canvas store 单元测试
 * 覆盖：节点增删 / 边连接 / 配置更新 / 节点重命名 / DSL 双向 roundtrip
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useCanvasStore } from '@/lib/stores/canvas-store';
import type { DSL } from '@/lib/types/dsl';

// 在每个测试前重置 store 到初始状态
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

describe('canvas-store', () => {
  beforeEach(() => {
    resetStore();
  });

  it('test_initial_state_empty：初始 nodes 和 edges 应为空数组', () => {
    const state = useCanvasStore.getState();
    expect(state.nodes).toHaveLength(0);
    expect(state.edges).toHaveLength(0);
    expect(state.selectedNodeId).toBeNull();
    expect(state.workflowName).toBe('新工作流');
  });

  it('test_add_node：addNode("llm") 后 nodes 含一项，id 形如 llm_1', () => {
    const { addNode } = useCanvasStore.getState();
    addNode('llm', { x: 100, y: 200 });

    const { nodes } = useCanvasStore.getState();
    expect(nodes).toHaveLength(1);
    expect(nodes[0].id).toBe('llm_1');
    expect(nodes[0].type).toBe('llm');
    expect(nodes[0].position).toEqual({ x: 100, y: 200 });
    expect(nodes[0].data.config).toBeDefined();
  });

  it('test_unique_id_auto_increment：两次 addNode("llm") 得 llm_1 / llm_2', () => {
    const { addNode } = useCanvasStore.getState();
    addNode('llm', { x: 0, y: 0 });
    addNode('llm', { x: 100, y: 0 });

    const { nodes } = useCanvasStore.getState();
    expect(nodes).toHaveLength(2);
    expect(nodes[0].id).toBe('llm_1');
    expect(nodes[1].id).toBe('llm_2');
  });

  it('test_on_nodes_change_position：applyNodeChanges 更新节点位置', () => {
    const { addNode, onNodesChange } = useCanvasStore.getState();
    addNode('start', { x: 0, y: 0 });

    const { nodes } = useCanvasStore.getState();
    const nodeId = nodes[0].id;

    // 模拟 ReactFlow 位置变更事件
    onNodesChange([
      {
        type: 'position',
        id: nodeId,
        position: { x: 300, y: 400 },
      },
    ]);

    const updatedNodes = useCanvasStore.getState().nodes;
    expect(updatedNodes[0].position).toEqual({ x: 300, y: 400 });
  });

  it('test_on_connect_creates_edge：onConnect 后 edges 长度 +1', () => {
    const { addNode, onConnect } = useCanvasStore.getState();
    addNode('start', { x: 0, y: 0 });
    addNode('end', { x: 300, y: 0 });

    const { nodes } = useCanvasStore.getState();
    onConnect({
      source: nodes[0].id,
      target: nodes[1].id,
      sourceHandle: null,
      targetHandle: null,
    });

    const { edges } = useCanvasStore.getState();
    expect(edges).toHaveLength(1);
    expect(edges[0].source).toBe(nodes[0].id);
    expect(edges[0].target).toBe(nodes[1].id);
    expect(edges[0].id).toBeTruthy();
  });

  it('test_update_node_config：updateNodeConfig 不影响其他节点', () => {
    const { addNode, updateNodeConfig } = useCanvasStore.getState();
    addNode('llm', { x: 0, y: 0 });
    addNode('llm', { x: 300, y: 0 });

    const { nodes } = useCanvasStore.getState();
    const firstId = nodes[0].id;
    const secondId = nodes[1].id;

    const newConfig = { model: 'anthropic:claude-sonnet-4-5', user_prompt: '你好' };
    updateNodeConfig(firstId, newConfig);

    const updatedNodes = useCanvasStore.getState().nodes;
    const firstNode = updatedNodes.find((n) => n.id === firstId);
    const secondNode = updatedNodes.find((n) => n.id === secondId);

    expect(firstNode?.data.config).toEqual(newConfig);
    // 第二个节点 config 不受影响
    expect(secondNode?.data.config).not.toEqual(newConfig);
  });

  it('test_rename_node：renameNode 同时更新 edges 的 source/target', () => {
    const { addNode, onConnect, renameNode } = useCanvasStore.getState();
    addNode('start', { x: 0, y: 0 });
    addNode('end', { x: 300, y: 0 });

    let { nodes } = useCanvasStore.getState();
    onConnect({
      source: nodes[0].id,
      target: nodes[1].id,
      sourceHandle: null,
      targetHandle: null,
    });

    renameNode(nodes[0].id, 'my_start');

    const state = useCanvasStore.getState();
    const renamedNode = state.nodes.find((n) => n.id === 'my_start');
    expect(renamedNode).toBeDefined();

    // 原 ID 不应再存在
    const oldNode = state.nodes.find((n) => n.id === nodes[0].id);
    expect(oldNode).toBeUndefined();

    // edges 的 source 也应更新
    expect(state.edges[0].source).toBe('my_start');
  });

  it('test_load_dsl_export_dsl_roundtrip：loadDSL → exportDSL 内容等价', () => {
    const sampleDSL: DSL = {
      version: '1.0',
      name: '测试工作流',
      state_schema: { result: 'str' },
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        {
          id: 'llm_1',
          type: 'llm',
          position: { x: 300, y: 0 },
          config: {
            model: 'openai/gpt-4o',
            user_prompt: '{{start.output}}',
            temperature: 0.7,
          },
        },
        { id: 'end', type: 'end', position: { x: 600, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'llm_1' },
        { id: 'e2', source: 'llm_1', target: 'end' },
      ],
    };

    const { loadDSL, exportDSL } = useCanvasStore.getState();
    loadDSL(sampleDSL);

    const exported = exportDSL();
    expect(exported.version).toBe('1.0');
    expect(exported.name).toBe('测试工作流');
    expect(exported.nodes).toHaveLength(3);
    expect(exported.edges).toHaveLength(2);
    expect(exported.state_schema).toEqual({ result: 'str' });

    // 节点位置保持等价
    const exportedStart = exported.nodes.find((n) => n.id === 'start');
    expect(exportedStart?.position).toEqual({ x: 0, y: 0 });

    // config 保持等价
    const exportedLlm = exported.nodes.find((n) => n.id === 'llm_1');
    expect(exportedLlm?.config).toMatchObject({
      model: 'openai/gpt-4o',
      user_prompt: '{{start.output}}',
    });
  });
});
