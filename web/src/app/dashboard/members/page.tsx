'use client';

/**
 * 成员管理页面
 * admin 可看成员列表 + 发邀请；editor/viewer 只能看列表
 */

import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { toast } from 'sonner';
import { listInvites, createInvite } from '@/lib/api/invites';
import { ApiCallError } from '@/lib/api/client';
import { RoleGate } from '@/components/auth/role-gate';
import type { InviteRecord, RoleCode } from '@/lib/types/api';
import { PlusIcon, MailIcon, UserCheckIcon, ClockIcon } from 'lucide-react';

const inviteFormSchema = z.object({
  email: z.string().email('请输入有效邮箱'),
  role_code: z.enum(['admin', 'editor', 'viewer'] as const),
});

type InviteFormValues = z.infer<typeof inviteFormSchema>;

const STATUS_LABELS: Record<InviteRecord['status'], string> = {
  pending: '待接受',
  accepted: '已接受',
  expired: '已过期',
};

const ROLE_LABELS: Partial<Record<RoleCode, string>> = {
  super_admin: '超级管理员',
  admin: '管理员',
  editor: '编辑',
  viewer: '查看者',
};

export default function MembersPage() {
  const [invites, setInvites] = useState<InviteRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showInviteModal, setShowInviteModal] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<InviteFormValues>({
    resolver: zodResolver(inviteFormSchema),
    defaultValues: { role_code: 'editor' },
  });

  const fetchInvites = async () => {
    try {
      setIsLoading(true);
      const data = await listInvites();
      setInvites(data);
    } catch (err) {
      if (err instanceof ApiCallError && err.status !== 403) {
        toast.error('获取成员列表失败');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void fetchInvites();
  }, []);

  const onInvite = async (data: InviteFormValues) => {
    try {
      await createInvite(data);
      toast.success('邀请邮件已发送');
      setShowInviteModal(false);
      reset();
      await fetchInvites();
    } catch (err) {
      if (err instanceof ApiCallError) {
        if (err.status === 409) {
          toast.error('该邮箱已在工作区中');
        } else {
          toast.error(`发送失败：${err.message}`);
        }
      } else {
        toast.error('网络错误，请重试');
      }
    }
  };

  return (
    <div className="max-w-4xl">
      {/* 页头 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">成员管理</h1>
          <p className="text-sm text-gray-500 mt-0.5">管理工作区成员与邀请记录</p>
        </div>

        {/* 发邀请按钮（admin 限定） */}
        <RoleGate need={['super_admin', 'admin']}>
          <button
            type="button"
            onClick={() => setShowInviteModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <PlusIcon className="h-4 w-4" />
            发送邀请
          </button>
        </RoleGate>
      </div>

      {/* 邀请列表 */}
      <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <MailIcon className="h-4 w-4 text-gray-400" />
            邀请记录
          </h2>
        </div>

        {isLoading ? (
          <div className="px-6 py-12 text-center text-gray-400 text-sm">加载中...</div>
        ) : invites.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-400 text-sm">
            暂无邀请记录
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {invites.map((invite) => (
              <div key={invite.id} className="px-6 py-4 flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-800 truncate">
                      {invite.email}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600">
                      {ROLE_LABELS[invite.role_code] ?? invite.role_code}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span
                      className={`text-xs ${
                        invite.status === 'accepted'
                          ? 'text-emerald-600'
                          : invite.status === 'expired'
                          ? 'text-red-400'
                          : 'text-yellow-600'
                      }`}
                    >
                      {STATUS_LABELS[invite.status]}
                    </span>
                    <span className="text-xs text-gray-400 flex items-center gap-1">
                      <ClockIcon className="h-3 w-3" />
                      过期：{new Date(invite.expires_at).toLocaleDateString('zh-CN')}
                    </span>
                  </div>
                </div>
                {invite.status === 'accepted' && (
                  <UserCheckIcon className="h-4 w-4 text-emerald-500 flex-shrink-0" />
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 发邀请 Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setShowInviteModal(false)}
          />
          <div className="relative bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm z-10">
            <h3 className="text-lg font-semibold text-gray-800 mb-5">发送邀请</h3>

            <form onSubmit={handleSubmit(onInvite)} noValidate className="space-y-4">
              <div>
                <label htmlFor="invite-email" className="block text-sm font-medium text-gray-700 mb-1">
                  邮箱
                </label>
                <input
                  id="invite-email"
                  type="email"
                  className={`w-full px-4 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                    errors.email ? 'border-red-400 bg-red-50' : 'border-gray-300'
                  }`}
                  placeholder="colleague@example.com"
                  {...register('email')}
                />
                {errors.email && (
                  <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>
                )}
              </div>

              <div>
                <label htmlFor="invite-role" className="block text-sm font-medium text-gray-700 mb-1">
                  角色
                </label>
                <select
                  id="invite-role"
                  className="w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                  {...register('role_code')}
                >
                  <option value="editor">编辑</option>
                  <option value="viewer">查看者</option>
                  <option value="admin">管理员</option>
                </select>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowInviteModal(false)}
                  className="flex-1 py-2.5 border border-gray-300 text-gray-600 text-sm rounded-lg hover:bg-gray-50 transition-colors"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white text-sm rounded-lg transition-colors"
                >
                  {isSubmitting ? '发送中...' : '发送邀请'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
