'use client';

/**
 * RoleGate 组件 — 页面级软权限隔离
 * 根据当前用户角色决定是否渲染 children
 * 注意：这是软隔离，硬隔离由后端 RBAC 兜底
 */

import type { ReactNode } from 'react';
import type { RoleCode } from '@/lib/types/api';
import { useUserStore } from '@/lib/stores/user-store';

export interface RoleGateProps {
  /** 需要的角色（字符串或数组，数组时满足其一即可） */
  need: RoleCode | RoleCode[];
  /** 角色不满足时渲染的内容（默认 null） */
  fallback?: ReactNode;
  children: ReactNode;
}

/**
 * 包裹需要特定角色才能看到的内容
 *
 * 例：
 * ```tsx
 * <RoleGate need="admin">
 *   <InviteMemberButton />
 * </RoleGate>
 * ```
 */
export function RoleGate({ need, children, fallback = null }: RoleGateProps) {
  const role = useUserStore((state) => state.role);

  const needArr: RoleCode[] = Array.isArray(need) ? need : [need];

  // 未知角色（未登录/加载中）时显示 fallback
  if (!role) {
    return <>{fallback}</>;
  }

  // super_admin 视为最高权限，包含所有角色
  if (role === 'super_admin' || needArr.includes(role)) {
    return <>{children}</>;
  }

  return <>{fallback}</>;
}
