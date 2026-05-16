'use client';

/**
 * 实例详情组件
 * 顶部：实例 ID + 状态 + 工作流 ID + 时间信息
 * 中部：Timeline 节点状态
 * 操作：abort（pending/running）/ 重跑（failed）
 */

import type { InstanceDetail, SseEvent } from '@/lib/types/instance';
import { INSTANCE_STATUS_CONFIG } from '@/lib/types/instance';
import { Timeline } from './timeline';

interface InstanceDetailViewProps {
  detail: InstanceDetail;
  onAbort?: () => void;
  onRerun?: () => void;
  aborting?: boolean;
}

/** 格式化时间 */
function fmt(s: string | null): string {
  if (!s) return '—';
  return new Date(s).toLocaleString('zh-CN');
}

/** 实例详情视图 */
export function InstanceDetailView({
  detail,
  onAbort,
  onRerun,
  aborting,
}: InstanceDetailViewProps) {
  const statusCfg =
    INSTANCE_STATUS_CONFIG[detail.status] ?? {
      label: detail.status,
      className: 'bg-gray-100 text-gray-600',
    };

  const canAbort = detail.status === 'pending' || detail.status === 'running';
  const canRerun = detail.status === 'failed' || detail.status === 'aborted';

  return (
    <div className="space-y-6">
      {/* 顶部基本信息 */}
      <div className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <h1 className="font-mono text-sm font-semibold text-gray-800">
                {detail.id}
              </h1>
              <span
                className={`rounded px-2 py-0.5 text-xs font-medium ${statusCfg.className}`}
              >
                {statusCfg.label}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs text-gray-500">
              <span>工作流 ID：{detail.workflow_id.substring(0, 16)}…</span>
              <span>创建时间：{fmt(detail.created_at)}</span>
              <span>开始时间：{fmt(detail.started_at)}</span>
              <span>完成时间：{fmt(detail.completed_at)}</span>
            </div>

            {detail.error_message && (
              <div className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700">
                错误：{detail.error_message}
              </div>
            )}
          </div>

          {/* 操作按钮 */}
          <div className="flex gap-2">
            {canAbort && onAbort && (
              <button
                type="button"
                onClick={onAbort}
                disabled={aborting}
                className="rounded-lg border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-60"
              >
                {aborting ? '中止中…' : '中止'}
              </button>
            )}
            {canRerun && onRerun && (
              <button
                type="button"
                onClick={onRerun}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700"
              >
                重跑
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 节点 Timeline */}
      <Timeline nodeStates={detail.node_states} />

      {/* 最终输出（若有） */}
      {detail.final_output && Object.keys(detail.final_output).length > 0 && (
        <div className="rounded-xl border border-green-100 bg-green-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-green-700">最终输出</h3>
          <pre className="text-xs text-green-800 overflow-auto max-h-48">
            {JSON.stringify(detail.final_output, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
