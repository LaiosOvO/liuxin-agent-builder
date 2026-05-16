---
phase: "02"
plan: "08"
subsystem: "workflow-api-instance-ui"
tags: [fastapi, workflow-crud, instance-api, sse, react, tanstack-query, vitest]
dependency_graph:
  requires: ["02-07"]
  provides: ["workflow-crud-api", "instance-list-api", "instance-detail-ui", "sse-listener", "run-instance-dialog"]
  affects: ["dashboard-pages", "backend-api-v1"]
tech_stack:
  added: []
  patterns: ["WorkspaceScopedQuery 多租户隔离", "URL-based filter state", "SSE EventSource with useReducer merge"]
key_files:
  created:
    - backend/app/agent_builder/schemas/workflow.py
    - backend/app/agent_builder/schemas/instance.py
    - backend/app/agent_builder/services/workflow_service.py
    - backend/app/agent_builder/services/instance_service.py
    - backend/app/agent_builder/api/v1/workflows.py
    - backend/app/agent_builder/api/v1/instances.py
    - backend/app/agent_builder/api/v1/__init__.py
    - backend/tests/test_workflows_api.py
    - backend/tests/test_instances_api.py
    - backend/tests/test_sse_endpoint.py
    - web/src/lib/types/instance.ts
    - web/src/lib/api/instances.ts
    - web/src/components/agent-builder/instances/instance-filter.tsx
    - web/src/components/agent-builder/instances/instances-list.tsx
    - web/src/components/agent-builder/instances/timeline.tsx
    - web/src/components/agent-builder/instances/instance-detail.tsx
    - web/src/components/agent-builder/instances/run-instance-dialog.tsx
    - web/src/components/agent-builder/canvas/sse-listener.tsx
    - web/src/app/dashboard/instances/page.tsx
    - web/src/app/dashboard/instances/[id]/page.tsx
    - web/tests/instances-list.spec.tsx
    - web/tests/instance-filter.spec.tsx
    - web/tests/sse-listener.spec.tsx
  modified:
    - backend/app/agent_builder/main.py
    - web/src/app/dashboard/canvas/[id]/page.tsx
decisions:
  - "validate 路由注册于 /{workflow_id} 之前，避免 FastAPI 路径冲突"
  - "SSE 详情页用 useReducer 合并增量 node 状态，instance 终止后 refetch 同步最终状态"
  - "实例列表采用 page/page_size URL 分页（不采用 Dify cursor 方案），与前端 URL filter 架构一致"
  - "canvas 页面 Run 按钮仅在 workflowStatus===published 时启用，mock 模式禁用"
metrics:
  duration_minutes: 26
  completed_date: "2026-05-16"
  tasks_completed: 4
  files_created: 23
  files_modified: 2
  tests_added: 40
---

# Phase 02 Plan 08: 工作流 CRUD + 实例列表 API + 实例详情 Timeline 摘要

**一句话说明：** 实现工作流草稿/发布 CRUD API（12 个集成测试）+ 实例创建/列表/详情/中止 API（10 个集成测试）+ React 实例列表/详情页含 SSE 实时 Timeline（18 个 vitest 测试）

## 完成的任务

| 任务 | 名称 | Commit | 说明 |
|------|------|--------|------|
| 0 | Dify 阅读文档（硬门禁） | e6aed6f | docs/reading-dify-02-08-instance-list-2026-05-16.md |
| 1 | 工作流 CRUD + Service + 12 集成测试 | adb39fd | workflow_service / workflows.py / test_workflows_api.py |
| 2 | 实例 API + Service + 10 集成测试 | 554a45b | instance_service / instances.py / test_instances_api.py |
| 3 | 前端实例页 + SSE + 18 vitest 测试 | 96aaf87 | instances 页面 / sse-listener / run-instance-dialog |

## 架构决策

### 1. validate 路由注册顺序
FastAPI 的路由匹配采用先注册先匹配策略。`/workflows/validate` 如果在 `/workflows/{workflow_id}` 之后注册，`validate` 字符串会被识别为 `workflow_id` 参数导致 404。解决方案：在 `workflows.py` 中先注册 `/validate`，再注册 `/{workflow_id}` 的子路由。

### 2. SSE 实例详情页状态合并策略
实例详情页用 `useReducer` 维护本地 `NodeMap`（以 node_id 为 key 的字典），SSE 事件（node.start/node.complete/node.error）增量更新本地状态；`instance.complete` / `instance.failed` 触发 `refetch()` 同步服务器最终状态。渲染时合并：`{...serverNodeMap, ...localNodeMap}`，本地 SSE 更新优先，保证实时性。

### 3. 仅活跃实例订阅 SSE
`SseListener` 组件只在 `detail.status === 'pending' || 'running'` 时渲染，终止状态下不创建 EventSource 连接，避免无效连接资源占用。

## Dify 参考

本 Plan 实现参考了以下 Dify 模块（见 docs/reading-dify-02-08-instance-list-2026-05-16.md）：

- `web/app/components/app/workflow-log/index.tsx` — Filter+List+Pagination 三层架构，URL 化 filter 参数
- `web/app/components/app/workflow-log/filter.tsx` — 状态下拉 + 搜索 debounce 模式
- `web/app/components/workflow/run/node.tsx` — NodePanel 状态图标 + getTime 耗时格式化
- `api/core/workflow/entities/workflow.py` — 草稿/发布双态 (draft/published) 版本管理

严禁拷贝 Dify 源码，仅参考设计模式。

## 后端 API 端点一览

| 方法 | 路径 | 权限 |
|------|------|------|
| POST | /api/agent_builder/v1/workflows | editor+ |
| GET | /api/agent_builder/v1/workflows | viewer+ |
| GET | /api/agent_builder/v1/workflows/{id} | viewer+ |
| PUT | /api/agent_builder/v1/workflows/{id} | editor+ |
| DELETE | /api/agent_builder/v1/workflows/{id} | admin |
| PUT | /api/agent_builder/v1/workflows/{id}/draft | editor+ |
| POST | /api/agent_builder/v1/workflows/{id}/publish | editor+ |
| POST | /api/agent_builder/v1/workflows/validate | editor+ |
| POST | /api/agent_builder/v1/workflows/{id}/instances | editor+ |
| GET | /api/agent_builder/v1/instances | viewer+ |
| GET | /api/agent_builder/v1/instances/{id} | viewer+ |
| POST | /api/agent_builder/v1/instances/{id}/abort | editor+ |
| GET | /api/agent_builder/v1/instances/{id}/events | viewer+ (SSE, 02-07) |

## 测试覆盖

**后端（pytest）：**
- test_workflows_api.py — 12 测试（工作流 CRUD、workspace 隔离、RBAC、草稿保存、发布校验）
- test_instances_api.py — 10 测试（启动、过滤、分页、中止）
- test_sse_endpoint.py — 6 测试（SSE 鉴权、replay、Last-Event-ID、自动关闭）

**前端（vitest）：**
- tests/instances-list.spec.tsx — 8 测试
- tests/instance-filter.spec.tsx — 5 测试
- tests/sse-listener.spec.tsx — 5 测试

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] validate 路由顺序冲突**
- **Found during:** Task 1
- **Issue:** `/validate` 注册在 `/{workflow_id}` 之后导致 404
- **Fix:** 在 `workflows.py` 中将 validate 端点移至 workflow_id 动态路由之前注册
- **Files modified:** backend/app/agent_builder/api/v1/workflows.py
- **Commit:** adb39fd

**2. [Rule 1 - Bug] test 事件循环关闭错误**
- **Found during:** Task 1 测试
- **Issue:** pytest-asyncio function-scope 事件循环；部分测试缺少 db_session fixture 导致连接池在错误循环上运行
- **Fix:** 统一给所有测试添加 `two_workspaces, db_session` fixture
- **Files modified:** backend/tests/test_workflows_api.py
- **Commit:** adb39fd

**3. [Rule 1 - Bug] NodeStateInfo retries 字段缺失**
- **Found during:** Task 3 TypeScript 检查
- **Issue:** SSE 合并逻辑创建 node 时未包含 retries 字段，导致 TS 类型错误
- **Fix:** 在 node_start case 中添加 `retries: existing?.retries ?? 0`
- **Files modified:** web/src/app/dashboard/instances/[id]/page.tsx
- **Commit:** 96aaf87

## Self-Check: PASSED
