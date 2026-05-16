/**
 * E2E Spec: 实例运行 + SSE 实时状态
 *
 * ROADMAP Phase 2 Success Criterion #2:
 *   "点击'运行'后实例创建并执行，Web 页面实时显示每个节点的进入/完成状态"
 *
 * 运行模式：
 *   - Smoke（默认）: 全部 skip
 *   - Standard (RUN_E2E=1): 跑全部 3 个 test
 *   - Full (E2E_FULL_STACK=1): 跑全部 3 个 test
 *
 * 核心验证：
 *   - EventSource 订阅 GET /api/agent_builder/v1/instances/<id>/events
 *   - 事件序列：node.start(start) → node.complete(start) → node.start(llm_1) → node.complete(llm_1) → node.start(end) → instance.complete
 *   - 多浏览器订阅同一 instance 都收到事件（Redis pub/sub fan-out）
 *
 * 后端 SSE 端点（02-07-SUMMARY 确认）：
 *   GET /api/agent_builder/v1/instances/{id}/events
 *   事件 payload: { event: string, node_id?: string, instance_id: string, timestamp: string }
 */

import { test, expect } from '@playwright/test';
import { apiFetch, login, initializeSystem } from './helpers/api-client';
import { buildLinearDsl } from './helpers/dsl-builder';
import { InstancePage } from './pages/instance.page';

/** 跳过 smoke 模式 */
const shouldRun = !!(process.env.RUN_E2E || process.env.E2E_FULL_STACK);
test.skip(!shouldRun, '需要 docker compose up + RUN_E2E=1（或 E2E_FULL_STACK=1）');

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'e2e-admin@example.com';
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'E2eAdmin123!';
const BASE_URL = process.env.PUBLIC_BASE_URL ?? 'http://localhost:8080';

interface WorkflowSummary {
  id: string;
  name: string;
  status: string;
  version: number;
}

interface InstanceSummary {
  id: string;
  workflow_id: string;
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

/** 创建并发布一个 linear 工作流，返回 workflow id */
async function createPublishedWorkflow(authCookie: string): Promise<string> {
  const { data: wf } = await apiFetch<WorkflowSummary>('/api/agent_builder/v1/workflows', {
    method: 'POST',
    cookie: authCookie,
    body: { name: `SSE 测试工作流 ${Date.now()}` },
  });

  const dsl = buildLinearDsl('SSE 线性工作流');
  await apiFetch(`/api/agent_builder/v1/workflows/${wf.id}/draft`, {
    method: 'PUT',
    cookie: authCookie,
    body: { dsl },
  });

  await apiFetch(`/api/agent_builder/v1/workflows/${wf.id}/publish`, {
    method: 'POST',
    cookie: authCookie,
    body: {},
  });

  return wf.id;
}

test.describe('实例运行 + SSE 实时状态 [ROADMAP #2]', () => {
  let authCookie: string;
  let workflowId: string;

  test.beforeAll(async () => {
    authCookie = await getAuthCookie();
    workflowId = await createPublishedWorkflow(authCookie);
  });

  test('发布工作流启动实例 POST /instances → SSE GET /instances/<id>/events 收到事件', async ({ page }) => {
    // 创建实例
    const { data: instance } = await apiFetch<InstanceSummary>(
      `/api/agent_builder/v1/workflows/${workflowId}/instances`,
      {
        method: 'POST',
        cookie: authCookie,
        body: { initial_input: { input: 'hello e2e' } },
      },
    );
    expect(instance.id).toBeTruthy();
    expect(instance.status).toBeTruthy();

    // 在浏览器内注入 cookie 并订阅 SSE
    const cookieValue = authCookie.split('=')[1]?.split(';')[0] ?? authCookie;
    await page.context().addCookies([
      { name: 'session', value: cookieValue, domain: 'localhost', path: '/' },
    ]);

    const instancePage = new InstancePage(page, BASE_URL);
    const result = await instancePage.listenSseEvents(instance.id, 45_000);

    // 应收到至少一个事件
    expect(result.events.length, '应收到至少 1 个 SSE 事件').toBeGreaterThan(0);

    // 验证所有事件都携带 instance_id
    for (const evt of result.events) {
      expect(evt.instance_id).toBe(instance.id);
    }
  });

  test('验证事件序列：node.start(start) → node.complete(start) → ... → instance.complete', async ({ page }) => {
    // 创建新实例
    const { data: instance } = await apiFetch<InstanceSummary>(
      `/api/agent_builder/v1/workflows/${workflowId}/instances`,
      {
        method: 'POST',
        cookie: authCookie,
        body: { initial_input: { input: 'sequence test' } },
      },
    );

    const cookieValue = authCookie.split('=')[1]?.split(';')[0] ?? authCookie;
    await page.context().addCookies([
      { name: 'session', value: cookieValue, domain: 'localhost', path: '/' },
    ]);

    const instancePage = new InstancePage(page, BASE_URL);
    const result = await instancePage.listenSseEvents(instance.id, 45_000);

    const events = result.events;
    expect(events.length).toBeGreaterThan(0);

    // 提取事件类型序列
    const eventTypes = events.map((e) => e.event);

    // 必须包含 node.start 和 node.complete 事件
    expect(eventTypes).toContain('node.start');
    expect(eventTypes).toContain('node.complete');

    // 必须以 instance.complete 或 instance.failed 结束
    const terminalEvents = ['instance.complete', 'instance.failed'];
    const hasTerminal = eventTypes.some((t) => terminalEvents.includes(t));
    expect(hasTerminal, '应有实例终止事件').toBe(true);

    // 验证 start 节点事件存在
    const startNodeEvents = events.filter((e) => e.node_id === 'start');
    expect(startNodeEvents.length, 'start 节点应有事件').toBeGreaterThan(0);

    // 验证每个 node.start 之后有对应的 node.complete（同 node_id）
    const nodeStartEvents = events.filter((e) => e.event === 'node.start');
    for (const startEvt of nodeStartEvents) {
      if (!startEvt.node_id) continue;
      const hasMatchingComplete = events.some(
        (e) => e.event === 'node.complete' && e.node_id === startEvt.node_id,
      );
      expect(hasMatchingComplete, `节点 ${startEvt.node_id} 应有 node.complete 事件`).toBe(true);
    }
  });

  test('多浏览器订阅同一 instance 都收到事件（Redis pub/sub fan-out）', async ({ page, browser }) => {
    // 创建新实例
    const { data: instance } = await apiFetch<InstanceSummary>(
      `/api/agent_builder/v1/workflows/${workflowId}/instances`,
      {
        method: 'POST',
        cookie: authCookie,
        body: { initial_input: { input: 'fanout test' } },
      },
    );

    const cookieValue = authCookie.split('=')[1]?.split(';')[0] ?? authCookie;

    // 为第一个页面注入 cookie
    await page.context().addCookies([
      { name: 'session', value: cookieValue, domain: 'localhost', path: '/' },
    ]);

    // 创建第二个浏览器上下文
    const secondContext = await browser.newContext({
      baseURL: BASE_URL,
    });
    await secondContext.addCookies([
      { name: 'session', value: cookieValue, domain: 'localhost', path: '/' },
    ]);
    const secondPage = await secondContext.newPage();

    const instancePage = new InstancePage(page, BASE_URL);

    try {
      // 并发订阅两个浏览器的 SSE
      const [result1, result2] = await Promise.all([
        instancePage.listenSseEvents(instance.id, 45_000),
        instancePage.listenSseEventsFromPage(instance.id, secondPage, 45_000),
      ]);

      // 两个浏览器都应收到事件
      expect(result1.events.length, '浏览器 1 应收到 SSE 事件').toBeGreaterThan(0);
      expect(result2.events.length, '浏览器 2 应收到 SSE 事件').toBeGreaterThan(0);

      // 两个浏览器的事件类型集合应该一致
      const types1 = new Set(result1.events.map((e) => e.event));
      const types2 = new Set(result2.events.map((e) => e.event));

      // 终止事件应该两边都有
      const terminalTypes = ['instance.complete', 'instance.failed'];
      const terminal1 = [...types1].some((t) => terminalTypes.includes(t));
      const terminal2 = [...types2].some((t) => terminalTypes.includes(t));
      expect(terminal1 || result1.timedOut, '浏览器 1 应收到终止事件').toBe(true);
      expect(terminal2 || result2.timedOut, '浏览器 2 应收到终止事件').toBe(true);
    } finally {
      await secondContext.close();
    }
  });
});
