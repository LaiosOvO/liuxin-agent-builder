/**
 * 申请人追踪页 Page Object（tracking.page.ts）
 *
 * 封装 /dashboard/instances/[id]/tracking 路径的所有操作（需要登录）。
 *
 * Phase 3 HITL-07 设计要点（03-08-SUMMARY 落地）：
 * - applicant_id == current_user.id 才可访问，否则 403
 * - 跨 workspace → 404（不泄漏存在性）
 * - admin 视角看到完整 ip/ua；申请人脱敏
 * - current_node banner（HITL active 节点优先）
 * - records timeline 倒序展示
 * - DeadlineCountdown 3 级颜色（urgent < 1h / warning < 6h / normal）
 */

import type { Page } from '@playwright/test';

/** 节点状态（与后端 schemas/tracking.py 对齐） */
export type TrackingNodeStatus =
  | 'pending'
  | 'waiting_human'
  | 'in_review'
  | 'done'
  | 'rejected'
  | 'returned';

/** decision action（5 态） */
export type TrackingAction =
  | 'submit'
  | 'approve'
  | 'return'
  | 'reject'
  | 'escalate';

export class TrackingPage {
  private readonly page: Page;
  private readonly baseUrl: string;

  constructor(page: Page, baseUrl = 'http://localhost:8080') {
    this.page = page;
    this.baseUrl = baseUrl;
  }

  /**
   * 导航到追踪页：/dashboard/instances/<instanceId>/tracking。
   */
  async goto(instanceId: string): Promise<void> {
    await this.page.goto(`/dashboard/instances/${instanceId}/tracking`, {
      waitUntil: 'networkidle',
      timeout: 15_000,
    });
  }

  /**
   * 用裸 fetch 调用 GET /api/agent_builder/v1/instances/<id>/tracking。
   *
   * @param instanceId  实例 UUID
   * @param cookie      认证 cookie
   * @returns           { status, json | text }
   */
  async fetchTrackingRaw(
    instanceId: string,
    cookie: string,
  ): Promise<{
    status: number;
    json?: TrackingResponse;
    text?: string;
  }> {
    const response = await fetch(
      `${this.baseUrl}/api/agent_builder/v1/instances/${instanceId}/tracking`,
      {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
          'Cookie': cookie,
        },
      },
    );

    const body = await response.text();
    try {
      return { status: response.status, json: JSON.parse(body) as TrackingResponse };
    } catch {
      return { status: response.status, text: body };
    }
  }

  /**
   * 等待追踪页加载完成（看到 instance_id 信息卡 / current_node banner / records timeline）。
   */
  async waitForLoaded(timeout = 10_000): Promise<void> {
    await this.page
      .locator(
        '[data-testid="tracking-timeline"], [data-testid="current-node-banner"], h1:has-text("流程进度"), h1:has-text("追踪")',
      )
      .first()
      .waitFor({ state: 'visible', timeout });
  }

  /**
   * 获取 current_node banner 的节点状态。
   */
  async getCurrentNodeStatus(): Promise<TrackingNodeStatus | null> {
    const banner = this.page
      .locator('[data-testid="current-node-banner"]')
      .first();
    if ((await banner.count()) === 0) return null;
    const status = await banner.getAttribute('data-status');
    return (status as TrackingNodeStatus | null) ?? null;
  }

  /**
   * 获取 records 时间线条目数。
   */
  async getRecordsCount(): Promise<number> {
    return this.page.locator('[data-testid^="record-row-"]').count();
  }

  /**
   * 获取 records 时间线条目（按倒序）。
   */
  async getRecordsTimeline(): Promise<
    Array<{
      action: string;
      actor: string;
      ts: string;
      reason?: string;
    }>
  > {
    const rows = await this.page.locator('[data-testid^="record-row-"]').all();
    const result: Array<{
      action: string;
      actor: string;
      ts: string;
      reason?: string;
    }> = [];

    for (const row of rows) {
      const action = (await row.getAttribute('data-action')) ?? '';
      const actor =
        (await row.locator('[data-field="actor"]').innerText().catch(() => '')) ?? '';
      const ts = (await row.locator('[data-field="ts"]').innerText().catch(() => '')) ?? '';
      const reason = await row
        .locator('[data-field="reason"]')
        .innerText()
        .catch(() => undefined);

      result.push({ action, actor, ts, reason });
    }

    return result;
  }

  /**
   * 获取申请人信息（顶部信息卡）。
   */
  async getApplicantInfo(): Promise<{ email?: string; name?: string }> {
    const card = this.page.locator('[data-testid="applicant-info"]').first();
    if ((await card.count()) === 0) return {};

    const email = await card
      .locator('[data-field="email"]')
      .innerText()
      .catch(() => undefined);
    const name = await card
      .locator('[data-field="name"]')
      .innerText()
      .catch(() => undefined);

    return { email, name };
  }

  /**
   * 断言申请人视角看不到 IP/UA（CONTEXT §申请人追踪页隐私）。
   * 用法：const isLeaked = await trackingPage.hasIpOrUaVisible();
   *      expect(isLeaked, '申请人视角不应看到 IP/UA').toBe(false);
   */
  async hasIpOrUaVisible(): Promise<boolean> {
    const bodyText = await this.page.locator('body').innerText();
    // 简单粗暴：搜常见的 IP 模式（如 192.168.x.x）+ user-agent 关键字
    const ipPattern = /\b(\d{1,3}\.){3}\d{1,3}\b/;
    const uaPattern = /Mozilla\/|Chrome\/|Safari\/|MSIE/i;
    return ipPattern.test(bodyText) || uaPattern.test(bodyText);
  }

  /**
   * 获取 deadline countdown 当前显示的剩余时间文本。
   */
  async getDeadlineCountdownText(): Promise<string | null> {
    const el = this.page.locator('[data-testid="deadline-countdown"]').first();
    if ((await el.count()) === 0) return null;
    return await el.innerText();
  }
}

/**
 * 后端 GET /api/agent_builder/v1/instances/<id>/tracking 响应结构
 * （与 backend/app/agent_builder/schemas/tracking.py 对齐）
 */
export interface TrackingResponse {
  instance_id: string;
  workflow_id: string;
  workflow_name?: string;
  status: string;
  applicant: {
    user_id?: string;
    email?: string;
    name?: string;
  };
  current_node: {
    id?: string;
    title?: string;
    status: TrackingNodeStatus;
    node_type?: string;
    actor?: string;
    deadline_at?: string;
    started_at?: string;
  } | null;
  records: Array<{
    actor_email?: string;
    action: string;
    ts: string;
    reason?: string;
    /** 申请人视角应该为 null；admin 视角有值 */
    ip?: string | null;
    /** 申请人视角应该为 null；admin 视角有值 */
    ua?: string | null;
  }>;
  started_at?: string;
  completed_at?: string;
}
