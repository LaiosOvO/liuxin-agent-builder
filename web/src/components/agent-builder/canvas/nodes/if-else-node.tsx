'use client';

/**
 * IfElse 节点：条件分支
 * 左 target handle + 多个右 source handle，橙色边框
 * 含错误状态：hasError → 红框 + 错误弹面板
 */

import { useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { IfElseNodeConfig } from '@/lib/types/dsl';
import { useValidatorStore } from '@/lib/stores/validator-store';
import { ErrorPopover } from '../panels/error-popover';

export function IfElseNode({ data, id }: NodeProps) {
  const errors = useValidatorStore((s) => s.nodeErrorsMap[id] ?? []);
  const hasError = errors.some((e) => e.severity === 'error');
  const hasWarning = !hasError && errors.some((e) => e.severity === 'warning');
  const [showPopover, setShowPopover] = useState(false);

  const config = (data?.config ?? {}) as Partial<IfElseNodeConfig>;
  const conditions = config.conditions ?? [];

  const borderClass = hasError
    ? 'border-red-500 shadow-red-100'
    : hasWarning
      ? 'border-yellow-500 shadow-yellow-100'
      : 'border-orange-500';

  return (
    <div className="relative">
      <div
        className={`min-w-[200px] rounded-lg border-2 bg-white px-4 py-2 shadow-sm ${borderClass}`}
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

      {/* 错误弹面板 */}
      {showPopover && errors.length > 0 && (
        <div className="absolute left-full top-0 z-50 ml-2">
          <ErrorPopover errors={errors} />
        </div>
      )}
    </div>
  );
}
