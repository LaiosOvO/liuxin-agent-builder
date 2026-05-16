'use client';

/**
 * ApplicantOnlyRecords — 申请人视角的极简 records 列表
 *
 * CONTEXT §申请人追踪页隐私：申请人只能看姓名 + 决策 + 时间，
 * 永远不显示 IP / UA（即使后端 service 万一漏掉脱敏，前端也强制丢弃这两个字段）。
 *
 * 与 TrackingTimeline 的区别：
 *  - TrackingTimeline：完整时间线含 current_node banner / 历史 records / 颜色徽章
 *  - ApplicantOnlyRecords：极简 records 列表（用于 sidebar / mini view 或 admin
 *    切换"申请人视角预览"时使用）
 */

import type { TrackingRecord } from '@/lib/types/tracking';
import { RECORD_ACTION_LABELS } from '@/lib/types/tracking';

interface ApplicantOnlyRecordsProps {
  records: TrackingRecord[];
  /** 可选：组件标题（默认"审批历史"） */
  title?: string;
}

function fmtTs(ts: string | null): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('zh-CN');
  } catch {
    return ts;
  }
}

/** 申请人视角脱敏后的 record 字段（前端强制丢弃 ip/ua）*/
function sanitizeRecord(record: TrackingRecord): Omit<TrackingRecord, 'ip' | 'ua'> {
  // 即使后端 service 漏掉脱敏，前端也不渲染 ip/ua（双重保险）
  const { ip: _ip, ua: _ua, ...rest } = record;
  return rest;
}

export function ApplicantOnlyRecords({
  records,
  title = '审批历史',
}: ApplicantOnlyRecordsProps) {
  if (records.length === 0) {
    return (
      <div
        data-testid="applicant-records-empty"
        className="rounded border border-gray-100 bg-white p-4 text-center text-xs text-gray-400"
      >
        暂无审批记录
      </div>
    );
  }

  return (
    <div
      data-testid="applicant-only-records"
      className="rounded-xl border border-gray-100 bg-white"
    >
      <h3 className="border-b border-gray-100 px-4 py-2 text-sm font-semibold text-gray-700">
        {title}
      </h3>
      <ul className="divide-y divide-gray-100">
        {records.map((rawRecord, idx) => {
          const record = sanitizeRecord(rawRecord);
          const actionCfg = RECORD_ACTION_LABELS[record.action] ?? {
            label: record.action,
            className: 'bg-gray-50 text-gray-600',
          };
          return (
            <li
              key={`${record.ts}-${idx}`}
              data-testid={`applicant-record-row-${idx}`}
              className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm"
            >
              <span
                className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${actionCfg.className}`}
              >
                {actionCfg.label}
              </span>
              <span className="font-medium text-gray-800">
                {record.actor_name || record.actor_email}
              </span>
              {record.reason && (
                <span className="flex-1 truncate text-xs text-gray-500">
                  {record.reason}
                </span>
              )}
              <time
                className="ml-auto text-xs text-gray-400"
                dateTime={record.ts}
              >
                {fmtTs(record.ts)}
              </time>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
