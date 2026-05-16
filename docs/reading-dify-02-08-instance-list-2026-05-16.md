# Dify 阅读笔记 — Workflow CRUD + Instance 列表 + 详情 Timeline

> 日期: 2026-05-16
> 仓库: https://github.com/langgenius/dify (commit e7e6fe88, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k

## 项目概述（一句话）

Dify 是成熟的开源工作流编排平台，workflow CRUD 走草稿/发布双态版本管理，实例（WorkflowRun）通过无限滚动分页 + status/keyword/time_range 三维过滤，详情页通过 NodeExecution 列表渲染 Timeline。

## 技术栈（关键技术选择）

- 后端：Flask / Flask-RESTx + SQLAlchemy（同步 ORM）
- 实例列表分页：**Cursor/无限滚动分页**（`last_id` + `limit`，非 page/offset）
- 实例详情 Timeline：`WorkflowRun` + `WorkflowNodeExecutionModel` 一对多关联
- 前端：React + `ahooks.useDebounce` debounce 过滤 + React Query（`useWorkflowLogs`）
- 节点状态图标：RiAlertFill / RiCheckboxCircleFill / RiErrorWarningFill / RiLoader2Line 按状态区分

## 架构要点（核心架构模式，用简图说明）

```
API Controller (workflow.py / workflow_run.py)
      │
      ├─ WorkflowService     ── save_draft / publish / validate
      │       │                  (草稿/发布双态；发布前全量校验 DSL)
      │       └─ Workflow ORM ── has_one: current_draft_version, current_published_version
      │
      └─ WorkflowRunService  ── paginate_runs (cursor-based) / get_run_detail
              │
              ├─ WorkflowRun ORM   ── 实例主记录 (status/inputs/outputs/elapsed_time)
              └─ WorkflowNodeExecution ORM ── 每节点一行（status/inputs/outputs/error）

前端 Timeline 渲染：
  components/app/workflow-log/index.tsx   ── 列表页（Filter + List + Pagination）
  components/app/workflow-log/list.tsx    ── 表格行（status badge/created_at/elapsed_time）
  components/app/workflow-log/detail.tsx  ── 抽屉详情（WorkflowContextProvider + Run 组件）
  components/workflow/run/node.tsx        ── 单节点 Timeline 行（status/duration/error/output）
```

## 可借鉴的设计模式（具体文件路径 + 模式名 + 一句话说明）

### 1. 草稿/发布双态版本管理
**文件**: `api/services/workflow_service.py`, `api/models/workflow.py`
**模式**: 草稿版本 (`kind="draft"`) 与发布版本 (`kind="published"`) 分离存储，发布时全量 DSL 校验通过后创建新版本快照，Workflow 主表保存两个版本指针。
**借鉴**: 我们的 `WorkflowService.save_draft()` 和 `publish()` 直接对应，版本号 draft=0, published=1/2/3+。

### 2. Cursor 无限滚动分页（而非 page/offset）
**文件**: `api/controllers/console/app/workflow_run.py` (`WorkflowRunListQuery`)
**模式**: 用 `last_id + limit` 替代 `page + page_size`，避免大分页 offset 性能问题，支持 100 条/页上限。
**借鉴差异**: 我们 Plan 02-08 要求 URL 化 + 固定 page/page_size，保留传统分页。但生产环境可考虑切换。

### 3. 实例状态 filter 枚举
**文件**: `api/controllers/console/app/workflow_run.py`
**模式**: `WORKFLOW_RUN_STATUS_CHOICES = ["running", "succeeded", "failed", "stopped", "partial-succeeded"]`，前端显示与后端 status 字段对齐。
**借鉴**: 我们用 pending/running/completed/failed/aborted，前端 filter 组件选项与此枚举对应。

### 4. 节点 Timeline 渲染（status + duration + error）
**文件**: `web/app/components/workflow/run/node.tsx`
**模式**: `NodePanel` 组件接收 `nodeInfo: NodeTracing`，根据 status 显示不同图标（运行中/完成/失败/暂停），时间格式化 `getTime(t)` 支持 ms/s/min 三级自适应。
**借鉴**: 我们的 `timeline.tsx` 按此设计渲染每个 NodeState 记录，status badge + elapsed time + error message。

### 5. Filter + List 分离架构
**文件**: `web/app/components/app/workflow-log/filter.tsx`, `list.tsx`, `index.tsx`
**模式**: Filter 组件接收 `queryParams` + `setQueryParams`，父组件统一管理查询状态，通过 `useDebounce` 控制 API 请求频率，分页状态在父组件。
**借鉴**: 我们的 `instance-filter.tsx` + `instances-list.tsx` + `page.tsx` 采用相同分层，URL query 化代替纯 state。

### 6. WorkflowRun Detail 抽屉
**文件**: `web/app/components/app/workflow-log/detail.tsx`
**模式**: 详情页通过 `WorkflowContextProvider` + `Run` 组件渲染完整 trace（复用画布 run 组件），按钮"以参数重跑"跳转画布 `?replayRunId=xxx`。
**借鉴**: 我们的 instance detail page 展示 NodeState timeline + "abort" / "以相同 input 重跑" 按钮，跳转逻辑类似。

### 7. DSL 校验在 save_draft 与 publish 两处都做
**文件**: `api/services/workflow_service.py`（validate 在 draft 存储前和 publish 前均调用）
**模式**: save_draft 允许 warning 级别通过，fatal error 422 返回；publish 必须 error-free 才执行版本快照创建。
**借鉴**: 直接对应我们 `WorkflowService.save_draft()` 的 `fatal = [e for e in errors if e.severity == "error"]` 逻辑。

### 8. 跨 workspace 隔离（Dify 用 app_id 限定）
**文件**: `api/controllers/console/app/workflow_run.py` (`@get_app_model`)
**模式**: 每个请求通过 `app_model` 限定 app 归属，WorkflowRun.app_id = app_model.id 防跨应用访问。
**借鉴**: 我们用 `WorkspaceScopedQuery.select(FlowInstance)` 自动注入 workspace_id WHERE，语义等价。

## 与本项目的关系（如何应用到当前 plan）

**Plan 02-08 直接对应 Dify 三个模块**：

| 我们实现 | 对应 Dify | 关键借鉴 |
|---------|----------|---------|
| `workflow_service.py` | `api/services/workflow_service.py` | save_draft/publish 双态 + fatal error 判断 |
| `api/v1/workflows.py` | `api/controllers/console/app/workflow.py` | 7 个端点结构 + validate 独立端点 |
| `instance_service.py` | `api/services/workflow_run_service.py` | list 过滤查询 + get detail with node_states |
| `api/v1/instances.py` | `api/controllers/console/app/workflow_run.py` | status filter 枚举 + pagination |
| `instances/page.tsx` | `web/app/components/app/workflow-log/index.tsx` | Filter + debounce + 分页 |
| `timeline.tsx` | `web/app/components/workflow/run/node.tsx` | 节点状态图标 + duration 格式化 |
| `instance-filter.tsx` | `web/app/components/app/workflow-log/filter.tsx` | status select + search input 分离 |

**关键差异**：
1. Dify 用 cursor 分页（last_id），我们用 page/page_size（URL 化要求）
2. Dify 实例状态 succeeded/failed/stopped，我们用 completed/failed/aborted
3. Dify Flask sync，我们 FastAPI async（service 层均为 async def）
4. 我们额外有 SSE 实时刷新（EventSource），Dify 靠前端 polling
