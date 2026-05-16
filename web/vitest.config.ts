import { defineConfig } from 'vitest/config';

/**
 * Vitest 配置 — Plan 01-01 测试基础设施。
 *
 * Phase 1 阶段：基础 jsdom 环境 + 全局 expect/describe/it。
 * Phase 2+：引入 @testing-library/react + setupFiles 做组件测试。
 */
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.{spec,test}.{ts,tsx}'],
    exclude: ['node_modules/**', 'dist/**', '.next/**'],
    coverage: {
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.spec.{ts,tsx}'],
    },
  },
});
