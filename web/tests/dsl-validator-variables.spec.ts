/**
 * DSL 变量引用校验测试（Category 2）
 *
 * 与后端 Python test_dsl_validator_variables.py 用例对应
 */

import { describe, it, expect } from 'vitest';
import { validateDSL } from '@/lib/validator/dsl-validator';
import type { DSL } from '@/lib/types/dsl';

/** 构建含 LLM 节点的标准 DSL */
function llmDSL(
  userPrompt: string,
  overrides?: Partial<{ stateSchema: Record<string, string> }>,
): DSL {
  return {
    version: '1.0',
    name: '变量测试工作流',
    state_schema: overrides?.stateSchema ?? { employee_id: 'str', name: 'str' },
    nodes: [
      { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
      {
        id: 'llm1',
        type: 'llm',
        position: { x: 100, y: 0 },
        config: {
          model: 'openai/gpt-4o',
          user_prompt: userPrompt,
          temperature: 0.7,
          timeout_sec: 30,
          retry_count: 3,
          backoff_base_sec: 1,
        },
      },
      { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm1' },
      { id: 'e2', source: 'llm1', target: 'end' },
    ],
  };
}

describe('DSL 变量引用校验', () => {
  // ─── test_undefined_var ─────────────────────────────────────────────────
  it('test_undefined_var: 引用未定义变量', () => {
    const dsl = llmDSL('你好 {{ nonexistent.output }}');
    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_UNDEFINED_VAR');

    const varErr = errors.find((e) => e.code === 'E_UNDEFINED_VAR');
    expect(varErr?.node_id).toBe('llm1');
  });

  // ─── test_state_field_always_valid ─────────────────────────────────────
  it('test_state_field_always_valid: state_schema 字段始终合法', () => {
    const dsl = llmDSL('员工 ID：{{ employee_id }}，姓名：{{ name }}');
    const errors = validateDSL(dsl);
    const varErrors = errors.filter(
      (e) => e.code === 'E_UNDEFINED_VAR' || e.code === 'E_VAR_NOT_UPSTREAM',
    );
    expect(varErrors).toHaveLength(0);
  });

  // ─── test_upstream_reference_valid ─────────────────────────────────────
  it('test_upstream_reference_valid: 合法的上游引用', () => {
    const dsl = llmDSL('分析：{{ start.output }}');
    const errors = validateDSL(dsl);
    const varErrors = errors.filter(
      (e) => e.code === 'E_UNDEFINED_VAR' || e.code === 'E_VAR_NOT_UPSTREAM',
    );
    expect(varErrors).toHaveLength(0);
  });

  // ─── test_downstream_reference_invalid ────────────────────────────────
  it('test_downstream_reference_invalid: 引用下游节点', () => {
    const dsl: DSL = {
      version: '1.0',
      name: '下游引用测试',
      state_schema: {},
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        {
          id: 'llm1',
          type: 'llm',
          position: { x: 100, y: 0 },
          config: {
            model: 'openai/gpt-4o',
            user_prompt: '{{ llm2.message }}', // 引用下游
            temperature: 0.7,
            timeout_sec: 30,
            retry_count: 3,
            backoff_base_sec: 1,
          },
        },
        {
          id: 'llm2',
          type: 'llm',
          position: { x: 200, y: 0 },
          config: {
            model: 'openai/gpt-4o',
            user_prompt: '你好',
            temperature: 0.7,
            timeout_sec: 30,
            retry_count: 3,
            backoff_base_sec: 1,
          },
        },
        { id: 'end', type: 'end', position: { x: 300, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'llm1' },
        { id: 'e2', source: 'llm1', target: 'llm2' },
        { id: 'e3', source: 'llm2', target: 'end' },
      ],
    };

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_VAR_NOT_UPSTREAM');
  });

  // ─── test_undefined_output_field ──────────────────────────────────────
  it('test_undefined_output_field: 引用不存在的输出字段', () => {
    const dsl = llmDSL('{{ start.nonexistent_field }}');
    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_UNDEFINED_FIELD');

    const fieldErr = errors.find((e) => e.code === 'E_UNDEFINED_FIELD');
    expect(fieldErr?.node_id).toBe('llm1');
    expect(fieldErr?.message).toContain('nonexistent_field');
  });

  // ─── test_valid_output_field ────────────────────────────────────────────
  it('test_valid_output_field: 合法的输出字段引用', () => {
    const dsl = llmDSL('{{ start.output }} 结果');
    const errors = validateDSL(dsl);
    const fieldErrors = errors.filter((e) => e.code === 'E_UNDEFINED_FIELD');
    expect(fieldErrors).toHaveLength(0);
  });
});
