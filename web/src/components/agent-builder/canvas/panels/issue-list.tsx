'use client';

/**
 * IssueList — 底部问题列表占位
 * Plan 02-09 接入实时 DSL 校验后填充真实数据
 */

export function IssueList() {
  return (
    <div className="flex h-10 items-center border-t border-gray-200 bg-gray-50 px-4">
      <span className="text-xs text-gray-400">
        DSL 校验将在 Plan 02-09 接入 — 暂无 issue
      </span>
    </div>
  );
}
