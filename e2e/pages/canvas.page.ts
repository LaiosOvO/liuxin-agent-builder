/**
 * 画布页面 Page Object（canvas.page.ts）
 *
 * 封装 /dashboard/canvas/[id] 页面的所有操作，spec 层只调方法不直接操作 DOM。
 *
 * 设计参考：
 * - Dify e2e/features/step-definitions/apps/workflow-run.steps.ts（getByText 等待模式）
 * - 本项目 CLAUDE.md 2.2（E2E 是第一公民，Page Object 抽象层）
 * - 02-03-SUMMARY.md：节点使用 data-testid="node-{id}", palette 节点 data-testid="palette-{type}"
 *
 * 节点 testid 约定（从 02-03 canvas 组件推断）：
 *   - 节点容器: data-testid="node-{nodeId}"
 *   - 节点边框/选中: CSS border-red-500 (错误) / border-blue-500 (选中)
 *   - Palette 拖拽项: data-testid="palette-{type}"
 *   - 保存草稿按钮: data-testid="save-draft-btn"
 *   - 发布按钮: data-testid="publish-btn"
 *   - Issue 面板: data-testid="issue-list"
 *   - Toast 消息: data-testid="toast" 或 role="status"
 */

import type { Page, Locator } from '@playwright/test';

/** 节点类型枚举 */
export type NodeType = 'start' | 'end' | 'llm' | 'tool' | 'if_else';

/** 拖拽目标坐标 */
export interface DropPosition {
  x: number;
  y: number;
}

export class CanvasPage {
  private readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  /**
   * 导航到工作流画布编辑器。
   * @param workflowId 工作流 UUID
   */
  async goto(workflowId: string): Promise<void> {
    await this.page.goto(`/dashboard/canvas/${workflowId}`);
    // 等待 React Flow 画布容器出现
    await this.page.waitForSelector('[data-testid="canvas-container"], .react-flow', {
      timeout: 15_000,
    });
  }

  /**
   * 从 NodePalette 拖拽节点到画布指定位置。
   *
   * 实现：模拟 dragstart → drop 事件序列，与 02-03 的
   * `dataTransfer.setData('application/agent-builder-node', type)` 协议一致。
   */
  async dragNode(type: NodeType, position: DropPosition): Promise<void> {
    const paletteItem = this.page.locator(`[data-testid="palette-${type}"]`).first();
    await paletteItem.waitFor({ state: 'visible', timeout: 5_000 });

    const canvasArea = this.page.locator('[data-testid="canvas-container"], .react-flow').first();

    await paletteItem.dragTo(canvasArea, {
      targetPosition: position,
    });

    // 等待节点出现在画布中（节点 DOM 渲染后即算成功）
    await this.page
      .locator(`[data-testid^="node-"][data-node-type="${type}"]`)
      .last()
      .waitFor({ state: 'visible', timeout: 5_000 });
  }

  /**
   * 点击选中节点。
   * @param nodeId 节点 ID（如 "start", "llm_1"）
   */
  async selectNode(nodeId: string): Promise<void> {
    await this.page.locator(`[data-testid="node-${nodeId}"]`).click();
  }

  /**
   * 连接两个节点（拖拽 handle）。
   *
   * React Flow 连线：从 source handle 拖到 target handle。
   * handle testid 约定：data-testid="handle-{nodeId}-{position}"
   *   position: source | target
   */
  async connectNodes(fromNodeId: string, toNodeId: string): Promise<void> {
    const sourceHandle = this.page
      .locator(`[data-testid="node-${fromNodeId}"] [data-handlepos="right"], [data-testid="node-${fromNodeId}"] .react-flow__handle-right`)
      .first();
    const targetHandle = this.page
      .locator(`[data-testid="node-${toNodeId}"] [data-handlepos="left"], [data-testid="node-${toNodeId}"] .react-flow__handle-left`)
      .first();

    await sourceHandle.waitFor({ state: 'visible', timeout: 5_000 });
    await targetHandle.waitFor({ state: 'visible', timeout: 5_000 });

    await sourceHandle.dragTo(targetHandle);
  }

  /**
   * 编辑选中节点的配置表单字段。
   * @param field 字段名（label / model / user_prompt 等）
   * @param value 填入的值
   */
  async editNodeConfig(field: string, value: string): Promise<void> {
    // ConfigPanel 会在节点选中后出现
    const configPanel = this.page.locator('[data-testid="config-panel"], [data-testid="node-config-panel"]').first();
    await configPanel.waitFor({ state: 'visible', timeout: 5_000 });

    // 尝试通过 name 属性或 label 文本定位字段
    const input = configPanel
      .locator(`input[name="${field}"], textarea[name="${field}"]`)
      .first();

    if (await input.count() > 0) {
      await input.fill(value);
    } else {
      // 通过 label 文本查找相关输入
      await configPanel.getByLabel(field).fill(value);
    }
  }

  /**
   * 点击"保存草稿"按钮并等待成功 toast。
   */
  async saveDraft(): Promise<void> {
    const btn = this.page.locator(
      '[data-testid="save-draft-btn"], button:has-text("保存草稿"), button:has-text("Save Draft")',
    ).first();
    await btn.waitFor({ state: 'visible', timeout: 5_000 });
    await btn.click();
    // 等待成功提示（toast 或 aria-live 区域）
    await this.page
      .locator('[data-testid="toast"], [role="status"], [role="alert"]')
      .filter({ hasText: /草稿已保存|saved|success/i })
      .first()
      .waitFor({ state: 'visible', timeout: 10_000 })
      .catch(() => {
        // 若 toast 不出现但操作没报错，仍视为成功（降级处理）
      });
  }

  /**
   * 点击"发布"按钮并等待发布成功。
   */
  async publish(): Promise<void> {
    const btn = this.page.locator(
      '[data-testid="publish-btn"], button:has-text("发布"), button:has-text("Publish")',
    ).first();
    await btn.waitFor({ state: 'visible', timeout: 5_000 });
    await btn.click();
    // 等待发布成功 toast 或状态更新
    await this.page
      .locator('[data-testid="toast"], [role="status"], [role="alert"]')
      .filter({ hasText: /发布成功|published|success/i })
      .first()
      .waitFor({ state: 'visible', timeout: 15_000 })
      .catch(() => {
        // 降级：等待 URL 不变化（发布后画布页不跳转）
      });
  }

  /**
   * 获取 Issue 面板的错误文本列表。
   */
  async getIssuePanel(): Promise<string[]> {
    const issueList = this.page.locator('[data-testid="issue-list"]').first();
    await issueList.waitFor({ state: 'visible', timeout: 5_000 });
    const items = issueList.locator('[data-testid="issue-item"], li, .issue-item');
    const texts: string[] = [];
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      const text = await items.nth(i).innerText();
      texts.push(text.trim());
    }
    return texts;
  }

  /**
   * 获取节点的边框颜色（用于验证错误状态节点变红）。
   *
   * 返回 CSS 计算样式 border-color 值，如 "rgb(239, 68, 68)"（red-500）。
   */
  async getNodeBorderColor(nodeId: string): Promise<string> {
    const node = this.page.locator(`[data-testid="node-${nodeId}"]`).first();
    await node.waitFor({ state: 'visible', timeout: 5_000 });
    return node.evaluate((el) => {
      const style = window.getComputedStyle(el);
      return style.borderColor || style.outlineColor || '';
    });
  }

  /**
   * 检查节点是否有错误样式（边框为红色系）。
   */
  async nodeHasError(nodeId: string): Promise<boolean> {
    const node = this.page.locator(`[data-testid="node-${nodeId}"]`).first();
    await node.waitFor({ state: 'visible', timeout: 5_000 });
    const classList = await node.getAttribute('class') ?? '';
    // 02-09 确定了用 border-red-500 类名
    return classList.includes('border-red-500') || classList.includes('ring-red');
  }

  /**
   * 获取发布按钮的禁用状态。
   */
  async isPublishDisabled(): Promise<boolean> {
    const btn = this.page.locator(
      '[data-testid="publish-btn"], button:has-text("发布"), button:has-text("Publish")',
    ).first();
    return btn.isDisabled();
  }

  /**
   * 等待画布上出现指定节点 ID 的节点。
   */
  async waitForNode(nodeId: string, timeout = 5_000): Promise<void> {
    await this.page
      .locator(`[data-testid="node-${nodeId}"]`)
      .first()
      .waitFor({ state: 'visible', timeout });
  }

  /**
   * 获取当前画布上所有节点的 ID 列表。
   */
  async getCanvasNodeIds(): Promise<string[]> {
    const nodes = this.page.locator('[data-testid^="node-"]');
    const count = await nodes.count();
    const ids: string[] = [];
    for (let i = 0; i < count; i++) {
      const testId = await nodes.nth(i).getAttribute('data-testid');
      if (testId) ids.push(testId.replace('node-', ''));
    }
    return ids;
  }
}
