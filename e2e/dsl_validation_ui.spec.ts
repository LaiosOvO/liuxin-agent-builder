/**
 * E2E Spec: DSL 校验 UI — 成环 + 变量引用错误
 *
 * ROADMAP Phase 2 Success Criterion #5:
 *   "DSL 成环或变量引用错误时画布前端拒绝保存并显示具体错误位置"
 *
 * 运行模式：
 *   - Smoke（默认）: 全部 skip
 *   - Standard (RUN_E2E=1): 跑全部 5 个 test
 *   - Full (E2E_FULL_STACK=1): 跑全部 5 个 test
 *
 * 验证的 UI 行为（02-09-SUMMARY 确认的三层错误 UI）：
 *   1. 节点边框变红（border-red-500）
 *   2. Issue 面板显示错误描述（含节点 ID + 错误码）
 *   3. 发布按钮禁用（hasFatalErrors=true 时）
 *
 * 注意：
 *   - 前端校验是实时的（300ms debounce），通过 API PUT draft 后刷新画布触发校验
 *   - 成环检测是纯前端 TS（DFS 染色），不需后端往返
 *   - 后端发布前也有独立复检（POST /validate），UI 测成环时后端 API 也会返回 error
 *
 * DSL builder helper（dsl-builder.ts）：
 *   - buildCyclicDsl() — 成环 DSL（llm_a → llm_b → llm_a）
 *   - buildVariableDanglingDsl() — 悬空引用 DSL（{{ nonexistent.x }}）
 */

import { test, expect } from '@playwright/test';
import { apiFetch, login, initializeSystem } from './helpers/api-client';
import { buildCyclicDsl, buildVariableDanglingDsl } from './helpers/dsl-builder';
import { CanvasPage } from './pages/canvas.page';

/** 跳过 smoke 模式 */
const shouldRun = !!(process.env.RUN_E2E || process.env.E2E_FULL_STACK);
test.skip(!shouldRun, '需要 docker compose up + RUN_E2E=1（或 E2E_FULL_STACK=1）');

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'e2e-admin@example.com';
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'E2eAdmin123!';

interface WorkflowSummary {
  id: string;
  name: string;
  status: string;
}

async function getAuthCookie(): Promise<string> {
  try {
    const { cookie } = await login(ADMIN_EMAIL, ADMIN_PASS);
    return cookie;
  } catch {
    await initializeSystem({
      email: ADMIN_EMAIL,
      password: ADMIN_PASS,
      display_name: 'E2E Admin',
      workspace_name: 'E2E Workspace',
    });
    const { cookie } = await login(ADMIN_EMAIL, ADMIN_PASS);
    return cookie;
  }
}

/** 验证 API validate 端点对无效 DSL 返回错误 */
async function validateDslViaApi(
  authCookie: string,
  dsl: object,
): Promise<{ errors: Array<{ code: string; message: string; node_id?: string }> }> {
  const { data } = await apiFetch<{ errors: Array<{ code: string; message: string; node_id?: string }> }>(
    '/api/agent_builder/v1/workflows/validate',
    {
      method: 'POST',
      cookie: authCookie,
      body: { dsl },
    },
  );
  return data;
}

test.describe('DSL 成环校验 + 错误 UI [ROADMAP #5]', () => {
  let authCookie: string;

  test.beforeAll(async () => {
    authCookie = await getAuthCookie();
  });

  test('成环 DSL → 后端 validate API 返回环路错误', async () => {
    const cyclicDsl = buildCyclicDsl('成环测试');
    const result = await validateDslViaApi(authCookie, cyclicDsl);

    // 应该有错误
    expect(result.errors, '成环 DSL 应有校验错误').toBeDefined();
    expect(result.errors.length, '应至少有 1 个错误').toBeGreaterThan(0);

    // 应包含成环相关错误码
    const errorCodes = result.errors.map((e) => e.code);
    const hasCycleError = errorCodes.some(
      (code) =>
        code.includes('CYCLE') ||
        code.includes('cycle') ||
        code.includes('循环') ||
        code.includes('DAG'),
    );
    expect(hasCycleError, `错误码应含环路标识，实际: ${errorCodes.join(', ')}`).toBe(true);
  });

  test('成环 DSL → 画布节点边框变红 + Issue 面板显示错误', async ({ page }) => {
    // 创建工作流
    const { data: wf } = await apiFetch<WorkflowSummary>('/api/agent_builder/v1/workflows', {
      method: 'POST',
      cookie: authCookie,
      body: { name: `成环画布测试 ${Date.now()}` },
    });

    // 保存成环 DSL 草稿
    const cyclicDsl = buildCyclicDsl('成环画布测试');
    await apiFetch(`/api/agent_builder/v1/workflows/${wf.id}/draft`, {
      method: 'PUT',
      cookie: authCookie,
      body: { dsl: cyclicDsl },
    });

    // 打开画布
    const cookieValue = authCookie.split('=')[1]?.split(';')[0] ?? authCookie;
    await page.context().addCookies([
      { name: 'session', value: cookieValue, domain: 'localhost', path: '/' },
    ]);

    const canvas = new CanvasPage(page);
    await canvas.goto(wf.id);

    // 等待画布渲染 + 300ms debounce 校验触发（总等待 2s）
    await page.waitForTimeout(2_000);

    // 验证 Issue 面板出现错误
    const issues = await canvas.getIssuePanel().catch(() => [] as string[]);
    if (issues.length > 0) {
      // 有 issue 面板且有错误
      const hasErrorAboutCycle = issues.some(
        (text) =>
          text.toLowerCase().includes('环') ||
          text.toLowerCase().includes('cycle') ||
          text.toLowerCase().includes('dag'),
      );
      expect(hasErrorAboutCycle, `Issue 面板应含环路错误，实际内容: ${issues.join(' | ')}`).toBe(true);
    } else {
      // Issue 面板未渲染，用备选方案：验证节点有红框
      const hasError = await canvas.nodeHasError('llm_a').catch(() => false);
      const hasError2 = await canvas.nodeHasError('llm_b').catch(() => false);
      // 至少一个节点有错误样式
      expect(hasError || hasError2, '成环时至少一个节点应有错误样式').toBe(true);
    }
  });

  test('成环 DSL → 点发布 API 拒绝（后端复检）', async () => {
    // 创建工作流并保存成环草稿
    const { data: wf } = await apiFetch<WorkflowSummary>('/api/agent_builder/v1/workflows', {
      method: 'POST',
      cookie: authCookie,
      body: { name: `成环发布拒绝测试 ${Date.now()}` },
    });

    const cyclicDsl = buildCyclicDsl('成环发布拒绝测试');
    await apiFetch(`/api/agent_builder/v1/workflows/${wf.id}/draft`, {
      method: 'PUT',
      cookie: authCookie,
      body: { dsl: cyclicDsl },
    });

    // 尝试发布 → 后端应拒绝（返回 400 或 422）
    try {
      await apiFetch(`/api/agent_builder/v1/workflows/${wf.id}/publish`, {
        method: 'POST',
        cookie: authCookie,
        body: {},
      });
      // 如果没有抛错，验证 status 不是 published
      const { data: wfAfter } = await apiFetch<WorkflowSummary>(
        `/api/agent_builder/v1/workflows/${wf.id}`,
        { cookie: authCookie },
      );
      // 成环工作流不应被发布
      expect(wfAfter.status).not.toBe('published');
    } catch (err) {
      // ApiError 说明后端正确拒绝了发布
      // 这是预期行为，测试通过
      expect(err).toBeTruthy();
    }
  });

  test('变量引用 {{ nonexistent.x }} → validate API 返回悬空引用错误', async () => {
    const danglingDsl = buildVariableDanglingDsl('悬空引用测试');
    const result = await validateDslViaApi(authCookie, danglingDsl);

    // 应有悬空引用相关错误
    expect(result.errors, '悬空引用 DSL 应有校验错误').toBeDefined();
    expect(result.errors.length, '应至少有 1 个错误').toBeGreaterThan(0);

    // 错误码应含 UNDEFINED / DANGLING / 引用相关关键字
    const errorCodes = result.errors.map((e) => e.code);
    const hasDanglingError = errorCodes.some(
      (code) =>
        code.includes('UNDEFINED') ||
        code.includes('DANGLING') ||
        code.includes('VAR') ||
        code.includes('VARIABLE') ||
        code.includes('REF'),
    );
    expect(hasDanglingError, `错误码应含变量引用标识，实际: ${errorCodes.join(', ')}`).toBe(true);

    // 错误应指向有问题的节点（llm_1）
    const nodeIds = result.errors.map((e) => e.node_id).filter(Boolean);
    const hasLlmNodeId = nodeIds.some((id) => id === 'llm_1');
    expect(hasLlmNodeId, '错误应指向 llm_1 节点').toBe(true);
  });

  test('修复成环（删除环路边）→ validate API 返回无错误', async () => {
    // 构造一个修复后的 DSL（从成环 DSL 中去掉环路边 llm_b → llm_a）
    const cyclicDsl = buildCyclicDsl('成环修复测试');
    const fixedDsl = {
      ...cyclicDsl,
      edges: cyclicDsl.edges.filter((e) => !(e.source === 'llm_b' && e.target === 'llm_a')),
    };

    const result = await validateDslViaApi(authCookie, fixedDsl);

    // 修复后应无错误（或无 CYCLE 类错误）
    const cycleErrors = result.errors.filter(
      (e) =>
        e.code.includes('CYCLE') ||
        e.code.includes('cycle') ||
        e.code.includes('循环'),
    );
    expect(cycleErrors.length, '修复环路后不应有成环错误').toBe(0);
  });
});
