/**
 * agent-builder API 类型定义
 * 与后端 Plan 01-04 API 接口对齐
 */

/** 用户在 workspace 中的角色编码 */
export type RoleCode =
  | 'super_admin'
  | 'admin'
  | 'editor'
  | 'viewer'
  | 'external';

/** 用户账号状态 */
export type UserStatus = 'pending_verification' | 'active' | 'disabled';

/** 用户基本信息 */
export interface User {
  id: string;
  email: string;
  display_name: string | null;
  department: string | null;
  is_super_admin: boolean;
  status: UserStatus;
}

/** Workspace 基本信息 */
export interface Workspace {
  id: string;
  name: string;
  slug: string;
}

/** Workspace 成员关联 */
export interface WorkspaceMembership {
  workspace: Workspace;
  role: RoleCode;
}

/** GET /api/auth/me 响应 */
export interface MeResponse {
  user: User;
  workspaces: WorkspaceMembership[];
  current_workspace: Workspace | null;
  role_in_current_workspace: RoleCode | null;
}

/** GET /api/invites/accept?token= 响应（预览） */
export interface InvitePreview {
  workspace_name: string;
  role_code: RoleCode;
  inviter_display_name: string;
  expires_at: string;
  already_used: boolean;
}

/** 邀请记录 */
export interface InviteRecord {
  id: string;
  email: string;
  role_code: RoleCode;
  status: 'pending' | 'accepted' | 'expired';
  expires_at: string;
  created_at: string;
}

/** API 错误响应体 */
export interface ApiErrorBody {
  error: string;
  detail?: string;
  redirect?: string;
}

/** POST /api/setup/initialize 请求体 */
export interface SetupInitializeRequest {
  email: string;
  password: string;
  display_name: string;
  workspace_name: string;
}

/** GET /api/setup/state 响应 */
export interface SetupStateResponse {
  initialized: boolean;
  version: string;
}

/** POST /api/auth/login 请求体 */
export interface LoginRequest {
  email: string;
  password: string;
}

/** POST /api/invites 请求体 */
export interface CreateInviteRequest {
  email: string;
  role_code: RoleCode;
}

/** POST /api/invites/accept 请求体 */
export interface AcceptInviteRequest {
  token: string;
  password: string;
  display_name: string;
  department?: string;
}

/** 通用消息响应 */
export interface MessageResponse {
  message: string;
}
