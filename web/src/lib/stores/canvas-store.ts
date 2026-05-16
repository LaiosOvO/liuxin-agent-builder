/**
 * Zustand Canvas Store
 * 管理 ReactFlow 画布状态：nodes / edges / 选中 / 工作流元信息
 * 所有状态变更均返回新对象（不可变模式）
 */

import { create } from 'zustand';
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
} from '@xyflow/react';
import type {
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  Connection,
} from '@xyflow/react';
import { nanoid } from 'nanoid';
import type { DSL, DSLNode, StateFieldType } from '@/lib/types/dsl';
import { defaultConfigFor, defaultLabelFor } from '@/lib/types/dsl';
import { dslToFlow } from '@/lib/converters/dsl-to-flow';
import { flowToDsl } from '@/lib/converters/flow-to-dsl';

/** 生成唯一节点 ID，格式：<type>_<seq> */
function generateNodeId(type: DSLNode['type'], existingNodes: Node[]): string {
  const sameTypeCount = existingNodes.filter((n) => n.type === type).length;
  const candidate = `${type}_${sameTypeCount + 1}`;

  // 若已存在同名，继续递增
  const ids = new Set(existingNodes.map((n) => n.id));
  if (!ids.has(candidate)) {
    return candidate;
  }

  let seq = sameTypeCount + 2;
  while (ids.has(`${type}_${seq}`)) {
    seq++;
  }
  return `${type}_${seq}`;
}

/** Canvas Zustand Store 状态与操作接口 */
interface CanvasState {
  /** 当前工作流 ID（null = 新建未保存） */
  workflowId: string | null;
  /** 工作流名称 */
  workflowName: string;
  /** 状态字段 schema */
  stateSchema: Record<string, StateFieldType>;
  /** ReactFlow 节点列表 */
  nodes: Node[];
  /** ReactFlow 边列表 */
  edges: Edge[];
  /** 当前选中节点 ID */
  selectedNodeId: string | null;
  /** 当前选中边 ID */
  selectedEdgeId: string | null;

  // ====== 加载 / 导出 ======
  /** 从 DSL JSON 加载到画布 */
  loadDSL: (dsl: DSL) => void;
  /** 将画布当前状态导出为 DSL JSON */
  exportDSL: () => DSL;

  // ====== 节点 / 边变更（ReactFlow 原生 handler） ======
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;

  // ====== 画布操作 ======
  /** 拖拽新节点到画布（从 node-palette） */
  addNode: (type: DSLNode['type'], position: { x: number; y: number }) => void;
  /** 更新指定节点的 config */
  updateNodeConfig: (nodeId: string, newConfig: Record<string, unknown>) => void;
  /** 重命名节点 ID（同步更新相关边的 source/target） */
  renameNode: (oldId: string, newId: string) => void;

  // ====== 选中状态 ======
  selectNode: (id: string | null) => void;
  selectEdge: (id: string | null) => void;

  // ====== 工作流元信息 ======
  setWorkflowName: (name: string) => void;
  setWorkflowId: (id: string | null) => void;
  updateStateSchema: (schema: Record<string, StateFieldType>) => void;
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  workflowId: null,
  workflowName: '新工作流',
  stateSchema: {},
  nodes: [],
  edges: [],
  selectedNodeId: null,
  selectedEdgeId: null,

  loadDSL: (dsl) => {
    const { nodes, edges } = dslToFlow(dsl);
    set({
      workflowName: dsl.name,
      stateSchema: { ...dsl.state_schema },
      nodes,
      edges,
      selectedNodeId: null,
      selectedEdgeId: null,
    });
  },

  exportDSL: () =>
    flowToDsl(
      get().nodes,
      get().edges,
      get().workflowName,
      get().stateSchema,
    ),

  onNodesChange: (changes) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),

  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),

  onConnect: (connection) =>
    set({
      edges: addEdge({ ...connection, id: nanoid() }, get().edges),
    }),

  addNode: (type, position) => {
    const newId = generateNodeId(type, get().nodes);
    const newNode: Node = {
      id: newId,
      type,
      position,
      data: {
        config: defaultConfigFor(type),
        label: defaultLabelFor(type),
      },
    };
    set({ nodes: [...get().nodes, newNode] });
  },

  updateNodeConfig: (nodeId, newConfig) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, config: newConfig } }
          : n,
      ),
    }),

  renameNode: (oldId, newId) => {
    const state = get();
    const updatedNodes = state.nodes.map((n) =>
      n.id === oldId ? { ...n, id: newId } : n,
    );
    const updatedEdges = state.edges.map((e) => ({
      ...e,
      source: e.source === oldId ? newId : e.source,
      target: e.target === oldId ? newId : e.target,
    }));
    const updatedSelectedNodeId =
      state.selectedNodeId === oldId ? newId : state.selectedNodeId;
    set({
      nodes: updatedNodes,
      edges: updatedEdges,
      selectedNodeId: updatedSelectedNodeId,
    });
  },

  selectNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),
  selectEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),

  setWorkflowName: (name) => set({ workflowName: name }),
  setWorkflowId: (id) => set({ workflowId: id }),
  updateStateSchema: (schema) => set({ stateSchema: { ...schema } }),
}));
