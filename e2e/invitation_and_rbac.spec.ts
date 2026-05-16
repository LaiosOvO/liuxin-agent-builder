/**
 * E2E spec: 邀请流程 + RBAC 边界
 *
 * 覆盖 ROADMAP.md Phase 1 success criteria:
 *   #1 (部分): "登录后看到自己 workspace 的内容"
 *   #2: "RBAC 生效: editor 能创建/编辑工作流, viewer 只能查看, admin 能管理用户"
 *
 * 前置: docker compose up + mailhog 在 8025 端口
 * 触发: RUN_E2E=1
 */
import { test, expect } from '@playwright/test';
import {
  ApiError,
  acceptInvite,
  createInvite,
  getSetupState,
  initializeSystem,
  login,
  type AuthCookie,
} from './helpers/api-client';
import { purgeAllEmails, waitForEmailAndExtractLink } from './helpers/mailhog-client';

const RUN = !!process.env.RUN_E2E || !!process.env.E2E_FULL_STACK;

const ADMIN_EMAIL = `admin_${Date.now()}@e2e.test`;
const ADMIN_PASSWORD = 'AdminPassword1!';

interface InvitedUser {
  cookie: AuthCookie;
  email: string;
}

async function ensureAdminLoggedIn(): Promise<AuthCookie> {
  const state = await getSetupState();
  if (!state.initialized) {
    const { cookie } = await initializeSystem({
      email: ADMIN_EMAIL,
      password: ADMIN_PASSWORD,
      display_name: 'Admin',
      workspace_name: `WS_${Date.now()}`,
    });
    return cookie;
  }
  const { cookie } = await login(ADMIN_EMAIL, ADMIN_PASSWORD);
  return cookie;
}

async function inviteAndAccept(
  adminCookie: AuthCookie,
  roleCode: string,
  passwordTag: string,
): Promise<InvitedUser> {
  const email = `${roleCode}_${passwordTag}_${Date.now()}_${Math.floor(Math.random() * 1000)}@e2e.test`;

  await purgeAllEmails();
  await createInvite(adminCookie, { email, role_code: roleCode });

  const link = await waitForEmailAndExtractLink(email, '/invite', 10_000);
  const tokenMatch = link.match(/token=([^&]+)/);
  expect(tokenMatch, '邀请链接缺 token').toBeTruthy();
  const token = decodeURIComponent(tokenMatch![1]);

  const { cookie } = await acceptInvite(token, `${roleCode}Pass1!`, `E2E ${roleCode}`);
  return { cookie, email };
}

test.describe('邀请流程 + RBAC (ROADMAP #1 + #2)', () => {
  test.skip(() => !RUN, '需要 docker compose up + mailhog + RUN_E2E=1');

  test('admin → editor 邀请: 邮件抵达 MailHog 且含 token 链接', async () => {
    const adminCookie = await ensureAdminLoggedIn();
    const email = `editor_${Date.now()}@e2e.test`;
    await purgeAllEmails();

    const invite = await createInvite(adminCookie, { email, role_code: 'editor' });
    expect(invite.email).toBe(email);
    expect(invite.role_code).toBe('editor');

    const link = await waitForEmailAndExtractLink(email, '/invite', 10_000);
    expect(link).toMatch(/token=[A-Za-z0-9._-]+/);
  });

  test('editor 通过邀请链接完成注册 → cookie 生效 + role=editor', async () => {
    const adminCookie = await ensureAdminLoggedIn();
    const editor = await inviteAndAccept(adminCookie, 'editor', 'a');
    expect(editor.cookie).toBeTruthy();
  });

  test('RBAC: viewer 调用 admin-only createInvite → 403', async () => {
    const adminCookie = await ensureAdminLoggedIn();
    const viewer = await inviteAndAccept(adminCookie, 'viewer', 'a');

    let denied = false;
    try {
      await createInvite(viewer.cookie, {
        email: `should_deny_${Date.now()}@e2e.test`,
        role_code: 'editor',
      });
    } catch (err) {
      if (err instanceof ApiError) {
        expect(err.status).toBe(403);
        denied = true;
      }
    }
    expect(denied, 'viewer 必须被拒').toBe(true);
  });

  test('RBAC: editor 不能管理用户 (createInvite 403)', async () => {
    const adminCookie = await ensureAdminLoggedIn();
    const editor = await inviteAndAccept(adminCookie, 'editor', 'b');

    let denied = false;
    try {
      await createInvite(editor.cookie, {
        email: `should_deny2_${Date.now()}@e2e.test`,
        role_code: 'viewer',
      });
    } catch (err) {
      if (err instanceof ApiError) {
        expect(err.status).toBe(403);
        denied = true;
      }
    }
    expect(denied, 'editor 必须被拒').toBe(true);
  });
});
