/**
 * 邀请相关 API 封装
 * 对应后端 /api/invites/* 端点
 */

import { apiCall } from './client';
import type {
  AcceptInviteRequest,
  CreateInviteRequest,
  InvitePreview,
  InviteRecord,
  MessageResponse,
} from '@/lib/types/api';

/** 获取邀请预览信息（不消费 token） */
export async function getInvitePreview(
  token: string,
  signal?: AbortSignal,
): Promise<InvitePreview> {
  return apiCall<InvitePreview>(
    `/invites/accept?token=${encodeURIComponent(token)}`,
    { signal },
  );
}

/** 接受邀请（注册并加入 workspace） */
export async function acceptInvite(
  data: AcceptInviteRequest,
): Promise<MessageResponse> {
  return apiCall<MessageResponse>('/invites/accept', {
    method: 'POST',
    body: data,
  });
}

/** 获取邀请列表（admin 限定） */
export async function listInvites(signal?: AbortSignal): Promise<InviteRecord[]> {
  return apiCall<InviteRecord[]>('/invites/list', { signal });
}

/** 发送邀请（admin 限定） */
export async function createInvite(
  data: CreateInviteRequest,
): Promise<MessageResponse> {
  return apiCall<MessageResponse>('/invites', {
    method: 'POST',
    body: data,
  });
}
