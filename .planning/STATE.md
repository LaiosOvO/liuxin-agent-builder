# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-16)

**Core value:** 让非编码人员通过拖拽 5 分钟搭出"多通道审批 + 公网回调"的 LangGraph 工作流，并真实跑起来
**Current focus:** Phase 1 — Skeleton + 账号体系

## Current Position

Phase: 1 of 7 (Skeleton + 账号体系)
Plan: 3 of TBD in current phase
Status: In Progress
Last activity: 2026-05-16 — Plan 01-03 完成（nginx 最小暴露面 + 启动校验 + slowapi）

Progress: [███░░░░░░░] 30%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 (Skeleton) | 3 | ~30min | ~10min |

**Recent Trend:**
- Last 5 plans: 01-01, 01-02, 01-03
- Trend: 稳定

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- M1 (Phase 1): Fork flock 后所有改动集中新增模块，不改 flock 上游文件（防 Pitfall 11）
- M1 (Phase 1): 多租户所有查询显式带 workspace_id WHERE + SQLAlchemy checkout 时 DISCARD ALL（防 Pitfall 6）
- M1 (Phase 1): HMAC_SECRET 启动校验 ≥ 32 字节（防 Pitfall 4）
- M1 (Phase 1): startup_checks 在模块顶层直接调用，不放 FastAPI lifespan（lifespan 触发太晚）
- M1 (Phase 1): slowapi get_token_from_path 用命名函数不用 lambda（slowapi 装饰器调用签名约束）
- M2 (Phase 2): state schema 重型数据走 Redis Pointer Pattern（防 Pitfall 1 Checkpoint 膨胀）
- M3 (Phase 3): GET 不消费 jti，POST 才消费（防 Pitfall 3 邮件扫描器预消费）
- M3 (Phase 3): jti 消费 + Advisory Lock 防并发双提交（防 Pitfall 2）

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 2: 需在 M2 首日确认 flock 是否已有 WebSocket 实时画布，决定是否复用或新建
- Phase 4: IM TokenManager（飞书/企微 token 并发刷新竞态）需在接入第一个 IM 适配器时就实现（防 Pitfall 7）
- Phase 5: IM 双向同步需防止"同步 → 触发通知 → IM Bot 收到 → 再次触发同步"循环（防 Pitfall 15）

## Session Continuity

Last session: 2026-05-16
Stopped at: Completed 01-skeleton-03-PLAN.md（nginx 双 server_block + 启动校验 + slowapi + E2E 路径扫描）
Resume file: None
