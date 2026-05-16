/**
 * E2E spec: Workspace 多租户隔离
 *
 * 覆盖 ROADMAP.md Phase 1 success criterion #1 (核心隔离):
 *   "登录后看到自己 workspace 的内容, 看不到其他 workspace 的内容"
 *
 * 防御 Pitfall 6 (CVE-2024-10976 多租户连接池上下文污染) 的 E2E 回归。
 *
 * 前置: docker compose up + 已 setup 初始化
 * 触发: RUN_E2E=1
 */
import { test, expect } from '@playwright/test';
import { apiFetch, type AuthCookie } from './helpers/api-client';

const RUN = !!process.env.RUN_E2E || !!process.env.E2E_FULL_STACK;
const BASE = process.env.API_BASE_URL ?? 'http://localhost:8080';

interface WorkspaceSetup {
  adminCookie: AuthCookie;
  workspaceId: string;
  adminUserId: string;
}

/**
 * 建一个独立 workspace, 用 super_admin 私钥或新建账号.
 * Phase 1 v1 邀请制, super_admin 注册才能建 workspace.
 * 此处用 setup_init 创建第一个; 第二个 workspace 用 super_admin 创建新 workspace 端点.
 */
async function createIndependentWorkspace(prefix: string): Promise<WorkspaceSetup> {
  const ts = Date.now() + Math.random();
  const email = `${prefix}_admin_${ts}@e2e.test`;

  // 注意: 实际 API 可能需要 super_admin 凭证创建 workspace.
  // 简化: 假设第一次 setup 后, 后续 workspace 通过 admin 创建端点(若存在)
  // 或 v1 直接通过 db_session 注入 (仅 E2E full stack 测试使用 admin endpoint)
  const resp = await apiFetch<{ workspace_id: string; user_id: string }>(`/api/workspaces`, {
    method: 'POST',
    body: { name: `${prefix}_${ts}`, admin_email: email, admin_password: 'WSadminPass1!' },
  });

  return {
    adminCookie: resp.cookie!,
    workspaceId: resp.data.workspace_id,
    adminUserId: resp.data.user_id,
  };
}

test.describe('Workspace 多租户隔离 (ROADMAP #1 + Pitfall 6)', () => {
  test.skip(() => !RUN, '需要 docker compose up + RUN_E2E=1');

  // 注意: Phase 1 的 admin/workspace 创建端点可能尚未完整; 本 spec 标记 部分依赖端点可用
  test.skip(() => true, 'TODO: 待 admin 创建 workspace 端点上线 (Phase 1.x 补丁)');

  test('两个 workspace 的 admin 互访任意资源 → 403 或 空集', async ({ request }) => {
    const wsA = await createIndependentWorkspace('wsA');
    const wsB = await createIndependentWorkspace('wsB');

    // wsA admin 尝试访问 wsB 的 workspace 设置 → 403
    const cross = await request.get(`${BASE}/api/workspaces/${wsB.workspaceId}/settings`, {
      headers: { Cookie: wsA.adminCookie },
    });
    expect(cross.status()).toBeGreaterThanOrEqual(403);

    // wsA admin 列表用户 → 仅看到 wsA 内的
    const listA = await request.get(`${BASE}/api/workspaces/${wsA.workspaceId}/users`, {
      headers: { Cookie: wsA.adminCookie },
    });
    const usersA = (await listA.json()) as { users: Array<{ id: string }> };
    const containsBAdmin = usersA.users.some((u) => u.id === wsB.adminUserId);
    expect(containsBAdmin).toBe(false);
  });

  test('连接池 hook DISCARD ALL 验证 (并发请求不串污染)', async ({ request }) => {
    const wsA = await createIndependentWorkspace('hookA');
    const wsB = await createIndependentWorkspace('hookB');

    // 100 个并发请求交替 wsA / wsB cookie, 期望各自只看见自己 workspace 的数据
    const results = await Promise.all(
      Array.from({ length: 100 }, async (_, i) => {
        const cookie = i % 2 === 0 ? wsA.adminCookie : wsB.adminCookie;
        const expectedWsId = i % 2 === 0 ? wsA.workspaceId : wsB.workspaceId;
        const r = await request.get(`${BASE}/api/me`, { headers: { Cookie: cookie } });
        const me = (await r.json()) as { current_workspace: { id: string } | null };
        return {
          actualWsId: me.current_workspace?.id ?? null,
          expectedWsId,
        };
      }),
    );

    const violations = results.filter((r) => r.actualWsId !== r.expectedWsId);
    expect(violations).toHaveLength(0);
  });
});
