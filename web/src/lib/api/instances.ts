/**
 * 实例 API 客户端（Plan 02-08）
 * 接入 /api/agent_builder/v1/instances 真实后端
 */

import { apiCall } from '@/lib/api/client';
import type {
  CreateInstanceInput,
  InstanceDetail,
  InstanceListParams,
  InstanceListResponse,
  InstanceSummary,
} from '@/lib/types/instance';

/** 实例 API 封装 */
export const instancesApi = {
  /** 列出实例（支持过滤 + 分页） */
  list: (params?: InstanceListParams): Promise<InstanceListResponse> => {
    const qs = new URLSearchParams();
    if (params?.workflow_id) qs.set('workflow_id', params.workflow_id);
    if (params?.status) qs.set('status', params.status);
    if (params?.search) qs.set('search', params.search);
    if (params?.page != null) qs.set('page', String(params.page));
    if (params?.page_size != null) qs.set('page_size', String(params.page_size));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return apiCall<InstanceListResponse>(`/agent_builder/v1/instances${suffix}`);
  },

  /** 获取实例详情（含 node_states[]） */
  get: (id: string): Promise<InstanceDetail> =>
    apiCall<InstanceDetail>(`/agent_builder/v1/instances/${id}`),

  /** 创建实例（基于已发布工作流版本） */
  start: (workflowId: string, input: CreateInstanceInput): Promise<InstanceSummary> =>
    apiCall<InstanceSummary>(`/agent_builder/v1/workflows/${workflowId}/instances`, {
      method: 'POST',
      body: input,
    }),

  /** 中止实例 */
  abort: (id: string): Promise<InstanceSummary> =>
    apiCall<InstanceSummary>(`/agent_builder/v1/instances/${id}/abort`, {
      method: 'POST',
    }),
};
