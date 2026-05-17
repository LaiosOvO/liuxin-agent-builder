---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-05-17T03:05:00.000Z"
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 38
  completed_plans: 35
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-16)

**Core value:** 让非编码人员通过拖拽 5 分钟搭出"多通道审批 + 公网回调"的 LangGraph 工作流，并真实跑起来
**Current focus:** Phase 4 — 审批链 + IM 通知（12 plans，Wave 1 启动）

## Current Position

Phase: 4 of 7 (审批链 + IM 通知)
Plan: 9 of 12 in current phase（Wave 4 04-07 完成 — WeComProvider wechatpy + Bot Webhook 双路径架构）
Status: ✅ Phase 4 Wave 4 进行中 — 04-06 Feishu / 04-07 WeCom / 04-08 DingTalk / 04-09 Slack 4 家 Provider 已全部完成；Wave 5 04-10 multichannel fan-out 待启动
Last activity: 2026-05-17 — Plan 04-07 完成（企微 IM 通知出站投递 NOTI-03：wechatpy 1.8.18 spike 发现完全无 template_card API → markdown 4 链接方案 + Bot Webhook fallback 双路径架构 + 共享 build_wecom_markdown_content / app_message / webhook envelope 完全一致 + supports_card_update=False 类属性 + update_card 显式 NotImplementedError 引导 send_supplement_text 兜底 + WeChatClientException/errcode≠0/httpx 错误统一包装为 ConnectionError 触发 im_jobs tenacity 重试 + WeComCredentials 新增 bot_webhook_key 字段向后兼容 + IMCredentialsManager 支持 fallback-only 模式 + lifespan 自动按凭据注册 + markdown 注入防护 5 类转义 + 2048 byte 边界保护 + 34 测试全绿 / 77 IM 测试 0 regression）

Progress: [███████░░░] 58%（3/7 phases complete; Phase 4 9/12 plans done — Wave 4 4 家 Provider 全部完成）

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
| Phase 03-hitl-email P06 | 25m | 5 tasks（Task0+pre1+1+2+3+4） | 16 files |
| Phase 03-hitl-email P05 | ~10m | 3 tasks（Task0 reading doc + Task1 impl + Task2 13 测试） | 9 files |
| Phase 03-hitl-email P06 | 25m | 5 tasks（Task 0+pre1+1+2+3+4） tasks | 16 files files |
| Phase 03-hitl-email P07 | 17m | 6 tasks（Task0+pre1+1+2+3+4） | 17 files (13 created + 4 modified) |
| Phase 03-hitl-email P09 | ~26m | 4 tasks（Task0 reading + Task1 scan + Task2 escalation + Task3 rounds） | 9 files (7 created + 2 modified) |
| Phase 03-hitl-email P08 | 28min | 3 tasks | 12 files |
| Phase 03-hitl-email P10 | 10min | 4 tasks | 10 files |
| Phase 04-approval-chain-im P01 | 10min | 3 tasks | 6 files |
| Phase 04-approval-chain-im P04 | 9min | 3 tasks | 6 files |
| Phase 04-approval-chain-im P02 | 16min | 3 tasks（Task0 reading doc + Task1 batch_create_tokens + Task2 chain executor）| 5 files (3 created + 2 modified) — 21 集成测试 (15 chain + 6 batch) |
| Phase 04-approval-chain-im P03 | 11min | 3 tasks（Task0 reading doc + Task1 service + Task2 API endpoint + tests）| 6 files (3 created + 3 modified) — 20 集成测试 (11 service + 9 API) |
| Phase 04-approval-chain-im P05 | 25min | 4 tasks | 14 files |
| Phase 04 P08 | 9min | 3 tasks（Task0 reading doc + Task1 card builder + Task2 Provider）| 7 files (5 created + 2 modified) — 37 测试 (19 单元 + 18 集成) / 80 IM 测试 0 regression / 锁定 dingtalk-stream==0.24.3 |
| Phase 04-approval-chain-im P06 | 12min | 3 tasks | 7 files |

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
- [Phase 03-06]: [Rule 3 - Blocking] node_states 加 payload JSONB 列（migration 0004）— PLAN 假设 payload 存在但 0002/0003 仅 output_summary；HITL 跨 interrupt 状态机必须独立列
- [Phase 03-06]: HMAC session cookie 名 hitl_session_<jti>（非单一 hitl_session）— 用户可同时打开多 token 互不干扰；cookie value = <jti>:<HMAC-SHA256(jti)>（hmac.compare_digest 防 timing attack）
- [Phase 03-06]: Bot UA 检测放 JWT decode 之前 — bot 可能用任意 token 探测，省 CPU + DB 查询（Pitfall 3 优化点）
- [Phase 03-06]: advisory_xact_lock (事务级 RAII) vs advisory_lock (会话级)：commit 时自动释放无需 finally unlock 防泄漏
- [Phase 03-06]: lock_key = hash(thread_id) & 0x7FFFFFFFFFFFFFFF — Python hash() 单进程一致；多进程 PYTHONHASHSEED caveat（v2+ 多实例时改 PG hashtext()）
- [Phase 03-06]: graph_loader 依赖注入（HitlActionService.__init__）— 测试 mock vs 生产 _default_graph_loader 编译 DSL 解耦
- [Phase 03-06]: 422 路径重新渲染 page.html 含 errors（UX 友好让用户修改重试）vs 简单 error.html
- [Phase 03-06]: 异常细分翻译：service 层抛业务异常 → controller 翻译 HTTP 状态码（JtiAlreadyConsumed=409 / FormDataValidationError=422 / TokenExpired=410 / InvalidSignature=401 / FlowInstanceNotFound=404）
- [Phase 03-06]: Bot 路径三重不可逆契约：无 Set-Cookie + 不动 hitl_tokens.used_at + Redis 不写 consumed 标记（Pitfall 3 P0 完整防护）
- [Phase 03-06]: Token-as-login HMAC cookie（Dify 完全没有的独立创新）— 30min session + jti-specific 多 token 隔离 + 防钓鱼（bot UA 路径不发 cookie 阻断 bot 直接 POST）
- [Phase 03-06]: [Rule 1 - Bug] HitlActionService form_schema 校验 if form_schema and form_data → if form_schema（空 form_data 不能跳过 required 字段校验）
- [Phase 03-06]: 并发测试断言宽松化（≥1 ok 而非 ==1）— asyncio.gather 不保证真并发（无 IO-block 时不切换）；advisory_lock 序列化执行后两个不同 jti 都可能 ok 但语义正确
- [Phase 03-07]: [Rule 3 - Blocking] 后端 /hitl/page 与 /hitl/action 增加 Accept: application/json content negotiation — Next.js 前端必须拿结构化 JSON 才能 hydrate UI（03-06 仅实现 HTML）
- [Phase 03-07]: [Rule 3 - Blocking] middleware.ts 加 /hitl/ BYPASS_PREFIXES — 公网决策页不依赖 setup 初始化状态
- [Phase 03-07]: Server Component 不直接 fetch（v1 简化）— useEffect 客户端 fetch 避免 Set-Cookie 头透传复杂性；首屏 loading 约 100ms 可接受
- [Phase 03-07]: 应用层防双提交 submitting useState + disabled 所有按钮 — Pitfall 2 第一道防护配合后端 advisory_lock 第二道防护
- [Phase 03-07]: Discriminated union 类型 HitlPageResponse (按 bot_scan) / HitlSubmitResult (按 ok) — TypeScript 编译期保证分支完整性
- [Phase 03-07]: DeadlineCountdown SSR 安全（初始 nowMs 用 deadlineMs 自身避免 hydration mismatch）+ AbortController + cancelled 双重防护（StrictMode 双 effect 安全）
- [Phase 03-07]: form_data 复杂类型客户端 JSON.stringify 后再 URLSearchParams 提交（后端 jsonschema 再校验）
- [Phase 03-07]: RJSF 5.24（不升 6.x）— 5.24 久经测试且 v1 schema 简单（string/number/textarea/enum），不必踩 6.x 早期坑
- [Phase 03-07]: '/hitl/success/already-submitted' 路径语义化兜底 — DecisionForm 收到 409 时跳此路径，success page 区分文案
- [Phase 03-09]: arq cron 替代 Celery beat（CLAUDE.md §3 锁定 + reading doc §7 详述 6 维度对比）
- [Phase 03-09]: 三档阶梯催办 24h/48h/72h（vs Dify 单一 TIMEOUT 终态）— 业务场景差异：审批人需主动催办，Dify 是表单等用户主动提交
- [Phase 03-09]: [Rule 1 - Bug] _trigger_reminder 不复用 NotificationService.enqueue_hitl_email — 后者内部 commit() 提前释放 advisory_lock 破坏并发隔离；改为直接 INSERT + 上层统一 commit
- [Phase 03-09]: [Rule 1 - Bug] _process_node 入参 ns_id（vs ORM 对象）— 锁内重新 db.get(NodeState, ns_id) 加载 fresh，避免 detached object 跨 session race
- [Phase 03-09]: [Rule 3 - Blocking] 测试 fixture clean_phase3_tables yield 后加 engine.dispose() — scan_hitl_timeouts 用 async_session_maker 跨 fixture session，跨测试事件循环需 dispose 防污染
- [Phase 03-09]: EscalationService.resolve_escalate_to Phase 3 简化 — node_config.escalate_to email > workspace admin > super_admin > None；Phase 5 扩展 role:admin / dept:HR
- [Phase 03-09]: 升级邮件无决策按钮 — admin 需先看上下文（不在邮件内直接决策升级件）；催办邮件保留按钮（actor 已知上下文）
- [Phase 03-09]: payload.escalation=True 标识 + reminder_round=3 — email_jobs._render_email_content 据此路由 hitl_escalation.html（与催办 hitl_reminder.html 解耦）
- [Phase 03-09]: scan_hitl_timeouts cron `unique=True` + `max_tries=1` — 多 worker 唯一执行（防重复扫描）+ 失败不重试（60s 后下次 cron 再来防补发风暴）
- [Phase 03-09]: advisory_xact_lock(hash(ns_id)) + UNIQUE 约束双保险 — lock 是性能层防 race，UNIQUE 是正确性层兜底
- [Phase 03-08]: Service 层脱敏 vs schema/controller 层 — OpenAPI 文档统一，前端无角色分支，DB 数据始终完整（admin 见 ip/ua，申请人置 None）
- [Phase 03-08]: 跨 workspace → 404 (WorkspaceScopedQuery 过滤即等同'实例不存在') vs 同 ws 非 applicant → 403 (CONTEXT 明确要求) — 双 status 防泄漏存在性
- [Phase 03-08]: current_node 优先 HITL active 节点 (waiting_human/in_review) — 申请人最关心当前等谁
- [Phase 03-08]: 节点可视化字段全套实现 (user feedback_node_visualization 2026-05-17): id/title/status/node_type/actor/deadline_at 全部暴露
- [Phase 03-08]: DeadlineCountdown 3 级颜色 urgent (<1h or overdue red) / warning (<6h amber) / normal (green) — 视觉紧迫感分层；前端 setInterval(1s) 不轮询后端
- [Phase 03-08]: 前端 sanitizeRecord 双重保险 — 即使后端漏脱敏 ip/ua，组件强制丢弃；CONTEXT 隐私契约 defense-in-depth
- [Phase 03-08]: useQuery refetchInterval 仅在 active 节点存在时 30s — 终态实例不浪费带宽
- [Phase 03-08]: 403/404 自动跳回 /dashboard/instances (1.2s 延时) — 给用户读错误信息但不卡死
- [Phase 03-08]: [Rule 1 - Bug] 移除多余 autouse engine.dispose fixture — 与 conftest.db_session 重叠 race（test_instances_api 同样模式 pre-existing 待 Phase 7 修复）
- [Phase 03-10]: 5 spec ↔ 5 ROADMAP criteria 1:1 追溯（spec 头注释 + describe 标签双重明示，可机械化 grep 验证）
- [Phase 03-10]: Smoke 默认 skip + RUN_E2E=1 opt-in 触发：CI 默认无 docker-compose 全栈，对 Phase 1/2 E2E 模式保持一致
- [Phase 03-10]: 复用 Phase 1 mailhog-client + Phase 2 dsl-builder；新增 hitl-builder + hitl.page (公网无登录) + tracking.page (申请人 dashboard)
- [Phase 03-10]: Bot UA 4 种 parametrize：Outlook AC-Detector-Tool / MS Defender / Slackbot / Googlebot — CLAUDE.md 2.5 P0 完整覆盖
- [Phase 03-10]: 裸 fetch (fetchPageRaw / submitActionRaw) 模拟 bot UA：spec 控制 headers + 无浏览器解析开销（page.setExtraHTTPHeaders 留 Phase 4 跨浏览器）
- [Phase 03-10]: 断言 jti 未消费用语义化方式（bot 扫描后真实用户仍可签 cookie + POST 成功）而非直连 DB — admin API 当前不存在
- [Phase 03-10]: advisory_lock 并发断言 ≥1 而非 ==1（与 03-06 同模式 — asyncio.gather 不保证真并发）
- [Phase 03-10]: 汇总型 reading doc（不读新 Dify 代码）— Phase 3 终结性 plan 整合前 9 plan reading docs + 测试模式总结
- [Phase 03-10]: mailhog MIME body 简单切分（regex HTML/text + quoted-printable 解码）— 不引入 mailparser 依赖
- [Phase 04-01]: ChainAdvanceResult 用 @dataclass(frozen=True) + field(default_factory=list) 而非 Pydantic/TypedDict/NamedTuple — frozen 保证 immutable + default_factory 防共享 mutable 默认值陷阱（零依赖 + 零运行时开销）
- [Phase 04-01]: compute_chain_advance 4 chain mode × 3 action = 12 状态机分支全覆盖（_advance_single/_advance_sequential/_advance_parallel_all/_advance_parallel_any 四 helper 各自负责一种 mode）
- [Phase 04-01]: build_initial_payload 默认 chain_mode='single' 保持 Phase 3 完全向后兼容；parallel_* 模式自动初始化 decisions 字典；single/sequential 不初始化 decisions（用 current_idx 推进）
- [Phase 04-01]: invalidate_chain used_ip='system:chain-invalidate' / used_ua='system:invalidate_chain' — 与 sibling-invalidate / 真实用户消费三层审计区分
- [Phase 04-01]: supplement_notify 智能过滤：parallel_* 终止时仅通知「未决策 + 非当前 actor」的 approver — 已决策 token 已自然消费，避免重复补通知
- [Phase 04-01]: sequential 越权防护：only approvers[current_idx] 能决策；不依赖 actor_id ∈ approvers 弱校验（防中间人提前 approve）
- [Phase 04-01]: [Rule 3 - Blocking] Alembic migration revision 0004 已被 0004_phase3_node_state_payload 占用 → 用 0005，down_revision='0004'（不重命名既有 migration，避免 alembic_version 表混乱）
- [Phase 04-01]: 0005 partial index `WHERE used_at IS NULL` — invalidate_chain 仅扫未消费 token，partial index 体积更小、更新代价更低
- [Phase 04-01]: 严格 immutability 测试：copy.deepcopy(payload) 前后 deep equal 断言 + result.new_payload["approval_chain"] is not payload["approval_chain"] 对象 identity 断言（4 测试覆盖三模式）
- [Phase 04-01]: _advance_single 包装 Phase 3 行为 + 返回 ChainAdvanceResult — 调用方对 4 模式统一处理无特殊分支（invalidate_others=False）
- [Phase 04-04]: resolve_escalate_to 返回类型 str → list[str] 向后兼容（role: 可能匹配多人，单 email 也包成 [email] 统一处理逻辑）
- [Phase 04-04]: Expression Prefix Routing — startswith('dept:'/'user:'/'role:') 顺序判断 + email (含 @ 无 :) + fallback workspace admin 五分支
- [Phase 04-04]: dept:<name> raise NotImplementedError + perform 层 catch 跳过升级 — Phase 5 IM 目录同步留 hook，worker 健壮性优先
- [Phase 04-04]: _get_user_email JOIN UserWorkspaceRole 强制 workspace_id WHERE — 多租户隔离防 attacker 配 user:<其他 ws uuid> 越权拿 email
- [Phase 04-04]: audit_log per-row vs 合并一行 — N 升级人写 N 条 audit，便于"我作为升级人收到过哪些"聚合查询；meta.escalate_to 单 email（本行）+ meta.escalate_count（总数）
- [Phase 04-04]: role: miss → fallback admin（与无 escalate_to 一致行为）—  不是「role: 必须命中」严格模式，保持 fallback chain 单一可预测
- [Phase 04-04]: structured logger.info('hitl.escalation.resolved', extra={expression, matched_count, successful_count, ws_id, ns_id, instance_id}) — Phase 7 ELK / Loki 表达式命中可观测性输入
- [Phase 04-04]: 单 email try/except 包住 — 一人发邮件失败不阻塞其他升级人（借鉴 Dify timeout task：单 form 异常不阻塞 worker）
- [Phase 04-02]: submit_action 在 Phase 3 11 步流程中插入 step 6 chain 分叉 (compute_chain_advance) — 保留 Phase 3 advisory_lock / jti 消费 / sibling 失效原结构，最小侵入 + 100% 单人模式向后兼容
- [Phase 04-02]: parallel_* mode invalidate_siblings 改为只失效自己其他 action token (_invalidate_self_other_actions) — 不像 single/sequential 整 node_state 失效（其他 actor 还需继续审批）
- [Phase 04-02]: parallel_* 终止（任一 reject 或 parallel_any 任一 approve）→ invalidate_chain 在 advisory_lock 内调（Pitfall 2 防 race）
- [Phase 04-02]: sequential approve 推进 → batch_create_tokens_for_actors(next_approvers, ['approve','return','reject']) — chain 中非首发审批人无 submit 权
- [Phase 04-02]: audit_log per submission 加 chain_mode + invalidated_count + next_approvers — 多人审批审计完整
- [Phase 04-02]: structured log message='hitl.chain.advance' + 8 字段 extra dict — Phase 7 ELK / Loki 结构化查询友好（vs 字符串拼接）
- [Phase 04-02]: ChainActorNotAuthorized 翻译 compute_chain_advance ValueError → 403（actor 不在 approvers）；不在 service 层暴露 ValueError 给 API 层
- [Phase 04-02]: chain_advance 失败 → 整事务回滚（jti 消费 + sibling 失效全 rollback） — 半状态防护
- [Phase 04-02]: single 模式仍走 compute_chain_advance 包装（new_status 仍用 compute_next_status）—向后兼容 Phase 3 测试 100%
- [Phase 04-02]: _supplement_notify 按 actor_id 去重发邮件 — A reject 时 B/C 6 token 失效只发 2 封（per actor 一封）避免邮件骚扰
- [Phase 04-03]: deadline_at **重置** (now + node_config.timeout_seconds) — 不继承原 deadline（04-RESEARCH §三决策修正 CONTEXT）；被委托人新上岗给完整 timeout 窗口
- [Phase 04-03]: 委托链深度 MAX_DELEGATION_DEPTH=3 常量定义 — 防责任稀释 + 防委托环；超过 raise DelegateError → 409 Conflict
- [Phase 04-03]: 5 DelegateError 错误码 + HTTP 状态映射：depth_exceeded → 409；self_delegate / circular / recipient_not_found / cross_workspace → 422
- [Phase 04-03]: 双层防环：to_user.id != from_user.id (self_delegate) + to_user.id NOT IN approvers_ids (circular)
- [Phase 04-03]: 同 workspace 强校验 SQL JOIN user_workspace_roles — 跨 ws 返回 recipient_not_found（统一 422 防 tenant 存在性泄漏，非 403）
- [Phase 04-03]: 原 token 立即失效 HitlTokenStore.consume + used_ip 标 ':delegate' 后缀识别来源（与 sibling-invalidate / chain-invalidate / 真实用户消费四种来源审计区分）
- [Phase 04-03]: records 追加 type=delegate 一条（含 delegate_to_id + depth + ip + ua） + approval_chain.delegated[from_user_id] = {to, depth} immutable 更新
- [Phase 04-03]: DelegateError 业务校验失败 → db.rollback 防 token 半状态（原 token 已 consume 但 new_tokens 未创建）
- [Phase 04-03]: 用 op Query 参数路由 vs 新路由 /hitl/delegate — 选 op Query (复用 advisory_lock + JWT 解码 + cookie 校验)；新路由需重复 200+ 行前置代码
- [Phase 04-03]: [Rule 3 - Blocking] 回归测试用 Accept: application/json 走 JSON 路径 — 规避 deferred-items.md §1 记录的 Starlette 1.0 HTML 模板预先存在 bug（不在 04-03 范围）
- [Phase 04-approval-chain-im]: [Phase 04-05] IMProvider Protocol（鸭子类型 + Phase 4.5 预留 subscribe/verify_webhook_signature）+ 模块级 Registry + MockIMProvider + IMCredentialsManager 5 家 frozen dataclass + im_jobs.send_hitl_card_job + 43 测试
- [Phase 04-05]: Protocol over ABC — 用 typing.Protocol + runtime_checkable 不用 abc.ABC（CLAUDE.md python/patterns.md 推荐 + MockIMProvider 无需继承基类即可满足鸭子类型）
- [Phase 04-05]: [Rule 3 - Blocking] runtime_checkable Protocol 校验依赖方法存在性 → MockIMProvider 必须显式实现 subscribe/verify_webhook_signature 抛 NotImplementedError（Protocol body NotImplementedError 默认行为不会被自动继承到鸭子类型 instance — 这与 ABC 行为不同）
- [Phase 04-05]: 模块级 Registry dict + factory function（不用 FastAPI Depends — provider 应在 startup 一次注册而非每请求初始化）
- [Phase 04-05]: 5 家 frozen dataclass per provider credentials（vs 通用 dict[str,str]）— 类型清晰 + immutable 防外部修改
- [Phase 04-05]: env 缺失 warn 不抛错（按需配置 — 用户可能只用 2-3 家）；getter 调用时缺失抛 RuntimeError + 提示需要的环境变量名
- [Phase 04-05]: env strip + 空字符串视为未配置（防 .env 文件意外引号 / 空格）
- [Phase 04-05]: register_provider 校验 name 必须在 KNOWN_PROVIDERS 集合（typo 防护，FakeProvider 抛 ValueError）
- [Phase 04-05]: get_provider 抛 KeyError 时携带已注册列表（便于排查）
- [Phase 04-05]: im_jobs 克隆 email_jobs 状态机（pending→sending→sent/failed + tenacity 3 次 1s/2s/4s + audit_log 失败可观测）
- [Phase 04-05]: im_jobs payload['im_message_id'] 写回供后续 update_card 用（新 dict immutable 模式，不修改既有 payload dict）
- [Phase 04-05]: 结构化日志 logger.info('im.card.send', extra={provider, recipient, status, latency_ms, notification_id, message_id}) — Phase 7 ELK / Loki 查询友好
- [Phase 04-05]: [Rule 1 - Bug] unknown provider 路径 audit_log 必须在 commit 之前调（而非之后） — 否则 audit_log 仅 buffered 不 flush 导致测试断言行数 0 失败
- [Phase 04-05]: 不引入新 IM SDK 依赖（lark-oapi / wechatpy / 等留 04-06+ Provider 实现 plan 单独 import）
- [Phase 04-05]: backend/app/agent_builder/core/ 独立目录（不动 flock app/core/ — CLAUDE.md §2.3 Fork discipline）
- [Phase 04-05]: CardBuilder 用 Protocol 不用基类（各 Provider plan 自实现 build_hitl_card / build_supplement_text）
- [Phase 04-05]: HitlCardPayload 用 tuple[dict[str,str], ...] 而非 list（frozen dataclass + 不可变集合双重防修改）
- [Phase 04-08]: OAPI HTTP 直调（dingtalk-stream 0.24.3 SDK 不暴露工作通知 ActionCard send 方法）— httpx.AsyncClient 调 /topapi/message/corpconversation/asyncsend_v2
- [Phase 04-08]: access_token 走 SDK 同步 get_access_token + asyncio.to_thread 桥接 — 保留 SDK 5min buffer 缓存逻辑，避免重写
- [Phase 04-08]: btn_orientation="0" 字符串硬编码横排（钉钉 OAPI 要求 string 类型，PC + 手机最佳兼容）
- [Phase 04-08]: update_card 抛 NotImplementedError + 提示用 send_supplement_text — 钉钉工作通知 ActionCard 静态不支持改（与企微一致）
- [Phase 04-08]: ConnectionError 统一包装 — OAPI errcode != 0（如 40078 token 过期）/ 网络错 / 5xx 都包装为 ConnectionError 触发 tenacity 重试新 token 后可成功
- [Phase 04-08]: _ZH_LABELS 中文 label 映射 + 未知 action 退化为原字符串（防新 action 类型加入报错）
- [Phase 04-08]: 固定走 btn_json_list（即使 1 按钮也用列表）— 避免 single_title/single_url 与 btn_json_list 互斥触发 OAPI 错
- [Phase 04-08]: DINGTALK_AGENT_ID 直接从 env 读（非 IMCredentialsManager 字段）— 是部署 config 而非凭据本身，避免改 04-05 已完成 plan
- [Phase 04-08]: [Rule 3 - Blocking] pyproject.toml 加 dingtalk-stream==0.24.3 锁定（手工 pip install 仅本地生效）
- [Phase 04-08]: [Rule 2 - Missing Critical] lifespan 新增 _register_im_providers_if_configured + _close_registered_im_providers 基础设施，为 Wave 4 其他 Provider plan 建好扩展点
- [Phase 04-approval-chain-im]: [Phase 04-06] importlib.metadata.version 取代不存在的 lark.__version__ — SDK 版本校验陷阱
- [Phase 04-approval-chain-im]: [Phase 04-06] update_card 24h 过期 (code=234016) → log warning 不抛错，避免 tenacity 无谓重试
- [Phase 04-approval-chain-im]: [Phase 04-06] 同步 lark-oapi 1.6.5 在 asyncio 内通过 loop.run_in_executor 包装 — 未公开 AsyncClient

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 2: 需在 M2 首日确认 flock 是否已有 WebSocket 实时画布，决定是否复用或新建
- Phase 3: 后续 plan 测试需保持 Redis 测试容器运行（`docker start agent-builder-redis-test`，端口 16379:6379）
- Phase 4: IM TokenManager（飞书/企微 token 并发刷新竞态）需在接入第一个 IM 适配器时就实现（防 Pitfall 7）
- Phase 5: IM 双向同步需防止"同步 → 触发通知 → IM Bot 收到 → 再次触发同步"循环（防 Pitfall 15）

## Session Continuity

Last session: 2026-05-17
Stopped at: Completed 04-08-PLAN.md（Phase 4 Wave 4：钉钉 ActionCard 工作通知出站投递 — DingTalkProvider 实现 IMProvider Protocol + build_dingtalk_action_card (btn_orientation="0" 横排 3 中文按钮) + access_token via SDK + httpx.AsyncClient OAPI 直调 + update_card → NotImplementedError + send_supplement_text 兜底 + agent_builder/main.py lifespan 按需注册扩展点 + 37 测试全绿 + 80 IM 测试 0 regression）
Resume file: None
Next action: Wave 5 04-10 multichannel fan-out（NotificationService 扩展支持 notify_channels 数组 + 并发投递路由到 5 家 Provider Registry + sibling token 跨通道失效）
