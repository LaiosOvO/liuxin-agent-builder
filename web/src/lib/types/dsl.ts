/**
 * DSL 类型定义
 * 与后端 Python Pydantic DSL schema 对齐
 * Phase 2 Plan 02-03 实现
 */

/** 节点类型枚举 */
export type NodeType = 'start' | 'end' | 'llm' | 'tool' | 'if_else';

/** LLM 节点配置 */
export interface LLMNodeConfig {
  model: string;
  system_prompt: string;
  user_prompt: string;
  temperature: number;
  timeout_sec: number;
  retry_count: number;
  backoff_base_sec: number;
  raw_prompt: boolean;
}

/** Tool 节点 HTTP 子配置 */
export interface ToolHttpConfig {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  url: string;
  headers: Record<string, string>;
  body: string;
}

/** Tool 节点 Python 子配置 */
export interface ToolPythonConfig {
  function: string;
  args: Record<string, unknown>;
}

/** Tool 节点配置 */
export interface ToolNodeConfig {
  kind: 'http' | 'python';
  http?: ToolHttpConfig;
  python?: ToolPythonConfig;
}

/** IfElse 节点单条件 */
export interface IfElseCondition {
  expr: string;
  target_node_id: string;
  label: string;
}

/** IfElse 节点配置 */
export interface IfElseNodeConfig {
  conditions: IfElseCondition[];
  default_target: string;
}

/** DSL 节点定义 */
export interface DSLNode {
  id: string;
  type: NodeType;
  position: { x: number; y: number };
  config: Record<string, unknown>;
}

/** DSL 边定义 */
export interface DSLEdge {
  id: string;
  source: string;
  target: string;
}

/** 状态字段类型 */
export type StateFieldType = 'str' | 'int' | 'float' | 'bool' | 'list' | 'dict' | 'any';

/** DSL 完整定义（与后端 WorkflowDsl Pydantic model 对齐） */
export interface DSL {
  version: '1.0';
  name: string;
  state_schema: Record<string, StateFieldType>;
  nodes: DSLNode[];
  edges: DSLEdge[];
}

/** 工作流摘要（API 列表返回） */
export interface WorkflowSummary {
  id: string;
  name: string;
  status: 'draft' | 'published';
  updated_at: string;
  created_at: string;
}

/** 工作流详情（API 详情返回，含 DSL） */
export interface WorkflowDetail extends WorkflowSummary {
  dsl: DSL;
}

/** DSL 校验错误 */
export interface ValidationError {
  node_id: string | null;
  edge_id: string | null;
  message: string;
  severity: 'error' | 'warning';
}

/** 创建工作流请求体 */
export interface CreateWorkflowInput {
  name: string;
}

/** DSL 版本号 */
export const DSL_VERSION = '1.0' as const;

/** 保留节点 ID 集合（与后端 RESERVED_NODE_IDS 对齐） */
export const RESERVED_NODE_IDS = new Set([
  'state',
  'event',
  'ptr',
  '__ptr__',
  'start_event',
  'end_event',
]);

/** 节点 ID 合法字符正则 */
export const NODE_ID_REGEX = /^[a-z][a-z0-9_]*$/;

/** 各节点类型的默认配置 */
export function defaultConfigFor(type: NodeType): Record<string, unknown> {
  switch (type) {
    case 'start':
      return {};
    case 'end':
      return {};
    case 'llm':
      return {
        model: 'openai/gpt-4o',
        system_prompt: '',
        user_prompt: '',
        temperature: 0.7,
        timeout_sec: 30,
        retry_count: 3,
        backoff_base_sec: 1,
        raw_prompt: false,
      } satisfies LLMNodeConfig;
    case 'tool':
      return {
        kind: 'http',
        http: {
          method: 'GET',
          url: '',
          headers: {},
          body: '',
        },
      } satisfies ToolNodeConfig;
    case 'if_else':
      return {
        conditions: [],
        default_target: '',
      } satisfies IfElseNodeConfig;
    default:
      return {};
  }
}

/** 各节点类型的默认显示标签 */
export function defaultLabelFor(type: NodeType): string {
  switch (type) {
    case 'start':
      return '开始';
    case 'end':
      return '结束';
    case 'llm':
      return 'LLM 节点';
    case 'tool':
      return '工具节点';
    case 'if_else':
      return '条件分支';
    default:
      return type;
  }
}
