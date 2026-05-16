/**
 * 当前用户相关 API 封装
 * 对应后端 /api/me/* 端点
 */

import { apiCall } from './client';
import type { MessageResponse } from '@/lib/types/api';

/** 切换当前 workspace */
export async function switchWorkspace(
  workspaceId: string,
): Promise<MessageResponse> {
  return apiCall<MessageResponse>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/switch`,
    { method: 'POST' },
  );
}
