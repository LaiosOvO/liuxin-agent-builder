/**
 * dsl-converter.spec.ts
 * DSL ↔ ReactFlow 双向转换器单元测试
 * 覆盖：dslToFlow / flowToDsl / 位置保持 / config 保持
 */

import { describe, it, expect } from 'vitest';
import { dslToFlow } from '@/lib/converters/dsl-to-flow';
import { flowToDsl } from '@/lib/converters/flow-to-dsl';
import type { DSL } from '@/lib/types/dsl';
import type { Node, Edge } from '@xyflow/react';

/** 示例 DSL */
const sampleDSL: DSL = {
  version: '1.0',
  name: '转换测试工作流',
  state_schema: { result: 'str', count: 'int' },
  nodes: [
    {
      id: 'start',
      type: 'start',
      position: { x: 50, y: 100 },
      config: {},
    },
    {
      id: 'llm_1',
      type: 'llm',
      position: { x: 350, y: 100 },
      config: {
        model: 'openai/gpt-4o',
        user_prompt: '处理 {{start.input}}',
        temperature: 0.5,
      },
    },
    {
      id: 'end',
      type: 'end',
      position: { x: 650, y: 100 },
      config: {},
    },
  ],
  edges: [
    { id: 'e-start-llm', source: 'start', target: 'llm_1' },
    { id: 'e-llm-end', source: 'llm_1', target: 'end' },
  ],
};

describe('dsl-converter', () => {
  it('test_dsl_to_flow：DSL 正确转为 ReactFlow nodes/edges', () => {
    const { nodes, edges } = dslToFlow(sampleDSL);

    expect(nodes).toHaveLength(3);
    expect(edges).toHaveLength(2);

    const startNode = nodes.find((n) => n.id === 'start');
    expect(startNode).toBeDefined();
    expect(startNode?.type).toBe('start');
    expect(startNode?.position).toEqual({ x: 50, y: 100 });
    expect(startNode?.data.config).toEqual({});

    const llmNode = nodes.find((n) => n.id === 'llm_1');
    expect(llmNode).toBeDefined();
    expect(llmNode?.type).toBe('llm');
    expect(llmNode?.data.config).toMatchObject({
      model: 'openai/gpt-4o',
      user_prompt: '处理 {{start.input}}',
    });

    const firstEdge = edges.find((e) => e.id === 'e-start-llm');
    expect(firstEdge?.source).toBe('start');
    expect(firstEdge?.target).toBe('llm_1');
  });

  it('test_flow_to_dsl：ReactFlow nodes/edges 正确反向转为 DSL', () => {
    const rfNodes: Node[] = [
      {
        id: 'start',
        type: 'start',
        position: { x: 0, y: 0 },
        data: { config: {}, label: '开始' },
      },
      {
        id: 'tool_1',
        type: 'tool',
        position: { x: 300, y: 0 },
        data: {
          config: { kind: 'http', http: { method: 'GET', url: 'https://api.example.com', headers: {}, body: '' } },
          label: '工具节点',
        },
      },
    ];
    const rfEdges: Edge[] = [
      { id: 'edge-1', source: 'start', target: 'tool_1' },
    ];

    const dsl = flowToDsl(rfNodes, rfEdges, 'API 调用流', { output: 'str' });

    expect(dsl.version).toBe('1.0');
    expect(dsl.name).toBe('API 调用流');
    expect(dsl.state_schema).toEqual({ output: 'str' });
    expect(dsl.nodes).toHaveLength(2);
    expect(dsl.edges).toHaveLength(1);

    const toolNode = dsl.nodes.find((n) => n.id === 'tool_1');
    expect(toolNode?.type).toBe('tool');
    expect(toolNode?.config).toMatchObject({ kind: 'http' });
  });

  it('test_roundtrip_preserves_position：DSL → RF → DSL 位置 x/y 保持不变', () => {
    const { nodes, edges } = dslToFlow(sampleDSL);
    const exported = flowToDsl(nodes, edges, sampleDSL.name, sampleDSL.state_schema);

    for (const originalNode of sampleDSL.nodes) {
      const exportedNode = exported.nodes.find((n) => n.id === originalNode.id);
      expect(exportedNode?.position).toEqual(originalNode.position);
    }
  });

  it('test_roundtrip_preserves_config：DSL → RF → DSL config 字典保持不变', () => {
    const { nodes, edges } = dslToFlow(sampleDSL);
    const exported = flowToDsl(nodes, edges, sampleDSL.name, sampleDSL.state_schema);

    const originalLlm = sampleDSL.nodes.find((n) => n.id === 'llm_1');
    const exportedLlm = exported.nodes.find((n) => n.id === 'llm_1');

    expect(exportedLlm?.config).toEqual(originalLlm?.config);
  });
});
