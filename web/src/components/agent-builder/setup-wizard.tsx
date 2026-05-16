'use client';

/**
 * Setup Wizard 组件
 * 首次启动时引导管理员完成系统初始化：创建 super_admin 账号 + 第一个 workspace
 */

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { initializeSetup } from '@/lib/api/auth';
import { ApiCallError } from '@/lib/api/client';

const setupSchema = z.object({
  email: z.string().email('请输入有效的邮箱地址'),
  password: z
    .string()
    .min(8, '密码至少 8 位')
    .regex(/(?=.*[a-z])/, '密码须包含小写字母')
    .regex(/(?=.*\d)/, '密码须包含数字'),
  display_name: z.string().min(1, '请输入显示名称').max(60, '显示名称不超过 60 字'),
  workspace_name: z.string().min(1, '请输入 Workspace 名称').max(60, 'Workspace 名称不超过 60 字'),
});

type SetupFormValues = z.infer<typeof setupSchema>;

export function SetupWizard() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SetupFormValues>({
    resolver: zodResolver(setupSchema),
    mode: 'onBlur',
  });

  const onSubmit = async (data: SetupFormValues) => {
    setServerError(null);
    try {
      await initializeSetup(data);
      toast.success('初始化成功，正在跳转到控制台...');
      router.push('/dashboard');
    } catch (err) {
      if (err instanceof ApiCallError) {
        if (err.status === 409) {
          setServerError('系统已经初始化，请直接登录');
        } else {
          setServerError(err.message || '初始化失败，请重试');
        }
        toast.error(serverError || '初始化失败');
      } else {
        setServerError('网络错误，请检查连接后重试');
      }
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-gray-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* 顶部 Banner */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-indigo-600 mb-2">agent-builder</h1>
          <p className="text-gray-600 text-sm">
            欢迎首次启动 agent-builder，请创建管理员账号
          </p>
        </div>

        {/* 表单卡片 */}
        <div className="bg-white rounded-2xl shadow-lg p-8">
          <h2 className="text-xl font-semibold text-gray-800 mb-6">初始化配置</h2>

          {serverError && (
            <div
              role="alert"
              className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm"
            >
              {serverError}
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-5">
            {/* 邮箱 */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                管理员邮箱 <span className="text-red-500">*</span>
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                className={`w-full px-4 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.email ? 'border-red-400 bg-red-50' : 'border-gray-300'
                }`}
                placeholder="admin@example.com"
                {...register('email')}
              />
              {errors.email && (
                <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>
              )}
            </div>

            {/* 密码 */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                密码 <span className="text-red-500">*</span>
              </label>
              <input
                id="password"
                type="password"
                autoComplete="new-password"
                className={`w-full px-4 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.password ? 'border-red-400 bg-red-50' : 'border-gray-300'
                }`}
                placeholder="至少 8 位，包含字母和数字"
                {...register('password')}
              />
              {errors.password && (
                <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>
              )}
            </div>

            {/* 显示名 */}
            <div>
              <label htmlFor="display_name" className="block text-sm font-medium text-gray-700 mb-1">
                显示名称 <span className="text-red-500">*</span>
              </label>
              <input
                id="display_name"
                type="text"
                autoComplete="name"
                className={`w-full px-4 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.display_name ? 'border-red-400 bg-red-50' : 'border-gray-300'
                }`}
                placeholder="您的姓名或昵称"
                {...register('display_name')}
              />
              {errors.display_name && (
                <p className="mt-1 text-xs text-red-600">{errors.display_name.message}</p>
              )}
            </div>

            {/* Workspace 名 */}
            <div>
              <label htmlFor="workspace_name" className="block text-sm font-medium text-gray-700 mb-1">
                Workspace 名称 <span className="text-red-500">*</span>
              </label>
              <input
                id="workspace_name"
                type="text"
                className={`w-full px-4 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.workspace_name ? 'border-red-400 bg-red-50' : 'border-gray-300'
                }`}
                placeholder="我的团队"
                {...register('workspace_name')}
              />
              {errors.workspace_name && (
                <p className="mt-1 text-xs text-red-600">{errors.workspace_name.message}</p>
              )}
            </div>

            {/* 提交按钮 */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-medium rounded-lg transition-colors text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
            >
              {isSubmitting ? '正在创建...' : '创建并开始使用'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-400 mt-6">
          agent-builder v1 · Phase 1
        </p>
      </div>
    </div>
  );
}
