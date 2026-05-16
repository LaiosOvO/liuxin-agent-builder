/**
 * HITL Bot 扫描静态响应页（Plan 03-07）— Pitfall 3 P0 防护。
 *
 * 设计要点（CLAUDE.md 2.5）：
 * - 后端 GET /hitl/page 检测到 bot UA → 直接返回 { bot_scan: true }
 * - 前端展示此静态页：明确说明"未触发任何状态变更"
 * - 不签 cookie / 不动 jti（后端三重不可逆契约）
 * - 加 noindex/nofollow meta（防搜索引擎索引）
 */

import type { Metadata } from 'next';

export const metadata: Metadata = {
  robots: {
    index: false,
    follow: false,
  },
};

export function BotScanPage() {
  return (
    <main
      className="mx-auto max-w-2xl px-6 py-16 text-center"
      data-testid="bot-scan-page"
    >
      <div className="space-y-6">
        <div className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-gray-100">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="h-8 w-8 text-gray-500"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </div>

        <h1 className="text-xl font-semibold text-gray-900">链接扫描已完成</h1>

        <p className="text-sm leading-7 text-gray-600">
          您看到的是邮件安全扫描结果，<span className="font-medium">未触发任何决策操作</span>。
          <br />
          流程状态保持不变，请放心。
        </p>

        <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-xs leading-6 text-gray-500">
          <div className="font-medium text-gray-700">如果您是审批人本人，请：</div>
          <ul className="mt-2 list-disc pl-5">
            <li>使用您的邮箱客户端直接点击邮件中的按钮</li>
            <li>或将链接复制到浏览器中打开（推荐 Chrome / Safari / Edge）</li>
          </ul>
        </div>
      </div>
    </main>
  );
}
