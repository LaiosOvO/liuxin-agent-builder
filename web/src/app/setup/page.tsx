import type { Metadata } from 'next';
import { SetupWizard } from '@/components/agent-builder/setup-wizard';

export const metadata: Metadata = {
  title: '初始化配置 — agent-builder',
  description: '首次启动配置：创建管理员账号与第一个工作区',
};

export default function SetupPage() {
  return <SetupWizard />;
}
