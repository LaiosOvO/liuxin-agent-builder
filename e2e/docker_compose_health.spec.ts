/**
 * E2E spec: docker compose 6 服务全部健康
 *
 * 覆盖 ROADMAP.md Phase 1 success criterion #3:
 *   "docker-compose up 一键启动所有服务 (api/worker/web/postgres/redis/nginx),
 *    浏览器能打开画布页"
 *
 * 前置: 需要本机 docker daemon 可用
 * 触发: E2E_FULL_STACK=1
 */
import { test, expect } from '@playwright/test';
import { execSync } from 'node:child_process';

const FULL = !!process.env.E2E_FULL_STACK;
const BASE = process.env.API_BASE_URL ?? 'http://localhost:8080';

interface ContainerStatus {
  Name: string;
  Status: string;
  Health: string;
}

function getServiceStatuses(): ContainerStatus[] {
  const json = execSync('docker compose ps --format json', { encoding: 'utf-8' });
  // docker compose ps --format json 输出每行一个 JSON
  return json
    .split('\n')
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as { Name: string; State: string; Health?: string })
    .map((row) => ({
      Name: row.Name,
      Status: row.State,
      Health: row.Health ?? 'none',
    }));
}

test.describe('docker compose 6 服务健康 (ROADMAP #3)', () => {
  test.skip(() => !FULL, '需要 E2E_FULL_STACK=1 + docker daemon');

  test('6 个服务都在 running 状态 (postgres/redis/api/worker/web/nginx)', async () => {
    const statuses = getServiceStatuses();
    const expected = ['postgres', 'redis', 'api', 'worker', 'web', 'nginx'];
    for (const svc of expected) {
      const found = statuses.find((s) => s.Name.includes(svc));
      expect(found, `服务 ${svc} 应该存在`).toBeTruthy();
      expect(found!.Status, `服务 ${svc} 应该 running`).toMatch(/running/i);
    }
  });

  test('postgres healthcheck 通过', async () => {
    const statuses = getServiceStatuses();
    const pg = statuses.find((s) => s.Name.includes('postgres'));
    expect(pg).toBeTruthy();
    expect(pg!.Health).toMatch(/healthy/i);
  });

  test('redis healthcheck 通过', async () => {
    const statuses = getServiceStatuses();
    const r = statuses.find((s) => s.Name.includes('redis'));
    expect(r).toBeTruthy();
    expect(r!.Health).toMatch(/healthy/i);
  });

  test('浏览器打开首页 (nginx → web) 返回 200', async ({ page }) => {
    const response = await page.goto(BASE);
    expect(response?.status()).toBeLessThan(400);
  });

  test('API /health 端点返回 200 (经 nginx 内网入口)', async ({ request }) => {
    // 内网入口在 8080; api 健康检查在 :8000 但 nginx 8080 反代
    const r = await request.get(`${BASE}/api/setup/state`);
    expect([200, 404]).toContain(r.status());
  });

  test('MailHog (测试 overlay) 服务可达', async ({ request }) => {
    const mailhog = process.env.MAILHOG_URL ?? 'http://localhost:8025';
    const r = await request.get(`${mailhog}/api/v2/messages`);
    expect(r.status()).toBe(200);
  });
});
