---
phase: 02-dsl
plan: "09"
subsystem: 前端 DSL 实时校验
tags: [typescript, validator, zustand, react, ui]
dependency_graph:
  requires: [02-03, 02-08]
  provides: [dsl-validation-frontend, error-ui-three-layer, debounced-checker]
  affects: [canvas-editor, node-components, publish-flow]
tech_stack:
  added:
    - zod（节点 config schema 校验）
    - 自实现 Jinja2 正则扫描器（无 nunjucks 依赖）
  patterns:
    - Zustand store（validator-store：errors/nodeErrorsMap/hasFatalErrors）
    - Kahn 算法拓扑排序（变量上游检查）
    - DFS 白/灰/黑染色（成环检测）
    - BFS 可达性（不可达 End 检测）
    - 300ms debounce（useEffect + setTimeout）
key_files:
  created:
    - web/src/lib/validator/types.ts
    - web/src/lib/validator/jinja-parser.ts
    - web/src/lib/validator/node-schemas.ts
    - web/src/lib/validator/structure.ts
    - web/src/lib/validator/configs.ts
    - web/src/lib/validator/variables.ts
    - web/src/lib/validator/dsl-validator.ts
    - web/src/lib/stores/validator-store.ts
    - web/src/lib/hooks/use-debounced-validator.ts
    - web/src/components/agent-builder/canvas/panels/error-popover.tsx
    - web/tests/dsl-validator-structure.spec.ts
    - web/tests/dsl-validator-variables.spec.ts
    - web/tests/dsl-validator-configs.spec.ts
    - web/tests/validator-debounce.spec.ts
    - web/tests/issue-list.spec.tsx
    - docs/reading-dify-02-09-dsl-validation-2026-05-16.md
  modified:
    - web/src/components/agent-builder/canvas/panels/issue-list.tsx
    - web/src/components/agent-builder/canvas/nodes/start-node.tsx
    - web/src/components/agent-builder/canvas/nodes/end-node.tsx
    - web/src/components/agent-builder/canvas/nodes/llm-node.tsx
    - web/src/components/agent-builder/canvas/nodes/tool-node.tsx
    - web/src/components/agent-builder/canvas/nodes/if-else-node.tsx
    - web/src/app/dashboard/canvas/[id]/page.tsx
decisions:
  - "Jinja 解析器用正则而非 nunjucks（减少 ~300KB bundle，DSL 不需要求值）"
  - "拓扑排序用 Kahn 算法（BFS 风格，比 graphlib 更易 TS 实现）"
  - "成环检测用 DFS 白/灰/黑染色（O(V+E)，与后端 graphlib CycleError 等价）"
  - "节点组件内部管理 popover 开关（useState），不通过全局 store"
  - "发布前后端复检降级策略：validate API 不可用时不阻断发布（network fault tolerance）"
metrics:
  duration_min: 21
  tasks_completed: 2
  files_created: 16
  files_modified: 7
  tests_passing: 33
  completed_at: "2026-05-16"
---

# Phase 2 Plan 09: DSL 实时校验 + 错误 UI 三层 Summary

## 一句话摘要

前端纯 TS DSL 验证器（4 类校验 + Jinja 正则扫描）+ Zustand validator-store + 300ms debounce hook + 节点红框/弹面板/底部 Issue 清单三层错误 UI，完整镜像后端 Python validator 逻辑。

## 完成情况

### Task 0: Dify 阅读文档（硬性 GATE）

读取并分析：
- `web/app/components/workflow/hooks/use-checklist.ts`（580 行）— 两阶段校验架构
- `web/app/components/workflow/nodes/_base/node.helpers.tsx` — getNodeStatusBorders 模式
- `api/services/workflow_service.py` — 后端发布前校验入口

阅读文档：`docs/reading-dify-02-09-dsl-validation-2026-05-16.md`

**Commit:** `80318d7`

### Task 1: TS Validator 模块（4 类校验）

实现 7 个文件：

| 文件 | 职责 |
|------|------|
| `types.ts` | ValidationError 接口 + 18 个错误码常量 |
| `jinja-parser.ts` | Jinja2 正则扫描（collectVariables/extractFieldRefs）|
| `node-schemas.ts` | 5 节点 zod schema + OUTPUT_FIELDS + SCHEMA_TYPES |
| `structure.ts` | 8 类结构检查（DFS 成环/BFS 不可达/孤立节点等）|
| `configs.ts` | 节点 ID 格式/保留字/zod safeParse/if_else 特殊 |
| `variables.ts` | 符号表 + Kahn 拓扑 + 上游引用检查 |
| `dsl-validator.ts` | 主入口（validateDSL/hasFatalErrors/groupErrorsByNode）|

测试：24 个用例全部通过（structure 11 + variables 6 + configs 7）

**Commit:** `3bd35db`

### Task 2: 错误 UI 三层 + validator-store + debounce

**validator-store.ts**：
- `errors[]`：全量错误列表
- `nodeErrorsMap`：按 node_id 索引，节点组件 O(1) 查找
- `hasFatalErrors`：控制发布按钮禁用
- `setResults()`：原子更新（不可变新对象）

**use-debounced-validator.ts**：
- 订阅 canvas-store 的 nodes/edges/stateSchema/workflowName
- useEffect + setTimeout 300ms debounce
- 调 validateDSL() → setResults()

**错误 UI 三层**（借鉴 Dify node.helpers.tsx 边框模式）：
1. 节点边框红：`hasError → border-red-500`；`hasWarning → border-yellow-500`
2. 节点点击弹面板：ErrorPopover（code + message + field_path + 修复建议）
3. 底部 IssueList：聚合全量 errors，按 severity 排序，点击跳转 selectNode()

**page.tsx 修改**：
- 顶层调用 `useDebouncedValidator(300)`
- `hasFatalErrors` 禁用发布按钮
- 发布前调 `workflowsApi.validate(dsl)` 后端权威复检

测试：9 个用例全部通过（validator-store 5 + issue-list 4）

**Commit:** `7f284b8`

## Dify 参考点

参见 `docs/reading-dify-02-09-dsl-validation-2026-05-16.md`：

1. **ChecklistItem 数据结构** → 我们的 `ValidationError`（severity/code/message/node_id/field_path）
2. **getNodeStatusBorders 函数式边框映射** → 节点组件 `cn(hasError && "border-red-500")` 模式
3. **两阶段校验架构** → 前端 300ms debounce（本地 TS）+ 发布前 POST /validate（后端权威）
4. **useMemo + useEffect 分离** → 我们用 useEffect + setTimeout 替代（更易测试）

## 偏差记录

无 — 计划按原方案执行，无意外偏差。

## Self-Check: PASSED

验证文件存在：
- `web/src/lib/validator/dsl-validator.ts` ✓
- `web/src/lib/stores/validator-store.ts` ✓
- `web/src/lib/hooks/use-debounced-validator.ts` ✓
- `web/src/components/agent-builder/canvas/panels/issue-list.tsx` ✓
- `web/src/components/agent-builder/canvas/panels/error-popover.tsx` ✓

验证 commits 存在：
- `80318d7` (docs gate) ✓
- `3bd35db` (task 1) ✓
- `7f284b8` (task 2) ✓

总测试数：33 个 vitest 用例全部通过
