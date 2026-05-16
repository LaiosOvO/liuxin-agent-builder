'use client';

/**
 * Zustand 用户状态 store
 * 存储当前登录用户、workspace 列表、当前 workspace 和角色
 */

import { create } from 'zustand';
import type {
  MeResponse,
  RoleCode,
  User,
  Workspace,
  WorkspaceMembership,
} from '@/lib/types/api';

interface UserState {
  /** 当前登录用户（null 表示未登录） */
  user: User | null;
  /** 用户所在的所有 workspace 列表 */
  workspaces: WorkspaceMembership[];
  /** 当前选中的 workspace */
  currentWorkspace: Workspace | null;
  /** 当前用户在 currentWorkspace 中的角色 */
  role: RoleCode | null;

  /** 从 /api/auth/me 响应更新 store */
  setMe: (response: MeResponse) => void;
  /** 清空用户状态（登出时调用） */
  clear: () => void;
}

const initialState = {
  user: null,
  workspaces: [],
  currentWorkspace: null,
  role: null,
} satisfies Omit<UserState, 'setMe' | 'clear'>;

export const useUserStore = create<UserState>((set) => ({
  ...initialState,

  setMe: (response: MeResponse) =>
    set({
      user: response.user,
      workspaces: response.workspaces,
      currentWorkspace: response.current_workspace,
      role: response.role_in_current_workspace,
    }),

  clear: () => set({ ...initialState }),
}));
