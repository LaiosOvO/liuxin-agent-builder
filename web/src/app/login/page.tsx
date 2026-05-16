/**
 * 登录页面
 * 替换 flock 原有登录页，使用 agent-builder 品牌与自建账号体系
 */

import type { Metadata } from 'next';
import { Suspense } from 'react';
import { LoginForm } from '@/components/agent-builder/login-form';

export const metadata: Metadata = {
  title: '登录 — agent-builder',
  description: '登录到 agent-builder 可视化工作流编排平台',
};

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center text-gray-400">加载中...</div>}>
      <LoginForm />
    </Suspense>
  );
}
