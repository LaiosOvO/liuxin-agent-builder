'use client';

/**
 * 实例详情页 /dashboard/instances/[id]
 * 参考 Dify web/app/components/workflow/run/ 的实例监控设计
 *
 * - useQuery 拉取初始实例详情（含 node_states）
 * - SseListener 订阅实时事件（node.start/node.complete/node.error/instance.complete/instance.failed）
 * - useReducer 合并 SSE 事件到本地 node_states 映射
 * - InstanceDetailView 显示详情 + Timeline
 * - 支持 abort（pending/running）和 rerun（failed/aborted）操作
 */

import { useCallback, use, useReducer } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { instancesApi } from '@/lib/api/instances';
import { InstanceDetailView } from '@/components/agent-builder/instances/instance-detail';
import { SseListener } from '@/components/agent-builder/canvas/sse-listener';
import type { InstanceDetail, NodeStateInfo, SseEvent } from '@/lib/types/instance';

interface PageParams {
  id: string;
}

/** SSE 事件 Action */
type SseAction =
  | { type: 'node_start'; payload: { node_id: string; node_type: string } }
  | { type: 'node_complete'; payload: { node_id: string; output_summary?: Record<string, unknown> } }
  | { type: 'node_error'; payload: { node_id: string; error_message: string } }
  | { type: 'instance_terminal' }; // instance.complete / instance.failed

/** 本地节点状态映射 */
type NodeMap = Record<string, NodeStateInfo>;

/** SSE 事件合并到节点映射 */
function mergeNodeEvent(state: NodeMap, action: SseAction): NodeMap {
  switch (action.type) {
    case 'node_start': {
      const { node_id, node_type } = action.payload;
      const existing = state[node_id];
      return {
        ...state,
        [node_id]: {
          id: node_id,
          node_id,
          node_type,
          status: 'running',
          started_at: new Date().toISOString(),
          completed_at: existing?.completed_at ?? null,
          error_message: null,
          retries: existing?.retries ?? 0,
          output_summary: existing?.output_summary ?? null,
        },
      };
    }
    case 'node_complete': {
      const { node_id, output_summary } = action.payload;
      const existing = state[node_id];
      if (!existing) return state;
      return {
        ...state,
        [node_id]: {
          ...existing,
          status: 'completed',
          completed_at: new Date().toISOString(),
          output_summary: output_summary ?? existing.output_summary,
        },
      };
    }
    case 'node_error': {
      const { node_id, error_message } = action.payload;
      const existing = state[node_id];
      if (!existing) return state;
      return {
        ...state,
        [node_id]: {
          ...existing,
          status: 'failed',
          completed_at: new Date().toISOString(),
          error_message,
        },
      };
    }
    case 'instance_terminal':
      // 实例终止时不改变节点映射，由 refetch 获取最新状态
      return state;
    default:
      return state;
  }
}

export default function InstanceDetailPage({ params }: { params: Promise<PageParams> }) {
  const { id } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();

  // 拉取实例详情
  const { data: detail, isLoading, refetch } = useQuery<InstanceDetail>({
    queryKey: ['instance', id],
    queryFn: () => instancesApi.get(id),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });

  // 本地节点状态（SSE 增量更新）
  const initialNodeMap: NodeMap = {};
  const [nodeMap, dispatch] = useReducer(mergeNodeEvent, initialNodeMap);

  // SSE 事件处理
  const handleSseEvent = useCallback(
    (event: SseEvent) => {
      switch (event.event) {
        case 'node.start':
          dispatch({
            type: 'node_start',
            payload: {
              node_id: (event as SseEvent & { node_id: string }).node_id,
              node_type: (event as SseEvent & { node_type: string }).node_type ?? 'unknown',
            },
          });
          break;
        case 'node.complete':
          dispatch({
            type: 'node_complete',
            payload: {
              node_id: (event as SseEvent & { node_id: string }).node_id,
              output_summary: (event as SseEvent & { output_summary?: Record<string, unknown> }).output_summary,
            },
          });
          break;
        case 'node.error':
          dispatch({
            type: 'node_error',
            payload: {
              node_id: (event as SseEvent & { node_id: string }).node_id,
              error_message: (event as SseEvent & { error_message: string }).error_message ?? '节点执行失败',
            },
          });
          break;
        case 'instance.complete':
        case 'instance.failed':
          dispatch({ type: 'instance_terminal' });
          // 实例终止后重新拉取以同步最终状态
          void refetch();
          break;
        default:
          break;
      }
    },
    [refetch],
  );

  // 中止实例
  const handleAbort = useCallback(async () => {
    try {
      await instancesApi.abort(id);
      await refetch();
    } catch (err: unknown) {
      // 中止失败时静默处理（API 返回 409 表示状态已不可中止）
      if (process.env.NODE_ENV !== 'production') {
        // eslint-disable-next-line no-console
        console.error('abort failed', err);
      }
    }
  }, [id, refetch]);

  // 重跑：复用相同 initial_input 创建新实例
  const handleRerun = useCallback(async () => {
    if (!detail) return;
    try {
      const newInst = await instancesApi.start(detail.workflow_id, {
        initial_input: detail.initial_input ?? {},
      });
      // 失效实例列表缓存
      await queryClient.invalidateQueries({ queryKey: ['instances'] });
      router.push(`/dashboard/instances/${newInst.id}`);
    } catch (err: unknown) {
      if (process.env.NODE_ENV !== 'production') {
        // eslint-disable-next-line no-console
        console.error('rerun failed', err);
      }
    }
  }, [detail, queryClient, router]);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="p-6 text-center text-sm text-gray-500">
        实例不存在或无权访问
      </div>
    );
  }

  // 合并 server node_states 与 SSE 增量更新
  const serverNodeMap: NodeMap = Object.fromEntries(
    detail.node_states.map((ns) => [ns.node_id, ns]),
  );
  const mergedNodeStates: NodeStateInfo[] = Object.values({
    ...serverNodeMap,
    ...nodeMap,
  });

  const mergedDetail: InstanceDetail = {
    ...detail,
    node_states: mergedNodeStates,
  };

  const isActive = detail.status === 'pending' || detail.status === 'running';

  return (
    <div className="p-6">
      <div className="mb-4">
        <button
          type="button"
          onClick={() => router.push('/dashboard/instances')}
          className="text-sm text-indigo-600 hover:underline"
        >
          ← 返回实例列表
        </button>
      </div>

      {/* SSE 监听器（仅在实例活跃时订阅）*/}
      {isActive && (
        <SseListener instanceId={id} onEvent={handleSseEvent} />
      )}

      <InstanceDetailView
        detail={mergedDetail}
        onAbort={handleAbort}
        onRerun={handleRerun}
      />
    </div>
  );
}
