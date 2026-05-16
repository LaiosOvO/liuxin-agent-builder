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
- [ ] **Phase 3: HITL 单节点 + Email 审批** - 四态决策、Token 即登录、邮件深链、公网回调
- [ ] **Phase 4: 审批链 + IM 通知** - 4 种审批链模式、飞书/企微/钉钉/Slack/Mattermost 通知卡片
- [ ] **Phase 4.5: Bot Triggers + Slash 分发 + Reply (双向 IM)** - 通用 Bot Trigger/Reply 节点 + Slash 命令路由，Mattermost 先行，飞书/企微/钉钉/Slack 后补
- [ ] **Phase 5: IM 目录双向同步** - 三家 IM 用户/部门同步、Assignee 多形态解析、高级节点
- [ ] **Phase 6: 插件机制** - 沙箱执行、插件安装/注册/卸载、画布动态加载
- [ ] **Phase 7: 可观测性 + 运维工具** - 实例 Timeline、预置模板、审计日志、运维工具

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
- [ ] 03-07-PLAN.md — 决策页前端（form_schema RJSF render）
- [ ] 03-08-PLAN.md — 申请人追踪页（HITL-07）
- [ ] 03-09-PLAN.md — 超时催办 worker（arq + NOTI-09 升级）
- [ ] 03-10-PLAN.md — E2E 验收（ROADMAP Phase 3 全 5 条 + Safe Links bot regression）

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
**Plans**: TBD

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

### Phase 5: IM 目录双向同步
**Goal**: 节点 assignee 能按邮箱/用户名/部门表达式解析，IM 用户与本地账号自动匹配
**Depends on**: Phase 4
**Requirements**: IM-01, IM-02, IM-03, IM-04, IM-05, NODE-04, NODE-08, NODE-09, NODE-10
**Success Criteria**（什么状态为完成）:
  1. 管理员触发同步后，飞书/企微/钉钉的用户列表和部门树能导入到本地 im_directory 表
  2. IM 用户按邮箱自动匹配本地账号，users.im_bindings 自动更新
  3. HITL 节点 assignee 填 `dept:研发部` 时，系统能正确解析为该部门所有成员的 user_id
  4. 画布上能拖拽 FanOut/FanIn 并行节点、Subgraph 嵌套节点、Loop 节点并正确执行
  5. EDIT-05 步进调试：选定节点输入测试数据，能看到该节点的输出和状态变更
**Plans**: TBD

### Phase 6: 插件机制
**Goal**: 管理员能上传第三方插件 zip，插件在沙箱中执行，画布节点面板出现新节点类型
**Depends on**: Phase 5
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

**执行顺序**: Phase 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Skeleton + 账号体系 | 6/6 | ✓ Complete | 2026-05-16 |
| 2. DSL 引擎 + 基础节点 | 10/10 | ✓ Complete | 2026-05-17 |
| 3. HITL 单节点 + Email 审批 | 6/10 | In Progress |  |
| 4. 审批链 + IM 通知 | 0/TBD | Not started | - |
| 4.5. Bot Triggers + Slash | 0/TBD | Not started | - |
| 5. IM 目录双向同步 | 0/TBD | Not started | - |
| 6. 插件机制 | 0/TBD | Not started | - |
| 7. 可观测性 + 运维工具 | 0/TBD | Not started | - |
