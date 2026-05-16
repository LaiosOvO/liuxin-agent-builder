/**
 * HITL 决策页主入口（Plan 03-07）— `/hitl/[token]`。
 *
 * 设计要点（reading doc §7）：
 * - Server Component（Next.js 16/15 App Router）
 * - 通过 next/headers 透传 cookie + UA 到后端 GET /hitl/page
 * - 后端 GET 返回 JSON（Accept: application/json） + Set-Cookie 头
 * - 后端 cookie 透传不便（Server Component 无法直接 set 浏览器 cookie）
 *   → v1 简化：客户端 hydration 阶段重新 fetch（自带浏览器 cookie/UA）
 *   → 首次渲染 server-side 仅生成骨架（加载提示）；客户端拿到数据后 hydrate
 *
 * 路由权限：公网无登录访问（Phase 1 NET-02 nginx 已放行 /hitl/*）。
 */

import { Metadata } from 'next';
import { DecisionPageClient } from './decision-page-client';

interface PageParams {
  token: string;
}

export const metadata: Metadata = {
  title: 'HITL 决策 - agent-builder',
  robots: {
    // 公网决策页不应被搜索引擎索引
    index: false,
    follow: false,
  },
};

interface HitlPageProps {
  params: Promise<PageParams>;
}

export default async function HitlPage({ params }: HitlPageProps) {
  const { token } = await params;

  return (
    <div className="min-h-screen bg-gray-50">
      <DecisionPageClient token={token} />
    </div>
  );
}
