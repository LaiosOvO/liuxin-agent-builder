'use client';

/**
 * SSE 事件监听器组件
 * 参考计划文档中的设计：订阅 GET /api/agent_builder/v1/instances/<id>/events SSE 流
 * 处理 node.start / node.complete / node.error / instance.complete / instance.failed 事件
 *
 * 设计要点（Dify 02-CONTEXT.md）：
 * - EventSource 自动重连（3s 默认），withCredentials=true 带 session cookie
 * - Last-Event-ID 断连补发（EventSource 自动处理）
 * - 返回 null（不渲染 DOM）
 */

import { useEffect } from 'react';
import type { SseEvent, SseEventType } from '@/lib/types/instance';

const SSE_EVENT_TYPES: SseEventType[] = [
  'node.start',
  'node.complete',
  'node.error',
  'state.update',
  'instance.complete',
  'instance.failed',
];

interface SseListenerProps {
  instanceId: string;
  onEvent: (event: SseEvent) => void;
}

/** SSE 实时事件监听器（不渲染 DOM）*/
export function SseListener({ instanceId, onEvent }: SseListenerProps) {
  useEffect(() => {
    const source = new EventSource(
      `/api/agent_builder/v1/instances/${instanceId}/events`,
      { withCredentials: true },
    );

    // 通用消息（无类型 discriminator）
    source.onmessage = (ev) => {
      try {
        onEvent(JSON.parse(ev.data) as SseEvent);
      } catch {
        // 忽略 JSON 解析错误
      }
    };

    // 具名事件类型（discriminated）
    SSE_EVENT_TYPES.forEach((type) => {
      source.addEventListener(type, (ev) => {
        try {
          const data = JSON.parse((ev as MessageEvent).data);
          onEvent({ event: type, ...data } as SseEvent);
        } catch {
          // 忽略
        }
      });
    });

    // onerror：EventSource 会自动重连，无需手动处理
    source.onerror = () => {
      // EventSource 默认 3s 后自动重连，不需要额外操作
    };

    return () => {
      source.close();
    };
  }, [instanceId, onEvent]);

  return null;
}
