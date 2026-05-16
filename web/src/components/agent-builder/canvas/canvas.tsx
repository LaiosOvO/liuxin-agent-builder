'use client';

/**
 * Canvas 主组件
 * 基于 @xyflow/react v12 封装，集成 Zustand canvas-store
 * 支持：节点拖拽放置 / 连线 / 删除 / 缩放 / MiniMap
 */

import { useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type NodeMouseHandler,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useCanvasStore } from '@/lib/stores/canvas-store';
import type { DSLNode } from '@/lib/types/dsl';
import { StartNode, EndNode, LLMNode, ToolNode, IfElseNode } from './nodes';

/** ReactFlow nodeTypes 注册表（key 必须与 DSLNode.type 对齐） */
const nodeTypes = {
  start: StartNode,
  end: EndNode,
  llm: LLMNode,
  tool: ToolNode,
  if_else: IfElseNode,
};

interface CanvasProps {
  /** ReactFlow 实例回调（可选，供父组件获取 project 坐标转换函数） */
  onInit?: (instance: ReactFlowInstance) => void;
}

export function Canvas({ onInit }: CanvasProps) {
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    selectNode,
    selectEdge,
    addNode,
  } = useCanvasStore();

  /** 点击节点 → 选中 */
  const handleNodeClick: NodeMouseHandler = useCallback(
    (_, node) => {
      selectNode(node.id);
    },
    [selectNode],
  );

  /** 点击画布空白区域 → 取消选中 */
  const handlePaneClick = useCallback(() => {
    selectNode(null);
    selectEdge(null);
  }, [selectNode, selectEdge]);

  /** 处理从 node-palette 拖拽放置到画布 */
  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const nodeType = event.dataTransfer.getData(
        'application/agent-builder-node',
      ) as DSLNode['type'];
      if (!nodeType) return;

      // 将浏览器坐标转换为 ReactFlow 画布坐标
      const canvas = event.currentTarget.getBoundingClientRect();
      const position = {
        x: event.clientX - canvas.left,
        y: event.clientY - canvas.top,
      };

      addNode(nodeType, position);
    },
    [addNode],
  );

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  return (
    <div
      className="h-full w-full"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      data-testid="canvas-drop-zone"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        onInit={onInit}
        fitView
        deleteKeyCode={['Backspace', 'Delete']}
        minZoom={0.25}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap
          nodeColor={(n) => {
            switch (n.type) {
              case 'start':
                return '#22c55e';
              case 'end':
                return '#ef4444';
              case 'llm':
                return '#a855f7';
              case 'tool':
                return '#3b82f6';
              case 'if_else':
                return '#f97316';
              default:
                return '#6b7280';
            }
          }}
        />
      </ReactFlow>
    </div>
  );
}
