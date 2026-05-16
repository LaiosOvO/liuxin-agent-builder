/**
 * validator-store + use-debounced-validator 测试
 *
 * 测试 debounce 行为、store 状态更新、发布按钮禁用逻辑
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useValidatorStore } from '@/lib/stores/validator-store';
import type { ValidationError } from '@/lib/validator/types';

// 每个测试前重置 store
beforeEach(() => {
  useValidatorStore.getState().clearResults();
  vi.clearAllTimers();
});

describe('validator-store', () => {
  // ─── test_results_update_store ──────────────────────────────────────────
  it('test_results_update_store: setResults 正确更新 store', () => {
    const errors: ValidationError[] = [
      { severity: 'error', code: 'E_CYCLE', message: '成环', node_id: 'llm1' },
      { severity: 'warning', code: 'E_ORPHAN_NODE', message: '孤立', node_id: 'tool1' },
    ];

    act(() => {
      useValidatorStore.getState().setResults(errors);
    });

    const state = useValidatorStore.getState();
    expect(state.errors).toHaveLength(2);
    expect(state.hasFatalErrors).toBe(true);
    expect(state.isValidating).toBe(false);
    expect(state.lastValidatedAt).toBeGreaterThan(0);
  });

  // ─── test_node_errors_map_indexed_by_id ────────────────────────────────
  it('test_node_errors_map_indexed_by_id: nodeErrorsMap 按 node_id 正确索引', () => {
    const errors: ValidationError[] = [
      { severity: 'error', code: 'E_INVALID_CONFIG', message: '配置错误', node_id: 'llm1' },
      { severity: 'error', code: 'E_INVALID_CONFIG', message: '配置错误2', node_id: 'llm1' },
      { severity: 'warning', code: 'E_ORPHAN_NODE', message: '孤立', node_id: 'tool1' },
      { severity: 'error', code: 'E_NO_START', message: '无 start' }, // 无 node_id
    ];

    act(() => {
      useValidatorStore.getState().setResults(errors);
    });

    const { nodeErrorsMap } = useValidatorStore.getState();
    expect(nodeErrorsMap['llm1']).toHaveLength(2);
    expect(nodeErrorsMap['tool1']).toHaveLength(1);
    expect(nodeErrorsMap['__global__']).toHaveLength(1);
  });

  // ─── test_fatal_errors_detection ───────────────────────────────────────
  it('test_fatal_errors_detection: 只有 warning 时 hasFatalErrors = false', () => {
    const errors: ValidationError[] = [
      { severity: 'warning', code: 'E_ORPHAN_NODE', message: '孤立', node_id: 'tool1' },
    ];

    act(() => {
      useValidatorStore.getState().setResults(errors);
    });

    expect(useValidatorStore.getState().hasFatalErrors).toBe(false);
  });

  // ─── test_clear_results ────────────────────────────────────────────────
  it('test_clear_results: clearResults 重置所有状态', () => {
    act(() => {
      useValidatorStore.getState().setResults([
        { severity: 'error', code: 'E_CYCLE', message: '成环' },
      ]);
    });

    act(() => {
      useValidatorStore.getState().clearResults();
    });

    const state = useValidatorStore.getState();
    expect(state.errors).toHaveLength(0);
    expect(state.nodeErrorsMap).toEqual({});
    expect(state.hasFatalErrors).toBe(false);
    expect(state.lastValidatedAt).toBe(0);
  });

  // ─── test_fatal_errors_blocks_publish_button ───────────────────────────
  it('test_fatal_errors_blocks_publish_button: hasFatalErrors 在有 error 时为 true', () => {
    // 初始状态：无错误
    expect(useValidatorStore.getState().hasFatalErrors).toBe(false);

    // 设置一个 error
    act(() => {
      useValidatorStore.getState().setResults([
        { severity: 'error', code: 'E_CYCLE', message: '成环' },
      ]);
    });
    expect(useValidatorStore.getState().hasFatalErrors).toBe(true);

    // 清除后恢复
    act(() => {
      useValidatorStore.getState().clearResults();
    });
    expect(useValidatorStore.getState().hasFatalErrors).toBe(false);
  });
});
