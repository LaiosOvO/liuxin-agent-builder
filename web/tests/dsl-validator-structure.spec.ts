/**
 * DSL 结构校验测试（Category 1 + Category 4 特殊规则）
 *
 * 与后端 Python test_dsl_validator_structure.py 用例一一对应
 */

import { describe, it, expect } from 'vitest';
import { validateDSL } from '@/lib/validator/dsl-validator';
import type { DSL } from '@/lib/types/dsl';

/** 构建最小合法 DSL 工具函数 */
function minimalDSL(overrides?: Partial<DSL>): DSL {
  return {
    version: '1.0',
    name: '测试工作流',
    state_schema: {},
    nodes: [
      { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
      { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'end' },
    ],
    ...overrides,
  };
}

describe('DSL 结构校验', () => {
  // ─── test_cycle_detected ────────────────────────────────────────────────
  it('test_cycle_detected: 检测到成环', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'llm1', type: 'llm', position: { x: 100, y: 0 }, config: { model: 'openai/gpt-4o', user_prompt: 'hi', temperature: 0.7, timeout_sec: 30, retry_count: 3, backoff_base_sec: 1 } },
        { id: 'llm2', type: 'llm', position: { x: 200, y: 0 }, config: { model: 'openai/gpt-4o', user_prompt: 'hi', temperature: 0.7, timeout_sec: 30, retry_count: 3, backoff_base_sec: 1 } },
        { id: 'end', type: 'end', position: { x: 300, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'llm1' },
        { id: 'e2', source: 'llm1', target: 'llm2' },
        { id: 'e3', source: 'llm2', target: 'llm1' }, // 成环
        { id: 'e4', source: 'llm2', target: 'end' },
      ],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_CYCLE');
  });

  // ─── test_unreachable_end ───────────────────────────────────────────────
  it('test_unreachable_end: end 节点从 start 不可达', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'mid', type: 'llm', position: { x: 100, y: 0 }, config: { model: 'openai/gpt-4o', user_prompt: 'hi', temperature: 0.7, timeout_sec: 30, retry_count: 3, backoff_base_sec: 1 } },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'mid' },
        // mid → end 的边缺失，end 不可达
      ],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_UNREACHABLE_END');
  });

  // ─── test_dangling_edge ─────────────────────────────────────────────────
  it('test_dangling_edge: 边指向不存在节点', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'nonexistent' }, // 目标不存在
        { id: 'e2', source: 'start', target: 'end' },
      ],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_DANGLING_EDGE');
  });

  // ─── test_duplicate_node_id ─────────────────────────────────────────────
  it('test_duplicate_node_id: 节点 ID 重复', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'start', type: 'llm', position: { x: 100, y: 0 }, config: {} }, // 重复
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_DUPLICATE_NODE_ID');
  });

  // ─── test_start_has_inbound ─────────────────────────────────────────────
  it('test_start_has_inbound: start 节点有入边', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'mid', type: 'llm', position: { x: 100, y: 0 }, config: { model: 'openai/gpt-4o', user_prompt: 'hi', temperature: 0.7, timeout_sec: 30, retry_count: 3, backoff_base_sec: 1 } },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'mid' },
        { id: 'e2', source: 'mid', target: 'end' },
        { id: 'e3', source: 'mid', target: 'start' }, // start 有入边
      ],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_START_HAS_INBOUND');
  });

  // ─── test_end_has_outbound ──────────────────────────────────────────────
  it('test_end_has_outbound: end 节点有出边', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'mid', type: 'llm', position: { x: 100, y: 0 }, config: { model: 'openai/gpt-4o', user_prompt: 'hi', temperature: 0.7, timeout_sec: 30, retry_count: 3, backoff_base_sec: 1 } },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'mid' },
        { id: 'e2', source: 'mid', target: 'end' },
        { id: 'e3', source: 'end', target: 'mid' }, // end 有出边
      ],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_END_HAS_OUTBOUND');
  });

  // ─── test_no_start ──────────────────────────────────────────────────────
  it('test_no_start: 无 start 节点', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'end', type: 'end', position: { x: 0, y: 0 }, config: {} },
      ],
      edges: [],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_NO_START');
  });

  // ─── test_no_end ────────────────────────────────────────────────────────
  it('test_no_end: 无 end 节点', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'mid', type: 'llm', position: { x: 100, y: 0 }, config: { model: 'openai/gpt-4o', user_prompt: 'hi', temperature: 0.7, timeout_sec: 30, retry_count: 3, backoff_base_sec: 1 } },
      ],
      edges: [{ id: 'e1', source: 'start', target: 'mid' }],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_NO_END');
  });

  // ─── test_multiple_start ────────────────────────────────────────────────
  it('test_multiple_start: 多个 start 节点', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start1', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'start2', type: 'start', position: { x: 0, y: 100 }, config: {} },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start1', target: 'end' },
        { id: 'e2', source: 'start2', target: 'end' },
      ],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_MULTIPLE_START');
  });

  // ─── test_orphan_node ───────────────────────────────────────────────────
  it('test_orphan_node: 孤立节点', () => {
    const dsl = minimalDSL({
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
        { id: 'orphan', type: 'llm', position: { x: 100, y: 200 }, config: {} }, // 孤立
      ],
      edges: [{ id: 'e1', source: 'start', target: 'end' }],
    });

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_ORPHAN_NODE');
    // 孤立节点是 warning 级别
    const orphanErr = errors.find((e) => e.code === 'E_ORPHAN_NODE');
    expect(orphanErr?.severity).toBe('warning');
    expect(orphanErr?.node_id).toBe('orphan');
  });

  // ─── 合法 DSL 无错误 ───────────────────────────────────────────────────
  it('合法的最小 DSL 应无结构错误', () => {
    const dsl = minimalDSL();
    const errors = validateDSL(dsl);
    const structureCodes = [
      'E_CYCLE', 'E_UNREACHABLE_END', 'E_DANGLING_EDGE', 'E_DUPLICATE_NODE_ID',
      'E_START_HAS_INBOUND', 'E_END_HAS_OUTBOUND', 'E_NO_START', 'E_NO_END',
      'E_MULTIPLE_START', 'E_ORPHAN_NODE',
    ];
    const structureErrors = errors.filter((e) => structureCodes.includes(e.code));
    expect(structureErrors).toHaveLength(0);
  });
});
