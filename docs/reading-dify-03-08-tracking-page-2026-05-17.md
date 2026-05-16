# Dify 阅读笔记 — 申请人追踪页（Plan 03-08）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k

## 1. 项目概述（一句话）

Dify 是国内最成熟的 LLM 工作流开源平台（141k stars），其 console 端实例详情 API（workflow_run.py）+ 前端 workflow-log 组件提供了"运行列表 + 详情 + 节点执行序列"三件套，本 plan 用其作为申请人追踪页的设计参考。

## 2. 技术栈

| 维度 | Dify | 本项目 03-08 |
| --- | --- | --- |
| 后端 Web 框架 | Flask + Flask-Restx | FastAPI + Pydantic v2 |
| ORM 查询 | SQLAlchemy + factory pattern repositories | SQLAlchemy 2.x + WorkspaceScopedQuery |
| 多租户 | tenant_id（与 current_user.current_tenant_id 比较） | workspace_id（WorkspaceScopedQuery 自动注入） |
| 实例 ID | workflow_run.id (UUID) | flow_instances.id (UUID) |
| 节点执行序列 | WorkflowRunNodeExecution（独立表） | node_states + node_states.payload.records（HITL 决策聚合） |
| 前端 | Next.js + dify-ui + react-i18next | Next.js 16 + Tailwind |

## 3. 架构要点

### 3.1 Dify 实例详情 API 流程

```
GET /apps/<app_id>/workflow-runs/<run_id>
  ↓
get_app_model() decorator → 加载 App + 校验 tenant 归属
  ↓
WorkflowRunService.get_workflow_run(app_model, run_id)
  ↓
DB SELECT WorkflowRun WHERE id=:run_id AND tenant_id=:app.tenant_id
  ↓
not found → NotFoundError(404)
found → WorkflowRunDetailResponse(model_validate)
  ↓
return model_dump(mode='json')
```

关键点：
1. **`@get_app_model()` decorator 在 controller 层完成 tenant 校验**：URL 中的 `<app_id>` 必须属于 `current_user.current_tenant_id`，否则 404。这是 Dify 多租户隔离的"第一道门"。
2. **Service 层负责 DB 查询 + 二次校验**：service 内还做 `workflow_run.tenant_id != current_user.current_tenant_id → NotFoundError`（防御性双重检查）。
3. **节点执行序列单独 endpoint**：`GET /apps/<app_id>/workflow-runs/<run_id>/node-executions` 返回 NodeExecution 列表，前端调两个 API。

### 3.2 Dify 暂停详情 API（最接近本 plan 场景）

`GET /workflow/<workflow_run_id>/pause-details` 返回**当前暂停的节点列表 + form_token 深链**：

```python
class WorkflowPauseDetailsResponse(ResponseModel):
    paused_at: str | None = None
    paused_nodes: list[PausedNodeResponse]

class PausedNodeResponse(ResponseModel):
    node_id: str
    node_title: str
    pause_type: HumanInputPauseTypeResponse  # type="human_input" + form_id + backstage_input_url
```

这与本 plan 的 `TrackingResponse.current_node` 设计**完全同源**——"实例当前等谁/什么节点"。

### 3.3 前端 workflow-log 组件分层

```
detail.tsx (Drawer 容器)
  ↓
<Run/> 组件 (WorkflowContextProvider 包裹)
  ↓
内部用 runDetailUrl + tracingListUrl 拉两个 API
  ↓
渲染节点 timeline + 状态徽章 (Indicator color="green/red/yellow/blue")
```

`list.tsx` 中的 `statusTdRender(status)` 是状态徽章模式：每个状态对应一个 `<Indicator color>` + 文本。本 plan 的 tracking-timeline 借鉴此模式做节点 status icon。

## 4. 可借鉴的设计模式

| 借鉴维度 | Dify 实现 | 本 plan 落地点 | 文件 |
| --- | --- | --- | --- |
| **多租户双重校验** | controller `@get_app_model()` + service tenant_id 二次比较 | `WorkspaceScopedQuery.select()` 自动注入 + service `applicant_id == current_user.id` 二次校验 | instance_service.py |
| **当前节点 + 历史分离** | `paused_nodes` (当前等谁) + `WorkflowRunNodeExecution[]`（历史时间线） | `current_node` (object\|null) + `records[]`（聚合时间线） | schemas/tracking.py |
| **状态徽章 5 态映射** | succeeded/failed/stopped/paused/running → Indicator color | done/rejected/returned/waiting_human/in_review → icon + 中文标签 | tracking-timeline.tsx |
| **暂停语义 = current_node** | `PausedNodeResponse` 含 node_id + node_title + pause_type | `current_node` 含 id + title + status + actor + deadline_at | API 契约 |
| **404 而非 403 对未授权** | tenant_id 不匹配 → NotFoundError(404)（避免泄漏存在性） | 跨 workspace → 404；同 workspace 但非 applicant → 403 (CONTEXT 要求) | API 异常处理 |
| **响应模型 from_attributes=True** | `model_validate(orm, from_attributes=True)` | 已用 Pydantic v2 `model_config = {"from_attributes": True}` | schemas/tracking.py |

## 5. 与本项目的关系

本 plan 实现申请人追踪页（HITL-07）：
1. **后端 endpoint** `GET /instances/<id>/tracking` 在已有 `/instances/<id>` 之外新建，专注**当前等谁 + records 时间线 + 脱敏**。
2. **service 方法** `get_tracking_for_applicant` 调用现有 InstanceService 模式 + 加 applicant 校验 + 脱敏逻辑。
3. **前端页面** `/dashboard/instances/[id]/tracking` 与现有 `/dashboard/instances/[id]` 并存：前者面向**申请人本人查看进度**，后者面向 editor+ 全方位运维。
4. **节点可视化（user feedback 2026-05-17 强制）**：本 plan 必须把节点的 title + status + actor + action + ts + 当前节点高亮 + 截止倒计时**全部展示**——这是用户明确要求"每节点要可视化"的最小达标线。

## 6. 与 hr/offboarding-flow 对照（5-10 行）

`/Users/admin/ai/resume/interview/liuxin/dongpo/hr/PRD.md §申请人追踪` 没有独立条款（PRD 聚焦多通道通知 + LangGraph interrupt），但其 records timeline 设计（"何人/何时/何决策"）与本 plan 一致。本 plan 申请人脱敏（不暴露 IP/UA）是**本项目独立隐私规约**，hr/PRD 未明确要求。

## 7. 申请人 vs admin 数据脱敏策略（本 plan 独有 — CONTEXT §申请人追踪页隐私）

### 7.1 数据视图差异表

| 字段 | 申请人（applicant_id == current_user.id 且非 admin） | admin / super_admin |
| --- | --- | --- |
| `records[].actor_email` | ✅ 显示（审批人邮箱） | ✅ 显示 |
| `records[].actor_name` | ✅ 显示（审批人姓名） | ✅ 显示 |
| `records[].action` | ✅ 显示（submit/approve/return/reject） | ✅ 显示 |
| `records[].reason` | ✅ 显示（审批理由） | ✅ 显示 |
| `records[].ts` | ✅ 显示（决策时间） | ✅ 显示 |
| `records[].ip` | ❌ **None / 不返回**（隐私） | ✅ 显示（NET-05 审计需要） |
| `records[].ua` | ❌ **None / 不返回**（隐私） | ✅ 显示（NET-05 审计需要） |
| `current_node.actor.email` | ✅ 显示（让申请人知道当前等谁） | ✅ 显示 |
| `current_node.deadline_at` | ✅ 显示（让申请人看到截止倒计时） | ✅ 显示 |

### 7.2 实现位置

脱敏在 **service 层完成**（不在 controller 层；不在 schema 层）：
- Service 接收 `current_user: User`，根据 `user.is_super_admin` + workspace 内 role == 'admin' 判断
- 非 admin 申请人 → `records[i] = TrackingRecord(..., ip=None, ua=None)` 显式置 None（而非省略字段）
- Admin → 原样回 `node_state.payload.records[i].ip / ua`

### 7.3 为什么 service 层脱敏（vs schema 字段隐藏）

| 方案 | 优点 | 缺点 | 决策 |
| --- | --- | --- | --- |
| Service 层根据用户角色返回不同值 | OpenAPI 文档统一；前端代码无需分支；DB 数据始终完整 | service 层逻辑稍复杂 | **采用** |
| Schema 层用两个 Pydantic 模型 | 类型上更严格 | 前端 / OpenAPI 客户端需处理 union | 不采用 |
| Controller 层手动 dict 移除 | 简单 | 散落多处易遗漏 | 不采用 |

### 7.4 403 vs 404 决策

- **跨 workspace（不在自己 workspace 内）**: 404 — 通过 WorkspaceScopedQuery 自动过滤，等同"实例不存在"
- **同 workspace 但 applicant_id != current_user.id 且非 admin**: **403** — CONTEXT 明确要求 "applicant_id == current_user.id 才放行（否则 403）"
- **admin 跨 applicant 查看**: 200 (放行 + 完整脱敏数据)

403 与 404 的区别：404 不泄漏实例是否存在；403 明确告知"实例存在但你无权"（admin 之外的同事/路过用户）。

### 7.5 attribution（CLAUDE.md 2.7 AGPL 警告）

未拷贝 Dify 源码。借鉴的设计模式 / 字段命名 / 状态徽章映射已全部重写为 Python typed FastAPI + Pydantic v2 + Tailwind 风格。

---

*Reading doc 完成于 2026-05-17，对应 Plan 03-08 申请人追踪页（HITL-07）。*
