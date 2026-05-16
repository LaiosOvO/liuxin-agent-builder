'use client';

/**
 * agent-builder API 客户端
 * 统一 fetch wrapper：自动携带 credentials（httpOnly cookie）+ JSON Content-Type + 错误处理
 */

import type { ApiErrorBody } from '@/lib/types/api';

const API_BASE =
  (typeof window !== 'undefined' && (window as Window & { __API_BASE_URL__?: string }).__API_BASE_URL__) ||
  process.env.NEXT_PUBLIC_API_BASE ||
  '/api';

export interface ApiCallOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

/** API 调用错误，携带 HTTP 状态码与后端错误详情 */
export class ApiCallError extends Error {
  public readonly status: number;
  public readonly detail: ApiErrorBody;

  constructor(message: string, status: number, detail: ApiErrorBody) {
    super(message);
    this.name = 'ApiCallError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * 统一 API 调用入口
 * - 自动携带 credentials=include（httpOnly cookie 鉴权）
 * - 非 200 时解析错误并抛出 ApiCallError
 * - 401 时（排除 /auth/login 与 /setup/ 路径）自动跳转到 /login
 */
export async function apiCall<T>(
  path: string,
  opts: ApiCallOptions = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;

  const headers: Record<string, string> = {};
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(url, {
    method: opts.method ?? 'GET',
    credentials: 'include',
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  if (!res.ok) {
    let errBody: ApiErrorBody;
    try {
      errBody = (await res.json()) as ApiErrorBody;
    } catch {
      errBody = { error: res.statusText };
    }

    // 401 时除 /auth/login 与 /setup/ 自身外，跳回登录页
    if (
      res.status === 401 &&
      !path.startsWith('/auth/login') &&
      !path.startsWith('/setup/')
    ) {
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
    }

    throw new ApiCallError(
      errBody.error || res.statusText,
      res.status,
      errBody,
    );
  }

  return res.json() as Promise<T>;
}
