/**
 * DSL 结构校验模块（Category 1 + Category 4 特殊规则）
 *
 * 检查项：
 * 1. 无 start 节点 / 多个 start 节点 / 无 end 节点
 * 2. 节点 ID 重复
 * 3. 边指向不存在节点（悬空边）
 * 4. Start 节点不能有入边
 * 5. End 节点不能有出边
 * 6. 孤立节点（无入无出，除 start 外）
 * 7. 成环检测（DFS 白/灰/黑染色法）
 * 8. End 节点从 start 不可达（BFS）
 *
 * 与后端 Python validator._validate_structure() 算法等价。
 */

import type { DSL } from '@/lib/types/dsl';
import type { ValidationError } from './types';
import { ERROR_CODES } from './types';

/** 节点染色状态（用于 DFS 成环检测） */
type NodeColor = 'white' | 'gray' | 'black';

/**
 * 检查 DSL 结构完整性，返回所有结构错误。
 *
 * @param dsl - 待检查的 DSL 对象
 * @returns ValidationError 数组（可能为空）
 */
export function validateStructure(dsl: DSL): ValidationError[] {
  const errors: ValidationError[] = [];
  const { nodes, edges } = dsl;

  // ─── 节点 ID 唯一性检查 ────────────────────────────────────────────────────
  const seenIds = new Set<string>();
  const nodeIdSet = new Set<string>();
  const nodeTypeMap = new Map<string, string>();

  for (const node of nodes) {
    if (seenIds.has(node.id)) {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_DUPLICATE_NODE_ID,
        message: `节点 ID '${node.id}' 重复，所有节点 ID 必须唯一`,
        node_id: node.id,
      });
    }
    seenIds.add(node.id);
    nodeIdSet.add(node.id);
    nodeTypeMap.set(node.id, node.type);
  }

  // ─── Start / End 节点数量检查 ──────────────────────────────────────────────
  const startNodes = nodes.filter((n) => n.type === 'start');
  const endNodes = nodes.filter((n) => n.type === 'end');

  if (startNodes.length === 0) {
    errors.push({
      severity: 'error',
      code: ERROR_CODES.E_NO_START,
      message: 'DSL 中没有 start 节点，每个工作流必须有且仅有一个 start 节点',
    });
  } else if (startNodes.length > 1) {
    const ids = startNodes.map((n) => n.id);
    errors.push({
      severity: 'error',
      code: ERROR_CODES.E_MULTIPLE_START,
      message: `DSL 中有多个 start 节点（${ids.join(', ')}），每个工作流只能有一个 start 节点`,
    });
  }

  if (endNodes.length === 0) {
    errors.push({
      severity: 'error',
      code: ERROR_CODES.E_NO_END,
      message: 'DSL 中没有 end 节点，每个工作流必须至少有一个 end 节点',
    });
  }

  // ─── 边检查：悬空边 + Start 入边 + End 出边 ───────────────────────────────
  // 同时构造邻接表（outbound + inbound）供后续使用
  const outbound = new Map<string, string[]>();
  const inbound = new Map<string, string[]>();

  for (const nodeId of nodeIdSet) {
    outbound.set(nodeId, []);
    inbound.set(nodeId, []);
  }

  for (const edge of edges) {
    const { id: eid, source: src, target: tgt } = edge;

    if (!nodeIdSet.has(src)) {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_DANGLING_EDGE,
        message: `边 '${eid}' 的起点 '${src}' 不是合法节点 ID`,
        edge_id: eid,
        node_id: src,
      });
      continue;
    }
    if (!nodeIdSet.has(tgt)) {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_DANGLING_EDGE,
        message: `边 '${eid}' 的终点 '${tgt}' 不是合法节点 ID`,
        edge_id: eid,
        node_id: tgt,
      });
      continue;
    }

    if (nodeTypeMap.get(tgt) === 'start') {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_START_HAS_INBOUND,
        message: `start 节点 '${tgt}' 不能有入边（边 '${eid}'）`,
        node_id: tgt,
        edge_id: eid,
      });
    }

    if (nodeTypeMap.get(src) === 'end') {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_END_HAS_OUTBOUND,
        message: `end 节点 '${src}' 不能有出边（边 '${eid}'）`,
        node_id: src,
        edge_id: eid,
      });
    }

    outbound.get(src)!.push(tgt);
    inbound.get(tgt)!.push(src);
  }

  // if_else 节点的隐式出边
  for (const node of nodes) {
    if (node.type !== 'if_else') continue;
    const cfg = node.config as Record<string, unknown>;
    const conditions = (cfg.conditions as Array<{ target_node_id?: string }>) ?? [];
    const defaultTarget = cfg.default_target as string | undefined;

    for (const cond of conditions) {
      const tgt = cond.target_node_id;
      if (tgt && nodeIdSet.has(tgt)) {
        outbound.get(node.id)!.push(tgt);
        inbound.get(tgt)!.push(node.id);
      }
    }
    if (defaultTarget && nodeIdSet.has(defaultTarget)) {
      outbound.get(node.id)!.push(defaultTarget);
      inbound.get(defaultTarget)!.push(node.id);
    }
  }

  // ─── 孤立节点检测 ──────────────────────────────────────────────────────────
  for (const node of nodes) {
    if (node.type === 'start') continue; // start 无入边是正常的
    const hasIn = (inbound.get(node.id)?.length ?? 0) > 0;
    const hasOut = (outbound.get(node.id)?.length ?? 0) > 0;
    if (!hasIn && !hasOut && node.type !== 'end') {
      errors.push({
        severity: 'warning',
        code: ERROR_CODES.E_ORPHAN_NODE,
        message: `节点 '${node.id}' 没有入边也没有出边（孤立节点）`,
        node_id: node.id,
      });
    }
  }

  // ─── 成环检测（DFS 白/灰/黑染色）─────────────────────────────────────────
  const colors = new Map<string, NodeColor>();
  for (const nodeId of nodeIdSet) {
    colors.set(nodeId, 'white');
  }

  let cycleDetected = false;

  function dfsVisit(nodeId: string): boolean {
    colors.set(nodeId, 'gray');
    for (const neighbor of outbound.get(nodeId) ?? []) {
      const color = colors.get(neighbor);
      if (color === 'gray') {
        // 发现返回边 → 成环
        return true;
      }
      if (color === 'white') {
        if (dfsVisit(neighbor)) return true;
      }
    }
    colors.set(nodeId, 'black');
    return false;
  }

  for (const nodeId of nodeIdSet) {
    if (colors.get(nodeId) === 'white') {
      if (dfsVisit(nodeId)) {
        cycleDetected = true;
        break;
      }
    }
  }

  if (cycleDetected) {
    errors.push({
      severity: 'error',
      code: ERROR_CODES.E_CYCLE,
      message: '检测到循环依赖（成环），请删除导致成环的边',
    });
  }

  // ─── 不可达 End 检测（BFS 从 start 出发）─────────────────────────────────
  if (!cycleDetected && startNodes.length === 1 && endNodes.length > 0) {
    const startId = startNodes[0]!.id;
    const reachable = new Set<string>();
    const queue: string[] = [startId];

    while (queue.length > 0) {
      const curr = queue.shift()!;
      if (reachable.has(curr)) continue;
      reachable.add(curr);
      for (const next of outbound.get(curr) ?? []) {
        if (!reachable.has(next)) {
          queue.push(next);
        }
      }
    }

    for (const endNode of endNodes) {
      if (!reachable.has(endNode.id)) {
        errors.push({
          severity: 'error',
          code: ERROR_CODES.E_UNREACHABLE_END,
          message: `end 节点 '${endNode.id}' 从 start 节点不可达`,
          node_id: endNode.id,
        });
      }
    }
  }

  return errors;
}
