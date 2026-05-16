'use client';

/**
 * 画布页面 — Phase 1 占位
 * Phase 2 将接入 React Flow / @xyflow/react 实现拖拽画布
 */

import Link from 'next/link';
import { WorkflowIcon, ArrowLeftIcon } from 'lucide-react';

export default function CanvasPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <div className="h-20 w-20 bg-indigo-100 rounded-2xl flex items-center justify-center mb-6">
        <WorkflowIcon className="h-10 w-10 text-indigo-500" />
      </div>

      <h1 className="text-2xl font-bold text-gray-800 mb-2">画布即将上线</h1>
      <p className="text-gray-500 text-sm max-w-sm mb-2">
        Phase 2 将带来基于 @xyflow/react 的可视化 LangGraph 工作流拖拽画布。
      </p>
      <p className="text-indigo-500 text-xs font-medium mb-8">
        预计 Phase 2 上线（敬请期待）
      </p>

      {/* Phase 2 预览功能列表 */}
      <div className="bg-gray-50 rounded-xl p-5 text-left max-w-xs w-full mb-8">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
          Phase 2 将支持
        </p>
        <ul className="space-y-2 text-sm text-gray-600">
          {[
            '拖拽节点组装 LangGraph DAG',
            'Start / End / LLM / Tool / IfElse 节点',
            '实时发布与运行工作流',
            '节点执行时间线查看',
          ].map((item) => (
            <li key={item} className="flex items-start gap-2">
              <span className="text-indigo-400 mt-0.5 flex-shrink-0">→</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>

      <Link
        href="/dashboard"
        className="flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-800 transition-colors"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        返回控制台
      </Link>
    </div>
  );
}
