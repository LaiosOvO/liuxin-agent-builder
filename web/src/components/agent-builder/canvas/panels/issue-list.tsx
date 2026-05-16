'use client';

/**
 * IssueList — 底部 DSL 问题清单
 *
 * 设计（借鉴 Dify ChecklistPanel 思路）：
 * - 聚合所有 ValidationError，按 severity 排序（error 在前）
 * - 点击条目 → selectNode(node_id) 跳转对应节点（高亮选中）
 * - 无 error 时显示绿色"校验通过"状态
 * - warning 和 error 分色显示
 */

import { useValidatorStore } from '@/lib/stores/validator-store';
import { useCanvasStore } from '@/lib/stores/canvas-store';

/** 底部 Issue 清单组件 */
export function IssueList() {
  const errors = useValidatorStore((s) => s.errors);
  const isValidating = useValidatorStore((s) => s.isValidating);
  const selectNode = useCanvasStore((s) => s.selectNode);

  // 按 severity 排序（error 在前）
  const sorted = [...errors].sort((a, b) => {
    if (a.severity === 'error' && b.severity !== 'error') return -1;
    if (a.severity !== 'error' && b.severity === 'error') return 1;
    return 0;
  });

  const errorCount = errors.filter((e) => e.severity === 'error').length;
  const warningCount = errors.filter((e) => e.severity === 'warning').length;

  // 无错误 — 显示通过状态
  if (!isValidating && sorted.length === 0) {
    return (
      <div
        className="flex h-10 items-center border-t border-gray-200 bg-green-50 px-4"
        data-testid="issue-list-empty"
      >
        <span className="text-xs font-medium text-green-700">
          DSL 校验通过
        </span>
      </div>
    );
  }

  // 校验中
  if (isValidating) {
    return (
      <div className="flex h-10 items-center border-t border-gray-200 bg-gray-50 px-4">
        <span className="text-xs text-gray-400">校验中…</span>
      </div>
    );
  }

  return (
    <div
      className="flex max-h-48 flex-col border-t border-gray-200 bg-gray-50"
      data-testid="issue-list"
    >
      {/* 标题栏 */}
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-gray-200 bg-white px-4 py-1.5">
        <span className="text-xs font-semibold text-gray-700">
          问题（{sorted.length}）
        </span>
        {errorCount > 0 && (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700">
            {errorCount} 错误
          </span>
        )}
        {warningCount > 0 && (
          <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-semibold text-yellow-700">
            {warningCount} 警告
          </span>
        )}
      </div>

      {/* 列表 */}
      <div className="overflow-y-auto">
        {sorted.map((err, idx) => (
          <div
            key={idx}
            onClick={() => {
              if (err.node_id) {
                selectNode(err.node_id);
              }
            }}
            className={`flex items-start gap-2 border-b border-gray-100 px-4 py-1.5 text-xs last:border-b-0 hover:bg-white ${
              err.node_id ? 'cursor-pointer' : 'cursor-default'
            }`}
            data-testid={`issue-item-${idx}`}
            data-node-id={err.node_id ?? ''}
          >
            <span
              className={`mt-0.5 shrink-0 font-semibold ${
                err.severity === 'error' ? 'text-red-600' : 'text-yellow-600'
              }`}
            >
              {err.code}
            </span>
            <span className="text-gray-500">[{err.node_id ?? '全局'}]</span>
            <span className="flex-1 text-gray-700">{err.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
