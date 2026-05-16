'use client';

/**
 * Tool 节点：HTTP 请求或 Python 函数调用
 * 左 target + 右 source handle，蓝色边框
 * 含错误状态：hasError → 红框 + 错误弹面板
 */

import { useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { useValidatorStore } from '@/lib/stores/validator-store';
import { ErrorPopover } from '../panels/error-popover';

export function ToolNode({ data, id }: NodeProps) {
  const errors = useValidatorStore((s) => s.nodeErrorsMap[id] ?? []);
  const hasError = errors.some((e) => e.severity === 'error');
  const hasWarning = !hasError && errors.some((e) => e.severity === 'warning');
  const [showPopover, setShowPopover] = useState(false);

  const config = (data?.config ?? {}) as Record<string, unknown>;
  const kind = (config.kind as string) || 'http';
  const httpConfig = config.http as Record<string, unknown> | undefined;
  const pythonConfig = config.python as Record<string, unknown> | undefined;

  const subInfo =
    kind === 'http'
      ? ((httpConfig?.url as string) || '未设置 URL')
      : ((pythonConfig?.function as string) || '未设置函数');

  const borderClass = hasError
    ? 'border-red-500 shadow-red-100'
    : hasWarning
      ? 'border-yellow-500 shadow-yellow-100'
      : 'border-blue-500';

  return (
    <div className="relative">
      <div
        className={`min-w-[180px] rounded-lg border-2 bg-white px-4 py-2 shadow-sm ${borderClass}`}
        onClick={() => {
          if (errors.length > 0) {
            setShowPopover((prev) => !prev);
          }
        }}
        data-testid={`node-${id}`}
        data-has-error={hasError}
        data-has-warning={hasWarning}
      >
        {/* 错误指示徽章 */}
        {hasError && (
          <span
            className="absolute -right-2 -top-2 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white"
            data-testid="error-badge"
          >
            !
          </span>
        )}
        {hasWarning && !hasError && (
          <span className="absolute -right-2 -top-2 flex h-4 w-4 items-center justify-center rounded-full bg-yellow-500 text-[9px] font-bold text-white">
            !
          </span>
        )}

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

      {/* 错误弹面板 */}
      {showPopover && errors.length > 0 && (
        <div className="absolute left-full top-0 z-50 ml-2">
          <ErrorPopover errors={errors} />
        </div>
      )}
    </div>
  );
}
