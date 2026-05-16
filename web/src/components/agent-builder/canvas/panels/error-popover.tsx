'use client';

/**
 * ErrorPopover — 节点错误弹面板
 *
 * 显示某个节点的所有 errors + 修复建议。
 * 由各节点组件在 hasError && isSelected 时渲染。
 *
 * 设计参考（Dify ChecklistItem 思路）：
 * - 每条错误显示 code + message + field_path
 * - getFixSuggestion() 映射所有已知错误码的修复建议（中文）
 */

import type { ValidationError } from '@/lib/validator/types';
import { ERROR_CODES } from '@/lib/validator/types';

interface ErrorPopoverProps {
  /** 当前节点的所有错误（包含 warning） */
  errors: ValidationError[];
}

/** 错误代码 → 修复建议映射 */
function getFixSuggestion(code: string): string {
  const suggestions: Record<string, string> = {
    [ERROR_CODES.E_CYCLE]: '删除导致成环的边，确保 DAG 无回路',
    [ERROR_CODES.E_UNREACHABLE_END]: '添加从 start 到 end 的连通路径',
    [ERROR_CODES.E_DANGLING_EDGE]: '删除悬空边，或补充缺失的目标节点',
    [ERROR_CODES.E_DUPLICATE_NODE_ID]: '修改节点 ID，确保每个 ID 全局唯一',
    [ERROR_CODES.E_START_HAS_INBOUND]: '删除连向 start 节点的入边',
    [ERROR_CODES.E_END_HAS_OUTBOUND]: '删除从 end 节点出发的出边',
    [ERROR_CODES.E_ORPHAN_NODE]: '将孤立节点连入主流程，或删除该节点',
    [ERROR_CODES.E_NO_START]: '添加一个 start 节点',
    [ERROR_CODES.E_NO_END]: '添加一个 end 节点',
    [ERROR_CODES.E_MULTIPLE_START]: '删除多余的 start 节点，只保留一个',
    [ERROR_CODES.E_INVALID_NODE_ID]: '节点 ID 须以小写字母开头，只含小写字母/数字/下划线',
    [ERROR_CODES.E_NODE_ID_RESERVED]: '修改为非保留字的 ID（如 my_start）',
    [ERROR_CODES.E_INVALID_CONFIG]: '查看配置面板，修正标红的必填字段',
    [ERROR_CODES.E_INVALID_STATE_TYPE]: '支持类型：str / int / float / bool / list / dict / any',
    [ERROR_CODES.E_IF_ELSE_NO_DEFAULT]: '在 if_else 配置中添加 default_target 字段',
    [ERROR_CODES.E_IF_ELSE_BAD_TARGET]: '检查条件目标节点 ID 拼写，确保节点存在',
    [ERROR_CODES.E_UNDEFINED_VAR]: '检查引用的节点 ID 拼写，确保该节点已定义',
    [ERROR_CODES.E_UNDEFINED_FIELD]: '查看该节点类型的输出字段列表，修正字段名',
    [ERROR_CODES.E_VAR_NOT_UPSTREAM]: '只能引用位于当前节点上游（已执行）的节点',
  };
  return suggestions[code] ?? '请联系管理员或查看文档';
}

/** 严重级别图标（纯文本，避免引入额外图标库） */
function SeverityBadge({ severity }: { severity: 'error' | 'warning' }) {
  if (severity === 'error') {
    return (
      <span className="inline-flex items-center rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
        错误
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-yellow-100 px-1.5 py-0.5 text-[10px] font-semibold text-yellow-700">
      警告
    </span>
  );
}

/** 节点错误弹面板 */
export function ErrorPopover({ errors }: ErrorPopoverProps) {
  if (errors.length === 0) return null;

  return (
    <div
      className="z-50 max-w-xs space-y-2 rounded-lg border border-gray-200 bg-white p-3 shadow-lg"
      data-testid="error-popover"
    >
      <div className="text-xs font-semibold text-gray-700">
        节点问题（{errors.length} 条）
      </div>

      {errors.map((err, idx) => (
        <div
          key={idx}
          className="flex items-start gap-2 rounded bg-gray-50 p-2 text-xs"
          data-testid={`error-item-${err.code}`}
        >
          <SeverityBadge severity={err.severity} />

          <div className="min-w-0 flex-1 space-y-0.5">
            <div className="text-gray-900">{err.message}</div>

            {err.field_path && (
              <div className="text-gray-400">字段：{err.field_path}</div>
            )}

            <div className="text-blue-600">{getFixSuggestion(err.code)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
