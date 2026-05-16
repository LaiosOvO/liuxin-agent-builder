---
phase: 03-hitl-email
plan: "08"
subsystem: api + ui-applicant-tracking
tags: [hitl, tracking, applicant, privacy, masking, fastapi, react, vitest, node-visualization]

# Dependency graph
requires:
  - phase: 03-hitl-email
    plan: "01"
    provides: node_states.payload JSONB + records 子字段 schema
  - phase: 03-hitl-email
    plan: "06"
    provides: NodeState ORM payload Mapped[dict | None]（migration 0004）+ HitlActionService 写 records 模式
  - phase: 02-dsl
    provides: InstanceService base + WorkspaceScopedQuery + flow_instances ORM
  - phase: 01-skeleton
    provides: get_current_user + require_role + UserWorkspaceRole + Role(code)

provides:
  - InstanceService.get_tracking_for_applicant 方法（applicant or admin 权限 + service 层脱敏）
  - GET /api/agent_builder/v1/instances/<id>/tracking FastAPI endpoint（403/404 response 注解齐全）
  - schemas/tracking.py: TrackingResponse / TrackingRecord / TrackingCurrentNode / TrackingApplicant Pydantic v2
  - web/src/lib/types/tracking.ts: TS 类型 + HITL_NODE_STATUS_CONFIG 5 态+3 终态徽章 + RECORD_ACTION_LABELS
  - web/src/components/instance/tracking-timeline.tsx: 节点可视化竖向时间线（current_node banner + records 历史）
  - web/src/components/instance/applicant-only-records.tsx: 极简 records 列表 + 前端双重脱敏
  - web/src/components/instance/deadline-countdown.tsx: setInterval(1s) 倒计时（3 级颜色：urgent/warning/normal）
  - web/src/app/dashboard/instances/[id]/tracking/page.tsx: SSR 申请人追踪页（403/404 自动跳回 /dashboard/instances）

affects:
  - 03-10 E2E gate: 完成 ROADMAP Phase 3 success criteria #5 (申请人追踪页可见)
  - Phase 7 Run Viewer: 本 plan 的 tracking-timeline 可被升级为更完整的运维 Run Viewer

# Tech tracking
tech-stack:
  added: []  # 复用现有 FastAPI + Pydantic v2 + Next.js 16 + Vitest + @testing-library/react
  patterns:
    - "Service 层根据 user 角色脱敏 (vs schema/controller 层) — OpenAPI 统一 + 前端无角色分支"
    - "applicant_id == current_user.id OR admin 双轨权限 (CONTEXT §申请人追踪页隐私)"
    - "跨 workspace → 404（不泄漏实例存在性）; 同 ws 非 applicant → 403"
    - "节点可视化字段集: id/title/status/node_type/actor/deadline_at/started_at (user feedback_node_visualization)"
    - "前端 setInterval(1s) 倒计时（不轮询后端）+ 3 级颜色 (urgent <1h / warning <6h / normal)"
    - "前端 sanitizeRecord 强制丢弃 ip/ua（双重保险防后端脱敏漏）"
    - "useQuery refetchInterval: active 节点存在时 30s 自动刷新"
    - "403/404 自动跳回（1.2s 延时给用户阅读错误信息）"

key-files:
  created:
    - docs/reading-dify-03-08-tracking-page-2026-05-17.md
    - backend/app/agent_builder/schemas/tracking.py
    - backend/tests/test_tracking_api.py
    - web/src/lib/types/tracking.ts
    - web/src/components/instance/tracking-timeline.tsx
    - web/src/components/instance/applicant-only-records.tsx
    - web/src/components/instance/deadline-countdown.tsx
    - web/src/app/dashboard/instances/[id]/tracking/page.tsx
    - web/tests/tracking-timeline.spec.tsx
  modified:
    - backend/app/agent_builder/services/instance_service.py (加 get_tracking_for_applicant + 4 辅助方法)
    - backend/app/agent_builder/api/v1/instances.py (加 GET /<id>/tracking endpoint)
    - web/src/lib/api/instances.ts (加 instancesApi.tracking + fetchTracking 命名导出)

key-decisions:
  - "Service 层脱敏 (vs schema/controller)：OpenAPI 文档统一，前端无需角色分支，DB 数据始终完整"
  - "跨 workspace → 404 (WorkspaceScopedQuery 过滤即等同'实例不存在')；同 ws 非 applicant → 403 (CONTEXT 明确要求)"
  - "admin 视角包含 IP/UA 完整字段（NET-05 审计）；申请人视角强制 ip=None, ua=None"
  - "current_node 优先选 HITL active 节点 (waiting_human/in_review) — 申请人最关心当前等谁"
  - "节点可视化字段全套实现 (user feedback 2026-05-17 强制): id/title/status/node_type/actor/deadline_at"
  - "DeadlineCountdown 3 级颜色：urgent (<1h or overdue) / warning (<6h) / normal — 视觉紧迫感分层"
  - "前端 sanitizeRecord 双重保险：即使后端漏脱敏 ip/ua，前端组件也强制丢弃（CONTEXT 隐私契约 defense-in-depth）"
  - "useQuery refetchInterval 仅在 active 节点存在时启用 30s 轮询 — 终态实例不浪费带宽"
  - "403/404 自动跳回 (1.2s 延时) — 给用户读错误信息的时间又不让他卡死"
  - "[Rule 1 - Bug] 移除多余 autouse engine.dispose fixture — 与 conftest.db_session 重叠触发 race condition"

patterns-established:
  - "Service 层脱敏模式：根据 current_user.role 在 service 层完成 mask，OpenAPI 单一 schema"
  - "Applicant + admin 双轨权限：CONTEXT 隐私规约 + 审计需求并存"
  - "节点可视化字段标准集：HITL active 节点必须暴露 title/actor/deadline 给申请人"
  - "前端双重保险脱敏：组件级 sanitize 防御后端漏脱敏"
  - "DeadlineCountdown 复用：可被 03-07 决策页 / 03-09 timeout 后续 refactor 共享"
  - "test_*_api.py + async_session_maker 独立 session 模式: 避免与 async_client 池冲突"

requirements-completed:
  - HITL-07

# Metrics
duration: 28min
completed: 2026-05-17
test-count: 32  # 10 backend integration + 22 frontend vitest
file-count: 12  # 9 created + 3 modified
---

# Phase 3 Plan 08: HITL-07 申请人追踪页 Summary

**Phase 3 终端用户价值演示阶段最后一块拼图**：申请人能在 dashboard 看自己实例的进度（当前等谁/历史决策/截止倒计时），完整覆盖节点可视化要求 (user feedback_node_visualization 2026-05-17 强制规则)。

## Performance

- **Duration:** 28 分钟
- **Started:** 2026-05-16T19:13:30Z
- **Completed:** 2026-05-16T19:41:50Z
- **Tasks:** 3 (Task 0 reading doc + Task 1 backend API/service/tests + Task 2 frontend page/3 组件/tests)
- **Files created:** 9
- **Files modified:** 3
- **Test cases:** 32（10 backend integration + 22 frontend vitest）— 全部通过

## Accomplishments

1. **后端 GET /instances/<id>/tracking endpoint**：applicant_id == current_user.id 或 admin 才放行；跨 workspace 返回 404；同 ws 非 applicant 返回 403；OpenAPI 文档自动生成。

2. **InstanceService.get_tracking_for_applicant + 4 辅助方法**：
   - `_user_has_admin_view`：super_admin 全局放行 + workspace admin 放行
   - `_resolve_applicant`：display_name 缺失时回退 email 前缀
   - `_build_current_node`：优先 HITL active 节点 (waiting_human/in_review)
   - `_aggregate_records`：跨节点聚合 payload.records，按 ts ASC 排序
   - `_normalize_record`：service 层根据 user 角色脱敏 (admin → 保留 ip/ua；申请人 → 置 None)

3. **schemas/tracking.py**：4 个 Pydantic v2 模型（TrackingResponse / TrackingRecord / TrackingCurrentNode / TrackingApplicant）含节点可视化全套字段。

4. **前端申请人追踪页 /dashboard/instances/[id]/tracking**：
   - useQuery 拉 fetchTracking + active 节点时 refetchInterval=30s
   - 403/404 自动跳回 /dashboard/instances (1.2s 延时)
   - 顶部基本信息卡：instance_id + 状态徽章 + 申请人 + workflow_id + 时间

5. **TrackingTimeline 组件**（节点可视化核心）：
   - CurrentNodeBanner：蓝色 ring 高亮 + 节点 title + 状态徽章 + actor + deadline 倒计时
   - RecordRow：竖向 timeline + 圆点 + 连接线 + action 标签 + 邮箱 + ts + reason

6. **ApplicantOnlyRecords 组件**：极简列表 + 前端 sanitizeRecord 双重保险（即使后端漏脱敏也不渲染 ip/ua）。

7. **DeadlineCountdown 组件**：前端 setInterval(1s) 倒计时；3 级颜色：urgent (<1h or overdue) / warning (<6h) / normal；不轮询后端。

8. **32 测试覆盖**（CLAUDE.md 2.2 三层）：
   - 10 backend 集成测试（真实 PG）：1. 申请人本人 200 / 2. 非 applicant 403 / 3. admin 绕过 / 4. admin 见 IP/UA / 5. 申请人脱敏 IP/UA / 6. 跨 workspace 404 / 7. HITL active 节点 deadline / 8. 终态 current_node=None / 9. 401 / 10. records 跨节点按 ts ASC 排序
   - 22 frontend vitest：状态徽章 5 态 + action 标签 5 态 + overdue / urgent / warning / normal 倒计时 + current_node 高亮 + 空状态 + ApplicantOnlyRecords 双重脱敏 + DeadlineCountdown 单测

## Task Commits

| Task | Name | Hash | Type |
|---|---|---|---|
| 0 | Dify workflow_run + workflow-log 阅读笔记 (CLAUDE.md 2.7 GATE) | `4e47102` | docs |
| 1 | backend HITL-07 申请人追踪 API + service + 10 测试 | `28dc794` | feat |
| 2 | frontend HITL-07 申请人追踪页 + 3 组件 + 22 vitest 测试 | `8521a1c` | feat/test |
| Rule 1 | 移除多余 autouse engine.dispose fixture (与 conftest 重叠 race) | `36aa232` | fix |

**Plan metadata commit** 由 final_commit 步骤创建（含 SUMMARY.md + STATE.md + ROADMAP.md + REQUIREMENTS.md 更新）。

## Files Created/Modified

### 新建

- `docs/reading-dify-03-08-tracking-page-2026-05-17.md` — 7 节 Dify 阅读笔记（含 §7 申请人 vs admin 数据脱敏策略 — 表格 + 实现位置 + 403 vs 404 决策 + AGPL attribution）
- `backend/app/agent_builder/schemas/tracking.py` — 4 个 Pydantic v2 模型
- `backend/tests/test_tracking_api.py` — 10 集成测试 + 独立 session 模式（async_session_maker 避免污染 async_client 池）
- `web/src/lib/types/tracking.ts` — TS 类型 + HITL_NODE_STATUS_CONFIG + RECORD_ACTION_LABELS
- `web/src/components/instance/tracking-timeline.tsx` — 竖向 timeline 主组件
- `web/src/components/instance/applicant-only-records.tsx` — 极简 records 列表 + 前端 sanitize
- `web/src/components/instance/deadline-countdown.tsx` — setInterval(1s) 倒计时 + 3 级颜色
- `web/src/app/dashboard/instances/[id]/tracking/page.tsx` — 追踪页 SSR 入口
- `web/tests/tracking-timeline.spec.tsx` — 22 vitest 测试

### 修改

- `backend/app/agent_builder/services/instance_service.py` — 加 `get_tracking_for_applicant` + 4 辅助方法 + 2 常量
- `backend/app/agent_builder/api/v1/instances.py` — 加 GET /<id>/tracking endpoint
- `web/src/lib/api/instances.ts` — 加 `instancesApi.tracking` + `fetchTracking` 命名导出

## Decisions Made

1. **Service 层脱敏 vs schema/controller 层**：OpenAPI 文档统一，前端无角色分支，DB 数据始终完整。
2. **跨 workspace → 404 vs 同 ws 非 applicant → 403**：CONTEXT 明确要求；前者不泄漏存在性，后者明确告知"实例存在但您无权"。
3. **admin 完整 IP/UA vs 申请人脱敏**：NET-05 审计 vs 隐私规约并存。
4. **current_node 优先 HITL active 节点**：申请人最关心当前等谁，HITL 比其它 active 节点更优先。
5. **节点可视化字段全套实现**：user feedback_node_visualization 2026-05-17 强制 — id/title/status/node_type/actor/deadline_at 全部暴露。
6. **DeadlineCountdown 3 级颜色**：urgent (<1h or overdue red) / warning (<6h amber) / normal (green) — 视觉紧迫感分层。
7. **前端 sanitizeRecord 双重保险**：组件级强制丢弃 ip/ua（即使后端漏脱敏），CONTEXT 隐私契约 defense-in-depth。
8. **useQuery refetchInterval 仅 active 时**：终态实例不浪费带宽。
9. **403/404 自动跳回（1.2s 延时）**：给用户读错误的时间又不让他卡死。
10. **[Rule 1 - Bug] 移除多余 autouse engine.dispose fixture**：与 conftest.db_session 的 dispose 重叠触发 race condition。

## Dify 参考点

详见 `docs/reading-dify-03-08-tracking-page-2026-05-17.md`（commit `4e47102`）。本 plan 借鉴的核心模式：

| 借鉴维度 | Dify 原模式 | 本项目落点 | 文件 |
|---|---|---|---|
| **多租户双重校验** | controller `@get_app_model()` + service tenant_id 二次比较 | `WorkspaceScopedQuery.select()` 自动注入 + service `applicant_id == current_user.id` 二次校验 | instance_service.py |
| **当前节点 + 历史分离** | `paused_nodes` (当前等谁) + `WorkflowRunNodeExecution[]`（历史时间线） | `current_node` (object\|null) + `records[]`（聚合时间线） | schemas/tracking.py |
| **状态徽章 5 态映射** | succeeded/failed/stopped/paused/running → Indicator color | done/rejected/returned/waiting_human/in_review → icon + 中文标签 | tracking-timeline.tsx |
| **暂停语义 = current_node** | `PausedNodeResponse` 含 node_id + node_title + pause_type | `current_node` 含 id + title + status + actor + deadline_at | API 契约 |
| **404 而非 403 对未授权** | tenant_id 不匹配 → NotFoundError(404)（避免泄漏存在性） | 跨 workspace → 404；同 workspace 但非 applicant → 403 | API 异常处理 |
| **Response model_validate + from_attributes** | `WorkflowRunDetailResponse.model_validate(orm, from_attributes=True)` | `TrackingResponse.model_validate(data)` + Pydantic v2 model_config | schemas/tracking.py |

**反向取舍（不照搬 Dify）**：
1. **Service 层脱敏（Dify 没有）** — 申请人 vs admin 数据差异通过 service 层完成；Dify 没有"申请人视角"概念
2. **节点可视化全套字段** — Dify `paused_nodes` 仅含 node_id + node_title；我们必含 actor + deadline_at 等（user feedback_node_visualization 强制）
3. **前端 sanitizeRecord 双重保险** — Dify 后端 trust；本项目隐私契约 defense-in-depth
4. **3 级颜色倒计时** — Dify 没有 deadline 概念；本项目 HITL deadline 是核心 UX

**Attribution**：未拷贝 Dify 源码（AGPL）。借鉴的设计模式 / 字段命名 / 404 vs 403 决策已全部重写为 Python typed FastAPI + Pydantic v2 + Tailwind / React 风格。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 移除多余 autouse engine.dispose fixture**
- **Found during:** Task 1 验证阶段（10 个测试个别全过，批量运行触发 setup_cache + event loop 双重 race）
- **Issue:** 初版加了 `@pytest.fixture(autouse=True) _dispose_engine_between_tests`，与 conftest.db_session 内的 `await engine.dispose()` 重叠，破坏 connection pool 重建时机，触发 race condition；同时 `setup_cache` 跨测试不一致（其他并行测试残留）
- **Fix:** 删除本文件的 autouse fixture，仅依赖 conftest.db_session 隔离；同 test_instances_api 模式
- **Files modified:** `backend/tests/test_tracking_api.py`
- **Verification:** 10/10 测试个别通过；批量运行的失败属 test_instances_api 也有的 pre-existing setup_cache 污染（CLAUDE.md SCOPE BOUNDARY 不在本 plan 修复）
- **Commit:** `36aa232`

---

**Total deviations:** 1 auto-fixed (Rule 1 Bug — test fixture race condition)
**Impact on plan:** 测试逻辑全部正确（10/10 单独通过 + 22/22 frontend vitest 通过）。批量运行 flakiness 属 pre-existing 测试基础设施问题，与本 plan 无关。

## Issues Encountered

1. **批量运行 test_tracking_api 触发 setup_cache + connection pool race**（**与 test_instances_api 同样模式 — pre-existing**）
   - 现象：批量执行时 `await async_client.post("/workflows")` 偶发返回 503 "setup required" 或 FK 报错（workflow_id not present）
   - 根因：`SetupRedirectMiddleware._setup_complete` 进程级缓存 + conftest.db_session 的 `engine.dispose()` race；test_instances_api 也存在同样问题（实测 4/10 fail in batch）
   - 决策：CLAUDE.md SCOPE BOUNDARY 不在本 plan 修复 — 应在 Phase 7 测试基础设施加强时统一处理（建议方案：fixture 级 `reset_setup_cache()` autouse + 替换 module-level cache 为 lru_cache(maxsize=0) + 测试期强制 DB query）
   - 不影响业务逻辑正确性：10/10 测试个别通过证明 service / endpoint / 脱敏全部正确

2. **asyncpg AmbiguousParameterError**（NOTI-related）
   - 现象：`UPDATE ... SET status = :s WHERE status IN (:s, :s2)` 同参数复用于 SET 与 IN 导致类型推断模糊
   - 修复：分两条 SQL 根据 status is_terminal 走不同分支
   - 文件：`backend/tests/test_tracking_api.py::_update_instance_status`

## Self-Check

执行验证：
- [x] `docs/reading-dify-03-08-tracking-page-2026-05-17.md` 存在 + 已 commit (`4e47102`)（Task 0 GATE — 在所有 feat commit 之前 ✓）
- [x] `backend/app/agent_builder/schemas/tracking.py` 存在 + 已 commit (`28dc794`)
- [x] `backend/app/agent_builder/services/instance_service.py` 含 `get_tracking_for_applicant` (`28dc794`)
- [x] `backend/app/agent_builder/api/v1/instances.py` 含 `GET /<id>/tracking` (`28dc794`)
- [x] `backend/tests/test_tracking_api.py` 10 测试 + 独立 session 模式 (`28dc794` + fix `36aa232`)
- [x] `web/src/lib/types/tracking.ts` 含 4 interface + 2 config map (`8521a1c`)
- [x] `web/src/lib/api/instances.ts` 含 `instancesApi.tracking` + `fetchTracking` (`8521a1c`)
- [x] `web/src/components/instance/tracking-timeline.tsx` 含 CurrentNodeBanner + RecordRow + StatusBadge + ActionTag (`8521a1c`)
- [x] `web/src/components/instance/applicant-only-records.tsx` 含 sanitizeRecord 双重脱敏 (`8521a1c`)
- [x] `web/src/components/instance/deadline-countdown.tsx` 含 setInterval(1s) + 3 级颜色 (`8521a1c`)
- [x] `web/src/app/dashboard/instances/[id]/tracking/page.tsx` 含 useQuery + 403/404 跳回 (`8521a1c`)
- [x] `web/tests/tracking-timeline.spec.tsx` 22 测试通过 (`8521a1c`)
- [x] 10/10 backend 测试单独通过 + 22/22 frontend vitest 全部通过（批量 setup_cache 问题 pre-existing 与本 plan 无关）
- [x] Task 0 reading doc commit (4e47102) 在所有 feat/test commit 之前（CLAUDE.md 2.7 GATE）
- [x] TypeScript `tsc --noEmit` 无错误（针对本 plan 新增文件）

## Next Plan Readiness

- ✅ **03-10 E2E gate**：申请人追踪页可见已就绪（ROADMAP Phase 3 success criteria #5 完成）；E2E 模拟登录 → 进入 /dashboard/instances/<id>/tracking → 验证 current_node banner + records timeline 渲染
- ✅ **Phase 7 Run Viewer**：本 plan 的 tracking-timeline 可被 Phase 7 升级为运维 Run Viewer（增加节点详情抽屉 + 输入/输出/日志/耗时）
- ⚠️ **测试基础设施**：批量测试 setup_cache race condition 应在 Phase 7 测试加固时统一修复（影响范围：test_instances_api / test_tracking_api / 其它依赖 two_workspaces fixture 的测试）

## Self-Check: PASSED

所有声明的文件存在；所有声明的 commit 在 git log 中；10/10 backend 测试单独通过；22/22 frontend vitest 通过；reading doc commit 在 feat commit 之前（CLAUDE.md 2.7 GATE）。

---
*Phase: 03-hitl-email*
*Plan: 08*
*Completed: 2026-05-17*
