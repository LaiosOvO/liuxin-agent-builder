/**
 * Vitest 全局测试设置
 * - 引入 jest-dom matchers（toBeInTheDocument 等）
 * - 在每个测试后清理 DOM
 */

import '@testing-library/jest-dom';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// 每个测试后自动清理 DOM，防止测试间互相污染
afterEach(() => {
  cleanup();
});
