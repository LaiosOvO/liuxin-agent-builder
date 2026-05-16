/**
 * E2E Spec: 实例列表过滤 + 搜索 + 分页
 *
 * ROADMAP Phase 2 Success Criterion #4:
 *   "实例列表页能按工作流/状态过滤，支持分页搜索"
 *
 * 运行模式：
 *   - Smoke（默认）: 全部 skip
 *   - Standard (RUN_E2E=1): 跑全部 5 个 test
 *   - Full (E2E_FULL_STACK=1): 跑全部 5 个 test
 *
 * 测试数据准备（API fixture 模式，Dify e2e/support/api.ts 借鉴）：
 *   - 创建 2 个工作流（wf_a / wf_b）
 *   - wf_a: 跑 10 个实例（full stack 再跑以模拟翻页）
 *   - wf_b: 跑 5 个实例
 *   - 全部通过 API 直接创建（不走 UI），速度快 + 稳定
 *
 * API 端点（02-08-SUMMARY 确认）：
 *   GET /api/agent_builder/v1/instances
 *   参数：workflow_id / status / search / page / page_size
 */

import { test, expect } from '@playwright/test';
import { apiFetch, login, initializeSystem } from './helpers/api-client';
import { buildLinearDsl, buildBranchDsl } from './helpers/dsl-builder';

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

interface InstanceSummary {
  id: string;
  workflow_id: string;
  status: string;
  created_at: string;
}

interface InstanceListResponse {
  items: InstanceSummary[];
  total: number;
  page: number;
  page_size: number;
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

/** 创建并发布工作流，返回 workflow id */
async function createAndPublishWorkflow(
  authCookie: string,
  name: string,
  useBranch = false,
): Promise<string> {
  const { data: wf } = await apiFetch<WorkflowSummary>('/api/agent_builder/v1/workflows', {
    method: 'POST',
    cookie: authCookie,
    body: { name },
  });

  const dsl = useBranch ? buildBranchDsl(name) : buildLinearDsl(name);
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

/** 创建指定数量的实例（并发创建，速度快） */
async function createInstances(
  authCookie: string,
  workflowId: string,
  count: number,
): Promise<string[]> {
  const promises = Array.from({ length: count }, (_, i) =>
    apiFetch<InstanceSummary>(`/api/agent_builder/v1/workflows/${workflowId}/instances`, {
      method: 'POST',
      cookie: authCookie,
      body: { initial_input: { input: `test input ${i + 1}` } },
    }).then((r) => r.data.id),
  );
  return Promise.all(promises);
}

test.describe('实例列表过滤 + 搜索 + 分页 [ROADMAP #4]', () => {
  let authCookie: string;
  let workflowIdA: string;
  let workflowIdB: string;
  let instanceIdsA: string[];
  let instanceIdsB: string[];
  const TIMESTAMP = Date.now();

  test.beforeAll(async () => {
    authCookie = await getAuthCookie();

    // 创建两个工作流
    workflowIdA = await createAndPublishWorkflow(
      authCookie,
      `过滤测试工作流 A ${TIMESTAMP}`,
    );
    workflowIdB = await createAndPublishWorkflow(
      authCookie,
      `过滤测试工作流 B ${TIMESTAMP}`,
      true,
    );

    // 并发创建实例（wf_a: 10 个, wf_b: 5 个）
    [instanceIdsA, instanceIdsB] = await Promise.all([
      createInstances(authCookie, workflowIdA, 10),
      createInstances(authCookie, workflowIdB, 5),
    ]);

    // 等待实例状态稳定（给后端处理时间）
    await new Promise((resolve) => setTimeout(resolve, 3_000));
  });

  test('实例列表显示所有创建的实例（≥ 15 条）', async () => {
    // 查询所有实例（大 page_size 以覆盖全部）
    const { data: list } = await apiFetch<InstanceListResponse>(
      '/api/agent_builder/v1/instances?page=1&page_size=100',
      { cookie: authCookie },
    );

    // 至少应包含本次创建的 15 条
    expect(list.total, '总实例数应 ≥ 15').toBeGreaterThanOrEqual(15);
    expect(list.items.length).toBeGreaterThan(0);
  });

  test('filter workflow_id=wf_a → 仅显示 wf_a 的实例', async () => {
    const { data: list } = await apiFetch<InstanceListResponse>(
      `/api/agent_builder/v1/instances?workflow_id=${workflowIdA}&page=1&page_size=50`,
      { cookie: authCookie },
    );

    // 所有返回实例都应属于 wf_a
    for (const item of list.items) {
      expect(item.workflow_id, '过滤后的实例应属于 wf_a').toBe(workflowIdA);
    }

    // 数量应 ≥ 10
    expect(list.total, 'wf_a 实例总数应 ≥ 10').toBeGreaterThanOrEqual(10);
  });

  test('filter workflow_id=wf_b → 仅显示 wf_b 的实例', async () => {
    const { data: list } = await apiFetch<InstanceListResponse>(
      `/api/agent_builder/v1/instances?workflow_id=${workflowIdB}&page=1&page_size=50`,
      { cookie: authCookie },
    );

    // 所有返回实例都应属于 wf_b
    for (const item of list.items) {
      expect(item.workflow_id, '过滤后的实例应属于 wf_b').toBe(workflowIdB);
    }

    // 数量应 ≥ 5
    expect(list.total, 'wf_b 实例总数应 ≥ 5').toBeGreaterThanOrEqual(5);
  });

  test('搜索 instance_id 前缀 → 精确命中', async () => {
    // 取第一个 wf_a 实例 ID 的前 8 字符搜索
    const targetId = instanceIdsA[0];
    if (!targetId) {
      console.log('无可用实例 ID，跳过搜索测试');
      return;
    }

    const searchPrefix = targetId.slice(0, 8);
    const { data: list } = await apiFetch<InstanceListResponse>(
      `/api/agent_builder/v1/instances?search=${encodeURIComponent(searchPrefix)}&page=1&page_size=20`,
      { cookie: authCookie },
    );

    // 搜索结果应包含目标实例
    const found = list.items.some((item) => item.id === targetId);
    expect(found, `搜索 "${searchPrefix}" 应命中实例 ${targetId}`).toBe(true);
  });

  test('分页 page=2 page_size=5 → 返回正确条目', async () => {
    // 验证 wf_a 的分页：第 1 页取 5 条，第 2 页取下 5 条，不重叠
    const [page1Result, page2Result] = await Promise.all([
      apiFetch<InstanceListResponse>(
        `/api/agent_builder/v1/instances?workflow_id=${workflowIdA}&page=1&page_size=5`,
        { cookie: authCookie },
      ),
      apiFetch<InstanceListResponse>(
        `/api/agent_builder/v1/instances?workflow_id=${workflowIdA}&page=2&page_size=5`,
        { cookie: authCookie },
      ),
    ]);

    const page1 = page1Result.data;
    const page2 = page2Result.data;

    // 两页数据应有内容
    expect(page1.items.length, '第 1 页应有数据').toBeGreaterThan(0);
    expect(page2.items.length, '第 2 页应有数据').toBeGreaterThan(0);

    // 分页标注正确
    expect(page1.page).toBe(1);
    expect(page2.page).toBe(2);

    // 两页数据不应重叠（ID 无交集）
    const page1Ids = new Set(page1.items.map((i) => i.id));
    const overlap = page2.items.filter((i) => page1Ids.has(i.id));
    expect(overlap.length, '分页数据不应重叠').toBe(0);
  });
});
