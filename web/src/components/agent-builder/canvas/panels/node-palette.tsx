'use client';

/**
 * NodePalette — 左侧节点拖拽库
 * 5 种节点类型卡片，可拖拽到 Canvas 放置
 * onDragStart 通过 dataTransfer 传递节点类型
 */

import type { DSLNode } from '@/lib/types/dsl';

/** 节点类型元数据 */
interface NodeTypeConfig {
  type: DSLNode['type'];
  label: string;
  description: string;
  colorClass: string;
  borderClass: string;
  bgClass: string;
}

const NODE_TYPES: NodeTypeConfig[] = [
  {
    type: 'start',
    label: '开始',
    description: '工作流入口节点',
    colorClass: 'text-green-700',
    borderClass: 'border-green-400',
    bgClass: 'bg-green-50 hover:bg-green-100',
  },
  {
    type: 'end',
    label: '结束',
    description: '工作流出口节点',
    colorClass: 'text-red-700',
    borderClass: 'border-red-400',
    bgClass: 'bg-red-50 hover:bg-red-100',
  },
  {
    type: 'llm',
    label: 'LLM',
    description: '调用大语言模型',
    colorClass: 'text-purple-700',
    borderClass: 'border-purple-400',
    bgClass: 'bg-purple-50 hover:bg-purple-100',
  },
  {
    type: 'tool',
    label: '工具',
    description: 'HTTP 请求或 Python 函数',
    colorClass: 'text-blue-700',
    borderClass: 'border-blue-400',
    bgClass: 'bg-blue-50 hover:bg-blue-100',
  },
  {
    type: 'if_else',
    label: '条件分支',
    description: '基于条件路由流程',
    colorClass: 'text-orange-700',
    borderClass: 'border-orange-400',
    bgClass: 'bg-orange-50 hover:bg-orange-100',
  },
];

export function NodePalette() {
  function handleDragStart(
    event: React.DragEvent<HTMLDivElement>,
    type: DSLNode['type'],
  ) {
    event.dataTransfer.setData('application/agent-builder-node', type);
    event.dataTransfer.effectAllowed = 'move';
  }

  return (
    <div className="flex h-full w-60 flex-shrink-0 flex-col border-r border-gray-200 bg-white">
      {/* 标题 */}
      <div className="border-b border-gray-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-700">节点库</h2>
        <p className="mt-0.5 text-xs text-gray-400">拖拽节点到画布</p>
      </div>

      {/* 节点列表 */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="space-y-2">
          {NODE_TYPES.map((node) => (
            <div
              key={node.type}
              draggable
              onDragStart={(e) => handleDragStart(e, node.type)}
              data-node-type={node.type}
              role="button"
              tabIndex={0}
              aria-label={`拖拽 ${node.label} 节点`}
              className={`cursor-grab rounded-lg border px-3 py-2.5 transition-colors active:cursor-grabbing ${node.bgClass} ${node.borderClass}`}
            >
              <div className={`text-sm font-medium ${node.colorClass}`}>
                {node.label}
              </div>
              <div className="mt-0.5 text-xs text-gray-500">
                {node.description}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
