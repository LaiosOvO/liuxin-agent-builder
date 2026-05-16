/**
 * SseListener 组件测试
 *
 * 验证：
 * - 挂载时创建 EventSource（正确 URL）
 * - 接收 SSE 消息触发 onEvent
 * - 具名事件类型（node.start 等）触发 onEvent
 * - 卸载时关闭 EventSource（source.close()）
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act } from '@testing-library/react';
import { SseListener } from '@/components/agent-builder/canvas/sse-listener';

/** Mock EventSource 实现 */
class MockEventSource {
  url: string;
  withCredentials: boolean;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners: Map<string, ((ev: MessageEvent) => void)[]> = new Map();
  closed = false;

  static instances: MockEventSource[] = [];

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (ev: MessageEvent) => void) {
    const existing = this.listeners.get(type) ?? [];
    this.listeners.set(type, [...existing, handler]);
  }

  /** 模拟服务器发送普通消息 */
  simulateMessage(data: unknown) {
    this.onmessage?.({
      data: JSON.stringify(data),
    } as MessageEvent);
  }

  /** 模拟服务器发送具名事件 */
  simulateNamedEvent(type: string, data: unknown) {
    const handlers = this.listeners.get(type) ?? [];
    const ev = { data: JSON.stringify(data) } as MessageEvent;
    handlers.forEach((h) => h(ev));
  }

  close() {
    this.closed = true;
  }
}

describe('SseListener', () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    // 注入 Mock EventSource 到全局
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('挂载时以正确 URL + withCredentials=true 创建 EventSource', () => {
    render(<SseListener instanceId="inst-001" onEvent={vi.fn()} />);

    expect(MockEventSource.instances).toHaveLength(1);
    const src = MockEventSource.instances[0];
    expect(src.url).toBe('/api/agent_builder/v1/instances/inst-001/events');
    expect(src.withCredentials).toBe(true);
  });

  it('收到普通消息时解析 JSON 并调用 onEvent', async () => {
    const onEvent = vi.fn();
    render(<SseListener instanceId="inst-002" onEvent={onEvent} />);

    const src = MockEventSource.instances[0];
    const payload = { event: 'state.update', key: 'val' };

    await act(async () => {
      src.simulateMessage(payload);
    });

    expect(onEvent).toHaveBeenCalledWith(payload);
  });

  it('收到具名事件（node.start）时触发 onEvent', async () => {
    const onEvent = vi.fn();
    render(<SseListener instanceId="inst-003" onEvent={onEvent} />);

    const src = MockEventSource.instances[0];
    const payload = { node_id: 'start', node_type: 'start' };

    await act(async () => {
      src.simulateNamedEvent('node.start', payload);
    });

    expect(onEvent).toHaveBeenCalledWith({ event: 'node.start', ...payload });
  });

  it('卸载时调用 source.close()', () => {
    const { unmount } = render(<SseListener instanceId="inst-004" onEvent={vi.fn()} />);

    const src = MockEventSource.instances[0];
    expect(src.closed).toBe(false);

    unmount();

    expect(src.closed).toBe(true);
  });

  it('instanceId 变化时重新创建 EventSource', () => {
    const { rerender } = render(<SseListener instanceId="inst-005a" onEvent={vi.fn()} />);

    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toContain('inst-005a');

    rerender(<SseListener instanceId="inst-005b" onEvent={vi.fn()} />);

    // 旧的 source 被关闭，新的 source 被创建
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[0].closed).toBe(true);
    expect(MockEventSource.instances[1].url).toContain('inst-005b');
  });
});
