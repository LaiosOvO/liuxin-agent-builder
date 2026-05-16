'use client';

/**
 * Dashboard 布局
 * 包含左侧 sidebar + 顶栏（WorkspaceSwitcher + 用户菜单）
 * 所有 /dashboard/* 路由共享此布局
 */

import type { ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { WorkspaceSwitcher } from '@/components/agent-builder/workspace-switcher';
import { RoleGate } from '@/components/auth/role-gate';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { useUserStore } from '@/lib/stores/user-store';
import { logout } from '@/lib/api/auth';
import { AgentBuilderQueryProvider } from '@/lib/providers/query-provider';
import {
  LayoutDashboardIcon,
  UsersIcon,
  WorkflowIcon,
  LogOutIcon,
  SettingsIcon,
} from 'lucide-react';
import { Toaster } from 'sonner';

function DashboardLayoutInner({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { user, loading } = useCurrentUser();
  const { clear } = useUserStore();

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // 忽略登出错误
    } finally {
      clear();
      router.push('/login');
    }
  };

  // 未登录时重定向（middleware 已处理大部分情况，这里是双重保险）
  if (!loading && !user) {
    router.push('/login');
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* 左侧 Sidebar */}
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
        {/* Logo */}
        <div className="h-14 flex items-center px-5 border-b border-gray-100">
          <Link href="/dashboard" className="text-indigo-600 font-bold text-lg tracking-tight">
            agent-builder
          </Link>
        </div>

        {/* 导航菜单 */}
        <nav className="flex-1 py-4 px-3 space-y-1">
          <SidebarLink href="/dashboard" icon={<LayoutDashboardIcon className="h-4 w-4" />} label="控制台" />
          <SidebarLink href="/dashboard/canvas" icon={<WorkflowIcon className="h-4 w-4" />} label="画布（Phase 2）" disabled />
          <RoleGate need={['super_admin', 'admin']}>
            <SidebarLink href="/dashboard/members" icon={<UsersIcon className="h-4 w-4" />} label="成员管理" />
          </RoleGate>
          <SidebarLink href="#" icon={<SettingsIcon className="h-4 w-4" />} label="设置（v2）" disabled />
        </nav>

        {/* 底部用户区 */}
        <div className="border-t border-gray-100 p-4">
          <div className="text-xs text-gray-500 truncate mb-2">
            {user?.display_name ?? user?.email ?? '...'}
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="flex items-center gap-2 text-xs text-gray-500 hover:text-red-500 transition-colors"
          >
            <LogOutIcon className="h-3.5 w-3.5" />
            退出登录
          </button>
        </div>
      </aside>

      {/* 主内容区 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 顶栏 */}
        <header className="h-14 bg-white border-b border-gray-200 flex items-center px-6 gap-4">
          <WorkspaceSwitcher />
          <div className="flex-1" />
          <span className="text-xs text-gray-400 bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-full font-medium">
            Phase 1
          </span>
        </header>

        {/* 页面内容 */}
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}

function SidebarLink({
  href,
  icon,
  label,
  disabled,
}: {
  href: string;
  icon: ReactNode;
  label: string;
  disabled?: boolean;
}) {
  if (disabled) {
    return (
      <div className="flex items-center gap-3 px-3 py-2 text-sm text-gray-300 cursor-not-allowed rounded-lg">
        {icon}
        <span>{label}</span>
      </div>
    );
  }

  return (
    <Link
      href={href}
      className="flex items-center gap-3 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 rounded-lg transition-colors"
    >
      {icon}
      <span>{label}</span>
    </Link>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <AgentBuilderQueryProvider>
      <Toaster position="top-right" richColors />
      <DashboardLayoutInner>{children}</DashboardLayoutInner>
    </AgentBuilderQueryProvider>
  );
}
