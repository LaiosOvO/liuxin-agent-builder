/**
 * Plan 01-01 Playwright 冒烟测试。
 *
 * 验证 E2E 测试基础设施工作 + 落地页含 agent-builder 字样。
 * 完整 Phase 1 E2E 用例在 Plan 01-06 实现（含 setup 向导 / 邀请 / RBAC 双 workspace 互访）。
 *
 * 前置: docker compose up -d (api/web/nginx 起来)
 *      或 RUN_E2E=1 + docker-compose up 后跑
 */
import { test, expect } from '@playwright/test';

test.describe('E2E smoke (基础设施)', () => {
  // 本地跑需先 docker-compose up；CI 通过 webServer 自动起
  test.skip(
    () => !process.env.PUBLIC_BASE_URL && !process.env.RUN_E2E && !process.env.CI,
    '设 RUN_E2E=1 + docker compose up 后跑'
  );

  test('打开首页能拿到 200 + 看到 agent-builder 字样', async ({ page, baseURL }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBeLessThan(400);

    const title = await page.title();
    const body = (await page.locator('body').textContent()) ?? '';

    // 接受 title 或 body 任意位置出现 agent-builder (大小写不敏感)
    const hasBrand = /agent-builder/i.test(title) || /agent-builder/i.test(body);
    expect(hasBrand, `期望在 ${baseURL} 看到 agent-builder 字样\nTitle: ${title}\nBody (前 200): ${body.slice(0, 200)}`).toBe(true);
  });

  test('nginx 应阻塞非允许路径 (公网入口安全测试占位)', async ({ request, baseURL }) => {
    // 注意: 本测试假设访问的是 PUBLIC server_block (Plan 03 实现)
    // Phase 1 阶段 nginx 单 server 可能不区分, 本测试可能 fallthrough
    test.skip(true, 'Plan 03 配置 nginx public/internal 分离后启用');
    const r = await request.get('/admin/secret-route', { failOnStatusCode: false });
    expect(r.status()).toBe(403);
  });
});
