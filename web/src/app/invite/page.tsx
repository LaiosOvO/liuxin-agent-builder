/**
 * 邀请接受页面
 * 解析 ?token=... 并渲染邀请预览 + 注册表单
 */

import type { Metadata } from 'next';
import { Suspense } from 'react';
import { InviteAcceptanceForm } from '@/components/agent-builder/invite-acceptance-form';

export const metadata: Metadata = {
  title: '接受邀请 — agent-builder',
  description: '接受邀请并加入工作区',
};

export default function InvitePage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center text-gray-400">加载中...</div>}>
      <InviteAcceptanceForm />
    </Suspense>
  );
}
