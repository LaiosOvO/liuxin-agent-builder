/**
 * WorkspaceSwitcher 组件测试
 */

import { describe, it, expect, beforeAll, afterAll, afterEach, beforeEach, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkspaceSwitcher } from '@/components/agent-builder/workspace-switcher';
import { useUserStore } from '@/lib/stores/user-store';
import { workspaceSwitchSuccess, meSuccess } from './_helpers/mock-api';
import type { WorkspaceMembership, Workspace } from '@/lib/types/api';

const server = setupServer();

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

const mockReload = vi.fn();
const ws1: Workspace = { id: 'ws-1', name: '工作区 A', slug: 'ws-a' };
const ws2: Workspace = { id: 'ws-2', name: '工作区 B', slug: 'ws-b' };

const singleWorkspace: WorkspaceMembership[] = [
  { workspace: ws1, role: 'admin' },
];

const multipleWorkspaces: WorkspaceMembership[] = [
  { workspace: ws1, role: 'admin' },
  { workspace: ws2, role: 'editor' },
];

beforeAll(() => {
  (window as Window & { __API_BASE_URL__?: string }).__API_BASE_URL__ = 'http://localhost/api';
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { reload: mockReload, href: 'http://localhost/dashboard' },
  });
  server.listen({ onUnhandledRequest: 'warn' });
});

beforeEach(() => {
  useUserStore.setState({
    user: {
      id: 'u1',
      email: 'test@test.com',
      display_name: '测试',
      department: null,
      is_super_admin: false,
      status: 'active',
    },
    workspaces: [],
    currentWorkspace: null,
    role: null,
  });
});

afterEach(() => {
  server.resetHandlers();
  mockReload.mockClear();
});

afterAll(() => server.close());

describe('WorkspaceSwitcher', () => {
  it('单个 workspace 时按钮 disabled', () => {
    useUserStore.setState({
      workspaces: singleWorkspace,
      currentWorkspace: ws1,
    });

    render(<WorkspaceSwitcher />);

    const button = screen.getByRole('button', { name: /切换工作区/ });
    expect(button).toBeDisabled();
  });

  it('单个 workspace 时不显示 ChevronDown 图标', () => {
    useUserStore.setState({
      workspaces: singleWorkspace,
      currentWorkspace: ws1,
    });

    render(<WorkspaceSwitcher />);
    expect(screen.getByText('工作区 A')).toBeInTheDocument();
  });

  it('多个 workspace 时按钮可点击', () => {
    useUserStore.setState({
      workspaces: multipleWorkspaces,
      currentWorkspace: ws1,
    });

    render(<WorkspaceSwitcher />);

    const button = screen.getByRole('button', { name: /切换工作区/ });
    expect(button).not.toBeDisabled();
  });

  it('多个 workspace 时点击下拉显示选项', async () => {
    useUserStore.setState({
      workspaces: multipleWorkspaces,
      currentWorkspace: ws1,
    });

    const user = userEvent.setup();
    render(<WorkspaceSwitcher />);

    await user.click(screen.getByRole('button', { name: /切换工作区/ }));

    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '工作区 A' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '工作区 B' })).toBeInTheDocument();
  });

  it('点击当前 workspace 时不触发切换', async () => {
    server.use(workspaceSwitchSuccess, meSuccess);
    useUserStore.setState({
      workspaces: multipleWorkspaces,
      currentWorkspace: ws1,
    });

    const user = userEvent.setup();
    render(<WorkspaceSwitcher />);

    await user.click(screen.getByRole('button', { name: /切换工作区/ }));
    await user.click(screen.getByRole('option', { name: '工作区 A' }));

    // 切换当前 workspace 不应 reload
    await waitFor(() => {
      expect(mockReload).not.toHaveBeenCalled();
    });
  });

  it('切换到其他 workspace 时调用 API 并 reload', async () => {
    server.use(workspaceSwitchSuccess, meSuccess);
    useUserStore.setState({
      workspaces: multipleWorkspaces,
      currentWorkspace: ws1,
    });

    const user = userEvent.setup();
    render(<WorkspaceSwitcher />);

    await user.click(screen.getByRole('button', { name: /切换工作区/ }));
    await user.click(screen.getByRole('option', { name: '工作区 B' }));

    await waitFor(() => {
      expect(mockReload).toHaveBeenCalled();
    });
  });
});
