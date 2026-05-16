/**
 * InviteAcceptanceForm 组件测试
 */

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InviteAcceptanceForm } from '@/components/agent-builder/invite-acceptance-form';
import {
  invitePreviewValid,
  invitePreviewAlreadyUsed,
  invitePreviewNotFound,
  inviteAcceptSuccess,
} from './_helpers/mock-api';

const server = setupServer();

const mockRouterPush = vi.fn();
const mockToken = { value: 'test-token-123' };

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useSearchParams: () => ({ get: (key: string) => key === 'token' ? mockToken.value : null }),
  usePathname: () => '/invite',
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

beforeAll(() => {
  (window as Window & { __API_BASE_URL__?: string }).__API_BASE_URL__ = 'http://localhost/api';
  server.listen({ onUnhandledRequest: 'warn' });
});

afterEach(() => {
  server.resetHandlers();
  mockRouterPush.mockClear();
});

afterAll(() => server.close());

describe('InviteAcceptanceForm', () => {
  it('挂载时自动拉取邀请预览信息', async () => {
    server.use(invitePreviewValid);
    render(<InviteAcceptanceForm />);

    // 初始加载状态
    expect(screen.getByText(/正在加载邀请信息/)).toBeInTheDocument();

    // 加载完成后显示预览
    await waitFor(() => {
      expect(screen.getByText(/测试工作区/)).toBeInTheDocument();
    });
    expect(screen.getByText(/张管理员/)).toBeInTheDocument();
  });

  it('已使用邀请（already_used=true）显示失效页', async () => {
    server.use(invitePreviewAlreadyUsed);
    render(<InviteAcceptanceForm />);

    await waitFor(() => {
      // 失效页包含 h2 标题
      expect(screen.getByRole('heading', { name: /邀请链接已失效/ })).toBeInTheDocument();
    });
  });

  it('404 邀请不存在显示失效页', async () => {
    server.use(invitePreviewNotFound);
    render(<InviteAcceptanceForm />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /邀请链接已失效/ })).toBeInTheDocument();
    });
  });

  it('成功提交注册后跳转 /dashboard', async () => {
    server.use(invitePreviewValid, inviteAcceptSuccess);
    const user = userEvent.setup();
    render(<InviteAcceptanceForm />);

    // 等待预览加载
    await waitFor(() => {
      expect(screen.getByLabelText(/显示名称/)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/显示名称/), '张三');
    await user.type(screen.getByLabelText(/设置密码/), 'securePass1');
    await user.click(screen.getByRole('button', { name: /加入工作区/ }));

    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith('/dashboard');
    });
  });

  it('弱密码（缺少数字）显示验证错误', async () => {
    server.use(invitePreviewValid);
    const user = userEvent.setup();
    render(<InviteAcceptanceForm />);

    await waitFor(() => {
      expect(screen.getByLabelText(/设置密码/)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/设置密码/), 'weakpassword');
    await user.tab();

    await waitFor(() => {
      expect(screen.getByText(/密码须包含数字/)).toBeInTheDocument();
    });
  });

  it('缺少 token 时显示失效提示', async () => {
    mockToken.value = '';
    render(<InviteAcceptanceForm />);

    await waitFor(() => {
      expect(screen.getByText(/邀请链接已失效/)).toBeInTheDocument();
    });

    // 恢复
    mockToken.value = 'test-token-123';
  });
});
