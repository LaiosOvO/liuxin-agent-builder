'use client';

/**
 * useDebouncedValidator — 300ms 防抖 DSL 实时校验 Hook
 *
 * 设计（借鉴 Dify 两阶段校验思路）：
 * - 画布变更（nodes/edges/stateSchema/workflowName）→ 300ms debounce → 本地 TS 校验
 * - 校验结果写入 validator-store，触发节点边框/IssueList 更新
 * - 网络离线时仍可校验（纯本地，不依赖后端）
 *
 * 用法：在画布编辑页面 mount 时调用一次：
 *   function CanvasEditor() {
 *     useDebouncedValidator(300);
 *     // ...
 *   }
 */

import { useEffect } from 'react';
import { useCanvasStore } from '@/lib/stores/canvas-store';
import { useValidatorStore } from '@/lib/stores/validator-store';
import { validateDSL } from '@/lib/validator/dsl-validator';
import type { ValidationError } from '@/lib/validator/types';

/**
 * 300ms 防抖实时校验 Hook
 *
 * @param delay - 防抖延迟毫秒数（默认 300）
 */
export function useDebouncedValidator(delay = 300): void {
  // 订阅画布状态（节点/边/stateSchema/名称）
  const nodes = useCanvasStore((s) => s.nodes);
  const edges = useCanvasStore((s) => s.edges);
  const stateSchema = useCanvasStore((s) => s.stateSchema);
  const workflowName = useCanvasStore((s) => s.workflowName);

  const setResults = useValidatorStore((s) => s.setResults);
  const setValidating = useValidatorStore((s) => s.setValidating);

  useEffect(() => {
    // 立即标记"正在校验"
    setValidating(true);

    const timerId = setTimeout(() => {
      try {
        // 从 canvas-store 获取最新 DSL（避免闭包捕获旧值）
        const dsl = useCanvasStore.getState().exportDSL();
        const errors: ValidationError[] = validateDSL(dsl);
        setResults(errors);
      } catch (e: unknown) {
        // 运行时异常（如 DSL 格式完全损坏）
        const message = e instanceof Error ? e.message : String(e);
        setResults([
          {
            severity: 'error',
            code: 'E_RUNTIME',
            message: `校验器运行时错误：${message}`,
          },
        ]);
      }
    }, delay);

    return () => {
      clearTimeout(timerId);
    };
    // 依赖项：画布状态变化时重新触发
  }, [nodes, edges, stateSchema, workflowName, delay, setResults, setValidating]);
}
