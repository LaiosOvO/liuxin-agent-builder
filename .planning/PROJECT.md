# agent-builder

## What This Is

通用拖拽式 LangGraph 编排平台（"LangGraph as Service"）。流程管理员在 Web 画布上拖拽节点搭建工作流 → 实时存为 DSL → 一键部署可运行实例 → HITL 节点通过邮件 / 主流 IM 通道（企微 / 飞书 / 钉钉 / Slack / Mattermost）做四态决策 → 配置公网地址即可发邮件深链，审批人点击 token 即登录。

面向**非编码的流程管理员**（HR / 行政 / 业务负责人）、**平台运维**、以及**审批人**（含外部账号、通过 token 链接进入）。

## Core Value

**让非编码人员通过拖拽 5 分钟搭出"多通道审批 + 公网回调"的 LangGraph 工作流，并真实跑起来。**

如果其它都失败，至少：拖一个 HITL 节点 → 配邮件收件人 → 发布 → 审批人收到邮件 → 点开链接同意 → 流程推进。这条主路径必须通。

## Requirements

### Validated

(None yet — ship to validate)

### Active

#### 编辑器与 DSL
- [ ] **EDIT-01**：用户能在 Web 画布上拖拽节点 / 连接 / 删除 / 重命名节点
- [ ] **EDIT-02**：每种节点类型有专属配置面板（动态表单）
- [ ] **EDIT-03**：工作流保存草稿 / 发布版本（草稿与发布分离）
- [ ] **EDIT-04**：导出 / 导入工作流 DSL（JSON）
- [ ] **EDIT-05**：节点步进调试（Debug 模式：选定节点 → 输入测试数据 → 看输出 + 状态变更）

#### 节点类型
- [ ] **NODE-01**：Start / End 节点
- [ ] **NODE-02**：HITL 节点（人工决策，详见 HITL 类目）
- [ ] **NODE-03**：If-Else 条件分支
- [ ] **NODE-04**：Parallel FanOut / FanIn（并行扇出/汇合）
- [ ] **NODE-05**：LLM 节点（调一次 LLM，参数化模板 + 模型选择）
- [ ] **NODE-06**：Tool 节点（HTTP API / Python function）
- [ ] **NODE-07**：Notification 节点（独立通知节点，不阻塞）
- [ ] **NODE-08**：Subgraph 节点（嵌套子工作流）
- [ ] **NODE-09**：Code 节点（受限 Python 沙箱）
- [ ] **NODE-10**：Loop 节点（for-each）

#### 执行引擎
- [ ] **EXEC-01**：DSL → LangGraph StateGraph 编译执行（解释器模式，热更新）
- [ ] **EXEC-02**：PostgresSaver checkpoint 持久化（thread_id = flow_instance_id）
- [ ] **EXEC-03**：实例运行/暂停/恢复/中止
- [ ] **EXEC-04**：Web 实时查看实例状态与节点时间线
- [ ] **EXEC-05**：运行实例列表页（按工作流/状态过滤，搜索，分页）

#### HITL 四态决策
- [ ] **HITL-01**：HITL 节点四态：执行人 submit/return/reject → 审核人 approve/return/reject
- [ ] **HITL-02**：审批链 4 种模式：单人 / 顺序会签 / 并行会签（全员同意）/ 或签（任一同意）
- [ ] **HITL-03**：单 interrupt + 自管审批链状态（payload 内 records / current_idx）
- [ ] **HITL-04**：节点级超时与超时升级策略
- [ ] **HITL-05**：决策表单可配置（JSON Schema 描述字段）
- [ ] **HITL-06**：任务委托/转交（审批人能把待办转给同事，含审计）
- [ ] **HITL-07**：申请人流程追踪页（提交人可看自己实例的当前状态和历史）

#### 通知通道
- [ ] **NOTI-01**：Email 通道（SMTP，Jinja2 模板，4 个独立 token 链接按钮）
- [ ] **NOTI-02**：飞书通道（卡片 + Bot 推送）
- [ ] **NOTI-03**：企业微信通道（应用消息 + 模板卡片）
- [ ] **NOTI-04**：钉钉通道（ActionCard + 工作通知）
- [ ] **NOTI-05**：Slack 通道（Block Kit）
- [ ] **NOTI-06**：Mattermost 通道（Incoming Webhook）
- [ ] **NOTI-07**：Webhook 通道（通用 POST JSON）
- [ ] **NOTI-08**：HITL 节点可同时配置多个通道（并行推送）
- [ ] **NOTI-09**：催办/提醒通知（超时升级前定时再推一次）
- [ ] **NOTI-10**：通知发送失败重试队列（arq + 指数退避）

#### IM L3 双向同步
- [ ] **IM-01**：飞书 contact API 拉取用户 / 部门 / 汇报关系
- [ ] **IM-02**：企微 contact API 拉取用户 / 部门
- [ ] **IM-03**：钉钉 contact API 拉取用户 / 部门
- [ ] **IM-04**：IM 用户匹配本地账号（按邮箱）
- [ ] **IM-05**：节点 assignee 支持多形态（email / @username / dept:研发部 / dynamic_expr）

#### 认证与权限
- [ ] **AUTH-01**：自建账号体系（邮箱注册 + 密码 bcrypt）
- [ ] **AUTH-02**：用户 profile（部门 + 显示名 + 角色 + IM 绑定）
- [ ] **AUTH-03**：RBAC（admin / editor / viewer / external）
- [ ] **AUTH-04**：HITL Token 即登录（JWT 解码 → session cookie）
- [ ] **AUTH-05**：Token 一次性消费（jti 写 Postgres / Redis）
- [ ] **AUTH-06**：Workspace 级多租户隔离

#### 公网入口与安全
- [ ] **NET-01**：配置 PUBLIC_BASE_URL + nginx 反代
- [ ] **NET-02**：公网仅暴露 `/hitl/page/*` `/hitl/action/*` `/api/im/webhook/*`
- [ ] **NET-03**：Rate limit（每 token / 每 IP 限频）
- [ ] **NET-04**：HMAC 密钥从 env 读，启动校验
- [ ] **NET-05**：决策审计日志（IP / UA / 时间 / 决策）

#### 节点扩展（插件市场）
- [ ] **PLUG-01**：插件包格式（zip：manifest.yaml + schema.json + node.py + requirements.txt）
- [ ] **PLUG-02**：上传 / dry-run / 注册 / 卸载
- [ ] **PLUG-03**：沙箱执行（子进程 + cgroups + 网络白名单）
- [ ] **PLUG-04**：插件可在 NodeRegistry 注册并出现在画布节点面板

#### 部署
- [ ] **DEPL-01**：docker-compose 一键起来（api / worker / web / postgres / redis / nginx）
- [ ] **DEPL-02**：`.env.example` + secret manager 兼容
- [ ] **DEPL-03**：内置 hr 离职流程预置模板

### Out of Scope

- 工作流模板市场前台 — v2，v1 仅本地预置
- 多模型 Provider 池 — v1 接一个 LLM 即可，v2 做 Provider 池
- 节点级 CPU/内存 quota 配置 UI — 沙箱本身有限制，配置 UI 留到 v2
- 完整 i18n — v1 中文 only
- 工作流跑到一半改 DSL 的热迁移 — 实例锁定创建时的 DSL 版本
- 完整插件 PKI 签名验证 — v1 由管理员手动审核
- 移动端 App — Web 优先
- 多语言 SDK — Python 后端 + Web 前端足够

## Context

### 技术环境
- 内网部署能力存在（参考姐妹项目 hr 部署到 192.168.2.44），同时支持公网入口配置
- 已有 GLM API 接入经验（来自父项目 ai-capability-service-laios）
- Postgres / Redis / Docker 是默认基础设施

### 相关参考
- 父目录 `liuxin/hr/PRD.md` 已规划"AI 驱动离职流程系统"，agent-builder 是它的可视化编排底座
- `/Users/admin/ai/ref/dify/repo/` 有 Dify 完整 clone（前端 Canvas 风格参考）
- `/Users/admin/ai/ref/agent/` 有 LangGraph 相关项目

### Skeleton 起点
**Fork [Onelevenvy/flock](https://github.com/Onelevenvy/flock)**（Apache-2.0，1k★），它已具备：
- 拖拽 Canvas + 节点直接映射 LangGraph node/edge
- Subgraph + MCP + 基础 HITL（Web 形态）
- FastAPI + Next.js + Postgres + Docker Compose

### 已研究的开源参考
| 项目 | 借鉴点 |
| ---- | ----- |
| Onelevenvy/flock | Skeleton |
| langchain-ai/agent-inbox | HITL UX schema (approve/edit/reject/respond) |
| activepieces / n8n | 邮件审批 piece、token 设计 |
| Dify | Canvas UI 设计语言、Plugin Daemon 架构 |
| KirtiJha/langgraph-interrupt-workflow-template | FastAPI + LangGraph interrupt 样例 |

## Constraints

- **Tech stack**：Python 3.11+ / FastAPI 0.136+ / LangGraph 1.2+ / langgraph-checkpoint-postgres 3.1+（**psycopg3** 驱动） / SQLAlchemy 2.0.49（asyncpg 驱动） / Postgres 15+ / Redis 7+ / arq 0.28+ / Next.js 16.2+ / @xyflow/react 12+ / Zustand 5+ — fork flock 的栈基础上升级
- **Deployment**：Docker Compose 单机优先，K8s 留到 v2
- **License**：Apache-2.0（与 flock 一致）
- **Language**：核心代码注释 / 文档 / 提交信息中文；UI v1 中文 only
- **Security**：公网仅暴露最小路径集；Token 走 path 不走 query；HMAC 密钥 ≥ 32 字节
- **HITL 中断模式**：单 interrupt + 自管审批链状态（决策板 #8 锁定）
- **执行模式**：DSL 解释执行，不做代码生成（决策板 #2 锁定）

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 执行引擎用 LangGraph + PostgresSaver | 原生 HITL interrupt + 持久化能力强 | — Pending |
| 画布转 DSL/JSON 解释执行（非代码生成） | 热更新友好、状态机一张表、与 Dify/n8n 同路 | — Pending |
| HITL 四态（含审核子流程） | 区分执行与审核职责，支持复杂审批 | — Pending |
| HITL 单 interrupt + 自管审批链状态 | 避免 LangGraph thread checkpoint 膨胀，简化恢复 | — Pending |
| 审批链 4 种模式都要 | 业务场景覆盖：单人 / 顺序 / 并行全 / 或签 | — Pending |
| Token 即登录（不做独立 OAuth） | 外部审批人零摩擦；安全靠 jti 一次性 + 短期 cookie | — Pending |
| Fork Onelevenvy/flock 作 Skeleton | 唯一同时满足拖拽 + LangGraph + 现代栈 + 活跃 | — Pending |
| IM 集成 L3（双向同步） | 节点 assignee 支持部门表达式、卡片决策入口 | — Pending |
| 节点扩展走"内置 + 一等公民 + 插件"三层 | 通用平台必备扩展性 | — Pending |
| 自建账号体系 + 部门 + 角色 | 用户自填部门 / 邮箱，预留 OAuth 后扩 | — Pending |
| 公网部署 + nginx 仅放行 HITL/IM 回调路径 | 最小公网暴露面 | — Pending |
| v1 不对齐父项目 hr/PRD（三态 vs 四态） | hr/ 后续可作为预置模板，按 v1 四态规范来 | — Pending |
| Token GET 不消费 jti、POST 才消费 | 防御 Outlook/Defender Safe Links 邮件扫描器预 GET 导致首次访问失效 | — Pending (P0 by PITFALLS.md) |
| LangGraph state schema 强制区分值字段 vs 引用字段（重型数据走 Redis pointer） | 防 checkpoint 写入放大（15 步 × 100KB = 1.5MB/次），WAL 复制延迟可降 99% | — Pending |
| 多租户所有查询显式带 workspace_id WHERE + SQLAlchemy checkout 时 DISCARD ALL | 防 PgBouncer 连接池上下文污染（CVE-2024-10976 类） | — Pending |
| Fork flock 后所有改动集中新增模块，不改 flock 上游文件 | 防上游 diverge 超过 30% 后无法 merge | — Pending |

---
*Last updated: 2026-05-16 after research synthesis (added 6 gap requirements + 4 P0 key decisions)*
