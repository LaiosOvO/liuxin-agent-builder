'use client';

/**
 * TrackingTimeline — 申请人追踪页竖向时间线（节点可视化）
 *
 * 用户 feedback_node_visualization (2026-05-17) 要求：
 *   - 每节点显示 title + status + actor + action + ts
 *   - 当前节点高亮（active ring）
 *   - 截止倒计时（active 节点）
 *
 * 设计参考：Dify list.tsx statusTdRender + workflow/run/node.tsx
 *  （详见 docs/reading-dify-03-08-tracking-page-2026-05-17.md §3.3）
 *
 * 数据源：
 *  - current_node：active HITL 节点（已聚合到顶部 banner 渲染）
 *  - records：所有审批决策事件（按 ts ASC 排序）— 单一权威时间线
 */

import type {
  TrackingCurrentNode,
  TrackingRecord,
} from '@/lib/types/tracking';
import { HITL_NODE_STATUS_CONFIG, RECORD_ACTION_LABELS } from '@/lib/types/tracking';
import { DeadlineCountdown } from './deadline-countdown';

interface TrackingTimelineProps {
  currentNode: TrackingCurrentNode | null;
  records: TrackingRecord[];
}

/** 格式化时间为本地中文字符串 */
function fmtTs(ts: string | null): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('zh-CN');
  } catch {
    return ts;
  }
}

/** 节点状态徽章 */
function StatusBadge({ status }: { status: string }) {
  const cfg = HITL_NODE_STATUS_CONFIG[status] ?? {
    label: status,
    icon: '•',
    className: 'bg-gray-100 text-gray-600',
  };
  return (
    <span
      data-testid={`status-badge-${status}`}
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${cfg.className}`}
    >
      <span aria-hidden="true">{cfg.icon}</span>
      <span>{cfg.label}</span>
    </span>
  );
}

/** Action 标签 */
function ActionTag({ action }: { action: string }) {
  const cfg = RECORD_ACTION_LABELS[action] ?? {
    label: action,
    className: 'bg-gray-50 text-gray-600',
  };
  return (
    <span
      data-testid={`action-tag-${action}`}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${cfg.className}`}
    >
      {cfg.label}
    </span>
  );
}

/** 当前节点高亮 Banner */
function CurrentNodeBanner({ currentNode }: { currentNode: TrackingCurrentNode }) {
  return (
    <div
      data-testid="current-node-banner"
      className="rounded-xl border-2 border-blue-400 bg-blue-50 p-4 ring-2 ring-blue-100"
    >
      <div className="mb-2 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-blue-900">
            当前节点：{currentNode.title || currentNode.id}
          </span>
          <StatusBadge status={currentNode.status} />
        </div>
        {currentNode.deadline_at && (
          <DeadlineCountdown deadlineAt={currentNode.deadline_at} />
        )}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-y-1 text-xs text-gray-700">
        <span>节点 ID：<code className="font-mono">{currentNode.id}</code></span>
        <span>节点类型：{currentNode.node_type}</span>
        {currentNode.actor?.email && (
          <span>
            等待人：{currentNode.actor.name || currentNode.actor.email}
          </span>
        )}
        {currentNode.started_at && (
          <span>开始时间：{fmtTs(currentNode.started_at)}</span>
        )}
      </div>
    </div>
  );
}

/** 单条历史记录（竖向 timeline 节点） */
function RecordRow({
  record,
  isLast,
}: {
  record: TrackingRecord;
  isLast: boolean;
}) {
  return (
    <li
      data-testid={`record-${record.action}-${record.ts}`}
      className="relative pl-8"
    >
      {/* 竖线 */}
      {!isLast && (
        <span
          aria-hidden="true"
          className="absolute left-3 top-5 bottom-[-1.5rem] w-px bg-gray-200"
        />
      )}
      {/* 圆点 */}
      <span
        aria-hidden="true"
        className="absolute left-2 top-2 inline-block h-2.5 w-2.5 rounded-full border-2 border-gray-300 bg-white"
      />
      <div className="rounded-lg border border-gray-100 bg-white p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm">
            <ActionTag action={record.action} />
            <span className="font-medium text-gray-800">
              {record.actor_name || record.actor_email}
            </span>
            <span className="text-xs text-gray-500">
              &lt;{record.actor_email}&gt;
            </span>
          </div>
          <time className="text-xs text-gray-500" dateTime={record.ts}>
            {fmtTs(record.ts)}
          </time>
        </div>
        {record.reason && (
          <div className="mt-2 rounded bg-gray-50 p-2 text-xs text-gray-700">
            {record.reason}
          </div>
        )}
      </div>
    </li>
  );
}

/** 主组件 */
export function TrackingTimeline({ currentNode, records }: TrackingTimelineProps) {
  return (
    <div className="space-y-4">
      {currentNode && <CurrentNodeBanner currentNode={currentNode} />}

      <div className="rounded-xl border border-gray-100 bg-gray-50 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-700">
          决策时间线 ({records.length} 条)
        </h3>
        {records.length === 0 ? (
          <p
            data-testid="empty-records"
            className="text-center text-xs text-gray-400 py-4"
          >
            暂无审批决策记录
          </p>
        ) : (
          <ol className="space-y-3" data-testid="timeline-list">
            {records.map((rec, idx) => (
              <RecordRow
                key={`${rec.ts}-${idx}`}
                record={rec}
                isLast={idx === records.length - 1}
              />
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
