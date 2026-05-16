'use client';

/**
 * ConfigPanel — 右侧节点配置面板
 * 根据当前选中节点类型动态渲染对应表单
 * 使用 react-hook-form + zod resolver 校验
 */

import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import type { Node } from '@xyflow/react';
import { useCanvasStore } from '@/lib/stores/canvas-store';

// ====== Zod Schemas ======

/** Start / End 节点表单 schema */
const startEndSchema = z.object({
  label: z.string().min(1, '标签不能为空'),
});

/** LLM 节点表单 schema */
const llmSchema = z.object({
  model: z.string().min(1, '模型不能为空'),
  system_prompt: z.string(),
  user_prompt: z.string().min(1, 'User Prompt 不能为空'),
  temperature: z.number().min(0).max(2),
  timeout_sec: z.number().int().min(1),
  retry_count: z.number().int().min(0),
  backoff_base_sec: z.number().min(0),
  raw_prompt: z.boolean(),
});

/** Tool 节点表单 schema（简化版，kind 切换） */
const toolSchema = z.object({
  kind: z.enum(['http', 'python']),
  url: z.string(),
  method: z.enum(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']).optional(),
  body: z.string(),
  function_name: z.string(),
});

/** IfElse 节点表单 schema */
const ifElseSchema = z.object({
  default_target: z.string(),
});

type StartEndFormData = z.infer<typeof startEndSchema>;
type LLMFormData = z.infer<typeof llmSchema>;
type ToolFormData = z.infer<typeof toolSchema>;
type IfElseFormData = z.infer<typeof ifElseSchema>;

// ====== 子表单组件 ======

/** Start / End 节点配置表单 */
function StartEndNodeConfig({ node }: { node: Node }) {
  const { updateNodeConfig } = useCanvasStore();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<StartEndFormData>({
    resolver: zodResolver(startEndSchema),
    defaultValues: { label: (node.data?.label as string) ?? node.id },
  });

  useEffect(() => {
    reset({ label: (node.data?.label as string) ?? node.id });
  }, [node.id, node.data?.label, reset]);

  function onSubmit(data: StartEndFormData) {
    updateNodeConfig(node.id, { ...(node.data.config as Record<string, unknown>), label: data.label });
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-gray-700">标签</label>
        <input
          {...register('label')}
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        {errors.label && (
          <p className="mt-0.5 text-xs text-red-500">{errors.label.message}</p>
        )}
      </div>
      <button
        type="submit"
        className="w-full rounded bg-indigo-600 py-1.5 text-sm text-white hover:bg-indigo-700"
      >
        保存
      </button>
    </form>
  );
}

/** LLM 节点配置表单 */
function LLMNodeConfig({ node }: { node: Node }) {
  const { updateNodeConfig } = useCanvasStore();
  const config = (node.data?.config ?? {}) as Record<string, unknown>;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<LLMFormData>({
    resolver: zodResolver(llmSchema),
    defaultValues: {
      model: (config.model as string) || 'openai/gpt-4o',
      system_prompt: (config.system_prompt as string) || '',
      user_prompt: (config.user_prompt as string) || '',
      temperature: (config.temperature as number) ?? 0.7,
      timeout_sec: (config.timeout_sec as number) ?? 30,
      retry_count: (config.retry_count as number) ?? 3,
      backoff_base_sec: (config.backoff_base_sec as number) ?? 1,
      raw_prompt: (config.raw_prompt as boolean) ?? false,
    },
  });

  useEffect(() => {
    reset({
      model: (config.model as string) || 'openai/gpt-4o',
      system_prompt: (config.system_prompt as string) || '',
      user_prompt: (config.user_prompt as string) || '',
      temperature: (config.temperature as number) ?? 0.7,
      timeout_sec: (config.timeout_sec as number) ?? 30,
      retry_count: (config.retry_count as number) ?? 3,
      backoff_base_sec: (config.backoff_base_sec as number) ?? 1,
      raw_prompt: (config.raw_prompt as boolean) ?? false,
    });
  }, [node.id, reset]);

  function onSubmit(data: LLMFormData) {
    updateNodeConfig(node.id, data);
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
      <div>
        <label className="block text-xs font-medium text-gray-700">模型</label>
        <input
          {...register('model')}
          placeholder="openai/gpt-4o"
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        {errors.model && (
          <p className="mt-0.5 text-xs text-red-500">{errors.model.message}</p>
        )}
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700">
          System Prompt
        </label>
        <textarea
          {...register('system_prompt')}
          rows={3}
          placeholder="可选。支持 Jinja2 变量 {{ node_id.field }}"
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700">
          User Prompt
        </label>
        <textarea
          {...register('user_prompt')}
          rows={4}
          placeholder="支持 Jinja2 变量 {{ start.output }}"
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        {errors.user_prompt && (
          <p className="mt-0.5 text-xs text-red-500">{errors.user_prompt.message}</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs font-medium text-gray-700">
            Temperature
          </label>
          <input
            {...register('temperature', { valueAsNumber: true })}
            type="number"
            step="0.1"
            min="0"
            max="2"
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700">
            超时（秒）
          </label>
          <input
            {...register('timeout_sec', { valueAsNumber: true })}
            type="number"
            min="1"
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700">
            重试次数
          </label>
          <input
            {...register('retry_count', { valueAsNumber: true })}
            type="number"
            min="0"
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700">
            退避基数（秒）
          </label>
          <input
            {...register('backoff_base_sec', { valueAsNumber: true })}
            type="number"
            min="0"
            step="0.5"
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </div>
      </div>

      <button
        type="submit"
        className="w-full rounded bg-indigo-600 py-1.5 text-sm text-white hover:bg-indigo-700"
      >
        保存
      </button>
    </form>
  );
}

/** Tool 节点配置表单 */
function ToolNodeConfig({ node }: { node: Node }) {
  const { updateNodeConfig } = useCanvasStore();
  const config = (node.data?.config ?? {}) as Record<string, unknown>;
  const httpConfig = (config.http ?? {}) as Record<string, unknown>;
  const pythonConfig = (config.python ?? {}) as Record<string, unknown>;

  const { register, handleSubmit, watch, reset } = useForm<ToolFormData>({
    resolver: zodResolver(toolSchema),
    defaultValues: {
      kind: (config.kind as 'http' | 'python') || 'http',
      url: (httpConfig.url as string) || '',
      method: (httpConfig.method as ToolFormData['method']) || 'GET',
      body: (httpConfig.body as string) || '',
      function_name: (pythonConfig.function as string) || '',
    },
  });

  useEffect(() => {
    reset({
      kind: (config.kind as 'http' | 'python') || 'http',
      url: (httpConfig.url as string) || '',
      method: (httpConfig.method as ToolFormData['method']) || 'GET',
      body: (httpConfig.body as string) || '',
      function_name: (pythonConfig.function as string) || '',
    });
  }, [node.id, reset]);

  const kind = watch('kind');

  function onSubmit(data: ToolFormData) {
    if (data.kind === 'http') {
      updateNodeConfig(node.id, {
        kind: 'http',
        http: { method: data.method, url: data.url, headers: {}, body: data.body },
      });
    } else {
      updateNodeConfig(node.id, {
        kind: 'python',
        python: { function: data.function_name, args: {} },
      });
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
      <div>
        <label className="block text-xs font-medium text-gray-700">类型</label>
        <select
          {...register('kind')}
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
        >
          <option value="http">HTTP 请求</option>
          <option value="python">Python 函数</option>
        </select>
      </div>

      {kind === 'http' ? (
        <>
          <div>
            <label className="block text-xs font-medium text-gray-700">Method</label>
            <select
              {...register('method')}
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            >
              {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">URL</label>
            <input
              {...register('url')}
              placeholder="https://api.example.com/endpoint"
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700">Body（JSON / Jinja2）</label>
            <textarea
              {...register('body')}
              rows={3}
              placeholder='{"key": "{{ start.value }}"}'
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
        </>
      ) : (
        <div>
          <label className="block text-xs font-medium text-gray-700">函数名称</label>
          <input
            {...register('function_name')}
            placeholder="my_custom_function"
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
        </div>
      )}

      <button
        type="submit"
        className="w-full rounded bg-indigo-600 py-1.5 text-sm text-white hover:bg-indigo-700"
      >
        保存
      </button>
    </form>
  );
}

/** IfElse 节点配置表单 */
function IfElseNodeConfig({ node }: { node: Node }) {
  const { updateNodeConfig } = useCanvasStore();
  const config = (node.data?.config ?? {}) as Record<string, unknown>;

  const { register, handleSubmit, reset } = useForm<IfElseFormData>({
    resolver: zodResolver(ifElseSchema),
    defaultValues: {
      default_target: (config.default_target as string) || '',
    },
  });

  useEffect(() => {
    reset({ default_target: (config.default_target as string) || '' });
  }, [node.id, reset]);

  function onSubmit(data: IfElseFormData) {
    updateNodeConfig(node.id, { ...config, default_target: data.default_target });
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
      <div>
        <label className="block text-xs font-medium text-gray-700">默认跳转节点 ID</label>
        <input
          {...register('default_target')}
          placeholder="end"
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
        />
      </div>
      <p className="text-xs text-gray-400">条件编辑功能 Plan 02-09 接入完整验证后扩展。</p>
      <button
        type="submit"
        className="w-full rounded bg-indigo-600 py-1.5 text-sm text-white hover:bg-indigo-700"
      >
        保存
      </button>
    </form>
  );
}

// ====== 空状态 ======

function EmptyState() {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <div>
        <div className="text-2xl text-gray-300">⚙</div>
        <p className="mt-2 text-sm text-gray-400">选中节点后在此编辑配置</p>
      </div>
    </div>
  );
}

// ====== 主组件 ======

export function ConfigPanel() {
  const selectedNodeId = useCanvasStore((s) => s.selectedNodeId);
  const node = useCanvasStore((s) =>
    s.nodes.find((n) => n.id === s.selectedNodeId),
  );

  if (!selectedNodeId || !node) {
    return (
      <div className="flex h-full w-[360px] flex-shrink-0 flex-col border-l border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-700">节点配置</h2>
        </div>
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="flex h-full w-[360px] flex-shrink-0 flex-col border-l border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-700">节点配置</h2>
        <p className="mt-0.5 truncate text-xs text-gray-400">
          {node.type} · {node.id}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {node.type === 'start' && <StartEndNodeConfig node={node} />}
        {node.type === 'end' && <StartEndNodeConfig node={node} />}
        {node.type === 'llm' && <LLMNodeConfig node={node} />}
        {node.type === 'tool' && <ToolNodeConfig node={node} />}
        {node.type === 'if_else' && <IfElseNodeConfig node={node} />}
      </div>
    </div>
  );
}
