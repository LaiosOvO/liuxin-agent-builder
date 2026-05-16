/**
 * E2E 测试用 API 客户端。
 *
 * 直接调用后端 API（绕过浏览器 UI），用于 test fixture 中快速创建测试数据。
 * 比 UI 操作快 10x+，减少测试脆弱性。
 *
 * 约定：
 * - 基础 URL 从 API_BASE_URL 环境变量读取，默认 http://localhost:8080（nginx 内网入口）
 * - Cookie 从响应自动提取，作为后续请求的认证凭据
 * - 错误统一抛出 ApiError，携带 status + message
 */

export const API_BASE_URL = process.env.API_BASE_URL ?? 'http://localhost:8080';

/** API 错误类型 */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown = null) {
    super(`API 错误 ${status}: ${message}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

/** 认证 cookie 字符串（Set-Cookie 头提取） */
export type AuthCookie = string;

/** API 客户端选项 */
interface FetchOptions {
  method?: string;
  body?: unknown;
  cookie?: AuthCookie;
  headers?: Record<string, string>;
}

/**
 * 底层 fetch 封装，统一处理认证 cookie 和错误。
 */
export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {},
): Promise<{ data: T; cookie?: AuthCookie; status: number }> {
  const { method = 'GET', body, cookie, headers = {} } = options;

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  };

  if (cookie) {
    requestHeaders['Cookie'] = cookie;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: requestHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // 提取认证 cookie（登录响应）
  const setCookieHeader = response.headers.get('set-cookie');
  const authCookie = setCookieHeader ?? undefined;

  const status = response.status;

  // 解析响应体
  let data: T;
  const contentType = response.headers.get('content-type') ?? '';

  if (contentType.includes('application/json')) {
    data = await response.json();
  } else {
    data = (await response.text()) as unknown as T;
  }

  if (!response.ok) {
    const errorMessage =
      typeof data === 'object' && data !== null && 'detail' in data
        ? String((data as Record<string, unknown>)['detail'])
        : `HTTP ${status}`;
    throw new ApiError(status, errorMessage, data);
  }

  return { data, cookie: authCookie, status };
}

/** Setup 初始化响应 */
export interface SetupStateResponse {
  initialized: boolean;
}

/** 登录响应 */
export interface LoginResponse {
  access_token?: string;
  token_type?: string;
  user?: {
    id: string;
    email: string;
    display_name: string;
    status: string;
    is_super_admin: boolean;
  };
}

/** 用户信息 */
export interface MeResponse {
  user: {
    id: string;
    email: string;
    display_name: string;
    status: string;
    is_super_admin: boolean;
  };
  workspaces: Array<{
    workspace_id: string;
    workspace_name: string;
    role_code: string;
  }>;
  current_workspace: {
    id: string;
    name: string;
    slug: string;
  } | null;
}

/** Workspace 初始化请求 */
export interface SetupInitRequest {
  email: string;
  password: string;
  display_name: string;
  workspace_name: string;
}

/** 邀请创建请求 */
export interface InviteCreateRequest {
  email: string;
  role_code: string;
}

/** 邀请创建响应 */
export interface InviteResponse {
  id: string;
  email: string;
  role_code: string;
  token?: string;
  expires_at: string;
}

/**
 * 查询系统初始化状态。
 */
export async function getSetupState(): Promise<SetupStateResponse> {
  const { data } = await apiFetch<SetupStateResponse>('/api/setup/state');
  return data;
}

/**
 * 初始化系统（创建第一个超级管理员 + workspace）。
 * @returns 认证 cookie（已登录的 super_admin 会话）
 */
export async function initializeSystem(
  req: SetupInitRequest,
): Promise<{ cookie: AuthCookie; data: unknown }> {
  const { data, cookie } = await apiFetch('/api/setup/initialize', {
    method: 'POST',
    body: req,
  });

  if (!cookie) throw new Error('setup/initialize 未返回认证 cookie');
  return { cookie, data };
}

/**
 * 登录。
 * @returns 认证 cookie
 */
export async function login(
  email: string,
  password: string,
): Promise<{ cookie: AuthCookie; data: LoginResponse }> {
  const { data, cookie } = await apiFetch<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: { email, password },
  });

  if (!cookie) throw new Error(`登录 ${email} 未返回认证 cookie`);
  return { cookie, data };
}

/**
 * 获取当前登录用户信息。
 */
export async function getMe(cookie: AuthCookie): Promise<MeResponse> {
  const { data } = await apiFetch<MeResponse>('/api/auth/me', { cookie });
  return data;
}

/**
 * 创建邀请。
 * @returns 邀请 token（用于构造邀请链接）
 */
export async function createInvite(
  adminCookie: AuthCookie,
  req: InviteCreateRequest,
): Promise<InviteResponse> {
  const { data } = await apiFetch<InviteResponse>('/api/invites', {
    method: 'POST',
    cookie: adminCookie,
    body: req,
  });
  return data;
}

/**
 * 接受邀请（通过邀请 token 完成注册）。
 */
export async function acceptInvite(
  inviteToken: string,
  password: string,
  displayName: string,
): Promise<{ cookie: AuthCookie }> {
  const { cookie } = await apiFetch('/api/invites/accept', {
    method: 'POST',
    body: {
      token: inviteToken,
      password,
      display_name: displayName,
    },
  });

  if (!cookie) throw new Error('acceptInvite 未返回认证 cookie');
  return { cookie };
}

/**
 * 发送验证邮件并验证（通过 token）。
 * 仅用于测试环境（直接消费 MailHog 捕获的 token）。
 */
export async function verifyEmail(token: string): Promise<void> {
  await apiFetch(`/api/auth/verify-email?token=${encodeURIComponent(token)}`);
}

/**
 * 发起任意 API 请求（低层访问，用于 RBAC 边界测试）。
 */
export async function rawFetch(
  path: string,
  options: FetchOptions = {},
): Promise<{ status: number; data: unknown }> {
  try {
    const result = await apiFetch<unknown>(path, options);
    return { status: result.status, data: result.data };
  } catch (err) {
    if (err instanceof ApiError) {
      return { status: err.status, data: err.body };
    }
    throw err;
  }
}
