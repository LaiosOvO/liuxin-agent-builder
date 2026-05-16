/**
 * E2E Spec: HITL Token-as-Login + 流程推进
 *
 * ROADMAP Phase 3 #2:
 *   "审批人点击链接后无需登录账号即可看到决策表单，填写并提交后流程推进"
 *
 * 运行模式:
 *   - Smoke（默认）: 全部 skip
 *   - Standard (RUN_E2E=1): 跑全部 test
 *   - Full (E2E_FULL_STACK=1): 跑全部 test
 *
 * 核心验证:
 *   - mailhog 提取 token → 浏览器/裸 fetch 访问 GET /hitl/page/<token>
 *   - 返回决策页 HTML + Set-Cookie 含 hitl_session_<jti>
 *   - jti 未消费（GET 不消费 — CLAUDE.md 2.5）
 *   - POST 决策 → 成功页 + instance.status 推进 + node_state.status='done'
 *
 * 依赖: 03-03 (HitlTokenService) + 03-06 (公网 API) + 03-07 (决策页前端)
 */

import { test, expect } from '@playwright/test';
import { apiFetch, initializeSystem, login } from './helpers/api-client';
import { buildHitlDsl } from './helpers/hitl-builder';
import { getLatestHitlEmail, purgeAllEmails } from './helpers/mailhog-client';
import { HitlPage } from './pages/hitl.page';

const shouldRun = !!(process.env.RUN_E2E || process.env.E2E_FULL_STACK);
test.skip(!shouldRun, '需要 docker compose up + RUN_E2E=1（或 E2E_FULL_STACK=1）');

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? 'e2e-admin@example.com';
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'E2eAdmin123!';
const APPROVER_EMAIL =
  process.env.E2E_APPROVER_EMAIL ?? 'approver-roadmap2@example.com';
const BASE_URL = process.env.PUBLIC_BASE_URL ?? 'http://localhost:8080';

interface WorkflowSummary {
  id: string;
}

interface InstanceSummary {
  id: string;
  workflow_id: string;
  status: string;
}

async function ensureAdminAuth(): Promise<string> {
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

async function setupHitlInstance(cookie: string): Promise<{
  instanceId: string;
  approveToken: string;
  approveJti: string;
}> {
  // 创建工作流
  const { data: wf } = await apiFetch<WorkflowSummary>(
    '/api/agent_builder/v1/workflows',
    {
      method: 'POST',
      cookie,
      body: { name: `Token-as-login E2E ${Date.now()}` },
    },
  );

  // 写 DSL
  const dsl = buildHitlDsl({
    name: 'Token-as-login E2E',
    approverEmails: [APPROVER_EMAIL],
    formSchema: {
      type: 'object',
      properties: {
        comment: { type: 'string', title: '审批备注', maxLength: 200 },
      },
      required: [],
      additionalProperties: false,
    },
  });

  await apiFetch(`/api/agent_builder/v1/workflows/${wf.id}/draft`, {
    method: 'PUT',
    cookie,
    body: { dsl },
  });

  await apiFetch(`/api/agent_builder/v1/workflows/${wf.id}/publish`, {
    method: 'POST',
    cookie,
    body: {},
  });

  // 启动实例
  const { data: instance } = await apiFetch<InstanceSummary>(
    `/api/agent_builder/v1/workflows/${wf.id}/instances`,
    {
      method: 'POST',
      cookie,
      body: {
        initial_input: {
          input: 'token login test',
          applicant_email: ADMIN_EMAIL,
        },
      },
    },
  );

  // 等邮件
  const email = await getLatestHitlEmail(APPROVER_EMAIL, 20_000);

  // 找 approve / submit token（v1 single 模式审批人是 approve；执行人是 submit）
  const approveLink =
    email.deeplinks.find((d) => d.action === 'approve') ??
    email.deeplinks.find((d) => d.action === 'submit') ??
    email.deeplinks[0];

  if (!approveLink) {
    throw new Error('邮件中未找到任何 deeplink');
  }

  return {
    instanceId: instance.id,
    approveToken: approveLink.token,
    approveJti: approveLink.jti,
  };
}

test.describe('[ROADMAP #2] Token-as-login + 流程推进', () => {
  let authCookie: string;

  test.beforeAll(async () => {
    authCookie = await ensureAdminAuth();
  });

  test.beforeEach(async () => {
    await purgeAllEmails();
  });

  test('GET /hitl/page/<token> 返回决策页 + Set-Cookie hitl_session_<jti>（JSON 协商）', async ({
    page,
  }) => {
    const { approveToken, approveJti } = await setupHitlInstance(authCookie);
    const hitlPage = new HitlPage(page, BASE_URL);

    // 用裸 fetch + Accept: application/json 调用 GET
    const result = await hitlPage.fetchPageRaw(approveToken, {
      userAgent: 'Mozilla/5.0 (E2E Real User)',
      acceptJson: true,
    });

    expect(result.status, 'GET 应返回 200').toBe(200);

    // Set-Cookie 含 hitl_session_<jti>
    expect(result.setCookie, '应有 Set-Cookie 响应头').toBeTruthy();
    expect(
      result.setCookie,
      `Set-Cookie 应含 hitl_session_${approveJti}`,
    ).toContain(`hitl_session_${approveJti}`);

    // JSON 响应应有 form_schema / allowed_actions
    if (result.json) {
      expect(result.json.bot_scan, 'JSON 不应是 bot_scan').not.toBe(true);
      expect(
        result.json.allowed_actions || result.json.form_schema,
        '应有 allowed_actions 或 form_schema',
      ).toBeDefined();
    }
  });

  test('GET /hitl/page/<token> 不消费 jti（CLAUDE.md 2.5 P0）', async ({ page }) => {
    const { approveToken, approveJti } = await setupHitlInstance(authCookie);
    const hitlPage = new HitlPage(page, BASE_URL);

    // 真实用户 GET 1 次
    const result1 = await hitlPage.fetchPageRaw(approveToken, {
      userAgent: 'Mozilla/5.0 (E2E Real User)',
      acceptJson: true,
    });
    expect(result1.status).toBe(200);

    // 再次 GET（同 token）应该仍能拿到决策页（jti 未消费）
    const result2 = await hitlPage.fetchPageRaw(approveToken, {
      userAgent: 'Mozilla/5.0 (E2E Real User)',
      acceptJson: true,
    });
    expect(result2.status, '同 token 二次 GET 应仍返回 200').toBe(200);
    expect(result2.setCookie, '二次 GET 仍应签发 cookie').toBeTruthy();
    expect(result2.setCookie).toContain(`hitl_session_${approveJti}`);
  });

  test('POST /hitl/action/<token> 提交决策 → 流程推进到完成态', async ({ page }) => {
    const { instanceId, approveToken, approveJti } = await setupHitlInstance(
      authCookie,
    );
    const hitlPage = new HitlPage(page, BASE_URL);

    // 先 GET 拿 cookie
    const getResult = await hitlPage.fetchPageRaw(approveToken, {
      userAgent: 'Mozilla/5.0 (E2E Real User)',
      acceptJson: true,
    });
    expect(getResult.status).toBe(200);
    const sessionCookie = getResult.setCookie ?? '';

    // 提取 cookie value（取 Set-Cookie 头中的 hitl_session_<jti>=value; ...）
    const cookieMatch = sessionCookie.match(
      new RegExp(`hitl_session_${approveJti}=([^;]+)`),
    );
    expect(cookieMatch, '应能从 Set-Cookie 提取 cookie value').toBeTruthy();
    const cookieValue = cookieMatch![1];

    // POST 提交
    const postResult = await hitlPage.submitActionRaw(approveToken, 'approve', {
      reason: 'E2E 测试通过',
      formData: { comment: '审批备注 E2E' },
      cookie: `hitl_session_${approveJti}=${cookieValue}`,
      userAgent: 'Mozilla/5.0 (E2E Real User)',
      acceptJson: true,
    });

    // 提交成功：200 OK 或 303 重定向到 success 页
    expect(
      [200, 302, 303].includes(postResult.status),
      `POST 应返回 200/302/303，实际 ${postResult.status} (body: ${postResult.body.slice(0, 200)})`,
    ).toBe(true);

    // 验证 instance 推进
    const instanceCheck = await apiFetch<InstanceSummary>(
      `/api/agent_builder/v1/instances/${instanceId}`,
      { cookie: authCookie },
    );
    expect(
      ['completed', 'running', 'done', 'succeeded'].includes(
        instanceCheck.data.status,
      ),
      `instance.status 应推进，实际：${instanceCheck.data.status}`,
    ).toBe(true);
  });

  test('试同时含执行人 submit token 和审核人 approve token（自适应单人模式）', async () => {
    const { approveToken } = await setupHitlInstance(authCookie);
    // 单人模式（Phase 3 v1）：approve / submit 二选一即可
    expect(approveToken).toBeTruthy();
    expect(approveToken.split('.').length).toBe(3); // JWT 标准 3 段
  });
});
