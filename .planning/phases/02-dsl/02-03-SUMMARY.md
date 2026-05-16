---
phase: "02-dsl"
plan: "03"
subsystem: "web-frontend-canvas"
tags: ["react-flow", "xyflow", "zustand", "canvas", "dsl", "node-palette", "config-panel", "drag-drop"]

dependency_graph:
  requires:
    - "02-01: LangGraph 升级 + Phase 2 业务表"
    - "01-05: Next.js 前端基线（路由树、Zustand、vitest）"
  provides:
    - "DSL TypeScript 类型（与后端 Pydantic schema 对齐）"
    - "Zustand canvas-store（nodes/edges/selectedNodeId 不可变更新）"
    - "DSL ↔ ReactFlow 双向转换器"
    - "5 种自定义节点（start/end/llm/tool/if_else）"
    - "NodePalette 拖拽组件"
    - "ConfigPanel 动态表单（react-hook-form + zod）"
    - "工作流列表页 + 编辑器路由"
  affects:
    - "02-07/02-08: 工作流持久化 API（本 plan 定义 workflowsApi 签名）"
    - "02-09: DSL 实时校验（IssueList 占位待接入）"
    - "02-10: E2E 测试（画布拖拽流程）"

tech_stack:
  added:
    - "@xyflow/react 升级：12.6.0 → 12.10.2"
    - "nanoid（已在 package.json，确认在 dependencies）"
  patterns:
    - "Zustand 5 不可变 store 模式（applyNodeChanges + 扩展运算符）"
    - "ReactFlow v12 自定义节点（NodeProps<T> + Handle + Position）"
    - "拖拽协议：dataTransfer.setData('application/agent-builder-node', type)"
    - "react-hook-form + zod resolver 动态表单（按节点类型切换 schema）"
    - "Next.js App Router 动态路由（canvas/[id]/page.tsx）"
    - "mock=1 查询参数降级到 localStorage 模拟 API"

key_files:
  created:
    - "web/src/lib/types/dsl.ts（DSL 类型 + defaultConfigFor + defaultLabelFor）"
    - "web/src/lib/converters/dsl-to-flow.ts（dslToFlow 函数）"
    - "web/src/lib/converters/flow-to-dsl.ts（flowToDsl 函数）"
    - "web/src/lib/stores/canvas-store.ts（useCanvasStore Zustand store）"
    - "web/src/lib/api/workflows.ts（workflowsApi — 签名，Plan 02-08 接入真实后端）"
    - "web/src/components/agent-builder/canvas/canvas.tsx（ReactFlow 画布主组件）"
    - "web/src/components/agent-builder/canvas/nodes/start-node.tsx"
    - "web/src/components/agent-builder/canvas/nodes/end-node.tsx"
    - "web/src/components/agent-builder/canvas/nodes/llm-node.tsx"
    - "web/src/components/agent-builder/canvas/nodes/tool-node.tsx"
    - "web/src/components/agent-builder/canvas/nodes/if-else-node.tsx"
    - "web/src/components/agent-builder/canvas/nodes/index.ts"
    - "web/src/components/agent-builder/canvas/panels/node-palette.tsx"
    - "web/src/components/agent-builder/canvas/panels/config-panel.tsx"
    - "web/src/components/agent-builder/canvas/panels/issue-list.tsx（占位）"
    - "web/src/app/dashboard/canvas/[id]/page.tsx（工作流编辑器）"
    - "web/tests/canvas-store.spec.ts（8 个测试）"
    - "web/tests/dsl-converter.spec.ts（4 个测试）"
    - "web/tests/canvas-node-palette.spec.tsx（4 个测试）"
    - "web/tests/config-panel.spec.tsx（5 个测试）"
  modified:
    - "web/src/app/dashboard/canvas/page.tsx（Phase 1 占位 → 工作流列表页）"
    - "web/package.json（@xyflow/react ^12.6.0 → ^12.10.2）"

decisions:
  - "@xyflow/react 升到 12.10.2（从 12.6）：v12 API 与 v11 reactflow 不兼容，但已存在于 dependencies；升级非破坏性"
  - "workflowsApi 先写签名不接后端：Plan 02-08 负责实现；?mock=1 允许 localStorage 离线体验"
  - "mock=1 查询参数降级策略：API 未就绪时静默降级，不影响 UI 研发并行进行"
  - "ConfigPanel 按 nodeType switch 而非泛型组件：5 种表单差异大，独立组件可维护性更高"
  - "IssueList 仅为占位：Plan 02-09 接入 DSL 实时校验；占位不影响编辑器整体结构"
  - "pre-existing flock TS 错误（Members/index.tsx）记录 deferred-items.md，不修复（fork discipline）"

metrics:
  duration: "约 15 分钟"
  completed_date: "2026-05-16"
  tasks_completed: 3
  files_created: 20
  files_modified: 2
  test_cases: 21
---

# Phase 2 Plan 03: React Flow Canvas 前端基础实现 Summary

**一句话：** @xyflow/react 12.10 + Zustand canvas-store + 5 种自定义节点 + NodePalette 拖拽 + ConfigPanel 动态表单（react-hook-form + zod）+ DSL ↔ ReactFlow 双向转换，共 21 个 vitest 测试全部通过，工作流编辑器路由替换 Phase 1 占位。

## 实现架构

```
┌────────────────────────────────────────────────────────────────┐
│ /dashboard/canvas/[id]/page.tsx（编辑器）                       │
│  Header: 工作流名编辑 | 保存草稿 | 发布 | 运行（禁用）          │
├──────────┬──────────────────────────────────────┬──────────────┤
│          │                                      │              │
│ NodePalette│      Canvas（ReactFlow）            │ ConfigPanel  │
│  (左 240px)│   onDrop → addNode                 │ (右 360px)  │
│  5 种拖拽│   onConnect → addEdge               │ 动态表单     │
│  draggable│   delete → removeNode/Edge          │ zod 校验     │
│          │                                      │              │
├──────────┴──────────────────────────────────────┴──────────────┤
│ IssueList（占位，Plan 02-09 接入 DSL 校验）                     │
└────────────────────────────────────────────────────────────────┘
```

## 数据流

```
DSL JSON（后端/localStorage）
    ↓ dslToFlow()
ReactFlow {nodes, edges}
    ↓ useCanvasStore（Zustand）
Canvas + ConfigPanel 渲染
    ↓ flowToDsl()
DSL JSON → workflowsApi.saveDraft() / localStorage
```

## 节点类型与颜色

| 节点类型 | 颜色 | Handle 配置 | 表单字段 |
|---------|------|------------|---------|
| start   | 绿色 | 右 source  | label  |
| end     | 红色 | 左 target  | label  |
| llm     | 紫色 | 左 target + 右 source | model/prompt/temperature/retry |
| tool    | 蓝色 | 左 target + 右 source | kind(http/python)/url/function |
| if_else | 橙色 | 左 target + N 右 source | conditions/default_target |

## 测试覆盖

| 测试文件 | 用例数 | 覆盖内容 |
|---------|--------|---------|
| canvas-store.spec.ts | 8 | 初始状态/addNode/唯一ID/位置更新/连线/配置更新/重命名/DSL roundtrip |
| dsl-converter.spec.ts | 4 | dslToFlow/flowToDsl/位置保持/config保持 |
| canvas-node-palette.spec.tsx | 4 | 渲染5种节点/dragStart事件/draggable属性/标题 |
| config-panel.spec.tsx | 5 | 空状态/LLM表单渲染/空model校验/提交更新store/切换节点 |
| **总计** | **21** | — |

全部 21 个新增用例通过，累计 76/76（含 Phase 1 遗留 55 个）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] config-panel.spec.tsx 测试 placeholder 模糊匹配**
- **Found during:** Task 2 测试执行
- **Issue:** `getByPlaceholderText(/支持 Jinja2 变量/)` 匹配到两个 textarea（system_prompt + user_prompt），testing-library 抛出 `Found multiple elements`
- **Fix:** 改用精确 placeholder 字符串 `'支持 Jinja2 变量 {{ start.output }}'`（user_prompt 专属）
- **Files modified:** `web/tests/config-panel.spec.tsx`
- **Commit:** cf34ae2（随 Task 2 提交）

### 计划外调整

**1. pre-existing flock TypeScript 错误**
- `web/src/components/Members/index.tsx:539` 类型不匹配（flock 上游文件）
- `npm run build` 失败，但 `build:no-check` 通过，新增页面编译正常
- 决策：不修复（fork discipline — 不改 flock 上游文件）
- 记录到 `.planning/phases/02-dsl/deferred-items.md`

**2. use(params) — Next.js 15 动态路由 params**
- Next.js 15 App Router 中 params 为 Promise，需用 `use()` 解包
- Plan 中代码片段未体现此变化，执行时自动适配

## Self-Check: PASSED

- 关键文件验证：20/20 FOUND
- 任务 commit 验证：3/3 FOUND（d400807, cf34ae2, 71d7a2d）
- 测试验证：76/76 PASSED（含新增 21 个）
- 构建验证：build:no-check 通过，新增路由全部编译成功
- @xyflow/react 版本：12.10.2（验证：node -e "require('./node_modules/@xyflow/react/package.json').version"）
