'use client';

/**
 * Workspace Switcher 组件
 * 显示当前 workspace，多 workspace 时可下拉切换
 */

import { useState } from 'react';
import { useUserStore } from '@/lib/stores/user-store';
import { switchWorkspace } from '@/lib/api/me';
import { getMe } from '@/lib/api/auth';
import { toast } from 'sonner';
import { ApiCallError } from '@/lib/api/client';
import { ChevronDownIcon, Building2Icon } from 'lucide-react';

export function WorkspaceSwitcher() {
  const { currentWorkspace, workspaces, setMe } = useUserStore();
  const [isOpen, setIsOpen] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);

  const hasMultiple = workspaces.length > 1;

  const handleSwitch = async (workspaceId: string) => {
    if (workspaceId === currentWorkspace?.id) {
      setIsOpen(false);
      return;
    }

    setIsSwitching(true);
    setIsOpen(false);

    try {
      await switchWorkspace(workspaceId);
      // 切换后重新拉取用户信息更新 store
      const me = await getMe();
      setMe(me);
      toast.success('已切换工作区');
      // 刷新页面确保所有数据与新 workspace 对齐
      window.location.reload();
    } catch (err) {
      if (err instanceof ApiCallError) {
        toast.error(`切换失败：${err.message}`);
      } else {
        toast.error('切换工作区失败，请重试');
      }
      setIsSwitching(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        disabled={!hasMultiple || isSwitching}
        onClick={() => hasMultiple && setIsOpen((prev) => !prev)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
          hasMultiple
            ? 'hover:bg-gray-100 cursor-pointer text-gray-700'
            : 'cursor-default text-gray-500'
        } ${isSwitching ? 'opacity-60' : ''}`}
        aria-label="切换工作区"
        aria-haspopup={hasMultiple ? 'listbox' : undefined}
        aria-expanded={hasMultiple ? isOpen : undefined}
      >
        <Building2Icon className="h-4 w-4 text-indigo-500 flex-shrink-0" />
        <span className="max-w-32 truncate">
          {currentWorkspace?.name ?? '选择工作区'}
        </span>
        {hasMultiple && (
          <ChevronDownIcon
            className={`h-3.5 w-3.5 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        )}
      </button>

      {/* 下拉列表 */}
      {isOpen && hasMultiple && (
        <>
          {/* 遮罩：点击外部关闭 */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />
          <ul
            role="listbox"
            aria-label="工作区列表"
            className="absolute top-full left-0 mt-1 w-48 bg-white rounded-xl shadow-lg border border-gray-100 z-20 py-1 overflow-hidden"
          >
            {workspaces.map(({ workspace }) => (
              <li key={workspace.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={workspace.id === currentWorkspace?.id}
                  onClick={() => handleSwitch(workspace.id)}
                  className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
                    workspace.id === currentWorkspace?.id
                      ? 'bg-indigo-50 text-indigo-700 font-medium'
                      : 'text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {workspace.name}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
