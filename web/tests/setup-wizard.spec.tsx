/**
 * SetupWizard 组件测试
 */

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SetupWizard } from '@/components/agent-builder/setup-wizard';
import {
  setupInitializeSuccess,
  setupInitializeConflict,
} from './_helpers/mock-api';

// MSW server
const server = setupServer();

// Mock next/navigation
const mockRouterPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/',
}));

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

// 设置 window.__API_BASE_URL__
beforeAll(() => {
  (window as Window & { __API_BASE_URL__?: string }).__API_BASE_URL__ = 'http://localhost/api';
  server.listen({ onUnhandledRequest: 'warn' });
});

afterEach(() => {
  server.resetHandlers();
  mockRouterPush.mockClear();
});

afterAll(() => server.close());

describe('SetupWizard', () => {
  it('渲染 4 个字段（邮箱/密码/显示名/Workspace名）', () => {
    render(<SetupWizard />);

    expect(screen.getByLabelText(/管理员邮箱/)).toBeInTheDocument();
    expect(screen.getByLabelText(/密码/)).toBeInTheDocument();
    expect(screen.getByLabelText(/显示名称/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Workspace 名称/)).toBeInTheDocument();
  });

  it('显示欢迎横幅文案', () => {
    render(<SetupWizard />);
    expect(screen.getByText(/欢迎首次启动 agent-builder/)).toBeInTheDocument();
  });

  it('弱密码（少于 8 字符）显示中文错误', async () => {
    const user = userEvent.setup();
    render(<SetupWizard />);

    await user.type(screen.getByLabelText(/密码/), 'abc');
    await user.tab(); // 触发 onBlur 验证

    await waitFor(() => {
      expect(screen.getByText(/密码至少 8 位/)).toBeInTheDocument();
    });
  });

  it('密码缺少数字显示中文错误', async () => {
    const user = userEvent.setup();
    render(<SetupWizard />);

    await user.type(screen.getByLabelText(/密码/), 'abcdefgh');
    await user.tab();

    await waitFor(() => {
      expect(screen.getByText(/密码须包含数字/)).toBeInTheDocument();
    });
  });

  it('邮箱格式错误显示提示', async () => {
    const user = userEvent.setup();
    render(<SetupWizard />);

    await user.type(screen.getByLabelText(/管理员邮箱/), 'not-an-email');
    await user.tab();

    await waitFor(() => {
      expect(screen.getByText(/请输入有效的邮箱地址/)).toBeInTheDocument();
    });
  });

  it('成功提交后跳转 /dashboard', async () => {
    server.use(setupInitializeSuccess);
    const user = userEvent.setup();
    render(<SetupWizard />);

    await user.type(screen.getByLabelText(/管理员邮箱/), 'admin@test.com');
    await user.type(screen.getByLabelText(/密码/), 'password123');
    await user.type(screen.getByLabelText(/显示名称/), '管理员');
    await user.type(screen.getByLabelText(/Workspace 名称/), '我的团队');

    await user.click(screen.getByRole('button', { name: /创建并开始使用/ }));

    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith('/dashboard');
    });
  });

  it('服务端 409（已初始化）显示错误提示', async () => {
    server.use(setupInitializeConflict);
    const user = userEvent.setup();
    render(<SetupWizard />);

    await user.type(screen.getByLabelText(/管理员邮箱/), 'admin@test.com');
    await user.type(screen.getByLabelText(/密码/), 'password123');
    await user.type(screen.getByLabelText(/显示名称/), '管理员');
    await user.type(screen.getByLabelText(/Workspace 名称/), '我的团队');

    await user.click(screen.getByRole('button', { name: /创建并开始使用/ }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByRole('alert')).toHaveTextContent(/系统已经初始化/);
    });
  });
});
