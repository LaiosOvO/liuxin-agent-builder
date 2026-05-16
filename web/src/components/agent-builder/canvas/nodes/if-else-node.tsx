'use client';

/**
 * IfElse 节点：条件分支
 * 左 target handle + 多个右 source handle（每条 condition + default），橙色边框
 */

import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { IfElseNodeConfig } from '@/lib/types/dsl';

export function IfElseNode({ data, id }: NodeProps) {
  const config = (data?.config ?? {}) as Partial<IfElseNodeConfig>;
  const conditions = config.conditions ?? [];

  return (
    <div className="min-w-[200px] rounded-lg border-2 border-orange-500 bg-white px-4 py-2 shadow-sm">
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-orange-500 !bg-white"
      />
      <div className="text-[10px] font-semibold uppercase tracking-wider text-orange-600">
        条件分支
      </div>
      <div className="mt-0.5 truncate text-sm font-medium text-gray-900">
        {(data?.label as string) ?? id}
      </div>

      {/* 条件 handles */}
      {conditions.map((cond, idx) => (
        <div key={idx} className="mt-1 flex items-center justify-between">
          <span className="max-w-[120px] truncate text-xs text-gray-500">
            {cond.label || cond.expr || `条件 ${idx + 1}`}
          </span>
          <Handle
            type="source"
            position={Position.Right}
            id={`condition-${idx}`}
            style={{ top: `${40 + idx * 24}px` }}
            className="!h-3 !w-3 !border-2 !border-orange-400 !bg-white"
          />
        </div>
      ))}

      {/* 默认 handle */}
      <div className="mt-1 flex items-center justify-between">
        <span className="text-xs text-gray-400">默认</span>
        <Handle
          type="source"
          position={Position.Right}
          id="default"
          style={{ top: `${40 + conditions.length * 24}px` }}
          className="!h-3 !w-3 !border-2 !border-orange-300 !bg-white"
        />
      </div>
    </div>
  );
}
