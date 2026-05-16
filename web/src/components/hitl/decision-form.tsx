/**
 * HITL 决策表单（Plan 03-07）— Phase 3 P0 价值演示阶段的公网交互核心。
 *
 * 设计要点（参考 docs/reading-dify-03-07-decision-page-2026-05-17.md §4）：
 * - RJSF 5.x 渲染 form_schema 动态字段
 * - 按 phase 切换 3 按钮：submit/return/reject 或 approve/return/reject
 * - reason textarea 独立于 form_schema（始终展示，建议必填于 return/reject）
 * - 提交后 disable 所有按钮防双提交（Pitfall 2 应用层第一道防护）
 * - 422 错误 inline 显示 / 409 跳成功页 / 410 / 401 错误页
 */

'use client';

import { useState } from 'react';
import Form from '@rjsf/core';
import validator from '@rjsf/validator-ajv8';
import type { RJSFSchema } from '@rjsf/utils';
import { submitHitlAction } from '@/lib/api/hitl';
import type { ActionButtonConfig, HitlSubmitResult } from '@/lib/types/hitl';

interface DecisionFormProps {
  token: string;
  jti: string;
  formSchema: RJSFSchema;
  phase: 'submit' | 'review';
  /** 超时禁用按钮（DeadlineCountdown 通知） */
  disabled?: boolean;
  /** 测试钩子：注入自定义 submitter 便于 vitest mock fetch */
  onSubmitOverride?: (
    token: string,
    body: {
      action: string;
      reason: string;
      form_data: Record<string, unknown>;
    },
  ) => Promise<HitlSubmitResult>;
}

/** 按 phase 决定 3 按钮组合 + Tailwind 颜色。 */
const ACTIONS_BY_PHASE: Record<'submit' | 'review', ActionButtonConfig[]> = {
  submit: [
    {
      id: 'submit',
      label: '提交',
      color: 'bg-emerald-600 hover:bg-emerald-700',
    },
    {
      id: 'return',
      label: '退回',
      color: 'bg-amber-500 hover:bg-amber-600',
    },
    {
      id: 'reject',
      label: '拒绝',
      color: 'bg-red-500 hover:bg-red-600',
    },
  ],
  review: [
    {
      id: 'approve',
      label: '通过',
      color: 'bg-emerald-600 hover:bg-emerald-700',
    },
    {
      id: 'return',
      label: '退回',
      color: 'bg-amber-500 hover:bg-amber-600',
    },
    {
      id: 'reject',
      label: '拒绝',
      color: 'bg-red-500 hover:bg-red-600',
    },
  ],
};

export function DecisionForm({
  token,
  jti,
  formSchema,
  phase,
  disabled = false,
  onSubmitOverride,
}: DecisionFormProps) {
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<string[]>([]);
  const actions = ACTIONS_BY_PHASE[phase] ?? ACTIONS_BY_PHASE.submit;
  const isDisabled = submitting || disabled;

  async function handleSubmit(actionId: string): Promise<void> {
    if (isDisabled) return;
    setSubmitting(true);
    setError(null);
    setFieldErrors([]);

    try {
      const submitter = onSubmitOverride ?? submitHitlAction;
      const result = await submitter(token, {
        action: actionId,
        reason,
        form_data: formData,
      });

      if (result.ok) {
        // 成功 → 跳成功页（client-side navigation）
        if (typeof window !== 'undefined') {
          window.location.assign(`/hitl/success/${result.instance_id}`);
        }
        // 不 reset submitting —— 防止跳转前用户再点
        return;
      }

      // 失败分类
      if (result.status_code === 409) {
        setError('决策已提交，无法重复操作。即将跳转到结果页…');
        setTimeout(() => {
          if (typeof window !== 'undefined') {
            window.location.assign('/hitl/success/already-submitted');
          }
        }, 1500);
        return;
      }

      if (result.status_code === 422) {
        setError(result.error || '表单校验失败');
        setFieldErrors(result.errors ?? []);
        setSubmitting(false);
        return;
      }

      setError(result.error || '提交失败');
      setSubmitting(false);
    } catch (caught: unknown) {
      const message =
        caught instanceof Error ? caught.message : '提交时发生未知错误';
      setError(message);
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6" data-testid="decision-form">
      {/* 隐藏字段：jti 供调试 */}
      <input type="hidden" name="jti" value={jti} readOnly />

      {/* RJSF 表单 —— 关闭默认 submit 按钮（我们自管） */}
      <Form
        schema={formSchema}
        validator={validator}
        formData={formData}
        onChange={(e) => setFormData(e.formData ?? {})}
        uiSchema={{ 'ui:submitButtonOptions': { norender: true } }}
        disabled={isDisabled}
      >
        <></>
      </Form>

      {/* Reason textarea */}
      <div>
        <label
          htmlFor="hitl-reason"
          className="block text-sm font-medium mb-2 text-gray-700"
        >
          备注 / 原因
          <span className="ml-2 text-xs text-gray-400">
            （建议必填于退回 / 拒绝）
          </span>
        </label>
        <textarea
          id="hitl-reason"
          name="reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={isDisabled}
          placeholder="请简要说明您的决策依据…"
          className="w-full min-h-[80px] rounded-md border border-gray-300 p-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:bg-gray-100"
        />
      </div>

      {/* 错误提示（inline） */}
      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          <div className="font-medium">{error}</div>
          {fieldErrors.length > 0 && (
            <ul className="mt-2 list-disc pl-5">
              {fieldErrors.map((fe, idx) => (
                <li key={idx}>{fe}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* 三按钮 */}
      <div className="flex flex-wrap gap-3" data-testid="action-buttons">
        {actions.map((action) => (
          <button
            key={action.id}
            type="button"
            disabled={isDisabled}
            onClick={() => handleSubmit(action.id)}
            data-action={action.id}
            className={`${action.color} text-white px-6 py-2 rounded-md font-medium text-sm transition disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            {submitting ? '处理中…' : action.label}
          </button>
        ))}
      </div>

      {disabled && !submitting && (
        <div className="text-xs text-gray-500" data-testid="disabled-hint">
          已超时或会话失效，按钮已锁定。
        </div>
      )}
    </div>
  );
}
