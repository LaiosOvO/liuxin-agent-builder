/**
 * Plan 01-01 vitest 冒烟测试。
 *
 * 仅验证测试基础设施工作正常 + agent-builder 品牌名生效。
 * 真正的组件 / 页面测试在后续 plan 实现。
 */
import { describe, expect, it } from 'vitest';

describe('vitest smoke', () => {
  it('基础断言可跑', () => {
    expect(1 + 1).toBe(2);
  });

  it('jsdom 环境就绪（有 document）', () => {
    expect(typeof document).toBe('object');
    expect(document.body).toBeTruthy();
  });

  it('package.json name 应该是 agent-builder-web（品牌重命名生效）', async () => {
    // 通过相对路径导入，避开 import-from-package-self 限制
    const pkg = (await import('../package.json')) as { name?: string; default?: { name?: string } };
    const name = pkg.name ?? pkg.default?.name;
    expect(name).toBe('agent-builder-web');
  });
});
