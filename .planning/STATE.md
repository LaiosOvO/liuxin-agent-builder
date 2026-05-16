---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-05-16T14:31:32.032Z"
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 16
  completed_plans: 8
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-16)

**Core value:** 让非编码人员通过拖拽 5 分钟搭出"多通道审批 + 公网回调"的 LangGraph 工作流，并真实跑起来
**Current focus:** Phase 2 — DSL 引擎 + 基础节点

## Current Position

Phase: 2 of 7 (DSL 引擎 + 基础节点)
Plan: 2 of 10 in current phase（02-02 完成，DSL Schema + 验证器 + 编译器骨架 + Jinja2 沙箱）
Status: In Progress
Last activity: 2026-05-16 — Plan 02-02 完成（DSL Schema + Jinja2 沙箱 + DSLValidator 4 类全检 + DSLCompiler 骨架 + 81 个测试通过）

Progress: [███░░░░░░░] 30%

## Performance Metrics

**Velocity:**
- Total plans completed: 6 (Phase 1 全部完成)
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 (Skeleton) | 5 | ~54min | ~11min |

**Recent Trend:**
- Last 5 plans: 01-01, 01-03 (并行), 01-02
- Trend: 稳定

*Updated after each plan completion*
| Phase 02-dsl P02 | 12 | 3 tasks | 17 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- M1 (Phase 1): Fork flock 后所有改动集中新增模块，不改 flock 上游文件（防 Pitfall 11）
- M1 (Phase 1): 多租户所有查询显式带 workspace_id WHERE + SQLAlchemy checkout 时 DISCARD ALL（防 Pitfall 6）
- M1 (Phase 1): HMAC_SECRET 启动校验 ≥ 32 字节（防 Pitfall 4）
- M1 (Phase 1): startup_checks 在模块顶层直接调用，不放 FastAPI lifespan（lifespan 触发太晚）
- M1 (Phase 1): slowapi get_token_from_path 用命名函数不用 lambda（slowapi 装饰器调用签名约束）
- M1 (Phase 1): 手写 migration 0001（不用 autogenerate，避免 CITEXT/复合索引出错）
- M1 (Phase 1): migrations/ 独立于 flock 原 app/alembic（fork discipline），新建 backend/migrations/
- M1 (Phase 1): audit_logs 使用 BIGSERIAL PK（时序有序，非 UUID）
- M1 (Phase 1): Docker 不可用时集成测试自动回退到 POSTGRES_DSN 指定的 SSH 隧道 DB
- M2 (Phase 2): state schema 重型数据走 Redis Pointer Pattern（防 Pitfall 1 Checkpoint 膨胀）
- M2 (Phase 2, 02-01): langchain-sandbox 与 langgraph 1.2.0 冲突 → 注释移除，Phase 6 插件机制替代
- M2 (Phase 2, 02-01): greenlet 需显式声明依赖（Python 3.13 + SQLAlchemy asyncio）
- M2 (Phase 2, 02-01): checkpoint 表由 AsyncPostgresSaver.setup() 管理，include_object 排除 Alembic autogenerate
- M2 (Phase 2, 02-01): thread_id = '{workspace_id}:{instance_id}'（防 Pitfall 13 跨租户碰撞）
- M2 (Phase 2, 02-01): FastAPI lifespan 用于异步初始化（checkpoint 表创建），失败记 warning 不阻断启动
- M3 (Phase 3): GET 不消费 jti，POST 才消费（防 Pitfall 3 邮件扫描器预消费）
- M3 (Phase 3): jti 消费 + Advisory Lock 防并发双提交（防 Pitfall 2）
- M5 (Phase 1): Next.js 保持 15.2.3（不升级到 16.2）：升级需 Tailwind codemod，风险超 Phase 1 收益
- M5 (Phase 1): login/page.tsx 替换 flock 版本：CONTEXT.md 外部可见层品牌规定优先于 fork discipline
- M5 (Phase 1): API_BASE 运行时动态计算（getApiBase 函数），支持测试环境覆盖
- M4 (Phase 1): rbac.denied 审计用独立 session（HTTPException 回滚主 session，需独立 session 确保审计提交）
- M4 (Phase 1): GET verify-email 消费 jti（与 HITL GET 不消费不同，代码注释明确区分）
- M4 (Phase 1): autouse pytest fixture 重置 slowapi limiter + app.state.limiter（防止 importlib.reload 后双 limiter 不一致）
- [Phase 02-dsl]: TopologicalSorter 使用入边依赖图（非出边），static_order() 返回正确执行顺序 start→...→end
- [Phase 02-dsl]: 孤立节点 E_ORPHAN_NODE 定为 warning 级别（可放行），不阻断工作流发布

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 2: 需在 M2 首日确认 flock 是否已有 WebSocket 实时画布，决定是否复用或新建
- Phase 4: IM TokenManager（飞书/企微 token 并发刷新竞态）需在接入第一个 IM 适配器时就实现（防 Pitfall 7）
- Phase 5: IM 双向同步需防止"同步 → 触发通知 → IM Bot 收到 → 再次触发同步"循环（防 Pitfall 15）

## Session Continuity

Last session: 2026-05-16
Stopped at: Completed 02-02-PLAN.md（DSL Schema + Jinja2 沙箱 + DSLValidator 4 类全检 + DSLCompiler 骨架 + 81 个测试通过）
Resume file: None
