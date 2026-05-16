/**
 * DSL 节点配置校验测试（Category 3）
 *
 * 与后端 Python test_dsl_validator_configs.py 用例对应
 */

import { describe, it, expect } from 'vitest';
import { validateDSL } from '@/lib/validator/dsl-validator';
import type { DSL } from '@/lib/types/dsl';

/** 构建含 LLM 节点的 DSL */
function dslWithLlm(llmConfig: Record<string, unknown>): DSL {
  return {
    version: '1.0',
    name: '配置校验测试',
    state_schema: {},
    nodes: [
      { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
      { id: 'llm1', type: 'llm', position: { x: 100, y: 0 }, config: llmConfig },
      { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm1' },
      { id: 'e2', source: 'llm1', target: 'end' },
    ],
  };
}

/** 合法 LLM 配置 */
const validLlmConfig = {
  model: 'openai/gpt-4o',
  user_prompt: '你好',
  temperature: 0.7,
  timeout_sec: 30,
  retry_count: 3,
  backoff_base_sec: 1,
};

describe('DSL 节点配置校验', () => {
  // ─── test_invalid_node_id_format ────────────────────────────────────────
  it('test_invalid_node_id_format: 节点 ID 格式不合规', () => {
    const dsl: DSL = {
      version: '1.0',
      name: '配置校验测试',
      state_schema: {},
      nodes: [
        { id: 'Start', type: 'start', position: { x: 0, y: 0 }, config: {} }, // 大写
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [{ id: 'e1', source: 'Start', target: 'end' }],
    };

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_INVALID_NODE_ID');
  });

  // ─── test_reserved_node_id ──────────────────────────────────────────────
  it('test_reserved_node_id: 节点 ID 使用保留字', () => {
    const dsl: DSL = {
      version: '1.0',
      name: '配置校验测试',
      state_schema: {},
      nodes: [
        { id: 'state', type: 'start', position: { x: 0, y: 0 }, config: {} }, // 保留字
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [{ id: 'e1', source: 'state', target: 'end' }],
    };

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_NODE_ID_RESERVED');
  });

  // ─── test_llm_invalid_temperature ──────────────────────────────────────
  it('test_llm_invalid_temperature: LLM 节点 temperature 超出范围', () => {
    const dsl = dslWithLlm({ ...validLlmConfig, temperature: 3.0 }); // > 2

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_INVALID_CONFIG');

    const configErr = errors.find((e) => e.code === 'E_INVALID_CONFIG');
    expect(configErr?.node_id).toBe('llm1');
  });

  // ─── test_llm_invalid_retry_count ──────────────────────────────────────
  it('test_llm_invalid_retry_count: LLM 节点 retry_count 为负数', () => {
    const dsl = dslWithLlm({ ...validLlmConfig, retry_count: -1 }); // < 0

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_INVALID_CONFIG');
  });

  // ─── test_if_else_no_default ────────────────────────────────────────────
  it('test_if_else_no_default: if_else 节点缺少 default_target', () => {
    const dsl: DSL = {
      version: '1.0',
      name: '配置校验测试',
      state_schema: {},
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        {
          id: 'branch',
          type: 'if_else',
          position: { x: 100, y: 0 },
          config: {
            conditions: [
              { expr: '{{ employee_id }}', target_node_id: 'end', label: '有值' },
            ],
            // default_target 缺失
          },
        },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [
        { id: 'e1', source: 'start', target: 'branch' },
      ],
    };

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_IF_ELSE_NO_DEFAULT');

    const ifErr = errors.find((e) => e.code === 'E_IF_ELSE_NO_DEFAULT');
    expect(ifErr?.node_id).toBe('branch');
    expect(ifErr?.field_path).toBe('config.default_target');
  });

  // ─── test_valid_config_no_errors ───────────────────────────────────────
  it('test_valid_config_no_errors: 合法配置无错误', () => {
    const dsl = dslWithLlm(validLlmConfig);
    const errors = validateDSL(dsl);
    const configErrors = errors.filter((e) => e.code === 'E_INVALID_CONFIG');
    expect(configErrors).toHaveLength(0);
  });

  // ─── test_invalid_state_schema_type ─────────────────────────────────────
  it('test_invalid_state_schema_type: state_schema 字段类型不支持', () => {
    const dsl: DSL = {
      version: '1.0',
      name: '类型校验测试',
      state_schema: { field1: 'invalid_type' as never },
      nodes: [
        { id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
        { id: 'end', type: 'end', position: { x: 200, y: 0 }, config: {} },
      ],
      edges: [{ id: 'e1', source: 'start', target: 'end' }],
    };

    const errors = validateDSL(dsl);
    const codes = errors.map((e) => e.code);
    expect(codes).toContain('E_INVALID_STATE_TYPE');
  });
});
