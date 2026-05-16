/**
 * Validator Zustand Store
 *
 * 缓存 DSL 校验结果，供所有节点组件和 Issue 清单订阅。
 *
 * 设计要点（借鉴 Dify use-checklist.ts 思路）：
 * - errors[]：全量错误列表，供 IssueList 渲染
 * - nodeErrorsMap：按 node_id 索引，供各节点组件快速查找
 * - hasFatalErrors：是否有 error 级别错误（控制发布按钮禁用）
 * - isValidating：校验进行中标志（防止并发）
 * - setResults()：原子更新上述所有字段（不可变）
 */

import { create } from 'zustand';
import type { ValidationError } from '@/lib/validator/types';

/** Validator Store 状态与操作接口 */
interface ValidatorState {
  /** 全量错误列表 */
  errors: ValidationError[];
  /** 按 node_id 索引的错误 Map */
  nodeErrorsMap: Record<string, ValidationError[]>;
  /** 是否有致命错误（severity=error） */
  hasFatalErrors: boolean;
  /** 是否正在校验中 */
  isValidating: boolean;
  /** 最后校验时间戳（毫秒） */
  lastValidatedAt: number;

  /** 原子设置校验结果 */
  setResults: (errors: ValidationError[]) => void;
  /** 设置校验进行中状态 */
  setValidating: (val: boolean) => void;
  /** 清空所有校验结果 */
  clearResults: () => void;
}

export const useValidatorStore = create<ValidatorState>((set) => ({
  errors: [],
  nodeErrorsMap: {},
  hasFatalErrors: false,
  isValidating: false,
  lastValidatedAt: 0,

  setResults: (errors: ValidationError[]) => {
    // 构造 nodeErrorsMap（不可变新对象）
    const nodeErrorsMap: Record<string, ValidationError[]> = {};
    for (const err of errors) {
      const key = err.node_id ?? '__global__';
      if (!nodeErrorsMap[key]) {
        nodeErrorsMap[key] = [];
      }
      nodeErrorsMap[key].push(err);
    }

    set({
      errors: [...errors],
      nodeErrorsMap,
      hasFatalErrors: errors.some((e) => e.severity === 'error'),
      isValidating: false,
      lastValidatedAt: Date.now(),
    });
  },

  setValidating: (val: boolean) => set({ isValidating: val }),

  clearResults: () =>
    set({
      errors: [],
      nodeErrorsMap: {},
      hasFatalErrors: false,
      isValidating: false,
      lastValidatedAt: 0,
    }),
}));
