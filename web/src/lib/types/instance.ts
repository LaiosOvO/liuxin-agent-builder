/**
 * 实例相关 TypeScript 类型定义
 * 与后端 schemas/instance.py Pydantic 模型对齐（Plan 02-08）
 */

/** 实例状态枚举（对应后端 FlowInstance.status）*/
export type InstanceStatus = 'pending' | 'running' | 'completed' | 'failed' | 'aborted';

/** 节点状态枚举（对应后端 NodeState.status）*/
export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed';

/** 单节点执行状态 */
export interface NodeStateInfo {
  id: string;
  node_id: string;
  node_type: string;
  status: NodeStatus;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  retries: number;
  output_summary: Record<string, unknown> | null;
}

/** 实例摘要（列表页使用） */
export interface InstanceSummary {
  id: string;
  workflow_id: string;
  workflow_version_id: string;
  status: InstanceStatus;
  initial_input: Record<string, unknown> | null;
  error_message: string | null;
  created_by: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** 实例详情（含节点状态 timeline） */
export interface InstanceDetail extends InstanceSummary {
  final_output: Record<string, unknown> | null;
  dsl_snapshot: Record<string, unknown> | null;
  node_states: NodeStateInfo[];
}

/** 实例分页列表响应 */
export interface InstanceListResponse {
  items: InstanceSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** 创建实例请求参数 */
export interface CreateInstanceInput {
  initial_input: Record<string, unknown>;
}

/** 实例列表过滤参数 */
export interface InstanceListParams {
  workflow_id?: string;
  status?: InstanceStatus;
  search?: string;
  page?: number;
  page_size?: number;
}

/** SSE 事件类型 */
export type SseEventType =
  | 'node.start'
  | 'node.complete'
  | 'node.error'
  | 'state.update'
  | 'instance.complete'
  | 'instance.failed';

/** SSE 事件 payload */
export interface SseEvent {
  event: SseEventType;
  node_id?: string;
  instance_id: string;
  timestamp: string;
  data: Record<string, unknown>;
}

/** 实例状态显示配置（badge 颜色 + 标签） */
export const INSTANCE_STATUS_CONFIG: Record<
  InstanceStatus,
  { label: string; className: string }
> = {
  pending: { label: '等待中', className: 'bg-gray-100 text-gray-600' },
  running: { label: '运行中', className: 'bg-blue-100 text-blue-700 animate-pulse' },
  completed: { label: '已完成', className: 'bg-green-100 text-green-700' },
  failed: { label: '失败', className: 'bg-red-100 text-red-700' },
  aborted: { label: '已中止', className: 'bg-orange-100 text-orange-700' },
};

/** 节点状态显示配置 */
export const NODE_STATUS_CONFIG: Record<
  NodeStatus,
  { label: string; className: string }
> = {
  pending: { label: '等待', className: 'text-gray-400' },
  running: { label: '运行中', className: 'text-blue-500' },
  completed: { label: '完成', className: 'text-green-600' },
  failed: { label: '失败', className: 'text-red-600' },
};
