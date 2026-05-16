'use client';

/**
 * 工作流列表页
 * 替换 Phase 1 占位 — Phase 2 Plan 02-03 实现
 *
 * - 展示当前 workspace 下所有工作流
 * - 新建工作流按钮（Plan 02-08 接入后 API 可用）
 * - 后端未就绪时降级显示友好提示
 */

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { WorkflowIcon, PlusIcon } from 'lucide-react';
import { workflowsApi } from '@/lib/api/workflows';
import type { WorkflowSummary } from '@/lib/types/dsl';

/** 工作流状态徽章 */
function StatusBadge({ status }: { status: WorkflowSummary['status'] }) {
  const cls =
    status === 'published'
      ? 'bg-green-100 text-green-700'
      : 'bg-yellow-100 text-yellow-700';
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status === 'published' ? '已发布' : '草稿'}
    </span>
  );
}

/** 工作流卡片 */
function WorkflowCard({ workflow }: { workflow: WorkflowSummary }) {
  const updatedAt = new Date(workflow.updated_at).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <Link
      href={`/dashboard/canvas/${workflow.id}`}
      className="block rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <WorkflowIcon className="h-5 w-5 flex-shrink-0 text-indigo-500" />
          <span className="truncate font-medium text-gray-800">{workflow.name}</span>
        </div>
        <StatusBadge status={workflow.status} />
      </div>
      <p className="mt-2 text-xs text-gray-400">最后更新：{updatedAt}</p>
    </Link>
  );
}

export default function CanvasListPage() {
  const router = useRouter();
  const [workflows, setWorkflows] = useState<WorkflowSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiAvailable, setApiAvailable] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    workflowsApi
      .list()
      .then((data) => {
        setWorkflows(data);
        setApiAvailable(true);
      })
      .catch(() => {
        setApiAvailable(false);
        setWorkflows([]);
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (creating) return;
    setCreating(true);
    try {
      const newWorkflow = await workflowsApi.create({ name: '新工作流' });
      router.push(`/dashboard/canvas/${newWorkflow.id}`);
    } catch {
      // API 未就绪时前端降级：直接跳转到 mock 编辑器
      router.push('/dashboard/canvas/demo?mock=1');
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="min-h-[60vh] p-6">
      {/* 页头 */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">工作流</h1>
          <p className="mt-0.5 text-sm text-gray-500">可视化编排 LangGraph 工作流</p>
        </div>
        <button
          onClick={handleCreate}
          disabled={creating}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
        >
          <PlusIcon className="h-4 w-4" />
          {creating ? '创建中…' : '新建工作流'}
        </button>
      </div>

      {/* 内容区 */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
        </div>
      ) : !apiAvailable ? (
        /* 后端 API 未就绪时的降级提示 */
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-6 text-center">
          <WorkflowIcon className="mx-auto h-10 w-10 text-indigo-400" />
          <h2 className="mt-3 font-semibold text-indigo-800">工作流 API 即将启用</h2>
          <p className="mt-1 text-sm text-indigo-600">
            工作流持久化将在 Plan 02-08 上线。现在可以进入编辑器体验拖拽画布。
          </p>
          <Link
            href="/dashboard/canvas/demo?mock=1"
            className="mt-4 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            进入体验画布
          </Link>
        </div>
      ) : workflows && workflows.length === 0 ? (
        /* 空状态 */
        <div className="flex flex-col items-center py-16 text-center">
          <WorkflowIcon className="h-12 w-12 text-gray-300" />
          <p className="mt-3 text-sm text-gray-500">暂无工作流，点击「新建工作流」开始</p>
        </div>
      ) : (
        /* 工作流卡片网格 */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(workflows ?? []).map((wf) => (
            <WorkflowCard key={wf.id} workflow={wf} />
          ))}
        </div>
      )}
    </div>
  );
}
