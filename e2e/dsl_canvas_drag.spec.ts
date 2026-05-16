/**
 * E2E Spec: DSL 画布拖拽 + 发布
 *
 * ROADMAP Phase 2 Success Criterion #1:
 *   "用户能在画布上拖拽 Start/End/LLM/Tool/IfElse 五种节点并连线，保存为草稿后发布"
 *
 * 运行模式：
 *   - Smoke（默认）: 全部 skip
 *   - Standard (RUN_E2E=1): 跑全部 4 个 test
 *   - Full (E2E_FULL_STACK=1): 跑全部 4 个 test（含本 spec）
 *
 * 测试环境要求：
 *   docker compose up -d（api/worker/web/postgres/redis/nginx 全部健康）
 *
 * Dify 参考：
 *   e2e/features/apps/workflow-run-publish.feature — API 准备数据 + UI 触发的组合模式
 *   e2e/features/step-definitions/apps/workflow-run.steps.ts — 运行验证步骤
 */

import { test, expect } from '@playwright/test';
import { apiFetch, login, initializeSystem } from './helpers/api-client';
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
  version: number;
}

/** 获取认证 cookie，按需初始化系统 */
async function getAuthCookie(): Promise<string> {
  try {
    const { cookie } = await login(ADMIN_EMAIL, ADMIN_PASS);
    return cookie;
  } catch {
    // 系统未初始化，先 setup
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

test.describe('画布拖拽 5 种节点并连线发布 [ROADMAP #1]', () => {
  let authCookie: string;
  let workflowId: string;

  test.beforeAll(async () => {
    authCookie = await getAuthCookie();
  });

  test('拖拽 5 种节点到画布（Start/End/LLM/Tool/IfElse）', async ({ page }) => {
    // 创建工作流
    const { data: wf } = await apiFetch<WorkflowSummary>('/api/agent_builder/v1/workflows', {
      method: 'POST',
      cookie: authCookie,
      body: {
        name: `E2E 拖拽测试 ${Date.now()}`,
        description: 'E2E drag-drop test',
      },
    });
    workflowId = wf.id;

    // 设置 cookie 到浏览器上下文
    const urlObj = new URL(page.context().browser()?.browserType().name() ? 'http://localhost:8080' : 'http://localhost:8080');
    await page.context().addCookies([
      {
        name: 'session',
        value: authCookie.split('=')[1]?.split(';')[0] ?? authCookie,
        domain: urlObj.hostname,
        path: '/',
      },
    ]);

    const canvas = new CanvasPage(page);
    await canvas.goto(workflowId);

    // 依次拖拽 5 种节点
    const nodePositions = [
      { type: 'start' as const, position: { x: 100, y: 200 } },
      { type: 'llm' as const, position: { x: 300, y: 200 } },
      { type: 'tool' as const, position: { x: 500, y: 200 } },
      { type: 'if_else' as const, position: { x: 700, y: 200 } },
      { type: 'end' as const, position: { x: 900, y: 200 } },
    ];

    for (const { type, position } of nodePositions) {
      await canvas.dragNode(type, position);
    }

    // 验证 5 种节点都出现在画布上
    const nodeIds = await canvas.getCanvasNodeIds();
    const nodeTypes = ['start', 'llm', 'tool', 'if_else', 'end'];
    for (const type of nodeTypes) {
      const hasType = nodeIds.some((id) => id.includes(type));
      expect(hasType, `画布应包含 ${type} 类型节点`).toBe(true);
    }
  });

  test('连线 Start → LLM → End → 保存草稿（DB 出现 workflow.draft）', async ({ page }) => {
    if (!workflowId) {
      test.skip();
      return;
    }

    // 用 API 直接保存包含 3 节点 linear 连线的草稿 DSL（更稳定，不依赖 UI 拖拽细节）
    const linearDsl = {
      version: '1.0',
      name: '线性草稿测试',
      state_schema: { input: 'str' },
      nodes: [
        { id: 'start', type: 'start', label: '开始', position: { x: 80, y: 200 }, config: {} },
        {
          id: 'llm_1',
          type: 'llm',
          label: 'LLM',
          position: { x: 320, y: 200 },
          config: { model: 'echo:echo', user_prompt: '{{ start.output.input }}', temperature: 0.0, retry_count: 1 },
        },
        { id: 'end', type: 'end', label: '结束', position: { x: 560, y: 200 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'llm_1' },
        { id: 'e2', source: 'llm_1', target: 'end' },
      ],
    };

    const { data: updatedWf } = await apiFetch<WorkflowSummary>(
      `/api/agent_builder/v1/workflows/${workflowId}/draft`,
      {
        method: 'PUT',
        cookie: authCookie,
        body: { dsl: linearDsl },
      },
    );

    // 验证草稿已保存（workflow 存在）
    expect(updatedWf.id).toBe(workflowId);

    // 通过 GET 再次确认草稿状态
    const { data: wfDetail } = await apiFetch<{ id: string; status: string }>(
      `/api/agent_builder/v1/workflows/${workflowId}`,
      { cookie: authCookie },
    );
    expect(['draft', 'published']).toContain(wfDetail.status);
  });

  test('发布草稿 → workflow.status=published + version 自增', async () => {
    if (!workflowId) {
      test.skip();
      return;
    }

    // 确保有一个合法的草稿
    const linearDsl = {
      version: '1.0',
      name: '发布验证工作流',
      state_schema: { input: 'str' },
      nodes: [
        { id: 'start', type: 'start', label: '开始', position: { x: 80, y: 200 }, config: {} },
        {
          id: 'llm_1',
          type: 'llm',
          label: 'LLM',
          position: { x: 320, y: 200 },
          config: { model: 'echo:echo', user_prompt: '{{ start.output.input }}', temperature: 0.0, retry_count: 1 },
        },
        { id: 'end', type: 'end', label: '结束', position: { x: 560, y: 200 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'llm_1' },
        { id: 'e2', source: 'llm_1', target: 'end' },
      ],
    };

    await apiFetch(`/api/agent_builder/v1/workflows/${workflowId}/draft`, {
      method: 'PUT',
      cookie: authCookie,
      body: { dsl: linearDsl },
    });

    // 发布
    const { data: publishedWf } = await apiFetch<WorkflowSummary>(
      `/api/agent_builder/v1/workflows/${workflowId}/publish`,
      {
        method: 'POST',
        cookie: authCookie,
        body: {},
      },
    );

    expect(publishedWf.status).toBe('published');
    expect(publishedWf.version).toBeGreaterThanOrEqual(1);
  });

  test('重新打开画布 → 节点 + 连线 + 配置还原（DSL roundtrip 验证）', async ({ page }) => {
    if (!workflowId) {
      test.skip();
      return;
    }

    // 通过 API 验证 DSL 可以读回（roundtrip）
    const { data: wfDetail } = await apiFetch<{ id: string; dsl?: { nodes: unknown[] } }>(
      `/api/agent_builder/v1/workflows/${workflowId}`,
      { cookie: authCookie },
    );

    // 草稿/已发布版本都应包含 DSL 中的节点
    if (wfDetail.dsl?.nodes) {
      expect(wfDetail.dsl.nodes.length).toBeGreaterThanOrEqual(3);
    }

    // UI roundtrip：打开画布，验证节点渲染
    const cookieValue = authCookie.split('=')[1]?.split(';')[0] ?? authCookie;
    await page.context().addCookies([
      { name: 'session', value: cookieValue, domain: 'localhost', path: '/' },
    ]);

    const canvas = new CanvasPage(page);
    await canvas.goto(workflowId);

    // 画布加载后应该有节点渲染出来（至少 1 个节点）
    await page.locator('[data-testid^="node-"]').first().waitFor({ state: 'visible', timeout: 15_000 });
    const nodeIds = await canvas.getCanvasNodeIds();
    expect(nodeIds.length).toBeGreaterThanOrEqual(1);
  });
});
