'use client';

/**
 * 运行实例弹窗
 * 参考 Dify web/app/components/workflow/run/ 的启动表单设计
 *
 * - 显示该 workflow 的 state_schema 各字段（动态表单）
 * - react-hook-form 渲染输入框（按 type：str/int/float/bool）
 * - onSubmit → POST /workflows/<id>/instances → 跳转详情页
 */

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { instancesApi } from '@/lib/api/instances';
import type { DSL } from '@/lib/types/dsl';
import type { CreateInstanceInput } from '@/lib/types/instance';

interface RunInstanceDialogProps {
  workflowId: string;
  workflowName: string;
  dsl: DSL | null;
  onClose: () => void;
}

/** 解析 state_schema 字段生成表单 */
function SchemaField({
  name,
  type,
  register,
}: {
  name: string;
  type: string;
  register: ReturnType<typeof useForm>['register'];
}) {
  const common = `w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none`;

  if (type === 'bool') {
    return (
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id={name}
          {...register(name)}
          className="rounded border-gray-300"
        />
        <label htmlFor={name} className="text-sm text-gray-700">
          {name}
          <span className="ml-1 text-xs text-gray-400">({type})</span>
        </label>
      </div>
    );
  }

  if (type === 'int') {
    return (
      <div>
        <label className="mb-1 block text-sm text-gray-700">
          {name}
          <span className="ml-1 text-xs text-gray-400">({type})</span>
        </label>
        <input
          type="number"
          step="1"
          id={name}
          {...register(name, { valueAsNumber: true })}
          className={common}
        />
      </div>
    );
  }

  if (type === 'float') {
    return (
      <div>
        <label className="mb-1 block text-sm text-gray-700">
          {name}
          <span className="ml-1 text-xs text-gray-400">({type})</span>
        </label>
        <input
          type="number"
          step="any"
          id={name}
          {...register(name, { valueAsNumber: true })}
          className={common}
        />
      </div>
    );
  }

  if (type === 'dict' || type === 'list' || type === 'any') {
    return (
      <div>
        <label className="mb-1 block text-sm text-gray-700">
          {name}
          <span className="ml-1 text-xs text-gray-400">({type}，JSON 格式)</span>
        </label>
        <textarea
          id={name}
          {...register(name)}
          rows={2}
          placeholder={type === 'list' ? '[]' : '{}'}
          className={`${common} resize-none font-mono`}
        />
      </div>
    );
  }

  // 默认 str
  return (
    <div>
      <label className="mb-1 block text-sm text-gray-700">
        {name}
        <span className="ml-1 text-xs text-gray-400">({type})</span>
      </label>
      <input
        type="text"
        id={name}
        {...register(name)}
        className={common}
      />
    </div>
  );
}

/** 运行实例弹窗 */
export function RunInstanceDialog({
  workflowId,
  workflowName,
  dsl,
  onClose,
}: RunInstanceDialogProps) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stateSchema = dsl?.state_schema ?? {};
  const schemaEntries = Object.entries(stateSchema);

  const { register, handleSubmit } = useForm();

  const onSubmit = useCallback(
    async (formData: Record<string, unknown>) => {
      setSubmitting(true);
      setError(null);
      try {
        // 解析 JSON 字段
        const processedInput: Record<string, unknown> = {};
        for (const [key, val] of Object.entries(formData)) {
          const type = stateSchema[key];
          if ((type === 'dict' || type === 'list' || type === 'any') && typeof val === 'string') {
            try {
              processedInput[key] = JSON.parse(val || (type === 'list' ? '[]' : '{}'));
            } catch {
              processedInput[key] = val;
            }
          } else {
            processedInput[key] = val;
          }
        }

        const input: CreateInstanceInput = { initial_input: processedInput };
        const inst = await instancesApi.start(workflowId, input);
        router.push(`/dashboard/instances/${inst.id}`);
        onClose();
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : '创建实例失败');
      } finally {
        setSubmitting(false);
      }
    },
    [workflowId, stateSchema, router, onClose],
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-800">运行工作流</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        <p className="mb-4 text-sm text-gray-500">{workflowName}</p>

        {schemaEntries.length === 0 ? (
          <p className="mb-4 rounded-lg bg-gray-50 py-4 text-center text-sm text-gray-400">
            该工作流无需初始输入（state_schema 为空）
          </p>
        ) : (
          <form onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="space-y-4">
            {schemaEntries.map(([name, type]) => (
              <SchemaField
                key={name}
                name={name}
                type={type as string}
                register={register}
              />
            ))}

            {error && (
              <div className="rounded-lg bg-red-50 p-2 text-xs text-red-600">{error}</div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60"
              >
                {submitting ? '创建中…' : '开始运行'}
              </button>
            </div>
          </form>
        )}

        {schemaEntries.length === 0 && (
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600"
            >
              取消
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={() =>
                onSubmit({}).catch(() => setError('创建失败'))
              }
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              {submitting ? '创建中…' : '立即运行'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
