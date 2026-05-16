'use client';

/**
 * 获取当前登录用户 hook
 * - 优先使用 Zustand store 中的缓存数据
 * - store 为空时自动从 /api/auth/me 拉取并写入 store
 */

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getMe } from '@/lib/api/auth';
import { useUserStore } from '@/lib/stores/user-store';
import type { MeResponse, RoleCode, User, Workspace, WorkspaceMembership } from '@/lib/types/api';

interface CurrentUserResult {
  user: User | null;
  workspaces: WorkspaceMembership[];
  currentWorkspace: Workspace | null;
  role: RoleCode | null;
  loading: boolean;
  refetch: () => void;
}

export function useCurrentUser(): CurrentUserResult {
  const { user, workspaces, currentWorkspace, role, setMe } = useUserStore();

  const query = useQuery<MeResponse>({
    queryKey: ['me'],
    queryFn: ({ signal }) => getMe(signal),
    // 已有缓存时不重复请求
    enabled: user === null,
    retry: false,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (query.data) {
      setMe(query.data);
    }
  }, [query.data, setMe]);

  return {
    user,
    workspaces,
    currentWorkspace,
    role,
    loading: query.isLoading,
    refetch: query.refetch,
  };
}
