/**
 * LoginForm 组件测试
 */

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginForm } from '@/components/agent-builder/login-form';
import {
  loginSuccess,
  loginUnauthorized,
  loginTooManyRequests,
  loginForbiddenPending,
} from './_helpers/mock-api';

const server = setupServer();

const mockRouterPush = vi.fn();
const mockGet = vi.fn((key: string) => key === 'verified' ? null : null);

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useSearchParams: () => ({ get: mockGet }),
  usePathname: () => '/login',
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
  mockGet.mockImplementation((_key: string) => null);
});

afterAll(() => server.close());

describe('LoginForm', () => {
  it('渲染邮箱和密码字段', () => {
    render(<LoginForm />);
    expect(screen.getByLabelText(/邮箱/)).toBeInTheDocument();
    expect(screen.getByLabelText(/密码/)).toBeInTheDocument();
  });

  it('没有"注册账号"链接（公开注册关闭）', () => {
    render(<LoginForm />);
    expect(screen.queryByText(/注册账号/)).not.toBeInTheDocument();
  });

  it('显示"忘记密码"联系管理员提示', () => {
    render(<LoginForm />);
    expect(screen.getByText(/忘记密码.*管理员/)).toBeInTheDocument();
  });

  it('提交正确凭据后跳转 /dashboard', async () => {
    server.use(loginSuccess);
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/邮箱/), 'test@example.com');
    await user.type(screen.getByLabelText(/密码/), 'password123');
    await user.click(screen.getByRole('button', { name: /登录/ }));

    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith('/dashboard');
    });
  });

  it('401 显示"邮箱或密码错误"', async () => {
    server.use(loginUnauthorized);
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/邮箱/), 'test@example.com');
    await user.type(screen.getByLabelText(/密码/), 'wrongpassword');
    await user.click(screen.getByRole('button', { name: /登录/ }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/邮箱或密码错误/);
    });
  });

  it('403 + pending_verification 显示邮件验证提示', async () => {
    server.use(loginForbiddenPending);
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/邮箱/), 'test@example.com');
    await user.type(screen.getByLabelText(/密码/), 'password123');
    await user.click(screen.getByRole('button', { name: /登录/ }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/邮箱内的验证链接/);
    });
  });

  it('429 显示"操作过于频繁"限频提示', async () => {
    server.use(loginTooManyRequests);
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/邮箱/), 'test@example.com');
    await user.type(screen.getByLabelText(/密码/), 'password123');
    await user.click(screen.getByRole('button', { name: /登录/ }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/操作过于频繁/);
    });
  });

  it('?verified=1 query 时显示验证成功提示', async () => {
    mockGet.mockImplementation((key: string) => key === 'verified' ? '1' : null);
    const { toast } = await import('sonner');
    const toastSpy = vi.spyOn(toast, 'success');

    render(<LoginForm />);

    // useEffect 会在 mount 后调用 toast.success
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('邮箱验证成功'));
    });
  });
});
