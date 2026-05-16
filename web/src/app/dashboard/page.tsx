'use client';

/**
 * Dashboard 落地页
 * 显示欢迎信息 + 快捷入口卡片
 */

import Link from 'next/link';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { RoleGate } from '@/components/auth/role-gate';
import {
  WorkflowIcon,
  UsersIcon,
  BoxIcon,
} from 'lucide-react';

export default function DashboardPage() {
  const { user, currentWorkspace } = useCurrentUser();

  return (
    <div className="max-w-4xl">
      {/* 欢迎区 */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">
          你好，{user?.display_name ?? user?.email ?? '...'} 👋
        </h1>
        {currentWorkspace && (
          <p className="mt-1 text-gray-500 text-sm">
            当前工作区：<span className="font-medium text-gray-700">{currentWorkspace.name}</span>
          </p>
        )}
      </div>

      {/* 快捷入口卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* 打开画布（Phase 2） */}
        <Link
          href="/dashboard/canvas"
          className="group flex flex-col p-6 bg-white rounded-2xl border border-gray-200 hover:border-indigo-300 hover:shadow-md transition-all"
        >
          <div className="h-10 w-10 bg-indigo-100 rounded-xl flex items-center justify-center mb-4 group-hover:bg-indigo-200 transition-colors">
            <WorkflowIcon className="h-5 w-5 text-indigo-600" />
          </div>
          <h3 className="font-semibold text-gray-800 text-sm mb-1">打开画布</h3>
          <p className="text-xs text-gray-400">Phase 2 即将上线</p>
        </Link>

        {/* 邀请成员（admin 限定） */}
        <RoleGate
          need={['super_admin', 'admin']}
          fallback={
            <div className="flex flex-col p-6 bg-gray-50 rounded-2xl border border-gray-100 opacity-60">
              <div className="h-10 w-10 bg-gray-100 rounded-xl flex items-center justify-center mb-4">
                <UsersIcon className="h-5 w-5 text-gray-400" />
              </div>
              <h3 className="font-semibold text-gray-500 text-sm mb-1">邀请成员</h3>
              <p className="text-xs text-gray-400">需要管理员权限</p>
            </div>
          }
        >
          <Link
            href="/dashboard/members"
            className="group flex flex-col p-6 bg-white rounded-2xl border border-gray-200 hover:border-indigo-300 hover:shadow-md transition-all"
          >
            <div className="h-10 w-10 bg-emerald-100 rounded-xl flex items-center justify-center mb-4 group-hover:bg-emerald-200 transition-colors">
              <UsersIcon className="h-5 w-5 text-emerald-600" />
            </div>
            <h3 className="font-semibold text-gray-800 text-sm mb-1">邀请成员</h3>
            <p className="text-xs text-gray-400">管理工作区成员与权限</p>
          </Link>
        </RoleGate>

        {/* 实例管理（v2） */}
        <div className="flex flex-col p-6 bg-gray-50 rounded-2xl border border-gray-100 opacity-60 cursor-not-allowed">
          <div className="h-10 w-10 bg-gray-100 rounded-xl flex items-center justify-center mb-4">
            <BoxIcon className="h-5 w-5 text-gray-400" />
          </div>
          <h3 className="font-semibold text-gray-500 text-sm mb-1">我的实例</h3>
          <p className="text-xs text-gray-400">Phase 2 上线</p>
        </div>
      </div>
    </div>
  );
}
