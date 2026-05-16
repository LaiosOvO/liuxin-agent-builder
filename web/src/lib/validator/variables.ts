/**
 * DSL 变量引用校验模块（Category 2）
 *
 * 检查项：
 * 1. 模板引用的顶层变量不在符号表（E_UNDEFINED_VAR）
 * 2. 引用了下游节点（拓扑序检查，E_VAR_NOT_UPSTREAM）
 * 3. 引用的节点输出字段不存在（E_UNDEFINED_FIELD）
 *
 * 算法：
 * - 构造符号表：所有节点 ID ∪ state_schema 字段名
 * - 拓扑排序（Kahn 算法，有环时跳过检查）
 * - 按拓扑序遍历每个节点，提取 config 中所有 Jinja2 字符串
 * - 对每个模板引用的顶层变量做上述 3 类检查
 *
 * 与后端 Python validator._validate_variables() 算法等价。
 */

import type { DSL, NodeType } from '@/lib/types/dsl';
import type { ValidationError } from './types';
import { ERROR_CODES } from './types';
import { collectVariables, extractFieldRefs } from './jinja-parser';
import { getNodeOutputFields, NODE_SCHEMAS } from './node-schemas';

/**
 * 检查所有模板变量引用，返回变量类错误。
 *
 * @param dsl - 待检查的 DSL 对象
 * @returns ValidationError 数组（可能为空）
 */
export function validateVariables(dsl: DSL): ValidationError[] {
  const errors: ValidationError[] = [];
  const { nodes, edges, state_schema } = dsl;

  // ─── 构造符号表 ────────────────────────────────────────────────────────────
  const nodeIdSet = new Set(nodes.map((n) => n.id));
  const stateFields = new Set(Object.keys(state_schema));
  const allSymbols = new Set([...nodeIdSet, ...stateFields]);

  // ─── 构造 outbound 图（包含 if_else 隐式出边）────────────────────────────
  const outbound = new Map<string, Set<string>>();
  const inbound = new Map<string, Set<string>>();
  for (const nodeId of nodeIdSet) {
    outbound.set(nodeId, new Set());
    inbound.set(nodeId, new Set());
  }

  for (const edge of edges) {
    if (nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target)) {
      outbound.get(edge.source)!.add(edge.target);
      inbound.get(edge.target)!.add(edge.source);
    }
  }

  for (const node of nodes) {
    if (node.type !== 'if_else') continue;
    const cfg = node.config as Record<string, unknown>;
    const conditions = (cfg.conditions as Array<{ target_node_id?: string }>) ?? [];
    for (const cond of conditions) {
      const tgt = cond.target_node_id;
      if (tgt && nodeIdSet.has(tgt)) {
        outbound.get(node.id)!.add(tgt);
        inbound.get(tgt)!.add(node.id);
      }
    }
    const defaultTgt = cfg.default_target as string | undefined;
    if (defaultTgt && nodeIdSet.has(defaultTgt)) {
      outbound.get(node.id)!.add(defaultTgt);
      inbound.get(defaultTgt)!.add(node.id);
    }
  }

  // ─── 拓扑排序（Kahn 算法）─────────────────────────────────────────────────
  const topoOrder = kahnSort(nodeIdSet, inbound, outbound);
  if (topoOrder === null) {
    // 有环时跳过变量检查（成环已在 structure 中报告）
    return errors;
  }

  // ─── 构造输出字段映射 ───────────────────────────────────────────────────────
  const outputFieldsMap = new Map<string, ReadonlySet<string>>();
  const nodeTypeMap = new Map<string, NodeType>();
  for (const node of nodes) {
    nodeTypeMap.set(node.id, node.type as NodeType);
    const ntype = node.type as NodeType;
    if (NODE_SCHEMAS[ntype]) {
      let fields = getNodeOutputFields(ntype);
      if (ntype === 'start') {
        // start 节点输出字段 = 基础字段 ∪ state_schema 字段
        fields = new Set([...fields, ...stateFields]);
      }
      outputFieldsMap.set(node.id, fields);
    } else {
      outputFieldsMap.set(node.id, new Set());
    }
  }

  // ─── 按拓扑序校验每个节点的模板变量 ────────────────────────────────────────
  const visitedNodes = new Set<string>();

  for (const nid of topoOrder) {
    const node = nodes.find((n) => n.id === nid);
    if (!node) continue;

    const templateStrings = extractTemplateStrings(node.config ?? {});

    for (const [tmpl, fieldPath] of templateStrings) {
      if (!tmpl.includes('{{')) continue;

      const topVars = collectVariables(tmpl);

      for (const varName of topVars) {
        // state_schema 字段始终合法
        if (stateFields.has(varName)) continue;

        if (!allSymbols.has(varName)) {
          errors.push({
            severity: 'error',
            code: ERROR_CODES.E_UNDEFINED_VAR,
            message: `节点 '${nid}' 的字段 '${fieldPath}' 引用了未定义变量 '${varName}'，合法符号：节点 ID [${Array.from(nodeIdSet).sort().join(', ')}] + state 字段 [${Array.from(stateFields).sort().join(', ')}]`,
            node_id: nid,
            field_path: `config.${fieldPath}`,
          });
          continue;
        }

        // varName 是节点 ID，检查是否上游
        if (!visitedNodes.has(varName) && varName !== nid) {
          errors.push({
            severity: 'error',
            code: ERROR_CODES.E_VAR_NOT_UPSTREAM,
            message: `节点 '${nid}' 的字段 '${fieldPath}' 引用了下游或同级节点 '${varName}'，只能引用已执行完毕的上游节点`,
            node_id: nid,
            field_path: `config.${fieldPath}`,
          });
          continue;
        }

        // 检查输出字段
        const fieldRefs = extractFieldRefs(tmpl, varName);
        const nodeOutFields = outputFieldsMap.get(varName);

        if (nodeOutFields && nodeOutFields.size > 0) {
          for (const fieldRef of fieldRefs) {
            if (!nodeOutFields.has(fieldRef)) {
              errors.push({
                severity: 'error',
                code: ERROR_CODES.E_UNDEFINED_FIELD,
                message: `节点 '${nid}' 的字段 '${fieldPath}' 引用了 '${varName}.${fieldRef}'，但 ${nodeTypeMap.get(varName)} 节点只有输出字段：[${Array.from(nodeOutFields).sort().join(', ')}]`,
                node_id: nid,
                field_path: `config.${fieldPath}`,
              });
            }
          }
        }
      }
    }

    visitedNodes.add(nid);
  }

  return errors;
}

// ─── 辅助函数 ─────────────────────────────────────────────────────────────────

/**
 * Kahn 算法拓扑排序。
 *
 * @returns 拓扑序节点 ID 数组，有环时返回 null
 */
function kahnSort(
  nodeIds: Set<string>,
  inbound: Map<string, Set<string>>,
  outbound: Map<string, Set<string>>,
): string[] | null {
  // 计算入度
  const inDegree = new Map<string, number>();
  for (const nid of nodeIds) {
    inDegree.set(nid, inbound.get(nid)?.size ?? 0);
  }

  const queue: string[] = [];
  for (const [nid, deg] of inDegree) {
    if (deg === 0) queue.push(nid);
  }

  const result: string[] = [];
  while (queue.length > 0) {
    const curr = queue.shift()!;
    result.push(curr);
    for (const neighbor of outbound.get(curr) ?? []) {
      const newDeg = (inDegree.get(neighbor) ?? 0) - 1;
      inDegree.set(neighbor, newDeg);
      if (newDeg === 0) queue.push(neighbor);
    }
  }

  return result.length === nodeIds.size ? result : null;
}

/**
 * 递归提取对象/数组中所有字符串字段及其路径。
 *
 * @param obj - 待提取对象
 * @param path - 当前路径前缀
 * @returns [字符串值, 字段路径] 元组数组
 */
function extractTemplateStrings(
  obj: unknown,
  path = '',
): Array<[string, string]> {
  const results: Array<[string, string]> = [];

  if (typeof obj === 'string') {
    results.push([obj, path]);
  } else if (Array.isArray(obj)) {
    for (let i = 0; i < obj.length; i++) {
      const subPath = path ? `${path}[${i}]` : `[${i}]`;
      results.push(...extractTemplateStrings(obj[i], subPath));
    }
  } else if (obj !== null && typeof obj === 'object') {
    for (const [key, val] of Object.entries(obj as Record<string, unknown>)) {
      const subPath = path ? `${path}.${key}` : key;
      results.push(...extractTemplateStrings(val, subPath));
    }
  }

  return results;
}
