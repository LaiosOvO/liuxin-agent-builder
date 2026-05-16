'use client';

/**
 * 实例列表页 /dashboard/instances
 * 参考 Dify web/app/components/app/workflow-log/index.tsx 的 Filter+List+Pagination 架构
 *
 * 特性：
 * - 顶部 InstanceFilter（workflow_id / status / search）
 * - filter 变化通过 router.replace 写入 URL query（URL 化）
 * - TanStack Query useQuery 取列表
 * - 分页（URL query `page` + `page_size`）
 * - 表格点击 → router.push 详情页
 */

import { useCallback, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { InstanceFilter } from '@/components/agent-builder/instances/instance-filter';
import { InstancesList } from '@/components/agent-builder/instances/instances-list';
import { instancesApi } from '@/lib/api/instances';
import { workflowsApi } from '@/lib/api/workflows';
import type { InstanceFilterValue } from '@/components/agent-builder/instances/instance-filter';
import type { InstanceStatus } from '@/lib/types/instance';

const PAGE_SIZE = 20;

/** 分页按钮 */
function Pagination({
  page,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) return null;

  return (
    <div className="mt-4 flex items-center justify-center gap-2">
      <button
        type="button"
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
        className="rounded px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 disabled:opacity-40"
      >
        上一页
      </button>
      <span className="text-sm text-gray-500">
        第 {page} / {totalPages} 页（共 {total} 条）
      </span>
      <button
        type="button"
        onClick={() => onPage(page + 1)}
        disabled={page >= totalPages}
        className="rounded px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 disabled:opacity-40"
      >
        下一页
      </button>
    </div>
  );
}

export default function InstancesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // 从 URL 读取过滤参数
  const urlFilter: InstanceFilterValue = {
    workflow_id: searchParams.get('workflow_id') ?? undefined,
    status: (searchParams.get('status') as InstanceStatus) ?? undefined,
    search: searchParams.get('search') ?? undefined,
  };
  const urlPage = Math.max(1, Number(searchParams.get('page') ?? '1'));

  const [filter, setFilter] = useState<InstanceFilterValue>(urlFilter);
  const [page, setPage] = useState(urlPage);

  // filter / page 变化时更新 URL
  const updateUrl = useCallback(
    (f: InstanceFilterValue, p: number) => {
      const params = new URLSearchParams();
      if (f.workflow_id) params.set('workflow_id', f.workflow_id);
      if (f.status) params.set('status', f.status);
      if (f.search) params.set('search', f.search);
      if (p > 1) params.set('page', String(p));
      router.replace(
        `/dashboard/instances${params.toString() ? `?${params.toString()}` : ''}`,
        { scroll: false },
      );
    },
    [router],
  );

  const handleFilterChange = useCallback(
    (f: InstanceFilterValue) => {
      setFilter(f);
      setPage(1);
      updateUrl(f, 1);
    },
    [updateUrl],
  );

  const handlePage = useCallback(
    (p: number) => {
      setPage(p);
      updateUrl(filter, p);
    },
    [filter, updateUrl],
  );

  // 拉取工作流列表（用于 filter 下拉）
  const { data: workflows = [] } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => workflowsApi.list(),
    staleTime: 60_000,
  });

  // 拉取实例列表
  const { data, isLoading } = useQuery({
    queryKey: ['instances', filter, page],
    queryFn: () =>
      instancesApi.list({
        ...filter,
        page,
        page_size: PAGE_SIZE,
      }),
    staleTime: 5_000,
    placeholderData: (prev) => prev,
  });

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">实例列表</h1>
          <p className="mt-0.5 text-sm text-gray-500">工作流运行历史</p>
        </div>
      </div>

      <InstanceFilter
        value={filter}
        onChange={handleFilterChange}
        workflows={workflows}
      />

      <InstancesList
        items={data?.items ?? []}
        onRowClick={(id) => router.push(`/dashboard/instances/${id}`)}
        loading={isLoading}
      />

      <Pagination
        page={page}
        total={data?.total ?? 0}
        pageSize={PAGE_SIZE}
        onPage={handlePage}
      />
    </div>
  );
}
