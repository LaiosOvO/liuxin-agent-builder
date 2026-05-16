/**
 * E2E Spec: Safe Links Bot UA 回归 (CLAUDE.md 2.5 P0)
 *
 * ROADMAP Phase 3 #3:
 *   "Outlook Safe Links 扫描器 GET token 链接不消费 jti，审批人首次点击仍可正常决策"
 *
 * CLAUDE.md 2.5 P0:
 *   "GET 即消费 jti 是永不可接受的实现"
 *   "E2E 必包含 Outlook Safe Links / Microsoft Defender 模拟 UA 触发 GET 的回归用例"
 *
 * 运行模式:
 *   - Smoke（默认）: 全部 skip
 *   - Standard (RUN_E2E=1): 跑全部 test
 *   - Full (E2E_FULL_STACK=1): 跑全部 test
 *
 * 核心验证 (4 种 Bot UA + 1 个真实用户 follow-up):
 *   1. Outlook Safe Links 真实 UA (CONTEXT §Specific Ideas)
 *   2. Microsoft Defender Safe Links
 *   3. Slackbot LinkExpanding
 *   4. Googlebot
 *
 * 每个 Bot UA 断言：
 *   - GET 返回 200 + bot_scan content (HTML "邮件扫描" or JSON {bot_scan: true})
 *   - 无 Set-Cookie 头 (不签 hitl_session)
 *   - jti 仍未消费 (验证后续真实用户访问能成功决策)
 *
 * 依赖: 03-03 (bot_detector.is_bot_ua) + 03-06 (公网 API bot 短路)
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
  process.env.E2E_APPROVER_EMAIL ?? 'approver-roadmap3@example.com';
const BASE_URL = process.env.PUBLIC_BASE_URL ?? 'http://localhost:8080';

/** 4 种 Safe Links Bot UA（CLAUDE.md 2.5 P0 + CONTEXT.md §Specific Ideas） */
const BOT_UAS: Array<{ name: string; ua: string }> = [
  {
    name: 'Outlook Safe Links (AC-Detector-Tool)',
    ua: 'Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; +safelinks.protection.outlook.com)',
  },
  {
    name: 'Microsoft Defender Safe Links',
    ua: 'Mozilla/5.0 (compatible; MicrosoftDefender/1.0; +https://docs.microsoft.com/security)',
  },
  {
    name: 'Slackbot LinkExpanding',
    ua: 'Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)',
  },
  {
    name: 'Googlebot',
    ua: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
  },
];

const REAL_USER_UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

interface WorkflowSummary {
  id: string;
}

interface InstanceSummary {
  id: string;
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

async function setupTokenForBotTest(
  cookie: string,
): Promise<{ token: string; jti: string }> {
  await purgeAllEmails();
  const { data: wf } = await apiFetch<WorkflowSummary>(
    '/api/agent_builder/v1/workflows',
    {
      method: 'POST',
      cookie,
      body: { name: `Safe Links bot E2E ${Date.now()}` },
    },
  );

  const dsl = buildHitlDsl({
    name: 'Safe Links bot E2E',
    approverEmails: [APPROVER_EMAIL],
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

  await apiFetch<InstanceSummary>(
    `/api/agent_builder/v1/workflows/${wf.id}/instances`,
    {
      method: 'POST',
      cookie,
      body: {
        initial_input: {
          input: 'safe links bot test',
          applicant_email: ADMIN_EMAIL,
        },
      },
    },
  );

  const email = await getLatestHitlEmail(APPROVER_EMAIL, 20_000);
  const firstLink = email.deeplinks[0];
  if (!firstLink) {
    throw new Error('邮件中未找到任何 deeplink');
  }
  return { token: firstLink.token, jti: firstLink.jti };
}

test.describe('[ROADMAP #3] Safe Links Bot UA Regression (CLAUDE.md 2.5 P0)', () => {
  let authCookie: string;

  test.beforeAll(async () => {
    authCookie = await ensureAdminAuth();
  });

  for (const { name, ua } of BOT_UAS) {
    test(`Bot UA "${name}" GET 不消费 jti + 无 Set-Cookie + bot_scan 返回`, async ({
      page,
    }) => {
      const { token, jti } = await setupTokenForBotTest(authCookie);
      const hitlPage = new HitlPage(page, BASE_URL);

      // 模拟 bot 扫描器 GET（裸 fetch + bot UA）
      const botResult = await hitlPage.fetchPageRaw(token, {
        userAgent: ua,
        acceptJson: true,
      });

      // 1. status 必须是 200（不阻止 bot 访问，但返回静态内容）
      expect(botResult.status, `bot UA "${name}" GET 应返回 200`).toBe(200);

      // 2. 无 Set-Cookie hitl_session_<jti>
      const setCookie = botResult.setCookie ?? '';
      expect(
        setCookie.includes(`hitl_session_${jti}`),
        `bot UA "${name}" 不应签发 hitl_session_${jti} cookie，实际 Set-Cookie: ${setCookie}`,
      ).toBe(false);

      // 3. 响应是 bot_scan 内容
      const isBotScanResponse =
        botResult.json?.bot_scan === true ||
        botResult.body.includes('邮件扫描') ||
        botResult.body.includes('未触发任何状态变更') ||
        botResult.body.toLowerCase().includes('bot');

      expect(
        isBotScanResponse,
        `bot UA "${name}" 应返回 bot_scan 内容（HTML 或 JSON {bot_scan:true}），实际 body 前 200 字符：${botResult.body.slice(0, 200)}`,
      ).toBe(true);
    });
  }

  test('Bot 扫描后真实用户用同一 token 仍能 GET 决策页（jti 未被预消费）', async ({
    page,
  }) => {
    const { token, jti } = await setupTokenForBotTest(authCookie);
    const hitlPage = new HitlPage(page, BASE_URL);

    // 1. Bot 扫描 4 次（模拟邮件经过多个安全网关）
    for (const { ua } of BOT_UAS) {
      const botResult = await hitlPage.fetchPageRaw(token, {
        userAgent: ua,
        acceptJson: true,
      });
      expect(botResult.status, `bot UA 扫描应返回 200`).toBe(200);
      // 关键断言：每次 bot 扫描都不应签 cookie
      expect(
        (botResult.setCookie ?? '').includes(`hitl_session_${jti}`),
        'bot 扫描不应签发 cookie',
      ).toBe(false);
    }

    // 2. 真实用户首次点击（应正常返回决策页 + 签 cookie）
    const userResult = await hitlPage.fetchPageRaw(token, {
      userAgent: REAL_USER_UA,
      acceptJson: true,
    });

    expect(userResult.status, '真实用户 GET 应返回 200').toBe(200);
    expect(
      (userResult.setCookie ?? '').includes(`hitl_session_${jti}`),
      `bot 扫描后真实用户首次点击应能签发 hitl_session_${jti}（证明 jti 未被预消费）`,
    ).toBe(true);

    // 3. 响应非 bot_scan
    expect(
      userResult.json?.bot_scan === true,
      '真实用户响应不应是 bot_scan',
    ).not.toBe(true);
  });

  test('Bot 扫描 + 真实用户最终能成功 POST 提交（完整 Pitfall 3 P0 回归）', async ({
    page,
  }) => {
    const { token, jti } = await setupTokenForBotTest(authCookie);
    const hitlPage = new HitlPage(page, BASE_URL);

    // 4 个 bot 都先扫一遍
    for (const { ua } of BOT_UAS) {
      await hitlPage.fetchPageRaw(token, {
        userAgent: ua,
        acceptJson: true,
      });
    }

    // 真实用户 GET → 拿 cookie
    const getResult = await hitlPage.fetchPageRaw(token, {
      userAgent: REAL_USER_UA,
      acceptJson: true,
    });
    expect(getResult.status).toBe(200);

    const cookieMatch = (getResult.setCookie ?? '').match(
      new RegExp(`hitl_session_${jti}=([^;]+)`),
    );
    expect(cookieMatch, '真实用户应能拿到 cookie').toBeTruthy();
    const cookieValue = cookieMatch![1];

    // 真实用户 POST 提交
    const postResult = await hitlPage.submitActionRaw(token, 'approve', {
      reason: 'Bot 扫描后真实用户成功决策',
      cookie: `hitl_session_${jti}=${cookieValue}`,
      userAgent: REAL_USER_UA,
      acceptJson: true,
    });

    // 成功（不应是 409/410 — 因 jti 未被 bot 消费）
    expect(
      [200, 302, 303].includes(postResult.status),
      `Bot 扫描后真实用户 POST 应成功（200/302/303），实际：${postResult.status} - ${postResult.body.slice(0, 200)}`,
    ).toBe(true);
  });
});
