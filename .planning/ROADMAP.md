# 路线图：agent-builder

## 概述

从 Fork Onelevenvy/flock 骨架出发，沿着严格的依赖层级（Level 0→6）逐阶段交付：
先建立多租户基础 + 账号体系（P1），再搭 DSL 解释引擎 + 基础节点（P2），
然后打通核心路径"邮件 HITL 单节点审批"（P3），再扩展审批链 + 国内 IM 通知（P4），
接着接入 IM 目录双向同步（P5），最后完成插件沙箱机制（P6）。
每个阶段都可独立验收；M3 完成即可演示 P0 核心价值。

## Phases

- [x] **Phase 1: Skeleton + 账号体系** - Fork flock、多租户隔离、自建账号/RBAC、公网最小暴露面 ✓ 2026-05-16
- [x] **Phase 2: DSL 引擎 + 基础节点** - DSL 编译执行、Postgres checkpoint、5 种内置节点、实例管理 ✓ 2026-05-17
- [x] **Phase 3: HITL 单节点 + Email 审批** - 四态决策、Token 即登录、邮件深链、公网回调 ✓ 2026-05-17
- [x] **Phase 4: 审批链 + IM 通知** - 4 种审批链模式、飞书/企微/钉钉/Slack/Mattermost 通知卡片（12/12 plan Complete，待 /gsd:verify-work 验证）
- [ ] **Phase 4.5: Bot Triggers + Slash 分发 + Reply (双向 IM)** - 通用 Bot Trigger/Reply 节点 + Slash 命令路由，Mattermost 先行，飞书/企微/钉钉/Slack 后补
- [x] **Phase 5.A: PlatformPlugin 框架（Dify-style）** - PlatformPlugin / 6 Capability Protocols / Manifest / Registry / LegacyAdapter / HulyPlugin acid test 5/5 pass（7/7 verified Score）✓ 2026-05-17
- [ ] **Phase 5.B: Plugin 沙箱 + Daemon 通信** - JSONRPC over stdio + 资源限制 + fault isolation（合并原 Phase 6 沙箱）
- [ ] **Phase 5.C: DocCapability 真接入** - Outline + Lark + Huly multi-capability plugin（CRDT collab edit + 全量 replace 双路径）
- [ ] **Phase 5.D: HRCapability + Identity 反向 sync** - 飞书/企微/钉钉/Huly HR 接入 + user_platform_mappings 反向同步 + dept: 表达式解析
- [ ] **Phase 6: Plugin Marketplace** - 第三方上传 zip / dry-run / 注册 / 画布动态加载（与 Phase 5.B 沙箱接力）
- [ ] **Phase 7: 可观测性 + 运维工具** - 实例 Timeline、预置模板、审计日志、运维工具、每节点可视化 Run Viewer

## Phase Details

### Phase 1: Skeleton + 账号体系
**Goal**: 多租户可运行的工程底座已就绪，管理员能注册登录并在画布上拖出一个 Demo 流程
**Depends on**: 无（首阶段）
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-06, NET-01, NET-02, NET-03, NET-04, DEPL-01, DEPL-02
**Success Criteria**（什么状态为完成）:
  1. 管理员能用邮箱密码注册并登录，登录后看到自己所在 workspace 的内容，看不到其他 workspace 的内容
  2. RBAC 生效：editor 能创建/编辑工作流，viewer 只能查看，admin 能管理用户
  3. docker-compose up 一键启动所有服务（api/worker/web/postgres/redis/nginx），浏览器能打开画布页
  4. nginx 只放行 `/hitl/page/*` `/hitl/action/*` `/api/im/webhook/*` 三条路径；扫描工具验证其他路径 403
  5. HMAC_SECRET 长度 < 32 字节时服务启动失败并打印明确错误信息
**Plans**: 6 plans

Plans:
- [ ] 01-01-PLAN.md — Fork flock + rebrand + docker-compose + 三层测试基线（Wave 1）
- [ ] 01-02-PLAN.md — DB schema + Alembic + WorkspaceScopedQuery + DISCARD ALL hook（Wave 2）
- [ ] 01-03-PLAN.md — nginx 双 server_block + HMAC 启动校验 + slowapi 限频（Wave 2）
- [x] 01-04-PLAN.md — Auth Service + API（setup/auth/invites/me）+ 集成测试（Wave 3）
- [x] 01-05-PLAN.md — Next.js 前端（setup/login/invite/dashboard）+ RoleGate（Wave 3）
- [ ] 01-06-PLAN.md — E2E 端到端验收 + MailHog + ROADMAP 5 条 success criteria 覆盖（Wave 4）

### Phase 2: DSL 引擎 + 基础节点
**Goal**: 简单 DAG 工作流（Start→LLM→Tool→IfElse→End）能端到端运行并持久化
**Depends on**: Phase 1
**Requirements**: EDIT-01, EDIT-02, EDIT-03, EDIT-04, NODE-01, NODE-03, NODE-05, NODE-06, EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05
**Success Criteria**（什么状态为完成）:
  1. 用户能在画布上拖拽 Start/End/LLM/Tool/IfElse 五种节点并连线，保存为草稿后发布
  2. 点击"运行"后实例创建并执行，Web 页面实时显示每个节点的进入/完成状态
  3. 服务重启后运行中的实例能从 Postgres checkpoint 恢复继续执行
  4. 实例列表页能按工作流/状态过滤，支持分页搜索
  5. DSL 成环或变量引用错误时画布前端拒绝保存并显示具体错误位置
**Plans**: 10 plans

Plans:
- [x] 02-01-PLAN.md — LangGraph 1.2.0 + checkpoint-postgres 3.1.0 + Phase 2 业务表（Wave 1）
- [x] 02-02-PLAN.md — DSL Schema + Jinja2 沙箱 + DSLValidator + DSLCompiler 骨架（Wave 1）
- [x] 02-03-PLAN.md — React Flow Canvas + 5 节点 + NodePalette + ConfigPanel + DSL 双向转换（Wave 2）
- [x] 02-04-PLAN.md — 5 种节点执行器（BaseNodeExecutor + Start/End/LLM/Tool/IfElse）
- [x] 02-05-PLAN.md — LLM 节点 + Redis Pointer Pattern
- [x] 02-06-PLAN.md — Redis Pointer Pattern（state 重型数据透明存储）
- [x] 02-07-PLAN.md — SSE 实时状态推送（EventBus + Redis Stream + pub/sub）
- [x] 02-08-PLAN.md — 工作流持久化 API（workflowsApi 真实后端）
- [x] 02-09-PLAN.md — DSL 实时校验（IssueList 接入）
- [x] 02-10-PLAN.md — E2E 验收（拖拽 DAG + 发布 + 运行 + 时间线）

### Phase 3: HITL 单节点 + Email 审批
**Goal**: 审批人收到邮件深链，点击链接完成四态决策，流程继续推进
**Depends on**: Phase 2
**Requirements**: HITL-01, HITL-03, HITL-05, HITL-07, NOTI-01, NOTI-08, NOTI-09, NOTI-10, AUTH-04, AUTH-05, NET-05, NODE-02, NODE-07
**Success Criteria**（什么状态为完成）:
  1. 审批人收到包含"同意/退回/拒绝"按钮的邮件，每个按钮有独立 token 深链
  2. 审批人点击链接后无需登录账号即可看到决策表单，填写并提交后流程推进
  3. Outlook Safe Links 扫描器 GET token 链接不消费 jti，审批人首次点击仍可正常决策
  4. 同一 token 提交后立即失效；同节点其他 token 同时失效；重复提交返回 409
  5. 申请人能在追踪页查看自己实例的当前节点状态和历史决策记录
**Plans**:
- [x] 03-01-PLAN.md — HITL DB schema + Redis 黑名单（HitlToken/Notification ORM + audit_logs NET-05 + HitlTokenStore，2026-05-17 完成）
- [x] 03-02-PLAN.md — HITL node executor（HITLNodeExecutor + hitl_payload 4 纯函数 + HitlService + 38 测试，2026-05-17 完成）
- [x] 03-03-PLAN.md — HITL Token Service（JWT 签发 + Safe Links bot detector，HitlTokenService + bot_detector + 44 测试，2026-05-17 完成）
- [x] 03-04-PLAN.md — Email 投递（NotificationService + arq + Jinja2 + tenacity NOTI-10 重试，3 模板 + 18 测试，2026-05-17 完成）
- [x] 03-05-PLAN.md — Notification node executor（NotificationNodeExecutor + generic_notification.html + 13 测试，2026-05-17 完成）
- [x] 03-06-PLAN.md — HITL public API（HitlActionService + /hitl/page + /hitl/action + 4 HTML 模板 + migration 0004 + 39 测试 — 含 Safe Links bot 6 用例 + advisory_lock 并发 3 用例 P0 回归，2026-05-17 完成）
- [x] 03-07-PLAN.md — 决策页前端（@rjsf/core 5.24 + 4 组件 + 2 路由 + 后端 JSON 协商补缺 + middleware /hitl/ 白名单 + 14 测试通过，2026-05-17 完成）
- [x] 03-08-PLAN.md — 申请人追踪页 HITL-07（GET /instances/<id>/tracking + tracking-timeline + applicant-only-records + 32 测试，节点可视化全字段，2026-05-17 完成）
- [x] 03-09-PLAN.md — 超时催办 worker（scan_hitl_timeouts arq cron 60s + 三档阶梯 24/48/72h + EscalationService + 21 测试，2026-05-17 完成）
- [x] 03-10-PLAN.md — E2E 验收（5 Playwright spec + hitl-builder + 2 Page Object + mailhog HITL 扩展 + CLAUDE.md 2.5 P0 Safe Links 4 UA + Smoke/Standard/Full 三档模式 + 23 test，2026-05-17 完成）

### Phase 4: 审批链 + IM 通知
**Goal**: 多人审批链（4 种模式）正确推进，审批人能通过飞书/企微/钉钉/Slack/Mattermost 卡片收到通知并跳转决策页
**Depends on**: Phase 3
**Requirements**: HITL-02, HITL-04, HITL-06, NOTI-02, NOTI-03, NOTI-04, NOTI-05, NOTI-06, NOTI-07
**Success Criteria**（什么状态为完成）:
  1. 顺序会签：A 同意后 B 才收到通知；A 拒绝后 B 不收到通知，流程终止
  2. 并行会签（全员同意）：A 拒绝后其余所有人的 token 立即失效，流程终止
  3. 或签（任一同意）：A 同意后流程立即推进，其余人的 token 同时失效
  4. 审批人节点超时后收到催办提醒，超时升级策略生效（指派给指定升级人）
  5. 飞书/企微/钉钉/Slack/Mattermost 卡片消息投递成功，点击卡片按钮跳转到正确的 Web 决策页
  6. 审批人能把待办任务委托给同事，委托记录写入审计日志
**Plans** (12 total, Wave 1+2+3+4+5+6+7):
- [x] 04-01-PLAN.md — chain payload + invalidate_chain + Alembic 0005 partial index（ChainAdvanceResult frozen dataclass + compute_chain_advance 4 mode × 3 action 状态机 + HitlTokenStore.invalidate_chain + 40 测试通过；HITL-02 + HITL-06 基础设施层完成，2026-05-17 完成）
- [x] 04-02-PLAN.md — chain executor (HitlActionService.submit_action 4 mode 完整分支 + invalidate_chain in advisory_lock + 结构化日志 hitl.chain.advance 8 字段 + 21 集成测试通过；HITL-02 完成，2026-05-17 完成)
- [x] 04-03-PLAN.md — delegation API (POST /hitl/action/<jwt>?op=delegate + create_delegate_token + DelegateError 5 错误码 + 委托链深度 ≤ 3 + deadline 重置 + 20 集成测试通过；HITL-06 完成,2026-05-17 完成)
- [x] 04-04-PLAN.md — EscalationService 4 表达式扩展 (resolve email/user:/role:/dept:NotImpl + perform 多 email fan-out + 40 escalation 测试通过；HITL-04 完成，2026-05-17 完成)
- [x] 04-05-PLAN.md — IMProvider Protocol + Registry + MockIMProvider + IMCredentialsManager + im_jobs.send_hitl_card_job（鸭子类型 + 5 家 frozen dataclass 凭据 + Phase 4.5 接口预留 + tenacity 3 次重试 + 结构化日志 'im.card.send' + 43 单元/集成测试通过；Wave 3 抽象层完成，2026-05-17 完成）
- [x] 04-06-PLAN.md — Feishu Provider (lark-oapi 1.6.5 + Interactive Card 2.0 + multi_url 4 URL 全填 + 按钮颜色映射 + 24h 过期 234016 跳过 + importlib.metadata 取版本 + loop.run_in_executor 包装同步 SDK / 45 单元测试通过；NOTI-02 完成，2026-05-17 完成)
- [x] 04-07-PLAN.md — WeCom Provider (wechatpy 1.8.18 + Bot Webhook fallback：spike 发现 wechatpy 1.8.18 完全无 template_card API + 双路径架构 markdown 4 链接 / 主路径 app message + Fallback Bot Webhook envelope 完全一致 / supports_card_update=False + update_card NotImplementedError 引导 send_supplement_text 兜底 / 错误统一包装 ConnectionError 触发 tenacity 重试 / WeComCredentials 新增 bot_webhook_key 字段向后兼容 / IMCredentialsManager 支持 fallback-only 模式 / lifespan 自动按凭据注册 / markdown 注入防护 5 类转义 + 2048 byte 边界 / 34 测试全绿 + 77 IM 测试 0 regression；NOTI-03 完成，2026-05-17 完成)
- [x] 04-08-PLAN.md — DingTalk Provider (dingtalk-stream 0.24.3 + ActionCard btn_orientation="0" 横排 3 按钮 + OAPI asyncsend_v2 直调 + update_card→NotImplemented 走 send_supplement_text + lifespan 按需注册 + 37 测试通过；NOTI-04 完成，2026-05-17 完成)
- [x] 04-09-PLAN.md — Slack + Mattermost + 通用 Webhook IMProviders（httpx 直调 REST 不引入 slack-bolt / mattermost-driver 重依赖；Slack Block Kit chat.postMessage + chat.update supports_card_update=True；Mattermost attachment /api/v4/posts + PUT /patch supports_card_update=True；通用 Webhook POST JSON + HMAC-SHA256 签名 X-Agent-Builder-Signature header 防伪造 supports_card_update=False；serialize_payload sort_keys 稳定序列化保证用户端可复现验签；3 个 event 常量 hitl_decision_required/hitl_supplement/hitl_card_update；WebhookCredentials 仅 delivery_url 字段 HMAC 走 HMAC_SECRET env；PROVIDER_WEBHOOK 加入 KNOWN_PROVIDERS 6 家扩展；59 新增测试全绿 19/21/19 + 33 既有 04-05 测试 0 regression；NOTI-05/06/07 完成，2026-05-17 完成）
- [x] 04-10-PLAN.md — NotificationService 多通道 fan-out + schema 扩展（enqueue_hitl_multichannel channels[]→fan-out N 行 notifications + N arq job / 事务边界 commit 后才 enqueue 防 Pitfall 2 / im_bindings.get(channel) 缺失 skip+warn / 每行独立 payload dict worker 写回 im_message_id 不污染 / enqueue_generic_im_card 与 enqueue_generic_email 平行 API / NOTIFY_CHANNELS_ENUM 7 值共享常量 hitl+notification schema / 'wechat'→'wecom' 修正 / notify_channels default=['email'] 向后兼容 / NotificationNodeExecutor 多 channel 分发 + _normalize_recipients email 严校验/IM 宽容 / per-channel try/except 失败隔离 / 结构化日志 notification.multichannel.enqueued / 39 新测试全绿 + 28 既有 0 regression + 126 IM provider 0 regression / 4 commits Task 0+1+2+3；NOTI-08 完成，2026-05-17 完成）
- [x] 04-11-PLAN.md — HITLNodeExecutor chain 集成 + multichannel 通知（HITLNodeExecutor.interrupt_payload 加 4 chain 字段 chain_mode/approvers/current_idx/notify_channels 默认值保 Phase 3 旧 DSL 100% 向后兼容 + approvers UUID list→str list 序列化 LangGraph checkpoint JSON 编码兼容 + ExecutionEngine._on_hitl_enter HITL 节点 enter 钩子集中处理副作用 NodeState INSERT + build_initial_payload(chain_mode, approvers) + chain_mode 分发 batch_create_tokens_for_actors single/sequential→approvers[0] vs parallel_*→全部 + per actor enqueue_hitl_multichannel Plan 04-10 复用多通道 fan-out + per-actor try/except 失败不阻塞 + 结构化日志 hitl.node.entered 8 字段 extra dict Phase 7 Run Viewer 钩子 + HitlService.resolve_assignees 4 表达式 router 独立实现 email/user:<uuid>/role:<code>/dept:<name>→NotImplementedError + 3 helper _resolve_user_uuid/_resolve_email_uuid/_resolve_role_uuids workspace 边界校验 + 去重保序防 sequential approvers[0] 不确定 + 25 新测试全绿 13 chain interrupt 单元测试 + 12 _on_hitl_enter 集成测试 / Phase 3+04-02+04-10 既有 ~94 测试 0 regression / 3 commits Task 0+1+2；HITL-02 + NOTI-08 收尾，2026-05-17 完成）
- [x] 04-12-PLAN.md — Phase 4 E2E gate 收官（工具切换 Playwright → browser-use/browser-harness 用户 2026-05-17 指令 / 双 reading doc gate 340+140 行 / backend test_helpers 5 endpoint 仅 ENABLE_TEST_API=1 挂载 + SetupRedirect /api/test/ 白名单 + mock_im_providers conftest fixture autouse=False session-scope / e2e_v2/ Python 测试栈 pytest+httpx+browser-harness 子进程 7 helpers + hitl_decision_page PageObject / 6 spec 一一对应 ROADMAP Phase 4 全 6 success criteria + ROADMAP 1:1 追溯 / Safe Links 4 bot UA × 3 chain mode = 12 parametrize 矩阵 CLAUDE.md §2.5 P0 防护 / 26 spec collect 通过 Smoke 默认 26 skipped Standard RUN_E2E=1 / 10 backend test_helpers 测试全绿 + 54 关联测试 0 regression + 17 Phase 1-3 Playwright spec 完全不动 / 部分 #5/#6 spec skip 因 backend 缺 admin user-update endpoint 留 Phase 5 完成；Phase 4 全 12 plan Complete，2026-05-17 完成）

### Phase 4.5: Bot Triggers + Slash 分发 + Reply (双向 IM)
**Goal**: 通用 IM Bot 双向接入 — 入站消息触发 workflow（含 Slash 命令分发到不同 workflow / 子图）+ 出站把 workflow 结果回帖到原 IM 线程；Mattermost 第一个 P0 落地，其它 IM (飞书/企微/钉钉/Slack) 作为可插拔 provider 后补
**Depends on**: Phase 4 (IM 通知通道适配器框架已建)
**Requirements**: 新增（详见 phases/04_5-bot-triggers/04_5-OUTLINE.md）
**Success Criteria**（什么状态为完成）:
  1. Mattermost 用户 @-mention bot 或发 `/<command>` → workflow 触发并接收消息上下文
  2. **Slash 命令路由**：单个 bot 可注册多个 slash 命令（如 `/leave` `/approve` `/status`），不同命令分发到不同 workflow 或同一 workflow 的不同入口子图
  3. workflow 执行结果回帖到原 thread (Mattermost bot reply to thread)
  4. Trigger / Reply 两类节点 + Provider 接口 + Slash Dispatcher 抽象完整 — 加新 IM 仅需实现 Provider 接口
  5. 飞书 / 企微 / 钉钉 / Slack provider 实现 (4.5.2 P1)
  6. Bot 鉴权 / Webhook 签名验证 (防伪造)
**Plans**: TBD (详见 OUTLINE.md, 大约 7-9 plans)

### Phase 5.A: PlatformPlugin 框架（Dify-style）
**Goal**: 把分散的 IMProvider / 计划中 DocProvider / HRProvider 统一为 PlatformPlugin 通用插件框架，达到 Dify 级别第三方平台接入能力 — 一份 YAML manifest 即可声明多 capability 接入
**Depends on**: Phase 4 (IMProvider 实测 + Huly acid test 5 gap 已暴露)
**Authoritative spec**: `docs/plans/2026-05-17-platform-plugin-framework-ADR.md` (ADR-001)
**Requirements**: 新增 PLUG-* / IM-* 子集（Phase 5.A 阶段定义 v1.1）
**Success Criteria**（什么状态为完成）:
  1. `PlatformPlugin` + 6 Capability Protocols（IM/Doc/HR/Identity/Trigger/Tool）完整定义 + 单测覆盖
  2. `platform.yaml` manifest Pydantic schema 校验通过；多 capability 声明可解析
  3. `PlatformPluginRegistry` discover / install / get_capability 工作（含 per-workspace 隔离）
  4. `LegacyIMProviderAdapter` 让 Phase 4 6 家 IMProvider 通过新 IMCapability 接口被调用，Phase 4 测试**零 regression**
  5. **Acid test**：真实写一个 HulyPlugin stub（manifest + 4 facade + JSONRPC over stdio）+ 至少 1 capability call 通过单测（user 2026-05-17 硬性要求 — 不再让"抽象只在纸面"发生）
  6. DocCapability 设计稿 + Mock 单测覆盖 replace_content / apply_document_delta 双路径
  7. HRCapability 设计稿 + Mock 单测含 resolve_department_members（服务后续 dept: 表达式）
**Plans**: 7 plans (Plan 01/02/03/04 ✅ Done — Wave 3 首发完成 4/7 57%)
  - [x] 05a-01-PLAN.md — Skeleton：Dify reading doc + Alembic 0006 + tests 目录 (Wave 1) — 2026-05-17 完成（16 smoke + 70 phase 4 regression / 0 fail / SUMMARY 已建）
  - [x] 05a-02-PLAN.md — IM + Doc Capability Protocol (Wave 2) — 2026-05-17 完成（17 测试 8 IM + 9 Doc / 全 pass / Huly acid test gap #a + #2 解决 / 双路径 replace_content vs apply_delta + RecipientSpec 多态 + 8 值对象 frozen=True）
  - [x] 05a-03-PLAN.md — HR + Identity + Trigger + Tool Capability Protocol (Wave 2) — 2026-05-17 完成（41 测试 13 HR + 11 Identity + 17 Trigger/Tool / 全 pass / 与 Plan 02 并行 bundled commit b0353c0）
  - [x] 05a-04-PLAN.md — Manifest schema + PlatformPlugin + Registry + capability_facades stub (Wave 3) — 2026-05-17 完成（36 测试 13 manifest schema 含 extra=forbid + 13 registry 含 test_two_workspaces_isolated Pitfall 5 防护 + 10 plugin_facades 含 isasyncgenfunction 静态断言 / 全 pass / 94/94 platforms tests 累积 / 51/51 Phase 4 IM 0 regression / PlatformManifest 4 类 extra=forbid + RuntimeConfig/CapabilitySpec/SandboxConfig / load_manifest yaml.safe_load 异常翻译 / Registry classmethod-only 进程级 singleton 含 discover/get_plugin/get_capability/clear / 4 lazy facade 共享 _daemon + attach_daemon 注入预留 / capability_facades 4 stub class Plan 05 替换 0 接口破坏 / plugins/huly/platform.yaml Plan 07 acid test 入口 / 6 借鉴点指回 Dify Manifest+PluginService+Permission / License attribution / PLUG-FW-02 + PLUG-FW-03 双 requirement 完成）
  - [x] 05a-05-PLAN.md — PlatformDaemonClient + capability_facades 真接 daemon + MockPlugin (Wave 4) — 2026-05-17 完成（24 新测试 11 daemon_client + 13 mock_plugin / 全 pass / 141/141 全 platforms tests + Phase 4 IM 51 0 regression / PlatformDaemonClient 460 行 asyncio.create_subprocess_exec python -u -m unbuffered + UUID4 hex request_id 路由 + line-delimited JSON envelope + Pitfall 2 stdout EOF _fail_all_pending fault isolation 立即失败 < 2s 实测 test_daemon_crash_fails_pending_future invoke_timeout=2.0 elapsed<2.0s / Pitfall 8 _stderr_drain 独立 task 防 pipe buffer 满死锁 / close 幂等 terminate→wait 5s→kill / start 幂等 + close 后 re-start 重置 _closed / structured log capability/method/latency_ms/outcome Phase 7 Run Viewer 钩子 / capability_facades 192→527 行 替换 Plan 04 stub 真转发 IMFacade/DocFacade/HRFacade/IdentityFacade 共享 _BaseFacade _ensure_daemon fail-fast PluginError / dataclass asdict 序列化 + 返回 dict 重建 dataclass / CRDTDelta.payload bytes → base64 encode JSONRPC 不支持 bytes 直传 / MockPlatformPlugin 299 行 4 capability in-process MockIMCapability/MockDocCapability/MockHRCapability/MockIdentityCapability records 调用历史 + 直接 isinstance Protocol duck typing / echo_daemon 141 行 测试用 daemon im.crash sys.exit(1) Pitfall 2 测试入口 / 5 借鉴点 Dify entities/plugin_daemon.py PluginDaemonBasicResponse[T]/PluginDaemonError/Go→Python 简化/PluginInstallTask 异步→v1 同步/spawn-restart→v1 crash 不自动重启 / License attribution AGPL-3.0 vs Apache-2.0 严禁拷源代码 / PLUG-FW-05 + PLUG-FW-06 双 requirement 完成）
  - [x] 05a-06-PLAN.md — LegacyIMProviderAdapter + base.py 双轨注册 + Registry fallback to legacy (Wave 4) — 2026-05-17 完成（23 测试 20 adapter + 3 registry fallback / 全 pass / LegacyIMProviderAdapter 311 行 Phase 4 6 家 IMProvider → IMCapability 适配零接口破坏共享 raw provider 实例 / base.py +78 行 _PROVIDERS_AS_CAP 双轨 + _maybe_wrap_for_capability hook 静默降级 + helper / registry.py +27 行 IM-only fallback Blocker 3 修复 / Phase 4 IM 61 + notification 33 + e2e_v2 26 specs collect 三套 0 regression / 用户硬性 DoD #3 达成 / 5 借鉴点 Dify data_migration+plugin_migration / License attribution / PLUG-FW-04 + IM-LEGACY-WRAP 双 requirement 完成）
  - [ ] 05a-07-PLAN.md — HulyPlugin acid test：真 subprocess + mock huly server + 1 send_card 端到端 + fault isolation (Wave 5)

### Phase 5.B: Plugin 沙箱 + Daemon 通信资源限制
**Goal**: Plugin daemon 跑在受限沙箱进程内 — manifest sandbox 段消费 + resource.setrlimit baseline + 可选 cgroups v2 + 网络白名单 + 三层超时强杀（invoke timeout / watchdog SIGTERM grace SIGKILL / idle 自动回收）
**Depends on**: Phase 5.A (PlatformDaemonClient 接口已定，5/5 acid test pass)
**Authoritative spec**: `.planning/phases/05b-plugin-sandbox/05b-RESEARCH.md`
**Requirements**: PLUG-FW-09 (PosixResourceSandbox), PLUG-FW-10 (CgroupsV2Sandbox), PLUG-FW-11 (AllowlistTransport), PLUG-FW-12 (Watchdog + IdleReaper), PLUG-FW-13 (SandboxConfig schema), PLUG-03 (Phase 6 marketplace 基础设施前置)
**Success Criteria**:
  1. PlatformDaemonClient 沙箱进程资源限制：CPU / memory baseline 通过 resource.setrlimit + RLIMIT_NPROC/NOFILE 防 fork bomb（Linux CI 真 enforcement 测）
  2. cgroups v2 opt-in（`use_cgroups: true` + Linux + systemd-userdbd 可用）走 systemd-run --user --scope；其它环境优雅降级到 PosixResourceSandbox + warning
  3. AllowlistTransport 应用层网络白名单 — plugin daemon 显式调 `make_sandboxed_http_client(allow_list)`；非白名单 host raise NetworkBlockedError
  4. 三层超时强杀：invoke timeout (5.A 30s) / watchdog SIGTERM 3s grace → SIGKILL（os.killpg 整组）/ idle daemon 300s auto-close
  5. env 变量 strip-all-allowlist（默认仅 PATH/HOME/LANG/TZ；manifest env_allowlist opt-in；AGENT_BUILDER_*/HMAC_*/DATABASE_* 永远拒绝）
  6. 5.A 5/5 acid test + 162 platforms 测试 + Phase 4 81 IM 0 regression
  7. macOS dev 全 suite 通过（含 enforcement test skip）；Linux CI ubuntu-latest 全 suite 通过（含 RLIMIT 真行为验证）
**Plans**: 5 plans (Wave 1 → 2⇉ → 3⇉)
  - [x] 05b-01-PLAN.md — SandboxConfig manifest schema 扩展 + parser.py + Dify reading doc（Wave 1，PLUG-FW-13）— Completed 2026-05-17 (14min, 49 测试 PASS, 193 platforms + 5/5 acid 0 regression)
  - [x] 05b-02-PLAN.md — SandboxRunner Protocol + PosixResourceSandbox + RLIMIT 4 类 + os.setsid 进程组 + Linux CI enforcement test（Wave 2 并行, PLUG-FW-09）— Completed 2026-05-18 (9 passed, 1 skipped macOS — HIGH-3 fix close_fds)
  - [x] 05b-03-PLAN.md — AllowlistTransport（httpx Transport API）+ NetworkBlockedError + make_sandboxed_http_client + huly_plugin env-gated 集成（Wave 2 并行，PLUG-FW-11）— Completed 2026-05-18 (25min, 13 unit + 4 integration PASS, 215 platforms + 5/5 acid 0 regression)
  - [x] 05b-04-PLAN.md — SandboxWatchdog（SIGTERM 3s grace → SIGKILL）+ IdleDaemonReaper + PlatformDaemonClient 集成（_choose_runner + _build_filtered_env strip-all + last_invoke_at）（Wave 3，PLUG-FW-12）— Completed 2026-05-18
  - [x] 05b-05-PLAN.md — CgroupsV2Sandbox（systemd-run --user --scope）+ is_cgroups_v2_available 4 检查 + 真试 + 优雅降级（Wave 3 并行，PLUG-FW-10）— Completed 2026-05-18 (17min, 16 unit + 3 integration tests, 271 platforms + 5/5 acid + 131 IM 0 regression)

### Phase 5.C: DocCapability 真接入
**Goal**: Outline + Lark + Huly multi-capability plugin 真实跑通，CRDT collab edit 不冲突
**Depends on**: Phase 5.B
**Requirements**: DOC-* (Phase 5.C 阶段定义)
**Success Criteria**:
  1. OutlineProvider plugin manifest + 全 6 method 实现 + 集成测试 (实跑 Outline self-hosted)
  2. LarkDocsProvider plugin + markdown→blocks 转换 + 评论 + @人
  3. HulyPlugin DocCapability facet 真接入 + Y.js CRDT delta apply 工作
  4. DAG 节点 `doc_write` / `doc_mention` 集成 + AI suggest mentions LLM 钩子
  5. E2E with browser-use/browser-harness：DAG 跑完 → Outline 出文档 → 协作人收 @ 提醒
**Plans**: TBD

### Phase 5.D: HRCapability + Identity 反向 sync
**Goal**: HR module 接入 + user_platform_mappings 反向同步（Huly / 飞书 source-of-truth → us）+ dept: 表达式解析
**Depends on**: Phase 5.C
**Requirements**: IM-01..05, NODE-04/08/09/10（原 Phase 5）+ HR-* + IDENT-* 新增
**Success Criteria**:
  1. user_platform_mappings 表 + identity_source enum + is_authoritative flag + identity_sync_jobs 表
  2. 4 家 HRCapability 实现（飞书 / 企微 / 钉钉 / Huly），含 resolve_department_members
  3. HITL 节点 assignee `dept:研发部` → 调 active HRCapability.resolve_department_members 解析正确
  4. IdentityCapability.watch_user_changes 反向 sync（Huly user 变化自动同步到 agent-builder users）
  5. 画布拖 FanOut/FanIn/Subgraph/Loop 节点正确执行（原 Phase 5 #4）
  6. EDIT-05 步进调试（原 Phase 5 #5）
**Plans**: TBD

### Phase 6: Plugin Marketplace
**Goal**: 管理员能上传第三方插件 zip，插件经 Phase 5.B 沙箱跑起来 + 注册到 workspace + 画布节点面板自动出现
**Depends on**: Phase 5.D
**Requirements**: PLUG-01, PLUG-02, PLUG-03, PLUG-04, EDIT-04, DEPL-03
**Success Criteria**（什么状态为完成）:
  1. 管理员上传插件 zip 后，系统自动解压校验 manifest + schema，沙箱 dry-run 通过后状态变为 registered
  2. 注册成功的插件在画布节点面板中出现，可拖拽到画布并配置
  3. 插件执行在独立子进程中运行，cgroups/resource limits 生效，超时强杀不影响主进程
  4. 插件内 `__subclasses__` 枚举等逃逸尝试被 seccomp/chroot 拦截（dry-run POC 测试通过）
  5. 工作流 DSL 能导出/导入 JSON，hr 离职预置模板可直接导入并运行
**Plans**: TBD

### Phase 7: 可观测性 + 运维工具
**Goal**: 运维人员能实时追踪实例全链路，管理员有工具处理卡住的实例
**Depends on**: Phase 6
**Requirements**: EXEC-04（增强）, NET-05（增强）, DEPL-03（增强）
**Success Criteria**（什么状态为完成）:
  1. **每节点可视化执行链路（参考 Dify `web/app/components/workflow/run/`）** — 用户要求 2026-05-17 加入：
     - 工作流 Run Viewer：DAG 上每节点叠加状态（pending/running/success/failed/skipped/interrupted）+ 颜色码
     - 节点详情抽屉：输入 / 输出 / 日志 stdout+stderr / 耗时 ms / 重试次数 / 错误堆栈 / LLM token cost（如适用）
     - 流式日志：SSE 推送每节点执行 chunk（参考 Dify `workflow_app_runner.py` stream 逻辑）
     - 时间线视图（横向 Gantt）+ DAG 视图（@xyflow/react 复用画布组件）双视角切换
     - 历史回放：选任意历史 run 重看每步执行细节（state diff 高亮）
  2. 实例详情页显示节点时间线（每个节点的进入时间/耗时/状态），支持 SSE 实时刷新
  3. 审计日志记录每次决策的 IP/UA/时间/决策内容，管理员可查询和导出（NET-05 强化）
  4. hr 离职预置模板可一键导入，填写员工信息后能完整跑通所有审批节点
  5. 节点失败回放：执行失败的实例支持"从失败节点重试"（Phase 2 已有局部，Phase 7 全链路）
**Plans**: TBD

## 进度

**执行顺序**: Phase 1 → 2 → 3 → 4 → 4.5 → 5.A → 5.B → 5.C → 5.D → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Skeleton + 账号体系 | 6/6 | ✓ Complete | 2026-05-16 |
| 2. DSL 引擎 + 基础节点 | 10/10 | ✓ Complete | 2026-05-17 |
| 3. HITL 单节点 + Email 审批 | 10/10 | ✓ Complete | 2026-05-17 |
| 4. 审批链 + IM 通知 | 12/12 | ✓ Complete | 2026-05-17 |
| 4.5. Bot Triggers + Slash | 0/TBD | Not started | - |
| 5.A. PlatformPlugin 框架（Dify-style）| 7/7 | ✓ Complete | 2026-05-17 |
| 5.B. Plugin 沙箱 + Daemon 通信资源限制 | 5/5 | ✓ Complete | 2026-05-18 |
| 5.C. DocCapability 真接入 | 0/TBD | Not started | - |
| 5.D. HRCapability + Identity 反向 sync | 0/TBD | Not started | - |
| 6. Plugin Marketplace | 0/TBD | Not started | - |
| 7. 可观测性 + 运维工具 | 0/TBD | Not started | - |
</content>
</invoke>
