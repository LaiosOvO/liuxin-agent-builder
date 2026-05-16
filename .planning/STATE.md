---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: in_progress
last_updated: "2026-05-17T18:46:25Z"
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 26
  completed_plans: 21
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-16)

**Core value:** 让非编码人员通过拖拽 5 分钟搭出"多通道审批 + 公网回调"的 LangGraph 工作流，并真实跑起来
**Current focus:** Phase 3 — HITL 单节点 + Email 审批

## Current Position

Phase: 3 of 7 (HITL 单节点 + Email 审批) — IN PROGRESS
Plan: 5 of 10 in current phase（03-01 / 03-02 / 03-03 / 03-04 / 03-05 完成，Wave 1 + Wave 2 + Wave 3 + Wave 4 部分交付）
Status: Wave 4 Plan 05 完成 — 可继续 Wave 4（03-06 HITL public API 部分已 commit 中）
Last activity: 2026-05-17 — Plan 03-05 完成（NotificationNodeExecutor + 通用通知模板 + 13 集成测试通过；与 HITL 节点完全解耦）

Progress: [███░░░░░░░] 22%

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
| Phase 02 P05 | 30m | 3 tasks | 5 files |
| Phase 02-dsl P06 | 11 | 2 tasks | 9 files |
| Phase 02-dsl P04 | 16 | 3 tasks | 13 files |
| Phase 02-dsl P08 | 26m | 4 tasks | 25 files |
| Phase 02-dsl P07 | ~3h | 4 tasks | 10 files |
| Phase 03-hitl-email P01 | 50m | 3 tasks | 10 files |
| Phase 03-hitl-email P03 | 6m | 3 tasks | 5 files |
| Phase 03-hitl-email P02 | 17m | 4 tasks | 15 files |
| Phase 03-hitl-email P04 | ~10m | 3 tasks（+Task0 已 commit） | 10 files |
| Phase 03-hitl-email P05 | ~10m | 3 tasks（Task0 reading doc + Task1 impl + Task2 13 测试） | 9 files |

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
- [Phase 02-dsl, 02-03]: workflowsApi 先定义签名不接后端，?mock=1 降级到 localStorage 离线体验（Plan 02-08 兑现）
- [Phase 02-dsl, 02-03]: ConfigPanel 按 nodeType switch 独立子组件（5 种表单差异大，可维护性优于泛型方案）
- [Phase 02-dsl, 02-03]: flock pre-existing TS 错误（Members/index.tsx）不修复（fork discipline），记录 deferred-items.md
- [Phase 02]: llm_client.py 前次 run 已实现完整，评估后无需补丁；LLMNodeExecutor 继承 BaseNodeExecutor，不重复重试逻辑
- [Phase 02-dsl]: pointer 格式用 __ptr__:redis:state:<32位hex>，Redis key = agent_builder:state_ptr:<ws>:<inst>:<uuid>，TTL=30天，阈值4096 bytes，missing pointer 返回标记不抛错
- [Phase 02-04]: IfElse.resolve_route 使用原始 self.config（非 _render_config 结果）：conditions[].expr 为 Jinja2 模板，提前渲染导致 UndefinedError，必须延迟到求值
- [Phase 02-04]: NODE_EXECUTORS 手动注册（非 pkgutil 自动发现），项目规模小可读性优先
- [Phase 02-04]: 集成测试 state_schema 需包含节点 ID 字段（dict 类型），LangGraph TypedDict 只保留已声明字段
- [Phase 02-08]: validate 路由注册于 /{workflow_id} 之前，避免 FastAPI 路径冲突
- [Phase 02-08]: SSE 详情页 useReducer 合并增量节点状态，instance 终止后 refetch 同步最终状态
- [Phase 02-08]: 实例列表采用 page/page_size URL 分页，canvas Run 按钮仅在 published 状态下启用
- [Phase 02-07]: Redis Stream 做历史存储 + pub/sub 做实时分发（改进 Dify 无断连补发痛点）
- [Phase 02-07]: EventBus 用单调递增 seq（Redis INCR）作为 Last-Event-ID，支持 Last-Event-ID 断连补发
- [Phase 02-07]: AppStatus.should_exit_event 重置 fixture 解决跨测试事件循环污染（sse_starlette 单例绑定问题）
- [Phase 02-09]: Jinja 解析器用正则而非 nunjucks（减少 ~300KB bundle，DSL 不需要求值）
- [Phase 02-09]: 拓扑排序用 Kahn 算法（比 graphlib 更易 TS 实现），成环检测用 DFS 白/灰/黑染色
- [Phase 02-09]: 发布前后端复检降级策略：validate API 不可用时不阻断发布（network fault tolerance）
- [Phase 02-10]: SSE 订阅用 page.evaluate + EventSource（携带浏览器 cookie，真实连接），非 Node.js polyfill
- [Phase 02-10]: API fixture 模式准备测试数据（不走 UI 拖拽）：速度快 + 不受 UI 渲染时机影响
- [Phase 02-10]: checkpoint_recovery spec 仅 E2E_FULL_STACK=1 触发（docker restart 需特殊权限，不适合 CI 默认）
- [Phase 02-10]: instance_list_filter 并发创建 15 实例（Promise.all），dsl-builder.ts 集中管理 4 种 DSL 变体
- [Phase 03-01]: hitl_tokens 单表统管 jti+actor+action（不照搬 Dify Form/Delivery/Recipient 三表，v1 单人审批不需要）
- [Phase 03-01]: action 字段 VARCHAR(16) 不做 DB 枚举约束（service 层校验，新增 action 不需要 migration）
- [Phase 03-01]: audit_logs 既有 ip/user_agent 保留，新增 actor_ip/actor_ua 作 HITL 决策审计专用语义
- [Phase 03-01]: Redis key 前缀 `agent_builder:jti:<jti>` + TTL 24h 对齐 token 默认过期时间
- [Phase 03-01]: is_consumed 未知 jti 返回 True（防伪造，与 consume 零行返回 None 语义一致）
- [Phase 03-01]: invalidate_siblings used_ip 写 'system:sibling-invalidate' 标识系统级失效（与真实用户消费区分）
- [Phase 03-01]: HitlTokenStore Redis-first + PG 权威双层存储模式（is_consumed 命中 Redis 走 hot path；miss 回查 PG + 回填）
- [Phase 03-03]: HitlTokenService 复用 Phase 1 _get_jwt_secret，aud='hitl' 单密钥多 audience 隔离（vs Dify 单一 SECRET_KEY 无 aud 校验）
- [Phase 03-03]: JWT decode options.require=['jti','exp','iat','aud','iss'] 强校验关键字段；Phase 1 session token 走 HitlTokenService.decode 必抛 HitlTokenError（隔离测试覆盖）
- [Phase 03-03]: service 层异常细分（InvalidSignature/TokenExpired/InvalidAudience/HitlTokenError）便于 API 层差异化错误页（vs Dify PassportService 单一 Unauthorized）
- [Phase 03-03]: BOT_UA_PATTERNS 15 项 = CONTEXT 13 + 'safelinks' 通用前缀 + 'ac-detector-tool'（Outlook 真实 UA from §Specific Ideas）
- [Phase 03-03]: bot_detector 纯函数 + 元组常量；None/空/unicode/超长 UA 鲁棒；O(n*m) 复杂度但 m=15 + 仅 GET 路径调用可接受
- [Phase 03-02]: HITLNodeExecutor override __call__ 跳过 tenacity 重试装饰器（重试会吞 GraphInterrupt 控制流异常）
- [Phase 03-02]: 节点函数副作用归外原则：node 函数仅读 state._node_state_id，写 DB / 发邮件由 ExecutionEngine / 03-06 API 一次性触发（防 resume 重跑导致重复副作用）
- [Phase 03-02]: state 中 node_state_id 用单下划线前缀 `_node_state_id` — LangGraph 1.2 剥离 __dunder__ 前缀字段（实测发现，记入 reading doc §7.5）
- [Phase 03-02]: hitl_payload 与 HitlService 解耦：前者无 DB 依赖纯函数单测，后者集成测试用真实 PG，加快 TDD feedback loop
- [Phase 03-02]: form_schema 用 jsonschema Draft-7（与前端 RJSF AJV-8 兼容），空 schema {} 视为不约束
- [Phase 03-02]: HitlService.batch_create_tokens flush 不 commit（保持事务可组合，外层 API handler 决定提交时机）
- [Phase 03-04]: Dify Celery shared_task → arq async function（CLAUDE.md §3 锁定 + asyncio 原生 + aiosmtplib 同构）
- [Phase 03-04]: Dify 三层 ORM (Form/Delivery/Recipient) → 单层 notifications + JSONB payload（v1 单人审批不复用）
- [Phase 03-04]: Jinja autoescape=html 单模式（Sandbox 三模式留 Phase 6 插件，用户不写模板）
- [Phase 03-04]: subject 代码组装 f-string 不走 Jinja（不含用户字段，防 SMTP 头注入风险）
- [Phase 03-04]: tenacity AsyncRetrying wait_exponential(multiplier=1, min=1, max=4) 实现 1s/2s/4s 公比 2 退避
- [Phase 03-04]: _RETRYABLE_EXCEPTIONS 加 OSError：aiosmtplib 底层 socket 错误兜底（实测发现）
- [Phase 03-04]: 失败写 notifications.status='failed' + error_message + audit_log（NOTI-10 显式可观测，vs Dify 仅 logger.exception）
- [Phase 03-04]: job 入参 notification_id（vs payload）：自包含 + 幂等（status=='sent' 跳过）+ 标记 'sending' 防并发抢
- [Phase 03-04]: job 用独立 async_session_maker session（不复用调用方 session）：arq worker 上下文隔离 + 测试 fixture 干净
- [Phase 03-04]: deeplinks 在模板内拼装（payload 只存 jti+action）：PUBLIC_BASE_URL 变化不需要回填历史
- [Phase 03-05]: Dify 没有独立 Notification 节点（通知耦合在 HumanInputForm 投递链），本项目按 CONTEXT §NODE-07 解耦：3 独立节点类 + 独立 schema + 独立 NODE_EXECUTORS key
- [Phase 03-05]: NotificationNodeExecutor 走 BaseNodeExecutor.execute 路径（vs HITL override __call__）：不抛 GraphInterrupt，可享受 retry/timeout 装饰器（_retryable_exceptions 返回空 tuple 避免重复重试）
- [Phase 03-05]: 复用 send_hitl_email_job worker（不新建 arq function）：通过 payload.generic=True 字段路由到 generic_notification.html，避免 WorkerSettings.functions 注册爆炸
- [Phase 03-05]: 失败不阻断模式：单 recipient 入队失败 → db.rollback() + failed_count + 1；graph 仍走完所有 recipient（vs HITL fail-stop）
- [Phase 03-05]: 节点自管 node_state_id（SELECT or INSERT 满足 FK 约束）vs HITL 要求 ExecutionEngine 预创建 + 注入 _node_state_id 到 state
- [Phase 03-05]: subject CR/LF 净化二次过滤：Jinja 渲染后 + 进 SMTP 前 replace('\\r', ' ').replace('\\n', ' ')[:200] 防 SMTP 头注入
- [Phase 03-05]: recipients oneOf list|string + 节点层规范化为 list：DSL UI 友好（单 recipient 时用户可直接写 string）
- [Phase 03-05]: 节点层 _is_valid_email 兜底过滤（正则简易匹配），service 不再二次校验（trust the boundary 原则）

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 2: 需在 M2 首日确认 flock 是否已有 WebSocket 实时画布，决定是否复用或新建
- Phase 3: 后续 plan 测试需保持 Redis 测试容器运行（`docker start agent-builder-redis-test`，端口 16379:6379）
- Phase 4: IM TokenManager（飞书/企微 token 并发刷新竞态）需在接入第一个 IM 适配器时就实现（防 Pitfall 7）
- Phase 5: IM 双向同步需防止"同步 → 触发通知 → IM Bot 收到 → 再次触发同步"循环（防 Pitfall 15）

## Session Continuity

Last session: 2026-05-17
Stopped at: Completed 03-05-PLAN.md（NotificationNodeExecutor 独立通知节点 NODE-07 + enqueue_generic_email + generic_notification.html + 13 集成测试通过；与 HITL 节点完全解耦）
Resume file: None
