/**
 * E2E spec: Setup 首启流程
 *
 * 覆盖 ROADMAP.md Phase 1 success criterion #1（部分）:
 *   "管理员能用邮箱密码注册并登录, 登录后看到自己 workspace 的内容"
 *
 * 前置: docker compose up -d (api/web/postgres/redis/mailhog/nginx 全起)
 * 触发: RUN_E2E=1 + PUBLIC_BASE_URL=http://localhost:8080
 */
import { test, expect } from '@playwright/test';
import { getSetupState, initializeSystem, getMe, type SetupInitRequest } from './helpers/api-client';

const RUN = !!process.env.RUN_E2E || !!process.env.E2E_FULL_STACK;

test.describe('Setup 首启流程 (ROADMAP #1 part 1)', () => {
  test.skip(() => !RUN, '需要 docker compose up + RUN_E2E=1');

  test('未初始化时访问首页跳到 /setup', async ({ page }) => {
    const state = await getSetupState();
    if (state.initialized) {
      test.skip(true, '已初始化, 此测试需要全新 DB (用 docker-compose.test.yml)');
    }

    await page.goto('/');
    await expect(page).toHaveURL(/\/setup/);
    await expect(page.locator('body')).toContainText(/agent-builder/i);
  });

  test('API: 提交 setup 初始化后创建 super_admin + workspace', async () => {
    const state = await getSetupState();
    if (state.initialized) {
      test.skip(true, '已初始化');
    }

    const uniqueId = Date.now();
    const payload: SetupInitRequest = {
      email: `admin_${uniqueId}@e2e.test`,
      password: 'AdminPassword1!',
      display_name: 'E2E Super Admin',
      workspace_name: `测试工作区_${uniqueId}`,
    };

    const { cookie } = await initializeSystem(payload);
    expect(cookie).toBeTruthy();

    const me = await getMe(cookie);
    expect(me.user.email).toBe(payload.email);
    expect(me.workspaces.length).toBe(1);
    expect(me.workspaces[0].role_code).toBe('admin');
  });

  test('UI: 提交 setup 表单后跳到 dashboard', async ({ page }) => {
    const state = await getSetupState();
    if (state.initialized) {
      test.skip(true, '已初始化, 此 UI 测试需要全新 DB');
    }

    const uniqueId = Date.now();
    await page.goto('/setup');
    await page.fill('input[name="email"]', `ui_admin_${uniqueId}@e2e.test`);
    await page.fill('input[name="password"]', 'UiAdminPass1!');
    await page.fill('input[name="display_name"]', 'UI Setup Admin');
    await page.fill('input[name="workspace_name"]', `UI测试工作区_${uniqueId}`);
    await page.click('button[type="submit"]');

    await page.waitForURL(/\/dashboard|\/$/, { timeout: 10_000 });
  });

  test('二次访问 /setup 应被隐藏 (中间件 404 或重定向)', async ({ page }) => {
    const state = await getSetupState();
    if (!state.initialized) {
      test.skip(true, '未初始化, 此测试需要先完成 setup');
    }
    const response = await page.goto('/setup');
    expect([404, 200, 302, 307]).toContain(response?.status() ?? 0);
    const formCount = await page.locator('input[name="workspace_name"]').count();
    expect(formCount).toBe(0);
  });
});
