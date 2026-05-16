'use client';

/**
 * 节点执行 Timeline 组件
 * 参考 Dify web/app/components/workflow/run/node.tsx 的 NodePanel + status icon 设计
 *
 * 每个节点行显示：
 * - 节点类型图标
 * - 节点 ID + 类型
 * - 状态徽章（运行中 / 完成 / 失败）
 * - 持续时间（若已完成）
 * - 错误信息（若失败，可展开）
 */

import { useState } from 'react';
import type { NodeStateInfo, NodeStatus } from '@/lib/types/instance';

interface TimelineProps {
  nodeStates: NodeStateInfo[];
}

/** 格式化耗时（参考 Dify node.tsx getTime 函数）*/
function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt || !completedAt) return '';
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  const s = ms / 1000;
  if (s < 1) return `${ms.toFixed(0)} ms`;
  if (s > 60) return `${Math.floor(s / 60)} m ${(s % 60).toFixed(1)} s`;
  return `${s.toFixed(2)} s`;
}

/** 状态图标（参考 Dify 的 RiCheckboxCircleFill / RiLoader2Line 等）*/
function StatusIcon({ status }: { status: NodeStatus }) {
  switch (status) {
    case 'running':
      return (
        <span
          className="inline-flex h-4 w-4 animate-spin items-center justify-center rounded-full border-2 border-blue-500 border-t-transparent"
          aria-label="运行中"
        />
      );
    case 'completed':
      return (
        <span className="text-green-500" aria-label="完成">
          ✓
        </span>
      );
    case 'failed':
      return (
        <span className="text-red-500" aria-label="失败">
          ✗
        </span>
      );
    default:
      return (
        <span className="h-4 w-4 rounded-full bg-gray-200" aria-label="等待" />
      );
  }
}

/** 节点类型显示名称 */
function nodeTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    start: '开始',
    end: '结束',
    llm: 'LLM',
    tool: '工具',
    if_else: '条件分支',
  };
  return labels[type] ?? type;
}

/** 单节点 Timeline 行 */
function NodeRow({ ns }: { ns: NodeStateInfo }) {
  const [expanded, setExpanded] = useState(false);
  const duration = formatDuration(ns.started_at, ns.completed_at);

  return (
    <div className="relative pl-8">
      {/* 竖线连接 */}
      <div className="absolute left-3 top-4 bottom-0 w-px bg-gray-100" />

      {/* 节点行 */}
      <div className="flex items-start gap-3 py-2">
        {/* 状态图标（圆圈位置）*/}
        <div className="absolute left-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-gray-200">
          <StatusIcon status={ns.status} />
        </div>

        {/* 节点信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-sm text-gray-800">{ns.node_id}</span>
            <span className="text-xs text-gray-400">{nodeTypeLabel(ns.node_type)}</span>
            {duration && (
              <span className="text-xs text-gray-400">{duration}</span>
            )}
            {ns.status === 'failed' && ns.error_message && (
              <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="text-xs text-red-500 underline"
              >
                {expanded ? '收起' : '查看错误'}
              </button>
            )}
          </div>

          {/* 错误详情展开区 */}
          {expanded && ns.error_message && (
            <div className="mt-1 rounded bg-red-50 p-2 text-xs text-red-700">
              {ns.error_message}
            </div>
          )}

          {/* 输出摘要（若有） */}
          {ns.output_summary && Object.keys(ns.output_summary).length > 0 && (
            <div className="mt-1 text-xs text-gray-400">
              输出：{Object.keys(ns.output_summary).join(', ')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** 节点执行 Timeline */
export function Timeline({ nodeStates }: TimelineProps) {
  if (nodeStates.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 py-8 text-center text-sm text-gray-400">
        暂无节点执行记录（实例仍在等待或执行引擎未写入）
      </div>
    );
  }

  return (
    <div className="relative rounded-xl border border-gray-100 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">节点执行 Timeline</h3>
      <div className="space-y-0">
        {nodeStates.map((ns) => (
          <NodeRow key={ns.id} ns={ns} />
        ))}
      </div>
    </div>
  );
}
