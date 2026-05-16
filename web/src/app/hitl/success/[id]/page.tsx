/**
 * HITL 决策成功页（Plan 03-07）— `/hitl/success/[id]`。
 *
 * 设计要点：
 * - 服务端组件（静态，无数据加载）
 * - 展示"已记录您的决策" + 流程实例 ID + 后续指引
 * - 不引用任何 token / cookie / jti（决策已完成，仅展示）
 */

import type { Metadata } from 'next';
import Link from 'next/link';

interface PageParams {
  id: string;
}

interface SuccessPageProps {
  params: Promise<PageParams>;
}

export const metadata: Metadata = {
  title: '决策已记录 - agent-builder',
  robots: {
    index: false,
    follow: false,
  },
};

export default async function HitlSuccessPage({ params }: SuccessPageProps) {
  const { id } = await params;
  const isAlreadySubmitted = id === 'already-submitted';

  return (
    <main
      className="mx-auto max-w-2xl px-6 py-16 text-center"
      data-testid="hitl-success-page"
    >
      <div className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="h-8 w-8 text-emerald-600"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
      </div>

      <h1
        className="mt-6 text-2xl font-semibold text-gray-900"
        data-testid="success-title"
      >
        {isAlreadySubmitted ? '决策已被处理' : '已记录您的决策'}
      </h1>

      <p className="mt-3 text-sm leading-7 text-gray-600">
        {isAlreadySubmitted ? (
          <>
            您之前已经完成过该决策，流程已正常推进，无需重复操作。
          </>
        ) : (
          <>
            您的决策已成功记录到审计日志，流程已开始下一步处理。
          </>
        )}
      </p>

      {!isAlreadySubmitted && (
        <div
          className="mt-6 rounded-md border border-gray-200 bg-gray-50 p-4 text-left"
          data-testid="success-meta"
        >
          <div className="text-xs text-gray-500">流程实例 ID</div>
          <div
            className="mt-1 font-mono text-sm text-gray-700"
            data-testid="instance-id"
          >
            {id}
          </div>
        </div>
      )}

      <div className="mt-8 space-y-3 text-sm text-gray-600">
        <p>您可以安全地关闭此页面。</p>
        <p>
          如有疑问，请联系流程发起人或
          <Link
            href="/login"
            className="ml-1 text-emerald-600 hover:text-emerald-700 hover:underline"
          >
            登录 agent-builder
          </Link>
          {' '}查看完整流程进度。
        </p>
      </div>
    </main>
  );
}
