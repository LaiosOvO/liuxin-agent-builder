/**
 * DSL 节点配置校验模块（Category 3）
 *
 * 检查项：
 * 1. 节点 ID 格式（^[a-z][a-z0-9_]*$）
 * 2. 节点 ID 命中保留字
 * 3. 各节点 config 用 zod safeParse 校验
 * 4. if_else 缺 default_target（E_IF_ELSE_NO_DEFAULT）
 * 5. if_else 条件目标节点不存在（E_IF_ELSE_BAD_TARGET）
 * 6. state_schema 字段类型不在支持列表（E_INVALID_STATE_TYPE）
 *
 * 与后端 Python validator._validate_node_configs() 算法等价。
 */

import type { DSL, NodeType } from '@/lib/types/dsl';
import { RESERVED_NODE_IDS, NODE_ID_REGEX } from '@/lib/types/dsl';
import type { ValidationError } from './types';
import { ERROR_CODES } from './types';
import { NODE_SCHEMAS, SCHEMA_TYPES } from './node-schemas';

/**
 * 检查所有节点配置，返回所有 config 类错误。
 *
 * @param dsl - 待检查的 DSL 对象
 * @returns ValidationError 数组（可能为空）
 */
export function validateConfigs(dsl: DSL): ValidationError[] {
  const errors: ValidationError[] = [];
  const { nodes, state_schema } = dsl;
  const nodeIdSet = new Set(nodes.map((n) => n.id));

  // ─── state_schema 类型检查 ─────────────────────────────────────────────────
  for (const [fieldName, typeStr] of Object.entries(state_schema)) {
    if (!SCHEMA_TYPES.has(typeStr)) {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_INVALID_STATE_TYPE,
        message: `state_schema 字段 '${fieldName}' 的类型 '${typeStr}' 不支持，支持的类型：${Array.from(SCHEMA_TYPES).join(', ')}`,
        field_path: `state_schema.${fieldName}`,
      });
    }
  }

  // ─── 节点 ID 格式 + 保留字检查 ────────────────────────────────────────────
  for (const node of nodes) {
    if (!NODE_ID_REGEX.test(node.id)) {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_INVALID_NODE_ID,
        message: `节点 ID '${node.id}' 格式不合规，须满足 ^[a-z][a-z0-9_]*$`,
        node_id: node.id,
      });
    }
    if (RESERVED_NODE_IDS.has(node.id)) {
      errors.push({
        severity: 'error',
        code: ERROR_CODES.E_NODE_ID_RESERVED,
        message: `节点 ID '${node.id}' 是保留字，不可使用`,
        node_id: node.id,
      });
    }
  }

  // ─── 节点 config 校验 ────────────────────────────────────────────────────────
  for (const node of nodes) {
    const ntype = node.type as NodeType;
    const schema = NODE_SCHEMAS[ntype];
    if (!schema) continue; // 未知类型由 JSON Schema 层拦截

    const cfg = node.config ?? {};

    // if_else 特殊检查：缺 default_target
    if (ntype === 'if_else') {
      const ifCfg = cfg as Record<string, unknown>;
      if (!ifCfg.default_target) {
        errors.push({
          severity: 'error',
          code: ERROR_CODES.E_IF_ELSE_NO_DEFAULT,
          message: `if_else 节点 '${node.id}' 缺少 default_target 字段`,
          node_id: node.id,
          field_path: 'config.default_target',
        });
      }

      // if_else 条件目标检查（需要节点 ID 集合）
      const conditions = (ifCfg.conditions as Array<{ target_node_id?: string }>) ?? [];
      for (let i = 0; i < conditions.length; i++) {
        const tgt = conditions[i]?.target_node_id;
        if (tgt && !nodeIdSet.has(tgt)) {
          errors.push({
            severity: 'error',
            code: ERROR_CODES.E_IF_ELSE_BAD_TARGET,
            message: `if_else 节点 '${node.id}' 的条件 [${i}] 目标 '${tgt}' 不存在`,
            node_id: node.id,
            field_path: `config.conditions[${i}].target_node_id`,
          });
        }
      }
      const defaultTgt = ifCfg.default_target as string | undefined;
      if (defaultTgt && !nodeIdSet.has(defaultTgt)) {
        errors.push({
          severity: 'error',
          code: ERROR_CODES.E_IF_ELSE_BAD_TARGET,
          message: `if_else 节点 '${node.id}' 的 default_target '${defaultTgt}' 不存在`,
          node_id: node.id,
          field_path: 'config.default_target',
        });
      }
    }

    // Zod safeParse 校验
    const result = schema.safeParse(cfg);
    if (!result.success) {
      for (const issue of result.error.issues) {
        const fieldPath = ['config', ...issue.path].join('.');
        errors.push({
          severity: 'error',
          code: ERROR_CODES.E_INVALID_CONFIG,
          message: `节点 '${node.id}'（类型 ${ntype}）配置错误：${issue.message}（字段 ${fieldPath}）`,
          node_id: node.id,
          field_path: fieldPath,
        });
      }
    }
  }

  return errors;
}
