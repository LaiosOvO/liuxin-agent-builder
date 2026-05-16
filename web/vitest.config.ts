import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

/**
 * Vitest 配置 — Plan 01-05 前端组件测试。
 *
 * 配置说明：
 * - jsdom 环境支持 DOM + React 组件测试
 * - setupFiles 引入 jest-dom matchers
 * - alias 对齐 Next.js 的 @/* → src/* 路径
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.{spec,test}.{ts,tsx}'],
    exclude: ['node_modules/**', 'dist/**', '.next/**'],
    coverage: {
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.spec.{ts,tsx}'],
    },
  },
});
