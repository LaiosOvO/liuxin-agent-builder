/**
 * 各节点类型的 Zod Schema + 输出字段定义
 *
 * 与后端 Python NODE_SCHEMAS 对齐，保证前端 TypeScript 校验规则与后端完全一致。
 *
 * 输出字段（OUTPUT_FIELDS）：节点执行后写入 state 的顶层字段集合。
 * 变量引用 {{ node_id.field }} 时，field 必须在此集合中。
 */

import { z } from 'zod';
import type { NodeType } from '@/lib/types/dsl';

// ─── Start 节点 ────────────────────────────────────────────────────────────────

export const startNodeSchema = z.object({}).passthrough();

export const START_OUTPUT_FIELDS = new Set<string>(['output', 'status']);

// ─── End 节点 ─────────────────────────────────────────────────────────────────

export const endNodeSchema = z.object({}).passthrough();

export const END_OUTPUT_FIELDS = new Set<string>(['output', 'status']);

// ─── LLM 节点 ─────────────────────────────────────────────────────────────────

export const llmNodeSchema = z.object({
  model: z.string().min(1, '模型名称不能为空'),
  system_prompt: z.string().optional().default(''),
  user_prompt: z.string().min(1, '用户 prompt 不能为空'),
  temperature: z.number().min(0).max(2),
  timeout_sec: z.number().int().min(1).max(600),
  retry_count: z.number().int().min(0).max(10),
  backoff_base_sec: z.number().min(0.1).max(60),
  raw_prompt: z.boolean().optional().default(false),
});

export const LLM_OUTPUT_FIELDS = new Set<string>(['message', 'usage', 'status']);

// ─── Tool 节点 ────────────────────────────────────────────────────────────────

export const toolHttpConfigSchema = z.object({
  method: z.enum(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']),
  url: z.string().min(1, 'URL 不能为空'),
  headers: z.record(z.string()).optional().default({}),
  body: z.string().optional().default(''),
});

export const toolPythonConfigSchema = z.object({
  function: z.string().min(1, 'function 不能为空'),
  args: z.record(z.unknown()).optional().default({}),
});

export const toolNodeSchema = z.object({
  kind: z.enum(['http', 'python']),
  http: toolHttpConfigSchema.optional(),
  python: toolPythonConfigSchema.optional(),
});

export const TOOL_OUTPUT_FIELDS = new Set<string>(['response', 'status_code', 'status']);

// ─── IfElse 节点 ──────────────────────────────────────────────────────────────

export const ifElseConditionSchema = z.object({
  expr: z.string().min(1, '条件表达式不能为空'),
  target_node_id: z.string().min(1, '目标节点 ID 不能为空'),
  label: z.string().optional().default(''),
});

export const ifElseNodeSchema = z.object({
  conditions: z.array(ifElseConditionSchema).min(1, '至少需要一个条件'),
  default_target: z.string().min(1, 'default_target 不能为空'),
});

export const IF_ELSE_OUTPUT_FIELDS = new Set<string>(['matched_branch', 'status']);

// ─── 汇总映射表 ────────────────────────────────────────────────────────────────

/** 节点类型 → Zod Schema */
export const NODE_SCHEMAS: Record<NodeType, z.ZodTypeAny> = {
  start: startNodeSchema,
  end: endNodeSchema,
  llm: llmNodeSchema,
  tool: toolNodeSchema,
  if_else: ifElseNodeSchema,
};

/** 节点类型 → 输出字段集合 */
export const NODE_OUTPUT_FIELDS: Record<NodeType, ReadonlySet<string>> = {
  start: START_OUTPUT_FIELDS,
  end: END_OUTPUT_FIELDS,
  llm: LLM_OUTPUT_FIELDS,
  tool: TOOL_OUTPUT_FIELDS,
  if_else: IF_ELSE_OUTPUT_FIELDS,
};

/** 获取节点的 Zod Schema */
export function getNodeSchema(type: NodeType): z.ZodTypeAny {
  return NODE_SCHEMAS[type];
}

/** 获取节点的输出字段集合 */
export function getNodeOutputFields(type: NodeType): ReadonlySet<string> {
  return NODE_OUTPUT_FIELDS[type] ?? new Set();
}

/** 支持的 state_schema 字段类型（与后端 SCHEMA_TYPES 对齐） */
export const SCHEMA_TYPES = new Set<string>([
  'str',
  'int',
  'float',
  'bool',
  'list',
  'dict',
  'any',
]);
