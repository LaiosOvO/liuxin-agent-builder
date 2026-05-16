/**
 * HITL 历史决策时间线（Plan 03-07）— 公网用户视角的脱敏展示。
 *
 * 设计要点：
 * - 倒序显示（最新在上）
 * - actor_email + action（colored chip） + reason + ts
 * - 列表为空 → 占位提示
 * - 隐私：仅展示 actor_email / action / reason / ts（不含 IP / UA — admin 视角才有）
 */

'use client';

import type { HitlRecord } from '@/lib/types/hitl';

interface RecordsTimelineProps {
  records: HitlRecord[];
}

/** Action → 颜色与文案映射。 */
const ACTION_STYLE: Record<string, { color: string; label: string }> = {
  submit: {
    color: 'bg-blue-100 text-blue-800 border-blue-200',
    label: '提交',
  },
  approve: {
    color: 'bg-emerald-100 text-emerald-800 border-emerald-200',
    label: '通过',
  },
  return: {
    color: 'bg-amber-100 text-amber-800 border-amber-200',
    label: '退回',
  },
  reject: {
    color: 'bg-red-100 text-red-800 border-red-200',
    label: '拒绝',
  },
  escalate: {
    color: 'bg-purple-100 text-purple-800 border-purple-200',
    label: '升级',
  },
};

const DEFAULT_STYLE = {
  color: 'bg-gray-100 text-gray-800 border-gray-200',
  label: '未知',
};

/** 中文时间格式化（YYYY-MM-DD HH:mm:ss）。 */
function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const HH = String(d.getHours()).padStart(2, '0');
    const MM = String(d.getMinutes()).padStart(2, '0');
    const SS = String(d.getSeconds()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${HH}:${MM}:${SS}`;
  } catch {
    return iso;
  }
}

export function RecordsTimeline({ records }: RecordsTimelineProps) {
  if (!records || records.length === 0) {
    return (
      <div
        className="rounded-md border border-dashed border-gray-200 p-6 text-center text-sm text-gray-500"
        data-testid="records-empty"
      >
        暂无历史决策
      </div>
    );
  }

  // 倒序（最新在上） —— 不变异原数组
  const sorted = [...records].sort((a, b) => {
    const ta = new Date(a.ts).getTime();
    const tb = new Date(b.ts).getTime();
    return tb - ta;
  });

  return (
    <ol
      className="space-y-3"
      data-testid="records-timeline"
      aria-label="历史决策时间线"
    >
      {sorted.map((record, idx) => {
        const style = ACTION_STYLE[record.action] ?? {
          ...DEFAULT_STYLE,
          label: record.action || DEFAULT_STYLE.label,
        };
        return (
          <li
            key={`${record.ts}-${idx}`}
            className="rounded-md border border-gray-200 bg-white p-3 text-sm shadow-sm"
            data-testid="record-item"
            data-action={record.action}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-gray-900">
                {record.actor_email || '系统'}
              </span>
              <span
                className={`inline-flex items-center rounded border px-2 py-0.5 text-xs ${style.color}`}
                data-testid="action-chip"
              >
                {style.label}
              </span>
              <span className="text-xs text-gray-500">
                {formatTimestamp(record.ts)}
              </span>
            </div>
            {record.reason && (
              <div className="mt-2 text-gray-700">
                <span className="text-xs font-medium text-gray-500">
                  原因：
                </span>
                <span className="ml-1 whitespace-pre-wrap">
                  {record.reason}
                </span>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
