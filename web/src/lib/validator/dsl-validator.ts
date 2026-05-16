/**
 * DSL 验证器主入口
 *
 * 一次调用返回所有 4 类错误，不因一类 error 短路（设计原则：
 * "所有 error 一次性返回，不要修一个 error 才发现下一个"）。
 *
 * 与后端 Python DSLValidator.validate() 完全对齐：
 * - 同样 4 类错误码（E_CYCLE / E_UNDEFINED_VAR / E_INVALID_CONFIG 等）
 * - 同样的中文错误消息格式
 * - 同样的 field_path 格式（如 "config.temperature"）
 *
 * 使用方式：
 *   const errors = validateDSL(dsl);
 *   const fatal = errors.filter(e => e.severity === 'error');
 *   if (fatal.length > 0) {
 *     // 阻断发布
 *   }
 */

import type { DSL } from '@/lib/types/dsl';
import type { ValidationError } from './types';
import { validateStructure } from './structure';
import { validateConfigs } from './configs';
import { validateVariables } from './variables';

export type { ValidationError } from './types';
export { ERROR_CODES } from './types';

/**
 * 验证 DSL，一次返回所有 4 类错误。
 *
 * @param dsl - 待验证的 DSL 对象
 * @returns ValidationError 数组（空数组表示无错误）
 */
export function validateDSL(dsl: DSL): ValidationError[] {
  // 顶层结构检查（基础字段是否存在）
  if (!dsl || typeof dsl !== 'object') {
    return [
      {
        severity: 'error',
        code: 'E_INVALID_DSL',
        message: 'DSL 必须是一个对象',
      },
    ];
  }

  if (!Array.isArray(dsl.nodes)) {
    return [
      {
        severity: 'error',
        code: 'E_INVALID_DSL',
        message: "DSL 缺少 'nodes' 字段或类型错误",
      },
    ];
  }

  if (!Array.isArray(dsl.edges)) {
    return [
      {
        severity: 'error',
        code: 'E_INVALID_DSL',
        message: "DSL 缺少 'edges' 字段或类型错误",
      },
    ];
  }

  // 4 类全检（并行收集，不互相短路）
  const errors: ValidationError[] = [
    ...validateStructure(dsl),
    ...validateConfigs(dsl),
    ...validateVariables(dsl),
  ];

  return errors;
}

/**
 * 判断 DSL 是否有致命错误（阻断发布）。
 *
 * @param errors - validateDSL 返回的错误列表
 * @returns true 表示有 error 级别错误
 */
export function hasFatalErrors(errors: ValidationError[]): boolean {
  return errors.some((e) => e.severity === 'error');
}

/**
 * 按节点 ID 分组错误。
 *
 * @param errors - validateDSL 返回的错误列表
 * @returns Map：node_id → errors（global 错误放在 key '__global__' 下）
 */
export function groupErrorsByNode(
  errors: ValidationError[],
): Record<string, ValidationError[]> {
  const map: Record<string, ValidationError[]> = {};
  for (const err of errors) {
    const key = err.node_id ?? '__global__';
    if (!map[key]) {
      map[key] = [];
    }
    map[key].push(err);
  }
  return map;
}
