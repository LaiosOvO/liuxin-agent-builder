'use client';

/**
 * Start 节点：工作流入口
 * 仅右侧 source handle，绿色边框
 */

import { Handle, Position, type NodeProps } from '@xyflow/react';

export function StartNode({ data, id }: NodeProps) {
  return (
    <div className="min-w-[140px] rounded-lg border-2 border-green-500 bg-white px-4 py-2 shadow-sm">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-green-600">
        开始
      </div>
      <div className="mt-0.5 truncate text-sm font-medium text-gray-900">
        {(data?.label as string) ?? id}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-green-500 !bg-white"
      />
    </div>
  );
}
