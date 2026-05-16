/**
 * decision-form.spec.tsx — DecisionForm 单元测试
 *
 * 覆盖（4 用例）：
 * 1. test_renders_three_buttons_for_submit_phase — submit/return/reject
 * 2. test_renders_three_buttons_for_review_phase — approve/return/reject
 * 3. test_button_disabled_when_submitting — Pitfall 2 应用层防双提交
 * 4. test_calls_submitHitlAction_with_form_data_and_reason — 提交语义
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DecisionForm } from '@/components/hitl/decision-form';
import type { HitlSubmitResult } from '@/lib/types/hitl';
import type { RJSFSchema } from '@rjsf/utils';

const EMPTY_SCHEMA: RJSFSchema = { type: 'object', properties: {} };

describe('DecisionForm', () => {
  it('test_renders_three_buttons_for_submit_phase: 提交阶段渲染 submit/return/reject', () => {
    render(
      <DecisionForm
        token="tok-1"
        jti="jti-1"
        formSchema={EMPTY_SCHEMA}
        phase="submit"
      />,
    );
    expect(screen.getByText('提交')).toBeDefined();
    expect(screen.getByText('退回')).toBeDefined();
    expect(screen.getByText('拒绝')).toBeDefined();
    // submit action 按钮 data-action 属性
    expect(screen.getByTestId('action-buttons').querySelector('[data-action="submit"]')).not.toBeNull();
    expect(screen.getByTestId('action-buttons').querySelector('[data-action="return"]')).not.toBeNull();
    expect(screen.getByTestId('action-buttons').querySelector('[data-action="reject"]')).not.toBeNull();
  });

  it('test_renders_three_buttons_for_review_phase: 审核阶段渲染 approve/return/reject', () => {
    render(
      <DecisionForm
        token="tok-2"
        jti="jti-2"
        formSchema={EMPTY_SCHEMA}
        phase="review"
      />,
    );
    expect(screen.getByText('通过')).toBeDefined();
    expect(screen.getByText('退回')).toBeDefined();
    expect(screen.getByText('拒绝')).toBeDefined();
    expect(screen.getByTestId('action-buttons').querySelector('[data-action="approve"]')).not.toBeNull();
    // submit 按钮在 review 阶段不存在
    expect(screen.getByTestId('action-buttons').querySelector('[data-action="submit"]')).toBeNull();
  });

  it('test_button_disabled_when_submitting: 提交期间禁用所有按钮（Pitfall 2 应用层防护）', async () => {
    // 用 Promise 控制 submitter 完成时机
    let resolveSubmit: (v: HitlSubmitResult) => void = () => undefined;
    const pending = new Promise<HitlSubmitResult>((res) => {
      resolveSubmit = res;
    });
    const mockSubmit = vi.fn().mockReturnValue(pending);

    render(
      <DecisionForm
        token="tok-3"
        jti="jti-3"
        formSchema={EMPTY_SCHEMA}
        phase="submit"
        onSubmitOverride={mockSubmit}
      />,
    );

    const submitBtn = screen
      .getByTestId('action-buttons')
      .querySelector('[data-action="submit"]') as HTMLButtonElement;
    expect(submitBtn).not.toBeNull();
    expect(submitBtn.disabled).toBe(false);

    fireEvent.click(submitBtn);

    await waitFor(() => {
      // 状态切到 submitting → 所有按钮 disabled
      expect(submitBtn.disabled).toBe(true);
    });

    // 其它 action 按钮也被禁用
    const returnBtn = screen
      .getByTestId('action-buttons')
      .querySelector('[data-action="return"]') as HTMLButtonElement;
    expect(returnBtn.disabled).toBe(true);

    // 释放 pending，让组件回到稳定状态
    resolveSubmit({
      ok: false,
      status_code: 500,
      error: 'mock fail',
    });
    // 等待 setSubmitting(false) 生效
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('mock fail');
    });
  });

  it('test_calls_submitHitlAction_with_form_data_and_reason: 点击按钮调用 submitter 传 action + reason + form_data', async () => {
    const mockSubmit = vi.fn().mockResolvedValue({
      ok: false,
      status_code: 422,
      error: '校验失败',
      errors: ['email 必填'],
    } as HitlSubmitResult);

    render(
      <DecisionForm
        token="tok-4"
        jti="jti-4"
        formSchema={EMPTY_SCHEMA}
        phase="submit"
        onSubmitOverride={mockSubmit}
      />,
    );

    // 填 reason
    const reasonTextarea = screen.getByPlaceholderText(
      /请简要说明您的决策依据/,
    ) as HTMLTextAreaElement;
    fireEvent.change(reasonTextarea, { target: { value: '我的备注' } });

    // 点 submit
    const submitBtn = screen
      .getByTestId('action-buttons')
      .querySelector('[data-action="submit"]') as HTMLButtonElement;
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledTimes(1);
    });
    const [tokenArg, body] = mockSubmit.mock.calls[0];
    expect(tokenArg).toBe('tok-4');
    expect(body.action).toBe('submit');
    expect(body.reason).toBe('我的备注');
    expect(body.form_data).toEqual({});

    // 422 → inline error 显示字段错误
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('校验失败');
      expect(screen.getByRole('alert').textContent).toContain('email 必填');
    });
  });
});
