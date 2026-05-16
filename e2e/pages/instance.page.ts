/**
 * 实例详情页面 Page Object（instance.page.ts）
 *
 * 封装 /dashboard/instances/[id] 或实例详情面板的所有操作。
 *
 * 核心功能：
 * - 订阅 SSE 事件流（用 page.evaluate + EventSource，ROADMAP #2 关键验证）
 * - 轮询 DOM 获取节点状态
 * - 等待实例完成
 *
 * SSE 端点（02-07-SUMMARY 确认）：
 *   GET /api/agent_builder/v1/instances/{id}/events
 *   事件类型：node.start / node.complete / node.error / instance.complete / instance.failed
 *
 * 实例列表端点（02-08-SUMMARY 确认）：
 *   GET /api/agent_builder/v1/instances?workflow_id=&status=&search=&page=&page_size=
 */

import type { Page } from '@playwright/test';

/** 节点执行状态 */
export type NodeStatus = 'pending' | 'running' | 'done' | 'failed';

/** SSE 事件 */
export interface SseEvent {
  event: string;
  node_id?: string;
  instance_id: string;
  timestamp: string;
  data?: Record<string, unknown>;
}

/** SSE 收集结果 */
export interface SseCollectionResult {
  events: SseEvent[];
  timedOut: boolean;
}

export class InstancePage {
  private readonly page: Page;
  private readonly baseUrl: string;

  constructor(page: Page, baseUrl = 'http://localhost:8080') {
    this.page = page;
    this.baseUrl = baseUrl;
  }

  /**
   * 导航到实例详情页。
   * @param instanceId 实例 UUID
   */
  async goto(instanceId: string): Promise<void> {
    await this.page.goto(`/dashboard/instances/${instanceId}`);
    await this.page.waitForLoadState('networkidle', { timeout: 10_000 });
  }

  /**
   * 点击"运行"按钮启动实例。
   * 通常在工作流详情页或画布页面上调用。
   */
  async clickRun(): Promise<void> {
    const runBtn = this.page.locator(
      '[data-testid="run-btn"], button:has-text("运行"), button:has-text("Run")',
    ).first();
    await runBtn.waitFor({ state: 'visible', timeout: 5_000 });
    await runBtn.click();
  }

  /**
   * 从 DOM 获取指定节点的当前状态。
   *
   * 约定 testid（02-08 SSE 详情页）：
   *   [data-testid="node-status-{nodeId}"]，text 内容为状态字符串
   */
  async getNodeStatus(nodeId: string): Promise<NodeStatus> {
    const statusEl = this.page
      .locator(`[data-testid="node-status-${nodeId}"], [data-node-id="${nodeId}"][data-status]`)
      .first();
    await statusEl.waitFor({ state: 'attached', timeout: 5_000 });

    // 尝试从 data-status 属性读取
    const dataStatus = await statusEl.getAttribute('data-status');
    if (dataStatus) {
      return dataStatus as NodeStatus;
    }

    // 退回读文本内容
    const text = (await statusEl.innerText()).toLowerCase();
    if (text.includes('running')) return 'running';
    if (text.includes('done') || text.includes('complete') || text.includes('success')) return 'done';
    if (text.includes('failed') || text.includes('error')) return 'failed';
    return 'pending';
  }

  /**
   * 等待实例达到完成或失败终态。
   * @param timeout 最大等待毫秒数（默认 60s）
   */
  async waitForInstanceComplete(timeout = 60_000): Promise<'completed' | 'failed'> {
    const start = Date.now();

    while (Date.now() - start < timeout) {
      const statusEl = this.page
        .locator('[data-testid="instance-status"]')
        .first();

      if (await statusEl.count() > 0) {
        const text = (await statusEl.innerText()).toLowerCase();
        if (text.includes('completed') || text.includes('complete') || text.includes('success')) {
          return 'completed';
        }
        if (text.includes('failed') || text.includes('error')) {
          return 'failed';
        }
      }

      await this.page.waitForTimeout(500);
    }

    throw new Error(`实例在 ${timeout}ms 内未到达终态`);
  }

  /**
   * 订阅实例的 SSE 事件流，收集所有事件直到 instance.complete 或超时。
   *
   * 使用 page.evaluate 在浏览器沙箱内建立 EventSource，保证：
   * 1. 携带 session cookie（浏览器原生行为）
   * 2. 真实的 SSE 连接（非 mock）
   * 3. 不受 Node.js EventSource polyfill 限制
   *
   * @param instanceId 实例 UUID
   * @param timeout    最大等待毫秒数（默认 30s）
   * @returns          收集到的事件数组 + 是否超时
   */
  async listenSseEvents(
    instanceId: string,
    timeout = 30_000,
  ): Promise<SseCollectionResult> {
    const sseUrl = `${this.baseUrl}/api/agent_builder/v1/instances/${instanceId}/events`;

    return this.page.evaluate(
      async ({ url, maxTimeout }: { url: string; maxTimeout: number }) => {
        return new Promise<{ events: SseEvent[]; timedOut: boolean }>((resolve) => {
          const events: SseEvent[] = [];
          let resolved = false;

          // 定义在 evaluate 内的接口（浏览器环境）
          interface SseEvent {
            event: string;
            node_id?: string;
            instance_id: string;
            timestamp: string;
            data?: Record<string, unknown>;
          }

          const es = new EventSource(url, { withCredentials: true });

          const finish = (timedOut: boolean) => {
            if (!resolved) {
              resolved = true;
              es.close();
              resolve({ events, timedOut });
            }
          };

          es.onmessage = (e: MessageEvent) => {
            try {
              const evt: SseEvent = JSON.parse(e.data as string) as SseEvent;
              events.push(evt);
              // 终止条件：收到 instance 完成事件
              if (evt.event === 'instance.complete' || evt.event === 'instance.failed') {
                finish(false);
              }
            } catch {
              // JSON 解析失败忽略
            }
          };

          es.onerror = () => {
            // SSE 断连不立即终止，等到超时
          };

          // 超时兜底
          setTimeout(() => finish(true), maxTimeout);
        });
      },
      { url: sseUrl, maxTimeout: timeout },
    );
  }

  /**
   * 在第二个浏览器上下文中监听同一实例的 SSE 事件。
   * 用于验证 Redis pub/sub fan-out（多浏览器订阅同一实例都收到事件）。
   *
   * @param instanceId  实例 UUID
   * @param secondPage  第二个浏览器 page 对象
   * @param timeout     最大等待毫秒数
   */
  async listenSseEventsFromPage(
    instanceId: string,
    secondPage: Page,
    timeout = 30_000,
  ): Promise<SseCollectionResult> {
    const sseUrl = `${this.baseUrl}/api/agent_builder/v1/instances/${instanceId}/events`;

    return secondPage.evaluate(
      async ({ url, maxTimeout }: { url: string; maxTimeout: number }) => {
        return new Promise<{ events: SseEvent[]; timedOut: boolean }>((resolve) => {
          const events: SseEvent[] = [];
          let resolved = false;

          interface SseEvent {
            event: string;
            node_id?: string;
            instance_id: string;
            timestamp: string;
            data?: Record<string, unknown>;
          }

          const es = new EventSource(url, { withCredentials: true });
          const finish = (timedOut: boolean) => {
            if (!resolved) {
              resolved = true;
              es.close();
              resolve({ events, timedOut });
            }
          };

          es.onmessage = (e: MessageEvent) => {
            try {
              const evt: SseEvent = JSON.parse(e.data as string) as SseEvent;
              events.push(evt);
              if (evt.event === 'instance.complete' || evt.event === 'instance.failed') {
                finish(false);
              }
            } catch {
              // ignore
            }
          };

          setTimeout(() => finish(true), maxTimeout);
        });
      },
      { url: sseUrl, maxTimeout: timeout },
    );
  }
}
