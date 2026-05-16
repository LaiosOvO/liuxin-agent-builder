'use client';

/**
 * 登录表单组件
 * 仅支持邮箱密码登录（公开注册关闭，无注册链接）
 */

import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';
import { login } from '@/lib/api/auth';
import { ApiCallError } from '@/lib/api/client';

const loginSchema = z.object({
  email: z.string().email('请输入有效的邮箱地址'),
  password: z.string().min(1, '请输入密码'),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [serverError, setServerError] = useState<string | null>(null);

  // 处理邮箱验证成功提示
  useEffect(() => {
    if (searchParams.get('verified') === '1') {
      toast.success('邮箱验证成功，请登录');
    }
  }, [searchParams]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    mode: 'onBlur',
  });

  const onSubmit = async (data: LoginFormValues) => {
    setServerError(null);
    try {
      await login(data);
      router.push('/dashboard');
    } catch (err) {
      if (err instanceof ApiCallError) {
        switch (err.status) {
          case 401:
            setServerError('邮箱或密码错误');
            break;
          case 403: {
            const detail = err.detail?.detail ?? '';
            if (detail.includes('pending_verification') || detail.includes('pending')) {
              setServerError('请先点击邮箱内的验证链接');
            } else if (detail.includes('disabled')) {
              setServerError('账号已被禁用，请联系管理员');
            } else {
              setServerError('登录失败，请联系管理员');
            }
            break;
          }
          case 429:
            setServerError('操作过于频繁，请稍后再试');
            break;
          default:
            setServerError('登录失败，请检查网络后重试');
        }
      } else {
        setServerError('网络错误，请检查连接后重试');
      }
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-gray-100 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-indigo-600 mb-1">agent-builder</h1>
          <p className="text-gray-500 text-sm">可视化 LangGraph 工作流编排平台</p>
        </div>

        {/* 表单卡片 */}
        <div className="bg-white rounded-2xl shadow-lg p-8">
          <h2 className="text-xl font-semibold text-gray-800 mb-6 text-center">登录</h2>

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
                邮箱
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                className={`w-full px-4 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.email ? 'border-red-400 bg-red-50' : 'border-gray-300'
                }`}
                placeholder="your@email.com"
                {...register('email')}
              />
              {errors.email && (
                <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>
              )}
            </div>

            {/* 密码 */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                密码
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                className={`w-full px-4 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  errors.password ? 'border-red-400 bg-red-50' : 'border-gray-300'
                }`}
                placeholder="••••••••"
                {...register('password')}
              />
              {errors.password && (
                <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>
              )}
            </div>

            {/* 提交按钮 */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-medium rounded-lg transition-colors text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
            >
              {isSubmitting ? '登录中...' : '登录'}
            </button>
          </form>

          {/* 忘记密码提示（无自助找回，v1） */}
          <p className="mt-4 text-center text-xs text-gray-400">
            忘记密码？请联系管理员重置
          </p>
        </div>
      </div>
    </div>
  );
}
