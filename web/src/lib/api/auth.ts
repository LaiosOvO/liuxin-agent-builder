/**
 * 认证相关 API 封装
 * 对应后端 /api/auth/* 与 /api/setup/* 端点
 */

import { apiCall } from './client';
import type {
  LoginRequest,
  MeResponse,
  MessageResponse,
  SetupInitializeRequest,
  SetupStateResponse,
} from '@/lib/types/api';

/** 获取系统初始化状态 */
export async function getSetupState(signal?: AbortSignal): Promise<SetupStateResponse> {
  return apiCall<SetupStateResponse>('/setup/state', { signal });
}

/** 首次启动初始化（创建 super_admin + 首个 workspace） */
export async function initializeSetup(
  data: SetupInitializeRequest,
): Promise<MessageResponse> {
  return apiCall<MessageResponse>('/setup/initialize', {
    method: 'POST',
    body: data,
  });
}

/** 邮箱密码登录 */
export async function login(data: LoginRequest): Promise<MessageResponse> {
  return apiCall<MessageResponse>('/auth/login', {
    method: 'POST',
    body: data,
  });
}

/** 登出 */
export async function logout(): Promise<MessageResponse> {
  return apiCall<MessageResponse>('/auth/logout', {
    method: 'POST',
  });
}

/** 获取当前登录用户信息 */
export async function getMe(signal?: AbortSignal): Promise<MeResponse> {
  return apiCall<MeResponse>('/auth/me', { signal });
}
