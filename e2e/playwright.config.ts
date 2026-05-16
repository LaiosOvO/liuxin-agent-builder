import { defineConfig, devices } from '@playwright/test';

/**
 * Plan 01-01 E2E 测试基础设施配置。
 *
 * 约定 (CLAUDE.md 2.2)：
 * - baseURL 走 PUBLIC_BASE_URL env, 默认 http://localhost:8080 (nginx 内网入口)
 * - 浏览器：chromium 主跑 + webkit 辅助 (Safari 兼容)
 * - 重试: CI 2 次, 本地 0 次
 * - trace: 首次失败保留 (调试)
 * - 截图: 仅失败时保留
 *
 * Phase 3 起补充：
 * - Microsoft Defender / Outlook Safe Links bot UA 模拟项目 (anti-Pitfall 3)
 * - 邮件 token GET 不消费 jti 的回归用例
 */
const baseURL = process.env.PUBLIC_BASE_URL ?? 'http://localhost:8080';

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // webkit 与 firefox 在 Phase 4 启用 (Safe Links UA 模拟更全)
    // { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
  // webServer 配置: 若 docker-compose 没起, 由 Playwright 自动起
  // 注释掉, 让用户显式 docker-compose up 来准备环境
  // webServer: {
  //   command: 'docker compose up -d',
  //   url: baseURL,
  //   reuseExistingServer: !process.env.CI,
  //   timeout: 120_000,
  // },
});
