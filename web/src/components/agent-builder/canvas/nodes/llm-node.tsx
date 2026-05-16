'use client';

/**
 * LLM 节点：调用大语言模型
 * 左 target + 右 source handle，紫色边框
 * 显示 model 名称与截断的 user_prompt
 */

import { Handle, Position, type NodeProps } from '@xyflow/react';

export function LLMNode({ data, id }: NodeProps) {
  const config = (data?.config ?? {}) as Record<string, unknown>;
  const model = (config.model as string) || '未设置模型';
  const prompt = (config.user_prompt as string) || '';
  const truncatedPrompt = prompt.length > 40 ? prompt.slice(0, 40) + '…' : prompt;

  return (
    <div className="min-w-[180px] rounded-lg border-2 border-purple-500 bg-white px-4 py-2 shadow-sm">
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-purple-500 !bg-white"
      />
      <div className="text-[10px] font-semibold uppercase tracking-wider text-purple-600">
        LLM
      </div>
      <div className="mt-0.5 truncate text-sm font-medium text-gray-900">
        {(data?.label as string) ?? id}
      </div>
      <div className="mt-1 truncate text-xs text-gray-500">{model}</div>
      {truncatedPrompt && (
        <div className="mt-0.5 truncate text-xs text-gray-400">{truncatedPrompt}</div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-purple-500 !bg-white"
      />
    </div>
  );
}
