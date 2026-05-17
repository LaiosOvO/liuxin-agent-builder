---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: milestone
status: unknown
last_updated: "2026-05-17T15:53:26.378Z"
progress:
  total_phases: 7
  completed_phases: 5
  total_plans: 50
  completed_plans: 46
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-16)

**Core value:** 让非编码人员通过拖拽 5 分钟搭出"多通道审批 + 公网回调"的 LangGraph 工作流，并真实跑起来
**Current focus:** Phase 4 — 审批链 + IM 通知（12 plans，Wave 1 启动）

## Current Position

Phase: 5.B of 7 (Plugin 沙箱 + Daemon 资源限制) — Wave 1 进行中
Plan: 01 of 05 in current phase（5.A 全 7/7 ✓；5.B Plan 01 Wave 1 ✓ — SandboxConfig schema 扩展完成）
Status: 🚀 Plan 05b-01 Complete（SandboxConfig 7 字段 + 2 派生属性 + sandbox/parser.py K8s 单位解析 helper — PLUG-FW-13 完成）
Last activity: 2026-05-17 — Plan 05b-01 完成（Phase 5.B Wave 1：SandboxConfig 从 3 字段 placeholder 扩展为 7 字段 + 2 派生属性 + 3 validators + sandbox/ 子包：cpu_limit '2.0' pattern ^\d+(\.\d+)?$ / memory rename memory_limit→memory '1Gi' + field_validator 调 parse_memory / network list[str] regex ^[a-z0-9.-]+:\d+$ 默认 [] 禁所有出站 / timeout_invoke int Field gt=0 le=3600 / timeout_idle int Field gt=0 le=86400 / use_cgroups bool False / env_allowlist list[str] 默认 [] Pitfall 8 防 secret 泄漏 + memory_bytes property → parse_memory / cpu_limit_seconds property → parse_cpu_seconds + sandbox/parser.py 119 行 0 Pydantic 依赖 K8s 单位 SI K/M/G/T + binary Ki/Mi/Gi/Ti + 裸 bytes + parse_cpu_seconds 保守 3600s × cores RLIMIT_CPU 累积秒 + docs/reading-dify-05b-01-sandbox-config-2026-05-17.md 174 行 6 借鉴点 5 显式偏离 Dify PluginResourceRequirements 仅 memory:int Python 主仓库不做 sandbox enforcement 全下沉 Go daemon vs 我们 Python 主进程 setrlimit baseline + ConfigDict extra=forbid 与 5.A 决策一致 + plugins/huly/platform.yaml 加 sandbox 段 timeout_* / use_cgroups / env_allowlist HULY_ENDPOINT 演示新字段 + 49 测试 pass 21 parser SI/binary 单位 edge case 负数 + 14 TestSandboxConfig 默认值 validator 范围 property 派生 + 13 5.A baseline 0 regression + 193 platforms tests pass + 5/5 acid test pass + deferred-items.md 记 lark_oapi 模块 pre-existing dev env 缺失 out of scope + 4 commits e5d06cd docs 0a33a08 feat parser 1fc573d feat SandboxConfig 1c4d79e test [Deviation Rule 3 - Blocking] rename memory_limit→memory 同步 fixture + test 断言）

Progress: [██████████] 97%（4/7 phases complete; Phase 5.A 7/7 ✓ 全完成 + Phase 5.B 1/5 plans done — Wave 1 SandboxConfig schema 落地完成，Wave 2/3 plans 接口契约 freeze，可并行 dispatch）

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
| Phase 04-approval-chain-im P07 | ~10min | 4 tasks（Task0 reading doc + Task1 spike 30min 上限内 5min 完成 + Task2 card builder + Task3 Provider/lifespan）| 8 files (5 created + 3 modified) — 34 测试 (17 card + 17 provider) / 77 IM 测试 0 regression / wechatpy 1.8.18 模块路径 enterprise 而非 work + 无 template_card API → 双路径 markdown 方案 |
| Phase 04-approval-chain-im P09 | 16min | 4 tasks | 13 files |
| Phase 04-approval-chain-im P10 | 22min | 4 tasks | 10 files |
| Phase 04-approval-chain-im P11 | 20min | 3 tasks（Task 0 reading doc + Task 1 interrupt chain + Task 2 _on_hitl_enter）| 6 files (3 created + 3 modified) — 25 新测试 (13 chain interrupt 单元 + 12 _on_hitl_enter 集成) / Phase 3+04-02+04-10 既有 61 测试 0 regression |
| Phase 04-approval-chain-im P12 | ~35min | 6 tasks（Task 0 双 reading doc + Task 1 backend test_helpers + Task 1.5 e2e_v2 helpers + Task 2 3 chain specs + Task 3-5 3 final specs）| 22 files (16 created + 3 modified + 3 docs) — 36 测试 (10 backend test_helpers + 26 e2e_v2 specs Smoke 全 skip / Standard 跑全部) / 17 Phase 1-3 Playwright spec 完全不动 / 54 关联 backend 测试 0 regression |
| Phase 05a-platform-plugin-framework P02 | ~14min | 3 tasks（Task 0 reading doc + Task 1 IMCapability + Task 2 DocCapability）| 7 files (1 doc + 4 source + 2 test) — 17 测试 (8 IM + 9 Doc) / 74/74 platforms tests pass / Phase 4 IM Protocol 0 regression / Huly acid test gap #a + #2 解决 / 注：Task 1 文件被并行 Plan 03 commit b0353c0 一并 bundled（git ls-tree 验证文件归属正确）|
| Phase 05a-platform-plugin-framework P03 | 15min | 3 tasks | 10 files |
| Phase 05a-platform-plugin-framework P04 | 15m | 3 tasks | 12 files |
| Phase 05a-platform-plugin-framework P06 | 14min | 3 tasks | 7 files |
| Phase 05a-platform-plugin-framework P05 | 16min | 3 tasks（Task 0 reading doc + Task 1 PlatformDaemonClient + echo_daemon + 11 单测 + Task 2 capability_facades 替换 stub + MockPlatformPlugin + 13 单测）| 9 files (6 created + 2 modified) — 24 新测试 pass（含 Pitfall 2 fault isolation 关键 test_daemon_crash_fails_pending_future invoke_timeout=2.0 elapsed<2.0s）+ 141/141 全 platforms tests pass + Phase 4 IM 51 测试 0 regression + 集成手工验证 facade→daemon→echo_daemon→response→dataclass rebuilt 通过 |
| Phase 05b-plugin-sandbox P01 | 14min | 3 tasks（Task 0 Dify reading doc + Task 1 SandboxConfig 扩展 + sandbox/parser.py + Task 2 49 单测）| 10 files (6 created + 4 modified) — 49 测试 pass（21 parser SI/binary 单位 + 14 TestSandboxConfig + 13 5.A baseline + 1 fixture update）+ 193 platforms tests pass + 5/5 acid test pass + 0 5.A regression / [Deviation Rule 3] rename memory_limit→memory 同步 fixture + 1 测试断言 / Wave 2/3 plans 接口契约 freeze（memory_bytes / cpu_limit_seconds / env_allowlist 注入点确定） |
| Phase 05b P01 | 14min | 3 tasks | 10 files |

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
- [Phase 04-07]: Spike 关键发现 — wechatpy 1.8.18 模块路径是 `wechatpy.enterprise` 不是 `wechatpy.work`（现代版本路径不存在），且完全无 template_card/button_interaction API；唯一能放置多链接的是 `send_markdown`（markdown 子集支持 `[text](url)`）
- [Phase 04-07]: 不引入 wxwork/wecom-api 替代 SDK — 未审计供应链风险更大；wechatpy markdown 4 链接是等效体验
- [Phase 04-07]: 双路径架构（主路径 wechatpy app message user-targeted + Fallback Bot Webhook 群投递）— SDK 停更时 fallback 完全独立运作（仅依赖 httpx）
- [Phase 04-07]: 自动 fallback 选择 — app 凭据缺失但 bot_webhook_key 存在 → use_bot_fallback=True 自动开启（用户无需手动配置 flag）
- [Phase 04-07]: 主路径 + fallback 共享 build_wecom_markdown_content（envelope 完全一致：{msgtype:markdown, markdown:{content}}）— DRY
- [Phase 04-07]: WeChatClientException + 业务 errcode≠0 + httpx 错误**统一**包装为 ConnectionError → 让 im_jobs tenacity 3 次重试（token 抖动 / 临时权限刷新场景必须可重试）
- [Phase 04-07]: 错误消息截断 200 字符（CLAUDE.md security 防 secret 泄露 / 日志爆量）
- [Phase 04-07]: update_card 显式 NotImplementedError + supports_card_update=False 类属性 — 让 04-10 fan-out 调用方据此自动选择 send_supplement_text 兜底
- [Phase 04-07]: WeComCredentials 新增 bot_webhook_key 字段默认 ""（向后兼容 — 上游 15 个 credentials 单元测试零修改）
- [Phase 04-07]: IMCredentialsManager._load_from_env 支持 fallback-only 模式（仅 bot_webhook_key 配置时创建 WeComCredentials with empty app fields）
- [Phase 04-07]: WeComProvider 延迟 SDK import + _get_client 私有方法 — 测试 monkeypatch 可拦截 client，主代码无需 wechatpy 可成功 import
- [Phase 04-07]: markdown 注入防护 5 类转义（方括号 `[` `]` / 反引号 `` ` `` / 星号 `*` / 下划线 `_` / 角括号 `<` `>`）+ 2048 byte 边界保护（超长截断 description + utf-8 字符边界对齐）
- [Phase 04-07]: [Rule 1 - Test Bug] test_content_with_only_subset_of_deeplinks 误判（'详情' 在 description label 中也出现） → 改为 `[详情](` 链接形态精确匹配
- [Phase 04-07]: [Rule 1 - Test Bug] test_send_via_app_message_passes_correct_agent_id_and_recipient agent_id 期望 str → wechatpy 要求 int，调整断言为 int
- [Phase 04-approval-chain-im]: Plan 04-09: 3 IM providers (Slack/Mattermost/Webhook) 全部用 httpx 直调 REST API 不引入 slack-bolt / mattermost-driver 重依赖
- [Phase 04-approval-chain-im]: Plan 04-09: WebhookProvider 用 HMAC-SHA256 + sort_keys 稳定序列化签名 X-Agent-Builder-Signature header 防伪造 (NOTI-07)
- [Phase 04-10]: enqueue_hitl_multichannel 是新方法（不修改 enqueue_hitl_email）— 保持 Phase 3 测试 100% 向后兼容
- [Phase 04-10]: 事务边界 commit 后才 enqueue_job — Dify 模式 2 + 本项目 Pitfall 2 防护（worker 抢跑事务未提交行）
- [Phase 04-10]: im_bindings 缺失 → log warning + skip channel（不抛错）— 用户可能只为部分 channel 配置 IM 账号
- [Phase 04-10]: 每行独立 payload dict 副本 — im_jobs 写回 im_message_id 不污染其他 channel 行
- [Phase 04-10]: NOTIFY_CHANNELS_ENUM 模块常量 — hitl_schema + notification_schema 共享一个 list 引用（identity check 测试覆盖）
- [Phase 04-10]: notification_schema 'wechat' → 'wecom' — 与 PROVIDER_WECOM / _IM_CHANNELS 全栈命名一致 (修正 Phase 3 残留)
- [Phase 04-10]: 旧 DSL 无 channels/notify_channels 字段 → 默认 ['email'] — Phase 3 测试 0 regression
- [Phase 04-10]: _normalize_recipients 按 channel 类型分校验策略 — email 严格 / IM 宽容（避免 IM user_id 被误过滤）
- [Phase 04-10]: 单 channel 失败不阻塞其他 — per-channel try/except 包裹整 channel 循环
- [Phase 04-10]: [Rule 1 - Bug] test_notification_node_unsupported_channel_skipped 改为 test_notification_node_unknown_channel_skipped — Plan 04-10 feishu 已支持，sms 才是真正未知
- [Phase 04-10]: 结构化日志 message='notification.multichannel.enqueued' + extra={channels, notification_ids, instance_id, ...} — Phase 7 ELK / Loki 查询友好
- [Phase 04-10]: [Rule 3 - Blocking] deferred-items.md 登记 test_dsl_schema.py::test_all_node_types_registered 失败 — Plan 03-05 引入 notification 时遗留，与 04-10 改动无关
- [Phase 04-10]: enqueue_generic_im_card(channel='email') → ValueError — 强制走 enqueue_generic_email 避免歧义
- [Phase 04-12]: 工具切换 (用户 2026-05-17 指令) — Playwright → browser-use/browser-harness；Phase 1-3 既有 11 Playwright spec 保留不动新建 e2e_v2/ 栈并存（fork discipline + 不破坏既有信号）
- [Phase 04-12]: 双 reading doc gate (CLAUDE.md §2.7 硬性) — reading-browser-harness (340 行) + reading-dify-e2e (140 行 关键结论 Dify 无 E2E 层) 先 commit 才允许写代码
- [Phase 04-12]: browser-harness 仅 #5 IM card click + #6 delegate UI 启浏览器；其他 4 chain/escalation spec 纯 pytest+httpx — bot UA 用 httpx 不走浏览器更直接验证后端
- [Phase 04-12]: test_helpers 路由 ENABLE_TEST_API=1 条件挂载 (双层防御) — main.py 启动时警告 log；生产 nginx 公网层可加 /api/test/ 黑名单 (第三层防御)
- [Phase 04-12]: SetupRedirectMiddleware /api/test/ 白名单 — test_helpers 路由需绕过 setup gate (E2E 准备数据前可能未 initialize)；仅 ENABLE_TEST_API=1 + 路由挂载才有效安全等价
- [Phase 04-12]: mock_im_providers fixture autouse=False scope='session' — 避免污染既有 81 IM provider 单元测试 (自管 mock)；显式引用时才覆盖 registry
- [Phase 04-12]: Safe Links 4 bot UA × 3 chain mode = 12 parametrize 测试矩阵 — chain mode 多 token 活跃时 bot 扫一个不能影响其他 (parallel/sequential 都需独立回归)
- [Phase 04-12]: GET /api/test/hitl_tokens?jti=X 查 used_at 是 Safe Links 回归 P0 基础 — vs 直连 DB (spec 进程不持有 DB 连接复杂性)
- [Phase 04-12]: MockIMProvider mock.calls 不通过 ORM 暴露 — GET endpoint 接口隔离 spec 进程与 DB session 复杂性
- [Phase 04-12]: 部分 E2E spec skip 解释 — 委托主流程 (#6) / IM card 严格路由 (#5) 需 backend 提供 admin user-update endpoint 写 im_bindings + 完整多用户 cookie 链路；委托后端单元 + 集成测试 100% 覆盖于 Plan 04-03 (17 测试)，escalation 24h 真实快进留 Phase 4.5+ 实现 mock_time
- [Phase 04-12]: frozen=True dataclass 3 处 — HitlDeeplink (mailhog 解析) / HitlEmailParsed (整封邮件结构) / DecisionPageVerification (browser-harness 结果) — CLAUDE.md immutability 全面落地
- [Phase 04-12]: [Rule 3 - Blocking] AuditLog 字段名 actor_user_id 不是 actor_id — 初版 test_helpers.py 用错字段，改 actor_user_id + 增 actor_meta/actor_ip/actor_ua/decision
- [Phase 04-12]: [Rule 3 - Blocking] engine.dispose() 防 audit_logs 测试 loop race — 跨测试 asyncpg 连接绑定旧 event loop 'Event loop is closed'，与 test_instances_api/test_hitl_action_service 同模式
- [Phase 04-approval-chain-im]: ✅ 全 12 plan 完成，等待 /gsd:verify-work 阶段验证
- [Phase 05a-01]: WorkspacePluginInstallation 9 字段表 + Alembic migration 0006 + tests/platforms/ 测试目录 + workspace_id 双租户 fixture
- [Phase 05a-02]: IMCapability `@runtime_checkable Protocol` + RecipientSpec 多态（kind: Literal["channel","dm_user","thread"]）解决 Huly acid test gap #a — Phase 4 仅 `recipient: str` 升级
- [Phase 05a-02]: DocCapability 双路径分离 — supports_collaborative_edit=False → replace_document_content (Outline/Lark) / =True → apply_document_delta (Huly/Notion CRDT) — 调错路径 raise NotImplementedError 解决 Huly acid test gap #2
- [Phase 05a-02]: DocInfo.content_markdown 设 Optional — Huly 二跳 fetchMarkup 风格支持（避免 N+1 调用强制返回）
- [Phase 05a-02]: subscribe_events `async def f: if False: yield {}` pattern + `inspect.isasyncgenfunction` 静态断言测试 — runtime_checkable 不检查方法类型（仅 name + attr），必须显式断言 async generator 语义
- [Phase 05a-02]: 8 值对象全 frozen=True 100% — RecipientSpec/MessageRef/NormalizedCard/DocRef/DocInfo/CRDTDelta/CommentRef/UserRef（CLAUDE.md immutability 全面落地）
- [Phase 05a-02]: PluginError 5 异常类集中定义于 platforms/exceptions.py — 不分散到各 capability file；PluginInvocationError 携带 error_payload dict 便于上层 except 后获取 daemon 原始错误码
- [Phase 05a-02]: 不写 capabilities/__init__.py 完整 exports — Plan 03 独占（避免并行写冲突）；Plan 02 tests 用直接子模块 import `from app.agent_builder.platforms.capabilities.im import ...`
- [Phase 05a-02]: capabilities/__init__.py 空 placeholder（Plan 02 创建）— 实际被并行 Plan 03 commit b0353c0 overwrite 为完整 exports（含 IM/Doc 条件 import + 4 类必有 export）
- [Phase 05a-02]: Task 1 文件（exceptions.py + im.py + test_capabilities_im.py + platforms/__init__.py）被并行 Plan 03 agent 一并 bundled 到 commit b0353c0 — git 文件归属 / 内容 100% 按 Plan 02 PLAN.md 设计，仅 commit message 归属 Plan 03（良性 git 行为，无返工）
- [Phase 05a-04]: PlatformManifest name pattern `^[a-z][a-z0-9_-]{2,31}$` 比 Dify `^[a-z0-9_-]{1,128}$` 更严 — 首字符强制小写字母 + 长度 3-32（便于 daemon 进程名 / 文件路径 / log subject 生成）
- [Phase 05a-04]: PlatformManifest version 三段 SemVer `^\\d+\\.\\d+\\.\\d+$` 简化 vs Dify `packaging.Version` 接受 dev/rc 后缀 — v1 不支持预发布版本（v2 可放宽）
- [Phase 05a-04]: CapabilitySpec 聚合单 class 含全 6 cap flag（vs PLAN.md 推荐分散 IMCapabilitySpec/DocCapabilitySpec/...）— extra=forbid 仍生效防 typo，让 manifest YAML 结构平 + 字段少（6 个）union 模型实用（v2 字段多了可拆细）
- [Phase 05a-04]: PlatformManifest 顶层 + 3 嵌套子类型（RuntimeConfig/CapabilitySpec/SandboxConfig）全 ConfigDict(extra="forbid") — 顶层 + 嵌套都防 typo（CONTEXT.md 强制决策）
- [Phase 05a-04]: load_manifest 异常翻译模式 — yaml.YAMLError / Pydantic ValidationError / file not found / 顶层非 mapping 统一翻译为 ManifestValidationError（用 `raise ... from e` 保 chain）
- [Phase 05a-04]: PlatformPluginRegistry classmethod-only + 模块级 class var _MANIFESTS / _PLUGINS — 进程级 singleton（多 worker 共享 read-only manifest + lazy plugin instance），测试用 clear() fixture 隔离
- [Phase 05a-04]: _PLUGINS dict key = (workspace_id, plugin_name) tuple — **Pitfall 5 per-workspace 隔离的关键防护**（vs 单 dict[plugin_name] 串户事故）；test_two_workspaces_isolated 明确验证
- [Phase 05a-04]: discover() fail-fast — 任一 manifest 校验失败 raise PluginError 阻断启动（Dify 同策略，防生产期半挂状态）
- [Phase 05a-04]: discover() 重复 plugin name 检测 — 两个不同目录都声明同 name → 第二个 raise PluginError("duplicate")（防 manifest 拷贝/分发场景的意外重名）
- [Phase 05a-04]: discover() 无 platform.yaml 子目录静默跳过 — plugins/docs / plugins/__pycache__ 等 CI / 工具目录不报错
- [Phase 05a-04]: get_plugin 懒加载缓存 — 同 workspace 二次访问返回同一 PlatformPlugin instance；首次创建时 daemon=None（Plan 05+ 通过 attach_daemon 注入）
- [Phase 05a-04]: get_capability fail-quiet 返回 None — 缺 capability 不抛 CapabilityMissingError（CONTEXT.md 决策；调用方显式 `if cap is None: log + fallback`，让 workflow 不中断）
- [Phase 05a-04]: get_capability prefer 参数 — 优先选指定 plugin；prefer plugin 未声明该 capability 时自动 fallback 到候选列表其他 plugin
- [Phase 05a-04]: _capability_type_to_name 模块级 dict 映射 6 capability — IMCapability/DocCapability/HRCapability/IdentityCapability/TriggerCapability/ToolCapability → "im"/"doc"/"hr"/"identity"/"trigger"/"tool"
- [Phase 05a-04]: PlatformPlugin 4 lazy facade 共享同一 _daemon — `@property im/doc/hr/identity` + _cap_cache（首次访问实例化 + 二次返回 cache）；4 facade 共享 daemon 是 RESEARCH §Pattern 4 关键设计
- [Phase 05a-04]: PlatformPlugin.attach_daemon 重复 attach raise RuntimeError — 每 plugin 1 daemon 严格 1:1（Plan 05+ Registry 一次注入；防误用重复 spawn）
- [Phase 05a-04]: PlatformPlugin TYPE_CHECKING import `daemon_client.PlatformDaemonClient` + `capabilities.*` — 引用 Plan 06 尚未创建的模块，from __future__ import annotations 让前向引用合法
- [Phase 05a-04]: capability_facades.py 选 (b) 创建 stub class（vs (a) 在 plugin.py @property 内部 import）— Plan 05 替换方法实现保签名 → 0 接口破坏；IDE/mypy 不报 ModuleNotFoundError
- [Phase 05a-04]: capability_facades 4 stub class（IMFacade/DocFacade/HRFacade/IdentityFacade）共享 _BaseFacade(_daemon, _manifest) 父类 — Plan 05 演进只需在 _BaseFacade 加 `async def _invoke(self, capability, method, **kwargs)` 真转发
- [Phase 05a-04]: subscribe_events / watch_user_changes stub 也用 `if False: yield {}` 模式 — 保 async generator function 标记（与 Plan 02/03 inspect.isasyncgenfunction 静态断言一致）；test_facade_async_generator_is_marked 验证
- [Phase 05a-04]: v1 Plan 04 不强制 DB workspace_plugin_installations 表查询 — get_plugin 直接从 _MANIFESTS dict（Plan 05+ install lifecycle 接入后再加 status='installed' 过滤）
- [Phase 05a-04]: plugins/huly/platform.yaml fixture 就位 — Plan 07 acid test 入口（discover 目标）；plugins/huly/__init__.py + huly_plugin.py daemon entry 留 Plan 07 创建
- [Phase 05a-04]: 6 借鉴点指回 Dify Manifest/PluginService/Permission 模块（≥ 5 PLAN.md 要求）— PluginDeclaration Pydantic v2 / PluginCategory StrEnum vs Literal / PluginInstallation tenant scoping / PluginService static / plugin_permission_service ACL / 启动期-懒加载分离
- [Phase 05a-04]: [Rule 1 - Bug] test_get_capability_im_returns_facade 初版 hr_cap_none 断言错误 — fixture manifest_valid.yaml 实际声明 4 capability 含 hr；改 isinstance(hr_cap, HRFacade) 与其他 capability 同模式
- [Phase 05a-04]: [Rule 1 - Bug] manifest.py docstring 含 `\\d` 触发 Python 3.13 SyntaxWarning — module docstring 前缀 `"""` 改为 raw string `r"""` 不处理 escape sequence
- [Phase 05a-04]: [Rule 3 - Blocking] ruff UP037 quoted-annotation 9 处 + I001 unsorted-imports 3 处 + black reformat 7 文件 — `ruff check --fix` + `black` 自动修复全部；re-run 测试全 pass 确认无回归
- [Phase 05a-platform-plugin-framework]: Plan 06: LegacyIMProviderAdapter 共享同一 raw provider 实例 — Phase 4 0 regression 关键不变量
- [Phase 05a-platform-plugin-framework]: Plan 06: register_provider 接口签名不变 + 内部追加 _maybe_wrap_for_capability hook 副作用 — Phase 4 调用 0 改动
- [Phase 05a-platform-plugin-framework]: Plan 06: Registry.get_capability(IMCapability) fallback to _PROVIDERS_AS_CAP — Blocker 3 修复 让新老 plugin 共存真正落地
- [Phase 05a-05]: PlatformDaemonClient JSONRPC 2.0 协议严格遵守 — jsonrpc/id/method/params/result/error 字段名标准 + 错误码 -32601 Method not found / -32602 Invalid params / -32603 Internal error / -32000~-32099 plugin 业务错误（与 Dify PluginDaemonError 借鉴点 #2 对齐）
- [Phase 05a-05]: PlatformDaemonClient request_id = uuid.uuid4().hex —— 36 字符 hex，0 碰撞概率（vs int(time.time()) 类 simple id 跨进程可能撞 — Pitfall 7 防护）
- [Phase 05a-05]: PlatformDaemonClient python -u 强制 unbuffered stdout —— 隐含 pitfall：默认 buffer 64KB 会让 JSONRPC response 卡在 daemon 不返回主进程（必须 -u 或 PYTHONUNBUFFERED=1）
- [Phase 05a-05]: PlatformDaemonClient daemon 子进程语言 v1 锁定 Python — node/go 留 v2（CONTEXT.md §Deferred Ideas 明确）；stdio JSONRPC vs HTTP RPC 简化 daemon 内嵌部署不需 HTTP overhead（stdio 比 HTTP 快 ~10x）
- [Phase 05a-05]: PlatformDaemonClient Pitfall 2 fault isolation 关键 — daemon crash 必须 < 2s 内立即失败（test_daemon_crash_fails_pending_future invoke_timeout=2.0 + timing assert elapsed < 2.0s 实测通过）；stdout EOF 检测 → _fail_all_pending(PluginDaemonExitedError) 立即失败而非 30s timeout
- [Phase 05a-05]: PlatformDaemonClient Pitfall 8 stderr 独立 drain task — 防 pipe buffer 满导致 daemon write() block；不读 stderr daemon 可能假死 RSS 上升
- [Phase 05a-05]: PlatformDaemonClient v1 daemon crash 不自动重启 — 调用方下次 invoke 走 re-spawn（test_invoke_after_close_starts_new）；Phase 5.B 加 supervisor + restart policy（CONTEXT.md decision）
- [Phase 05a-05]: PlatformDaemonClient close 幂等 + close 后 re-start — _closed 标志在 start 重置（test_invoke_after_close_starts_new 验证）；start 幂等防并发首次 invoke 重复 spawn
- [Phase 05a-05]: PlatformDaemonClient structured log capability/method/latency_ms/outcome 埋点 — Phase 7 Run Viewer 直接消费此日志可视化每次 capability call latency
- [Phase 05a-05]: capability_facades 4 facade 真接入 daemon 替换 Plan 04 stub — Plan 04 raise NotImplementedError → Plan 05 await daemon.invoke()；接口签名 + 文件位置 0 改动 → Plan 04 调用方代码 0 破坏（_BaseFacade(_daemon, _manifest) 设计保持）
- [Phase 05a-05]: capability_facades dataclass asdict() 序列化 → JSONRPC params；list[dataclass] 走 [asdict(x) for x in xs]（asdict 不递归 list 内）；返回 dict 重建 dataclass + plugin_name fallback self.name
- [Phase 05a-05]: capability_facades CRDTDelta.payload bytes → base64 encode 字符串 — JSONRPC 协议不支持 bytes 直传；daemon side base64 decode 恢复（约定 {"format": "yjs", "payload_b64": "..."} envelope）
- [Phase 05a-05]: capability_facades _ensure_daemon() fail-fast — daemon=None 时立即 raise PluginError 防 silent 失败；调用方应先 PlatformPlugin.attach_daemon(daemon) 再调 method
- [Phase 05a-05]: MockPlatformPlugin 4 capability records 调用历史（sent/updated/texts/created）— 便于业务 test 断言 cap.sent 列表内容
- [Phase 05a-05]: MockDocCapability supports_collaborative_edit=False — apply_document_delta raise（让调用方测试双路径分流）
- [Phase 05a-05]: MockHRCapability/MockIdentityCapability is_source_of_truth=False — create_leave_request / watch_user_changes raise（验证 Phase 03 source_of_truth 决策的运行时 gate）
- [Phase 05a-05]: Mock 类直接 isinstance Protocol（duck typing）— 不强制 Protocol 继承（Plan 02/03 决策延续）；MockX() 都 isinstance(IMCapability/DocCapability/HRCapability/IdentityCapability) 通过
- [Phase 05a-05]: echo_daemon fixture im.crash sys.exit(1) — Pitfall 2 fault isolation 测试入口；最小测试 daemon 模式 + 各种 method 覆盖（im.send_card/update_card/send_text/echo_error/im.slow）便于后续 plugin daemon 复用模板
- [Phase 05a-05]: [Rule 1 - Bug] test_plugin_facades.py test_facade_methods_raise_not_implemented 改为 test_facade_methods_raise_plugin_error_when_daemon_missing — Plan 04 stub 合约升级为 Plan 05 新合约（NotImplementedError → PluginError）；deferred-items.md Plan 06 已 log 此场景，本 plan Rule 1 修复 close loop
- [Phase 05a-05]: [Rule 3 - Blocking] ruff B007 unused loop variable + 3 F401 unused import + 4 文件 black 需 reformat — ruff --fix + black 自动修复全部；re-run 24 单测全 pass 确认无回归
- [Phase 05b]: Plan 05b-01: SandboxConfig 7 字段 schema 落地 — rename memory_limit→memory（K8s 风格）+ network/env_allowlist 默认 [] restrictive baseline + memory_bytes/cpu_limit_seconds property 派生 Wave 2/3 用 + sandbox/parser.py 0 Pydantic 依赖 K8s 单位解析 helper

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 2: 需在 M2 首日确认 flock 是否已有 WebSocket 实时画布，决定是否复用或新建
- Phase 3: 后续 plan 测试需保持 Redis 测试容器运行（`docker start agent-builder-redis-test`，端口 16379:6379）
- Phase 4: IM TokenManager（飞书/企微 token 并发刷新竞态）需在接入第一个 IM 适配器时就实现（防 Pitfall 7）
- Phase 5: IM 双向同步需防止"同步 → 触发通知 → IM Bot 收到 → 再次触发同步"循环（防 Pitfall 15）

## Session Continuity

Last session: 2026-05-17
Stopped at: Completed 05a-05-PLAN.md（PlatformDaemonClient JSONRPC over stdio 460 行 asyncio.create_subprocess_exec python -u -m unbuffered + UUID4 hex request_id 路由 + _read_loop stdout EOF Pitfall 2 fault isolation 立即失败 < 2s + _stderr_drain Pitfall 8 防死锁 + close 幂等 + structured log capability/method/latency_ms/outcome Phase 7 Run Viewer 钩子 + 4 capability facades 替换 Plan 04 stub 真转发 daemon.invoke dataclass asdict 序列化 + bytes base64 encode + 返回 dict 重建 dataclass + _ensure_daemon fail-fast PluginError + MockPlatformPlugin 4 capability in-process + Mock 类 isinstance Protocol duck typing + echo_daemon fixture im.crash sys.exit(1) Pitfall 2 测试入口 + 24 新测试 pass 含 test_daemon_crash_fails_pending_future invoke_timeout=2.0 timing assert + 141/141 全 platforms tests + Phase 4 IM 51 测试 0 regression + 集成手工验证 facade→daemon→echo_daemon roundtrip + Plan 04 test_plugin_facades 1 测试改写 NotImplementedError→PluginError Plan 05 新合约 + 5 借鉴点 Dify entities/plugin_daemon.py + License attribution AGPL-3.0 vs Apache-2.0 + ruff clean + black clean）
Resume file: None
Next action: Plan 07 (HulyPlugin acid test) / Wave 5 启动 — plugins/huly/__init__.py + huly_plugin.py daemon entry + mock huly server + tests/platforms_integration/test_huly_acid_test.py 端到端

### Plan 05a-03 关键决策

- [Phase 05a-03]: HRCapability.resolve_department_members(expression: str) 接口为 Phase 5.D dept:研发部 表达式预留 — 8 method 含 list/get/dept 全套
- [Phase 05a-03]: IdentityCapability.is_source_of_truth: bool flag 区分 Huly (True) vs Phase 4 IM provider (False) — 决定 sync 方向：True 时 watch_user_changes 真推送；False 时 raise NotImplementedError
- [Phase 05a-03]: HRCapability.create_leave_request 仅 source_of_truth=True plugin 实现 — 非权威 plugin 第一行检查 raise NotImplementedError（双 capability 同模式：identity.watch_user_changes 同 gate）
- [Phase 05a-03]: Trigger / Tool v1.1 仅 Protocol 骨架（subscribe_events / verify_event_signature / list_tools / invoke_tool）— 实现留 Phase 5.D+（CONTEXT.md §Deferred Ideas 明确）
- [Phase 05a-03]: subscribe_events / watch_user_changes 用 async generator pull 模式 — 比 Dify webhook + Flask route 简化（调用方 async for 自然 backpressure）；定义时即使不真 yield 也要写 `if False: yield ...` 让 Python 标记为 asyncgenfunction
- [Phase 05a-03]: ToolSpec.input_schema / output_schema 用 dict[str, Any] 透传不强类型化（借鉴 Dify ToolEntity.parameters 模式让 plugin 自由选 OpenAPI / JSON Schema / 自定义格式）
- [Phase 05a-03]: ToolInvocationResult success / error 互斥 envelope（result vs error_message 二选一 — 借鉴 Dify PluginDaemonBasicResponse 简化无泛型 YAGNI v1）
- [Phase 05a-03]: capabilities/__init__.py 用 try/except ImportError 模式处理 Plan 02 并行执行边界（doc.py 可能尚未存在时 __all__ 字段动态构建 — Plan 02 提交后 IM/Doc exports 自动追加）
- [Phase 05a-03]: Department.member_ids 用 tuple[str, ...]（不可变） — Phase 5.D dept: 表达式解析直接读此字段展开成员列表（无 N+1 查询）
- [Phase 05a-03]: 双 Mock plugin 测试覆盖（SourceOfTruth + NonSourceOfTruth） — 验证 runtime_checkable + 业务语义同时（HR + Identity 均含此模式）
- [Phase 05a-03]: inspect.isasyncgenfunction 静态断言（High 5 防 `if False: yield {}` 模式被误写）— identity.watch_user_changes / trigger.subscribe_events 各自单测覆盖（im.subscribe_events 已在 Plan 02 测试，Plan 03 累积全 3 处 async generator 静态断言）
- [Phase 05a-03]: lark_oapi env 缺失 pre-existing 问题不属本 plan scope_boundary（deferred-items.md 记录）— Plan 03 仅新增 capabilities/ 文件未触碰 feishu provider
