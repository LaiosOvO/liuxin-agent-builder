'use client';

/**
 * 邀请接受表单组件
 * 从 query string 读取 token → 预览邀请信息 → 填写密码和显示名 → 注册并登录
 */

import { useState, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { toast } from 'sonner';
import { getInvitePreview, acceptInvite } from '@/lib/api/invites';
import { ApiCallError } from '@/lib/api/client';
import type { InvitePreview, RoleCode } from '@/lib/types/api';

const inviteSchema = z.object({
  password: z
    .string()
    .min(8, '密码至少 8 位')
    .regex(/(?=.*[a-z])/, '密码须包含小写字母')
    .regex(/(?=.*\d)/, '密码须包含数字'),
  display_name: z.string().min(1, '请输入显示名称').max(60, '显示名称不超过 60 字'),
  department: z.string().max(100, '部门名称不超过 100 字').optional(),
});

type InviteFormValues = z.infer<typeof inviteSchema>;

const ROLE_LABELS: Record<RoleCode, string> = {
  super_admin: '超级管理员',
  admin: '管理员',
  editor: '编辑',
  viewer: '查看者',
  external: '外部用户',
};

export function InviteAcceptanceForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get('token') ?? '';

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(true);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    mode: 'onBlur',
  });

  // 挂载时拉取邀请预览
  useEffect(() => {
    if (!token) {
      setPreviewError('邀请链接无效：缺少 token 参数');
      setIsLoadingPreview(false);
      return;
    }

    const controller = new AbortController();
    setIsLoadingPreview(true);

    getInvitePreview(token, controller.signal)
      .then((data) => {
        if (data.already_used) {
          setPreviewError('邀请链接已失效（已使用或已过期）');
        } else {
          setPreview(data);
        }
        setIsLoadingPreview(false);
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === 'AbortError') return;
        if (err instanceof ApiCallError) {
          if (err.status === 404 || err.status === 410) {
            setPreviewError('邀请链接已失效或不存在');
          } else if (err.status === 400) {
            setPreviewError('邀请链接已过期');
          } else {
            setPreviewError('无法获取邀请信息，请重试');
          }
        } else {
          setPreviewError('网络错误，请检查连接后重试');
        }
        setIsLoadingPreview(false);
      });

    return () => controller.abort();
  }, [token]);

  const onSubmit = async (data: InviteFormValues) => {
    setServerError(null);
    try {
      await acceptInvite({
        token,
        password: data.password,
        display_name: data.display_name,
        department: data.department || undefined,
      });
      toast.success('注册成功，正在跳转...');
      router.push('/dashboard');
    } catch (err) {
      if (err instanceof ApiCallError) {
        if (err.status === 410 || err.status === 404) {
          setServerError('邀请链接已失效，请联系管理员重新发送');
        } else if (err.status === 409) {
          setServerError('该邮箱已注册，请直接登录');
        } else {
          setServerError(err.message || '注册失败，请重试');
        }
      } else {
        setServerError('网络错误，请检查连接后重试');
      }
    }
  };

  // 加载中
  if (isLoadingPreview) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">正在加载邀请信息...</div>
      </div>
    );
  }

  // 邀请失效
  if (previewError) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-gray-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 max-w-sm w-full text-center">
          <div className="text-4xl mb-4">⚠️</div>
          <h2 className="text-xl font-semibold text-gray-800 mb-2">邀请链接已失效</h2>
          <p className="text-gray-500 text-sm">{previewError}</p>
          <p className="text-gray-400 text-xs mt-4">请联系管理员重新发送邀请邮件</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-gray-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <h1 className="text-3xl font-bold text-indigo-600 mb-1">agent-builder</h1>
          <p className="text-gray-500 text-sm">您已被邀请加入工作区</p>
        </div>

        {/* 邀请预览卡片 */}
        {preview && (
          <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-5 mb-4">
            <div className="text-sm space-y-1.5">
              <div className="flex justify-between">
                <span className="text-gray-500">工作区</span>
                <span className="font-medium text-gray-800">{preview.workspace_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">角色</span>
                <span className="font-medium text-indigo-700">
                  {ROLE_LABELS[preview.role_code] ?? preview.role_code}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">邀请人</span>
                <span className="font-medium text-gray-800">{preview.inviter_display_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">过期时间</span>
                <span className="text-gray-600 text-xs">
                  {new Date(preview.expires_at).toLocaleString('zh-CN')}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* 注册表单 */}
        <div className="bg-white rounded-2xl shadow-lg p-8">
          <h2 className="text-xl font-semibold text-gray-800 mb-6">完善账号信息</h2>

          {serverError && (
            <div
              role="alert"
              className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm"
            >
              {serverError}
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-5">
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

            {/* 密码 */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                设置密码 <span className="text-red-500">*</span>
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

            {/* 部门（可选） */}
            <div>
              <label htmlFor="department" className="block text-sm font-medium text-gray-700 mb-1">
                部门 <span className="text-gray-400 text-xs">（可选）</span>
              </label>
              <input
                id="department"
                type="text"
                autoComplete="organization"
                className="w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="研发部、市场部..."
                {...register('department')}
              />
            </div>

            {/* 提交 */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-medium rounded-lg transition-colors text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
            >
              {isSubmitting ? '正在加入...' : '加入工作区'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
