/**
 * DSL → ReactFlow 格式转换器
 * 将后端 DSL JSON 转为 @xyflow/react 使用的 nodes[] + edges[] 格式
 */

import type { Edge, Node } from '@xyflow/react';
import type { DSL } from '@/lib/types/dsl';
import { defaultLabelFor } from '@/lib/types/dsl';

/**
 * 将 DSL JSON 转换为 ReactFlow 可用的 nodes 和 edges
 *
 * DSL node: { id, type, position, config }
 * RF node:  { id, type, position, data: { config, label } }
 *
 * DSL edge: { id, source, target }
 * RF edge:  { id, source, target }
 */
export function dslToFlow(dsl: DSL): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = dsl.nodes.map((n) => ({
    id: n.id,
    type: n.type, // 与 canvas.tsx 注册的 nodeTypes key 对齐
    position: { x: n.position.x, y: n.position.y },
    data: {
      config: { ...n.config },
      label: defaultLabelFor(n.type),
    },
  }));

  const edges: Edge[] = dsl.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
  }));

  return { nodes, edges };
}
