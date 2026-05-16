/**
 * DSL 预设构建器
 *
 * 提供 4 种预设 DSL JSON，供 E2E spec 复用，避免每个 spec 内联 DSL 字符串。
 * 设计参考 Dify e2e/support/api.ts 的 syncRunnableWorkflowDraft 模式，
 * 但集中管理多种 DSL 变体以覆盖不同测试场景。
 *
 * 适配本项目 DSL schema（02-02-PLAN.md 定义）：
 *   { version: "1.0", name, state_schema, nodes[], edges[] }
 */

/** DSL 节点位置 */
export interface Position {
  x: number;
  y: number;
}

/** DSL 边 */
export interface DslEdge {
  id: string;
  source: string;
  target: string;
  source_handle?: string;
}

/** DSL 节点 */
export interface DslNode {
  id: string;
  type: string;
  label: string;
  position: Position;
  config: Record<string, unknown>;
}

/** DSL 完整结构 */
export interface DslJson {
  version: string;
  name: string;
  state_schema: Record<string, string>;
  nodes: DslNode[];
  edges: DslEdge[];
}

/**
 * 线性 DSL（3 节点 Start → LLM → End）。
 *
 * 用途：
 * - instance_run_realtime.spec.ts（基本运行验证）
 * - dsl_canvas_drag.spec.ts（发布验证）
 */
export function buildLinearDsl(name = '线性测试工作流'): DslJson {
  return {
    version: '1.0',
    name,
    state_schema: {
      input: 'str',
      output: 'str',
    },
    nodes: [
      {
        id: 'start',
        type: 'start',
        label: '开始',
        position: { x: 80, y: 200 },
        config: {},
      },
      {
        id: 'llm_1',
        type: 'llm',
        label: 'LLM 回声',
        position: { x: 320, y: 200 },
        config: {
          model: 'echo:echo',
          user_prompt: '{{ start.output.input }}',
          temperature: 0.0,
          retry_count: 1,
        },
      },
      {
        id: 'end',
        type: 'end',
        label: '结束',
        position: { x: 560, y: 200 },
        config: {},
      },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm_1' },
      { id: 'e2', source: 'llm_1', target: 'end' },
    ],
  };
}

/**
 * 分支 DSL（5 节点）。
 *
 * 拓扑：Start → LLM → IfElse → (true) Tool → End-A
 *                                → (false) End-B
 *
 * 用途：
 * - dsl_canvas_drag.spec.ts（复杂拓扑拖拽验证）
 * - instance_list_filter.spec.ts（多工作流测试数据准备）
 */
export function buildBranchDsl(name = '分支测试工作流'): DslJson {
  return {
    version: '1.0',
    name,
    state_schema: {
      input: 'str',
      score: 'float',
      result: 'str',
    },
    nodes: [
      {
        id: 'start',
        type: 'start',
        label: '开始',
        position: { x: 80, y: 200 },
        config: {},
      },
      {
        id: 'llm_1',
        type: 'llm',
        label: 'LLM 评分',
        position: { x: 280, y: 200 },
        config: {
          model: 'echo:echo',
          user_prompt: '输入：{{ start.output.input }}',
          temperature: 0.0,
          retry_count: 1,
        },
      },
      {
        id: 'if_else_1',
        type: 'if_else',
        label: '分支判断',
        position: { x: 480, y: 200 },
        config: {
          conditions: [
            {
              id: 'cond_true',
              expr: '{{ llm_1.message | length > 0 }}',
              target: 'tool_1',
            },
          ],
          default_target: 'end_b',
        },
      },
      {
        id: 'tool_1',
        type: 'tool',
        label: 'HTTP 工具',
        position: { x: 680, y: 120 },
        config: {
          kind: 'http',
          method: 'GET',
          url: 'https://httpbin.org/get',
          headers: {},
          body: '',
        },
      },
      {
        id: 'end_a',
        type: 'end',
        label: '结束 A',
        position: { x: 880, y: 120 },
        config: {},
      },
      {
        id: 'end_b',
        type: 'end',
        label: '结束 B',
        position: { x: 680, y: 280 },
        config: {},
      },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm_1' },
      { id: 'e2', source: 'llm_1', target: 'if_else_1' },
      {
        id: 'e3',
        source: 'if_else_1',
        target: 'tool_1',
        source_handle: 'cond_true',
      },
      {
        id: 'e4',
        source: 'if_else_1',
        target: 'end_b',
        source_handle: 'default',
      },
      { id: 'e5', source: 'tool_1', target: 'end_a' },
    ],
  };
}

/**
 * 成环 DSL（故意构造环路 A → B → A）。
 *
 * 用途：
 * - dsl_validation_ui.spec.ts（验证画布拒绝保存 + 显示环路错误）
 */
export function buildCyclicDsl(name = '成环测试工作流'): DslJson {
  return {
    version: '1.0',
    name,
    state_schema: {
      input: 'str',
    },
    nodes: [
      {
        id: 'start',
        type: 'start',
        label: '开始',
        position: { x: 80, y: 200 },
        config: {},
      },
      {
        id: 'llm_a',
        type: 'llm',
        label: 'LLM A',
        position: { x: 320, y: 200 },
        config: {
          model: 'echo:echo',
          user_prompt: '{{ start.output.input }}',
          temperature: 0.0,
          retry_count: 1,
        },
      },
      {
        id: 'llm_b',
        type: 'llm',
        label: 'LLM B',
        position: { x: 560, y: 200 },
        config: {
          model: 'echo:echo',
          user_prompt: '{{ llm_a.message }}',
          temperature: 0.0,
          retry_count: 1,
        },
      },
      {
        id: 'end',
        type: 'end',
        label: '结束',
        position: { x: 800, y: 200 },
        config: {},
      },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm_a' },
      { id: 'e2', source: 'llm_a', target: 'llm_b' },
      // 故意成环：llm_b → llm_a
      { id: 'e3', source: 'llm_b', target: 'llm_a' },
      { id: 'e4', source: 'llm_b', target: 'end' },
    ],
  };
}

/**
 * 变量悬空 DSL（LLM prompt 引用不存在的节点输出 {{ nonexistent.x }}）。
 *
 * 用途：
 * - dsl_validation_ui.spec.ts（验证悬空变量引用错误 UI）
 */
export function buildVariableDanglingDsl(name = '悬空引用测试工作流'): DslJson {
  return {
    version: '1.0',
    name,
    state_schema: {
      input: 'str',
    },
    nodes: [
      {
        id: 'start',
        type: 'start',
        label: '开始',
        position: { x: 80, y: 200 },
        config: {},
      },
      {
        id: 'llm_1',
        type: 'llm',
        label: 'LLM 悬空引用',
        position: { x: 320, y: 200 },
        config: {
          model: 'echo:echo',
          // 故意引用不存在节点输出
          user_prompt: '{{ nonexistent.x }} 来自 {{ start.output.input }}',
          temperature: 0.0,
          retry_count: 1,
        },
      },
      {
        id: 'end',
        type: 'end',
        label: '结束',
        position: { x: 560, y: 200 },
        config: {},
      },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm_1' },
      { id: 'e2', source: 'llm_1', target: 'end' },
    ],
  };
}
