'use client';

/**
 * 实例列表过滤器组件
 * 参考 Dify web/app/components/app/workflow-log/filter.tsx 的 Filter+State 分离架构
 *
 * 过滤项：
 * - workflow_id 下拉（传入可选 workflows 列表）
 * - status 多选（pending/running/completed/failed/aborted）
 * - search input（按实例 ID 前缀）
 */

import { useCallback, useEffect, useState } from 'react';
import type { InstanceStatus } from '@/lib/types/instance';
import type { WorkflowSummary } from '@/lib/types/dsl';

export interface InstanceFilterValue {
  workflow_id?: string;
  status?: InstanceStatus;
  search?: string;
}

interface InstanceFilterProps {
  value: InstanceFilterValue;
  onChange: (v: InstanceFilterValue) => void;
  workflows?: WorkflowSummary[];
}

const STATUS_OPTIONS: { value: InstanceStatus; label: string }[] = [
  { value: 'pending', label: '等待中' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'aborted', label: '已中止' },
];

/** 实例列表过滤器 */
export function InstanceFilter({ value, onChange, workflows = [] }: InstanceFilterProps) {
  const [searchDraft, setSearchDraft] = useState(value.search ?? '');

  // search 输入 debounce 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchDraft !== (value.search ?? '')) {
        onChange({ ...value, search: searchDraft || undefined });
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchDraft, value, onChange]);

  const handleWorkflowChange = useCallback(
    (wfId: string) => {
      onChange({ ...value, workflow_id: wfId || undefined });
    },
    [value, onChange],
  );

  const handleStatusChange = useCallback(
    (s: string) => {
      onChange({ ...value, status: (s as InstanceStatus) || undefined });
    },
    [value, onChange],
  );

  const handleClear = useCallback(() => {
    setSearchDraft('');
    onChange({});
  }, [onChange]);

  const hasFilter =
    !!value.workflow_id || !!value.status || !!value.search;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      {/* 工作流下拉 */}
      {workflows.length > 0 && (
        <select
          value={value.workflow_id ?? ''}
          onChange={(e) => handleWorkflowChange(e.target.value)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-indigo-400 focus:outline-none"
          aria-label="按工作流过滤"
        >
          <option value="">全部工作流</option>
          {workflows.map((wf) => (
            <option key={wf.id} value={wf.id}>
              {wf.name}
            </option>
          ))}
        </select>
      )}

      {/* 状态过滤 */}
      <select
        value={value.status ?? ''}
        onChange={(e) => handleStatusChange(e.target.value)}
        className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-indigo-400 focus:outline-none"
        aria-label="按状态过滤"
      >
        <option value="">全部状态</option>
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* 搜索 */}
      <input
        type="text"
        value={searchDraft}
        onChange={(e) => setSearchDraft(e.target.value)}
        placeholder="按实例 ID 前缀搜索…"
        className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-indigo-400 focus:outline-none"
        aria-label="搜索实例"
      />

      {/* 清空按钮 */}
      {hasFilter && (
        <button
          type="button"
          onClick={handleClear}
          className="text-xs text-indigo-500 hover:text-indigo-700 underline"
          aria-label="清空过滤条件"
        >
          清空过滤
        </button>
      )}
    </div>
  );
}
