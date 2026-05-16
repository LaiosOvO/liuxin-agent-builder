/**
 * HITL 公网决策页 Page Object（hitl.page.ts）
 *
 * 封装 /hitl/[token] 公网决策页的所有操作（不需要登录）。
 *
 * Phase 3 设计要点：
 * - GET 不消费 jti（CLAUDE.md 2.5 P0）
 * - HMAC session cookie hitl_session_<jti>（多 token 隔离）
 * - 3 button form (submit/approve + return + reject)
 * - reason textarea + form_data 动态字段
 *
 * 与 InstancePage / CanvasPage 不同：本 Page Object **不需要登录**（公网决策页）。
 */

import type { Page, Response } from '@playwright/test';

/** decision action 名称（v1 single 模式 6 选 3） */
export type HitlAction = 'submit' | 'approve' | 'return' | 'reject';

/** HITL 页面 fetch 结果（JSON content negotiation 后） */
export interface HitlPageJson {
  bot_scan?: boolean;
  form_schema?: Record<string, unknown>;
  allowed_actions?: HitlAction[];
  records?: Array<{
    actor_email: string;
    action: string;
    ts: string;
    reason?: string;
    ip?: string | null;
    ua?: string | null;
  }>;
  deadline_at?: string;
  flow_title?: string;
  node_title?: string;
  applicant_email?: string;
}

export class HitlPage {
  private readonly page: Page;
  private readonly baseUrl: string;

  constructor(page: Page, baseUrl = 'http://localhost:8080') {
    this.page = page;
    this.baseUrl = baseUrl;
  }

  /**
   * 导航到决策页：/hitl/<token>。
   *
   * @param token  JWT token 字符串（不带 URL prefix）
   * @returns      response（spec 可断言 status / headers）
   */
  async goto(token: string): Promise<Response | null> {
    return this.page.goto(`/hitl/${token}`);
  }

  /**
   * 用裸 fetch 调用 GET /hitl/page/<token>（不经浏览器，便于 bot UA 模拟 + JSON 协商）。
   *
   * @param token       JWT token
   * @param options     { userAgent, acceptJson, cookie }
   * @returns           { status, headers, json | html, setCookie }
   */
  async fetchPageRaw(
    token: string,
    options: {
      userAgent?: string;
      acceptJson?: boolean;
      cookie?: string;
    } = {},
  ): Promise<{
    status: number;
    headers: Record<string, string>;
    body: string;
    json?: HitlPageJson;
    setCookie?: string;
  }> {
    const headers: Record<string, string> = {};
    if (options.userAgent) headers['User-Agent'] = options.userAgent;
    if (options.acceptJson) headers['Accept'] = 'application/json';
    if (options.cookie) headers['Cookie'] = options.cookie;

    const response = await fetch(`${this.baseUrl}/hitl/page/${token}`, {
      method: 'GET',
      headers,
      redirect: 'manual',
    });

    const responseHeaders: Record<string, string> = {};
    response.headers.forEach((value: string, key: string) => {
      responseHeaders[key] = value;
    });

    const body = await response.text();
    const result: {
      status: number;
      headers: Record<string, string>;
      body: string;
      json?: HitlPageJson;
      setCookie?: string;
    } = {
      status: response.status,
      headers: responseHeaders,
      body,
      setCookie: response.headers.get('set-cookie') ?? undefined,
    };

    if (options.acceptJson) {
      try {
        result.json = JSON.parse(body) as HitlPageJson;
      } catch {
        // 非 JSON 响应（如 bot_scan.html），忽略
      }
    }

    return result;
  }

  /**
   * POST /hitl/action/<token> 提交决策（裸 fetch）。
   *
   * @param token     JWT token
   * @param action    decision action
   * @param options   { reason, form_data, cookie, userAgent, acceptJson }
   * @returns         { status, headers, body, json? }
   */
  async submitActionRaw(
    token: string,
    action: HitlAction,
    options: {
      reason?: string;
      formData?: Record<string, unknown>;
      cookie?: string;
      userAgent?: string;
      acceptJson?: boolean;
    } = {},
  ): Promise<{
    status: number;
    headers: Record<string, string>;
    body: string;
    json?: { ok?: boolean; instance_id?: string; status?: string; errors?: unknown };
  }> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/x-www-form-urlencoded',
    };
    if (options.userAgent) headers['User-Agent'] = options.userAgent;
    if (options.acceptJson) headers['Accept'] = 'application/json';
    if (options.cookie) headers['Cookie'] = options.cookie;

    const params = new URLSearchParams();
    params.set('action', action);
    if (options.reason) params.set('reason', options.reason);
    if (options.formData) {
      params.set('form_data', JSON.stringify(options.formData));
    }

    const response = await fetch(`${this.baseUrl}/hitl/action/${token}`, {
      method: 'POST',
      headers,
      body: params.toString(),
      redirect: 'manual',
    });

    const responseHeaders: Record<string, string> = {};
    response.headers.forEach((value: string, key: string) => {
      responseHeaders[key] = value;
    });

    const body = await response.text();
    const result: {
      status: number;
      headers: Record<string, string>;
      body: string;
      json?: { ok?: boolean; instance_id?: string; status?: string; errors?: unknown };
    } = {
      status: response.status,
      headers: responseHeaders,
      body,
    };

    if (options.acceptJson) {
      try {
        result.json = JSON.parse(body) as {
          ok?: boolean;
          instance_id?: string;
          status?: string;
          errors?: unknown;
        };
      } catch {
        // 非 JSON
      }
    }

    return result;
  }

  /**
   * 等待决策页加载完成（locator 等待）。
   * 决策页约定含 data-testid="hitl-decision-form" 容器。
   */
  async waitForDecisionForm(timeout = 10_000): Promise<void> {
    await this.page
      .locator(
        '[data-testid="hitl-decision-form"], form, .decision-form, button:has-text("通过"), button:has-text("提交")',
      )
      .first()
      .waitFor({ state: 'visible', timeout });
  }

  /**
   * 检查浏览器是否设置了 hitl_session_<jti> cookie。
   */
  async hasSessionCookie(jti: string): Promise<boolean> {
    const cookies = await this.page.context().cookies();
    return cookies.some((c) => c.name === `hitl_session_${jti}`);
  }

  /**
   * 获取浏览器内的所有 hitl_session_* cookie 列表（spec 断言用）。
   */
  async getHitlSessionCookies(): Promise<Array<{ name: string; value: string }>> {
    const cookies = await this.page.context().cookies();
    return cookies
      .filter((c) => c.name.startsWith('hitl_session_'))
      .map((c) => ({ name: c.name, value: c.value }));
  }

  /**
   * 填写 form_data 字段（前端 RJSF 渲染的字段）。
   * @param name  field 名（form_schema.properties 的 key）
   * @param value 值
   */
  async fillFormField(name: string, value: string): Promise<void> {
    const input = this.page
      .locator(
        `input[name="${name}"], textarea[name="${name}"], select[name="${name}"], [data-field="${name}"] input, [data-field="${name}"] textarea`,
      )
      .first();
    await input.waitFor({ state: 'visible', timeout: 5_000 });
    await input.fill(value);
  }

  /** 填写 reason textarea */
  async fillReason(text: string): Promise<void> {
    const input = this.page
      .locator(
        'textarea[name="reason"], [data-testid="reason-input"], textarea[placeholder*="原因"], textarea[placeholder*="备注"]',
      )
      .first();
    await input.waitFor({ state: 'visible', timeout: 5_000 });
    await input.fill(text);
  }

  /**
   * 点击 action button（"通过" / "提交" / "退回" / "拒绝"）。
   * @param action  按钮 action
   */
  async clickActionButton(action: HitlAction): Promise<void> {
    const labelMap: Record<HitlAction, string[]> = {
      submit: ['提交', 'Submit'],
      approve: ['通过', '同意', 'Approve'],
      return: ['退回', 'Return'],
      reject: ['拒绝', 'Reject'],
    };

    const labels = labelMap[action];
    for (const label of labels) {
      const button = this.page
        .locator(`button:has-text("${label}"), [data-action="${action}"]`)
        .first();
      if ((await button.count()) > 0) {
        await button.click();
        return;
      }
    }
    throw new Error(`未找到 action button "${action}"（尝试了 ${labels.join(', ')}）`);
  }

  /** 等待成功页（URL 含 /hitl/success/ 或文案"已记录"） */
  async waitForSuccess(timeout = 10_000): Promise<void> {
    await Promise.race([
      this.page.waitForURL(/\/hitl\/success\//, { timeout }),
      this.page
        .locator(
          'text=已记录, text=已提交, [data-testid="hitl-success"], text=Decision recorded',
        )
        .first()
        .waitFor({ state: 'visible', timeout }),
    ]);
  }

  /** 获取错误页文本（用于 410/409/422 等场景）*/
  async getErrorMessage(): Promise<string> {
    const errorEl = this.page
      .locator('[data-testid="hitl-error"], .error-message, [role="alert"]')
      .first();
    if ((await errorEl.count()) === 0) {
      // 退化为 body text
      return await this.page.locator('body').innerText();
    }
    return await errorEl.innerText();
  }

  /** 判断当前页是否是 bot_scan 静态页 */
  async isBotScanPage(): Promise<boolean> {
    const body = await this.page.locator('body').innerText();
    return (
      body.includes('邮件扫描') ||
      body.includes('未触发任何状态变更') ||
      body.includes('bot scan') ||
      body.toLowerCase().includes('scanner')
    );
  }
}
