/**
 * nginx 公网最小暴露面 E2E 验收测试（NET-02）。
 *
 * 验证 nginx 80 端口（公网入口）仅放行 3 条路径，其余全部 403：
 * - /hitl/page/*
 * - /hitl/action/*
 * - /api/im/webhook/*
 *
 * 前置条件：
 *   docker-compose up -d nginx api web
 *   等待约 5s 让服务就绪
 *
 * 运行方式：
 *   cd e2e && npx playwright test nginx_path_scan.spec.ts --reporter=list
 *
 * 环境变量：
 *   PUBLIC_BASE_URL - 公网入口 URL（默认 http://localhost:80）
 *
 * Plan 06 联动：本 spec 会被纳入整体 E2E 测试矩阵，本 Plan 仅保证 spec 就位与单独通过。
 */

import { test, expect } from '@playwright/test';
import {
  EXPECTED_FORBIDDEN_PATHS,
  EXPECTED_PROXIED_PATHS,
} from './helpers/path_scan';

/** 公网 80 端口的 baseURL（独立于 playwright.config.ts 的 baseURL） */
const PUBLIC_URL: string = process.env.PUBLIC_BASE_URL ?? 'http://localhost:80';

/**
 * 工具函数：发起 GET 请求并返回状态码。
 * 使用 Playwright APIRequestContext 而非浏览器导航，速度更快。
 */
async function getStatus(request: import('@playwright/test').APIRequestContext, path: string): Promise<number> {
  const response = await request.get(`${PUBLIC_URL}${path}`, {
    failOnStatusCode: false,
    // 超时配置（nginx 直接 403 极快，后端路由可能稍慢）
    timeout: 8_000,
  });
  return response.status();
}

// ============================================================
// 测试套件：公网最小暴露面（NET-02）
// ============================================================

test.describe('公网最小暴露面（NET-02）', () => {

  // ----------------------------------------------------------
  // 应被拦截的路径：nginx 直接返回 403
  // ----------------------------------------------------------
  test.describe('禁止路径 — nginx 直接 403', () => {
    for (const path of EXPECTED_FORBIDDEN_PATHS) {
      test(`forbidden: ${path}`, async ({ request }) => {
        const status = await getStatus(request, path);
        expect(
          status,
          `路径 ${path} 应被 nginx 拦截（返回 403），实际返回 ${status}`,
        ).toBe(403);
      });
    }
  });

  // ----------------------------------------------------------
  // 应放行的路径：nginx 转给后端，后端决定最终响应
  // ----------------------------------------------------------
  test.describe('放行路径 — nginx 转给后端（非 403）', () => {
    for (const path of EXPECTED_PROXIED_PATHS) {
      test(`proxied: ${path}`, async ({ request }) => {
        const status = await getStatus(request, path);
        expect(
          status,
          `路径 ${path} 应被 nginx 转发给后端（返回非 403），实际返回 ${status}`,
        ).not.toBe(403);
      });
    }
  });

  // ----------------------------------------------------------
  // server_tokens off 验证：响应头不包含 nginx 版本号
  // ----------------------------------------------------------
  test('server_tokens off — nginx 不暴露版本号', async ({ request }) => {
    const response = await request.get(`${PUBLIC_URL}/`, {
      failOnStatusCode: false,
      timeout: 8_000,
    });

    const serverHeader: string = response.headers()['server'] ?? '';

    expect(
      serverHeader,
      `响应头 Server 不应包含 nginx 版本号（server_tokens off），实际：「${serverHeader}」`,
    ).not.toMatch(/nginx\/\d/);
  });

  // ----------------------------------------------------------
  // 综合验证：403 响应无泄漏信息
  // ----------------------------------------------------------
  test('403 响应体不应包含服务器技术细节', async ({ request }) => {
    const response = await request.get(`${PUBLIC_URL}/admin`, {
      failOnStatusCode: false,
      timeout: 8_000,
    });

    expect(response.status()).toBe(403);

    const body: string = await response.text();

    // 响应体不应泄漏内部路径或服务版本
    expect(
      body,
      '403 响应体不应包含内部路径信息（如 /app/ 或 /backend/）',
    ).not.toMatch(/\/backend\/|\/app\/|django|flask|tornado/i);
  });
});
