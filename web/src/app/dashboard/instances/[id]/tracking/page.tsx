'use client';

/**
 * 申请人追踪页 /dashboard/instances/[id]/tracking
 * HITL-07：申请人能在 dashboard 看到自己提交的实例的当前节点状态 + 历史时间线。
 *
 * 权限：
 *  - 申请人本人 → 200（service 层脱敏 IP/UA）
 *  - admin → 200（完整 IP/UA）— 但此页 UI 与申请人一致，不暴露 IP/UA（用户视角统一）
 *  - 非 applicant 非 admin → 403 → 跳回 /dashboard/instances
 *  - 实例不存在 / 跨 workspace → 404 → 跳回 /dashboard/instances
 *
 * 数据：调 instancesApi.tracking(id) 拉 TrackingResponse
 */

import { use, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import { instancesApi } from '@/lib/api/instances';
import { ApiCallError } from '@/lib/api/client';
import { INSTANCE_STATUS_CONFIG } from '@/lib/types/instance';
import type { TrackingResponse } from '@/lib/types/tracking';
import { TrackingTimeline } from '@/components/instance/tracking-timeline';

interface PageParams {
  id: string;
}

function fmt(s: string | null): string {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString('zh-CN');
  } catch {
    return s;
  }
}

export default function TrackingPage({ params }: { params: Promise<PageParams> }) {
  const { id } = use(params);
  const router = useRouter();

  const { data, error, isLoading } = useQuery<TrackingResponse>({
    queryKey: ['instance-tracking', id],
    queryFn: () => instancesApi.tracking(id),
    // active 节点存在时每 30s 自动刷新一次（让 deadline 倒计时与 records 同步推进）
    refetchInterval: (q) => {
      const cur = q.state.data?.current_node;
      return cur ? 30_000 : false;
    },
    retry: (failureCount, err) => {
      if (err instanceof ApiCallError && (err.status === 403 || err.status === 404)) {
        return false;
      }
      return failureCount < 2;
    },
  });

  // 处理 403/404 → 跳回实例列表
  useEffect(() => {
    if (error instanceof ApiCallError && (error.status === 403 || error.status === 404)) {
      const timer = window.setTimeout(() => {
        router.push('/dashboard/instances');
      }, 1200);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [error, router]);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center" data-testid="loading-spinner">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  if (error instanceof ApiCallError) {
    const msg =
      error.status === 403
        ? '您不是该实例的申请人，无权访问追踪页'
        : error.status === 404
        ? '实例不存在或已被删除'
        : '加载失败';
    return (
      <div className="p-6 text-center text-sm text-red-600" data-testid="error-banner">
        {msg}
        <div className="mt-2 text-xs text-gray-500">即将返回实例列表…</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6 text-center text-sm text-gray-500">未找到数据</div>
    );
  }

  const statusCfg =
    INSTANCE_STATUS_CONFIG[data.status] ?? {
      label: data.status,
      className: 'bg-gray-100 text-gray-600',
    };

  return (
    <div className="p-6 space-y-6">
      <div>
        <button
          type="button"
          onClick={() => router.push('/dashboard/instances')}
          className="text-sm text-indigo-600 hover:underline"
        >
          ← 返回实例列表
        </button>
      </div>

      {/* 顶部基本信息卡片 */}
      <div className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <h1 className="font-mono text-sm font-semibold text-gray-800">
                {data.instance_id}
              </h1>
              <span
                data-testid="instance-status-badge"
                className={`rounded px-2 py-0.5 text-xs font-medium ${statusCfg.className}`}
              >
                {statusCfg.label}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs text-gray-500">
              <span>
                申请人：{data.applicant.name || data.applicant.id}
              </span>
              <span>创建时间：{fmt(data.created_at)}</span>
              <span>
                工作流 ID：<code className="font-mono">{data.workflow_id.substring(0, 16)}…</code>
              </span>
              <span>完成时间：{fmt(data.completed_at)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 节点可视化时间线（含 current_node banner + records 历史）*/}
      <TrackingTimeline
        currentNode={data.current_node}
        records={data.records}
      />
    </div>
  );
}
