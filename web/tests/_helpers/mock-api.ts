/**
 * MSW handler 集合，用于测试中模拟后端 API
 */

import { http, HttpResponse } from 'msw';
import type {
  InvitePreview,
  MeResponse,
  SetupStateResponse,
} from '@/lib/types/api';

export const BASE = 'http://localhost/api';

// ===== 初始化状态 =====
export const setupStateInitialized = http.get(
  `${BASE}/setup/state`,
  () => HttpResponse.json({ initialized: true, version: '1.0.0' } satisfies SetupStateResponse),
);

export const setupStateUninitialized = http.get(
  `${BASE}/setup/state`,
  () => HttpResponse.json({ initialized: false, version: '1.0.0' } satisfies SetupStateResponse),
);

// ===== 初始化 =====
export const setupInitializeSuccess = http.post(
  `${BASE}/setup/initialize`,
  () => HttpResponse.json({ message: '初始化成功' }),
);

export const setupInitializeConflict = http.post(
  `${BASE}/setup/initialize`,
  () => HttpResponse.json({ error: '系统已初始化' }, { status: 409 }),
);

// ===== 登录 =====
export const loginSuccess = http.post(
  `${BASE}/auth/login`,
  () => HttpResponse.json({ message: '登录成功' }),
);

export const loginUnauthorized = http.post(
  `${BASE}/auth/login`,
  () => HttpResponse.json({ error: '邮箱或密码错误' }, { status: 401 }),
);

export const loginForbiddenPending = http.post(
  `${BASE}/auth/login`,
  () =>
    HttpResponse.json(
      { error: '账号未激活', detail: 'pending_verification' },
      { status: 403 },
    ),
);

export const loginTooManyRequests = http.post(
  `${BASE}/auth/login`,
  () => HttpResponse.json({ error: '请求过于频繁' }, { status: 429 }),
);

// ===== 当前用户 =====
export const meSuccess = http.get(`${BASE}/auth/me`, () => {
  const response: MeResponse = {
    user: {
      id: 'user-1',
      email: 'test@example.com',
      display_name: '测试用户',
      department: null,
      is_super_admin: false,
      status: 'active',
    },
    workspaces: [
      {
        workspace: { id: 'ws-1', name: '默认工作区', slug: 'default' },
        role: 'admin',
      },
    ],
    current_workspace: { id: 'ws-1', name: '默认工作区', slug: 'default' },
    role_in_current_workspace: 'admin',
  };
  return HttpResponse.json(response);
});

// ===== 邀请预览 =====
export const invitePreviewValid = http.get(
  `${BASE}/invites/accept`,
  () => {
    const preview: InvitePreview = {
      workspace_name: '测试工作区',
      role_code: 'editor',
      inviter_display_name: '张管理员',
      expires_at: new Date(Date.now() + 86_400_000).toISOString(),
      already_used: false,
    };
    return HttpResponse.json(preview);
  },
);

export const invitePreviewAlreadyUsed = http.get(
  `${BASE}/invites/accept`,
  () => {
    const preview: InvitePreview = {
      workspace_name: '测试工作区',
      role_code: 'editor',
      inviter_display_name: '张管理员',
      expires_at: new Date(Date.now() - 86_400_000).toISOString(),
      already_used: true,
    };
    return HttpResponse.json(preview);
  },
);

export const invitePreviewNotFound = http.get(
  `${BASE}/invites/accept`,
  () => HttpResponse.json({ error: '邀请不存在' }, { status: 404 }),
);

// ===== 接受邀请 =====
export const inviteAcceptSuccess = http.post(
  `${BASE}/invites/accept`,
  () => HttpResponse.json({ message: '注册成功' }),
);

// ===== Workspace 切换 =====
export const workspaceSwitchSuccess = http.post(
  new RegExp(`${BASE}/me/workspaces/.+/switch`),
  () => HttpResponse.json({ message: '切换成功' }),
);
