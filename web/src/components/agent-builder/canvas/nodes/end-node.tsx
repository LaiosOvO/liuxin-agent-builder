'use client';

/**
 * End 节点：工作流出口
 * 仅左侧 target handle，红色边框
 */

import { Handle, Position, type NodeProps } from '@xyflow/react';

export function EndNode({ data, id }: NodeProps) {
  return (
    <div className="min-w-[140px] rounded-lg border-2 border-red-500 bg-white px-4 py-2 shadow-sm">
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-red-500 !bg-white"
      />
      <div className="text-[10px] font-semibold uppercase tracking-wider text-red-600">
        结束
      </div>
      <div className="mt-0.5 truncate text-sm font-medium text-gray-900">
        {(data?.label as string) ?? id}
      </div>
    </div>
  );
}
