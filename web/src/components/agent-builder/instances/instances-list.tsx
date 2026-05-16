'use client';

/**
 * 实例列表表格组件
 * 参考 Dify web/app/components/app/workflow-log/list.tsx 的 List+StatusBadge 架构
 *
 * 列：实例 ID（截短）/ 状态徽章 / 创建时间 / 操作（详情）
 */

import type { ReactNode } from 'react';
import type { InstanceSummary } from '@/lib/types/instance';
import { INSTANCE_STATUS_CONFIG } from '@/lib/types/instance';

interface InstancesListProps {
  items: InstanceSummary[];
  onRowClick: (id: string) => void;
  loading?: boolean;
  emptyState?: ReactNode;
}

/** 实例状态徽章 */
function StatusBadge({ status }: { status: InstanceSummary['status'] }) {
  const { label, className } = INSTANCE_STATUS_CONFIG[status] ?? {
    label: status,
    className: 'bg-gray-100 text-gray-600',
  };
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}

/** 格式化时间（本地时间短格式）*/
function formatTime(isoStr: string | null): string {
  if (!isoStr) return '—';
  return new Date(isoStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** 实例列表表格 */
export function InstancesList({ items, onRowClick, loading, emptyState }: InstancesListProps) {
  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-gray-400">
        {emptyState ?? '暂无实例'}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-100 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left font-medium text-gray-500">实例 ID</th>
            <th className="px-4 py-3 text-left font-medium text-gray-500">状态</th>
            <th className="px-4 py-3 text-left font-medium text-gray-500">创建时间</th>
            <th className="px-4 py-3 text-left font-medium text-gray-500">完成时间</th>
            <th className="px-4 py-3 text-right font-medium text-gray-500">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {items.map((inst) => (
            <tr
              key={inst.id}
              className="cursor-pointer transition-colors hover:bg-indigo-50"
              onClick={() => onRowClick(inst.id)}
            >
              <td className="px-4 py-3 font-mono text-xs text-gray-700">
                {inst.id.substring(0, 16)}…
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={inst.status} />
              </td>
              <td className="px-4 py-3 text-gray-500">{formatTime(inst.created_at)}</td>
              <td className="px-4 py-3 text-gray-500">{formatTime(inst.completed_at)}</td>
              <td className="px-4 py-3 text-right">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRowClick(inst.id);
                  }}
                  className="text-indigo-500 hover:text-indigo-700 text-xs font-medium"
                >
                  详情
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
