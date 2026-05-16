/**
 * DSL 验证错误类型定义
 * 与后端 Python ValidationError dataclass 完全对齐
 *
 * 错误代码说明：
 *   E_NO_START            — 无 start 节点
 *   E_NO_END              — 无 end 节点
 *   E_MULTIPLE_START      — 超过一个 start 节点
 *   E_DUPLICATE_NODE_ID   — 节点 ID 重复
 *   E_DANGLING_EDGE       — 边指向不存在节点
 *   E_START_HAS_INBOUND   — start 节点有入边
 *   E_END_HAS_OUTBOUND    — end 节点有出边
 *   E_ORPHAN_NODE         — 节点孤立（无入无出，除 start 外）
 *   E_CYCLE               — 节点连成环
 *   E_UNREACHABLE_END     — end 节点从 start 不可达
 *   E_INVALID_NODE_ID     — 节点 ID 格式不合规
 *   E_NODE_ID_RESERVED    — 节点 ID 命中保留字
 *   E_INVALID_CONFIG      — 节点 config 不符合其 Schema
 *   E_INVALID_STATE_TYPE  — state_schema 字段类型不在支持列表
 *   E_IF_ELSE_NO_DEFAULT  — if_else 节点缺 default_target
 *   E_IF_ELSE_BAD_TARGET  — if_else 条件目标节点不存在
 *   E_UNDEFINED_VAR       — 模板引用变量不在符号表
 *   E_UNDEFINED_FIELD     — 模板引用 node_id.field，field 不在该节点输出字段
 *   E_VAR_NOT_UPSTREAM    — 引用了下游节点（拓扑序检查）
 */

/** 验证错误严重级别 */
export type ValidationSeverity = 'error' | 'warning';

/** 单个 DSL 验证错误（与后端 ValidationError dataclass 对齐） */
export interface ValidationError {
  /** 严重级别："error" 阻断执行，"warning" 可放行 */
  severity: ValidationSeverity;
  /** 错误代码，如 E_CYCLE */
  code: string;
  /** 中文错误描述 */
  message: string;
  /** 涉及的节点 ID（可选） */
  node_id?: string;
  /** 涉及的边 ID（可选） */
  edge_id?: string;
  /** 涉及的字段路径（如 "config.temperature"，可选） */
  field_path?: string;
}

/** 已知错误代码枚举（便于静态检查） */
export const ERROR_CODES = {
  E_NO_START: 'E_NO_START',
  E_NO_END: 'E_NO_END',
  E_MULTIPLE_START: 'E_MULTIPLE_START',
  E_DUPLICATE_NODE_ID: 'E_DUPLICATE_NODE_ID',
  E_DANGLING_EDGE: 'E_DANGLING_EDGE',
  E_START_HAS_INBOUND: 'E_START_HAS_INBOUND',
  E_END_HAS_OUTBOUND: 'E_END_HAS_OUTBOUND',
  E_ORPHAN_NODE: 'E_ORPHAN_NODE',
  E_CYCLE: 'E_CYCLE',
  E_UNREACHABLE_END: 'E_UNREACHABLE_END',
  E_INVALID_NODE_ID: 'E_INVALID_NODE_ID',
  E_NODE_ID_RESERVED: 'E_NODE_ID_RESERVED',
  E_INVALID_CONFIG: 'E_INVALID_CONFIG',
  E_INVALID_STATE_TYPE: 'E_INVALID_STATE_TYPE',
  E_IF_ELSE_NO_DEFAULT: 'E_IF_ELSE_NO_DEFAULT',
  E_IF_ELSE_BAD_TARGET: 'E_IF_ELSE_BAD_TARGET',
  E_UNDEFINED_VAR: 'E_UNDEFINED_VAR',
  E_UNDEFINED_FIELD: 'E_UNDEFINED_FIELD',
  E_VAR_NOT_UPSTREAM: 'E_VAR_NOT_UPSTREAM',
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];
