'use client';

/**
 * Tool 节点：HTTP 请求或 Python 函数调用
 * 左 target + 右 source handle，蓝色边框
 * 显示 kind（http/python）及 url 或 function 名
 */

import { Handle, Position, type NodeProps } from '@xyflow/react';

export function ToolNode({ data, id }: NodeProps) {
  const config = (data?.config ?? {}) as Record<string, unknown>;
  const kind = (config.kind as string) || 'http';
  const httpConfig = config.http as Record<string, unknown> | undefined;
  const pythonConfig = config.python as Record<string, unknown> | undefined;

  const subInfo =
    kind === 'http'
      ? ((httpConfig?.url as string) || '未设置 URL')
      : ((pythonConfig?.function as string) || '未设置函数');

  return (
    <div className="min-w-[180px] rounded-lg border-2 border-blue-500 bg-white px-4 py-2 shadow-sm">
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-blue-500 !bg-white"
      />
      <div className="text-[10px] font-semibold uppercase tracking-wider text-blue-600">
        工具 · {kind.toUpperCase()}
      </div>
      <div className="mt-0.5 truncate text-sm font-medium text-gray-900">
        {(data?.label as string) ?? id}
      </div>
      <div className="mt-1 truncate text-xs text-gray-500">{subInfo}</div>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-blue-500 !bg-white"
      />
    </div>
  );
}
