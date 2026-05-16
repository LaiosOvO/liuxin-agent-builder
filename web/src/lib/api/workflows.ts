/**
 * 工作流 API 客户端
 * Plan 02-03 定义接口签名；Plan 02-08 接入真实后端实现
 */

import { apiCall } from '@/lib/api/client';
import type {
  WorkflowSummary,
  WorkflowDetail,
  DSL,
  ValidationError,
  CreateWorkflowInput,
} from '@/lib/types/dsl';

/** 工作流 API 封装 */
export const workflowsApi = {
  /** 列出当前 workspace 下所有工作流 */
  list: (): Promise<WorkflowSummary[]> =>
    apiCall<WorkflowSummary[]>('/v1/workflows'),

  /** 获取工作流详情（含 DSL） */
  get: (id: string): Promise<WorkflowDetail> =>
    apiCall<WorkflowDetail>(`/v1/workflows/${id}`),

  /** 创建新工作流 */
  create: (input: CreateWorkflowInput): Promise<WorkflowSummary> =>
    apiCall<WorkflowSummary>('/v1/workflows', {
      method: 'POST',
      body: input,
    }),

  /** 保存草稿 DSL */
  saveDraft: (id: string, dsl: DSL): Promise<WorkflowDetail> =>
    apiCall<WorkflowDetail>(`/v1/workflows/${id}/draft`, {
      method: 'PUT',
      body: { dsl },
    }),

  /** 发布工作流（后端先全量校验 DSL） */
  publish: (id: string): Promise<WorkflowDetail> =>
    apiCall<WorkflowDetail>(`/v1/workflows/${id}/publish`, {
      method: 'POST',
      body: {},
    }),

  /** 删除工作流 */
  delete: (id: string): Promise<void> =>
    apiCall<void>(`/v1/workflows/${id}`, {
      method: 'DELETE',
    }),

  /** 校验 DSL（不保存，返回 errors 列表） */
  validate: (dsl: DSL): Promise<{ errors: ValidationError[] }> =>
    apiCall<{ errors: ValidationError[] }>('/v1/workflows/validate', {
      method: 'POST',
      body: { dsl },
    }),
};
