'use client';

/**
 * End 节点：工作流出口
 * 仅左侧 target handle，红色边框
 * 含错误状态：hasError → 深红框 + 错误弹面板
 */

import { useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { useValidatorStore } from '@/lib/stores/validator-store';
import { ErrorPopover } from '../panels/error-popover';

export function EndNode({ data, id }: NodeProps) {
  const errors = useValidatorStore((s) => s.nodeErrorsMap[id] ?? []);
  const hasError = errors.some((e) => e.severity === 'error');
  const hasWarning = !hasError && errors.some((e) => e.severity === 'warning');
  const [showPopover, setShowPopover] = useState(false);

  const borderClass = hasError
    ? 'border-red-600 shadow-red-200'
    : hasWarning
      ? 'border-yellow-500 shadow-yellow-100'
      : 'border-red-500';

  return (
    <div className="relative">
      <div
        className={`min-w-[140px] rounded-lg border-2 bg-white px-4 py-2 shadow-sm ${borderClass}`}
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
          className="!h-3 !w-3 !border-2 !border-red-500 !bg-white"
        />
        <div className="text-[10px] font-semibold uppercase tracking-wider text-red-600">
          结束
        </div>
        <div className="mt-0.5 truncate text-sm font-medium text-gray-900">
          {(data?.label as string) ?? id}
        </div>
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
