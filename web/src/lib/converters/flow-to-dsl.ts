/**
 * ReactFlow → DSL 格式转换器
 * 将 @xyflow/react 的 nodes[] + edges[] 反向转换为后端 DSL JSON
 */

import type { Edge, Node } from '@xyflow/react';
import type { DSL, DSLNode, StateFieldType } from '@/lib/types/dsl';
import { DSL_VERSION } from '@/lib/types/dsl';

/**
 * 将 ReactFlow nodes/edges 转换为 DSL JSON
 *
 * RF node:  { id, type, position, data: { config, label } }
 * DSL node: { id, type, position, config }
 *
 * RF edge:  { id, source, target }
 * DSL edge: { id, source, target }
 */
export function flowToDsl(
  nodes: Node[],
  edges: Edge[],
  name: string,
  state_schema: Record<string, StateFieldType>,
): DSL {
  const dslNodes: DSLNode[] = nodes.map((n) => ({
    id: n.id,
    type: n.type as DSLNode['type'],
    position: { x: n.position.x, y: n.position.y },
    config: (n.data?.config ?? {}) as Record<string, unknown>,
  }));

  return {
    version: DSL_VERSION,
    name,
    state_schema: { ...state_schema },
    nodes: dslNodes,
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
    })),
  };
}
