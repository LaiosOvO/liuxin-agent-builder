# Phase 1: Skeleton + 账号体系 - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Fork Onelevenvy/flock 改造成 agent-builder 工程底座，建立多租户 workspace 隔离基线 + 自建账号体系 + 4 角色 RBAC + nginx 最小公网暴露面 + HMAC 密钥校验。docker-compose 一键启动到能登录画布页。

**Phase 1 涵盖 10 个 requirements**：AUTH-01, AUTH-02, AUTH-03, AUTH-06, NET-01, NET-02, NET-03, NET-04, DEPL-01, DEPL-02

**Phase 1 不做（在后续 Phase）**：HITL token 鉴权（AUTH-04/05 → Phase 3）、决策审计日志（NET-05 → Phase 3）、内置模板（DEPL-03 → Phase 6/7）、DSL 引擎和节点（→ Phase 2）。

</domain>

<decisions>
## Implementation Decisions

### Fork 策略与品牌重命名

- **外部可见层全改为 agent-builder**：UI 标题 / logo / favicon / page.json `name` / Docker image name / docker-compose service name / 环境变量前缀（`FLOCK_*` → `AGENT_BUILDER_*`） / README.md / docs/ 全部替换
- **内部代码层保留 flock**：Python import path（`from flock.xxx`）、内部类名/变量名/函数名含 flock 字样的不动，减少未来改名带来的工作量与 bug 风险（即使 never merge 也遵守"最少改上游"纪律）
- **上游同步策略**：**Never merge** — fork 视为快照，自此独立演进，不跟进 flock 的新 feature/bugfix
- **目录树**：保留 flock 原目录结构不变；所有新增模块加在 backend/api/、backend/app/ 等现有路径下作为新增 module 或 sub-package（与 ARCHITECTURE.md 模块树规划保持一致：新增 `hitl/`、`adapters/notification/`、`adapters/im_directory/`、`plugin_runtime/` 等）
- **flock 现有节点（RAG / Subgraph / MCP / 等）**：**代码保留但运行时隐藏** —— 新 `NodeRegistry` 仅注册 Phase 2 所需的节点类型（Start/End/LLM/Tool/IfElse/Parallel-FanOut/Parallel-FanIn/Loop/Subgraph/Code）。flock 原节点保留在仓库内不删，留作未来启用或参考

### 多租户与注册流程

- **租户模型**：**多租户 + 邀请制**（v1 公开注册默认关闭）；workspace 是隔离边界单位，所有业务表都带 `workspace_id` 复合主键 / 复合索引第一列
- **首个 super_admin 通过首次启动 setup 页面创建**（Dify / Gitea 模式）：未初始化时所有路由跳到 `/setup`，填邮箱 + 密码 + 第一个 workspace 名 → 创建 super_admin 账号 + 默认 workspace → 二次启动后 setup 路由对外 404
- **邮箱验证强制开启**：注册或被邀请后需点击验证邮件中的链接才能登录；这恰好同时验证 SMTP 是否配通（一举两得）
- **邀请流程**：admin 在 workspace 设置页输入邮箱 + 选择角色 → 系统生成 24h 一次性 token → 发邀请邮件含 `/invite/accept?token=<jwt>` 链接 → 被邀请人点链接 → 进入注册页（已预填邮箱、不可改）→ 完成密码与个人信息填写 → 直接加入该 workspace 并以指定角色
- **跨 workspace 协作**：v1 不做，workspace 彻底隔离（详见 Deferred）

### RBAC 权限矩阵

| Capability | super_admin | admin | editor | viewer | external |
|------------|-------------|-------|--------|--------|----------|
| 创建/删除 workspace | ✓ | ✗ | ✗ | ✗ | ✗ |
| 工作区设置 / 邀请成员 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 创建/编辑/发布 workflow | ✓ | ✓ | ✓（**含同 ws 他人创建的**） | ✗ | ✗ |
| 启动实例（运行）| ✓ | ✓ | ✓ | **✗（仅查看）** | ✗ |
| 查看实例状态 / 历史 | ✓ | ✓ | ✓ | ✓ | ✗（除自己作为 actor 的） |
| 查看决策页（HITL）| ✓ | ✓ | ✓ | ✓ | **✓（通过 token，仅本节点）** |
| 安装/卸载插件 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 登录 web 管理端 | ✓ | ✓ | ✓ | ✓ | **✗** |

- **editor 修改权限**：能编辑同 workspace 内**任何** workflow（即使是别人创建的）；记录 `last_modified_by` 字段供审计，不强行作者锁
- **viewer 严格只读**：不能启动实例，仅能查看
- **external 角色仅由 HITL token 临时产生**：HITL 节点 assignee 配置邮箱（且邮箱不在 users 表中）时，系统在 token 签发时临时给一个 external actor_id（uuid + email），决策完即作废；external 不能登录 web 管理端，**只有 token 链接是它的唯一入口**（与决策板 #13 "Token 即登录" 一致）
- **super_admin** 是平台级超级管理员（仅 setup 页面创建那一个，可看所有 workspace 但通常不参与日常业务）；admin 是 workspace 级管理员

### 项目级约束（来自 CLAUDE.md，本 phase 强制遵守）

- **并行开发优先**：Phase 1 内独立 plans（auth schema / nginx config / docker-compose / FastAPI scaffolding）必须并行 dispatch
- **全流程测试 + E2E（browser-harness via `webapp-testing` skill）**：
  - Unit / Integration / E2E 三层全覆盖
  - E2E 必测：setup 首启流程 / 注册 + 邮箱验证 / 登录 / 邀请用户 / **RBAC 双 workspace 互访 403** / nginx 仅放行路径扫描
  - 集成测试**禁止 mock 数据库**，用 testcontainers-postgres
- **Fork discipline**：所有改动作为新增 module，不动 flock 原文件（PR diff > 10% 阻断）
- **多租户隔离**：所有业务表 + `workspace_id` 复合索引；SQLAlchemy `DISCARD ALL` checkout hook

### Claude's Discretion（未指定，Claude 决定）

- **公网/内网拓扑**：默认使用**单 nginx 双 server_block** 方案 —— `server { listen 80; server_name 公网域名; location ^~ /hitl/ {...} location ^~ /api/im/webhook/ {...} location / { return 403; } }` + `server { listen 8080; server_name _; location / {proxy to api/web;} }`（内网管理端走 8080）
- **开发模式公网模拟**：推荐 `cloudflared tunnel` 一键暴露本地 8000 端口（无需 ngrok 帐号）
- **Secret 来源**：v1 用 `.env` 文件（`.env.example` 模板入仓 + `.env` 加入 `.gitignore`）；预留 `secret_provider` 抽象，便于 v2 接 Vault / AWS Secrets Manager
- **密码策略**：bcrypt 12 轮哈希（`pwdlib==0.3.0`）；密码长度 ≥ 8 含字母与数字；不强制特殊字符（避免用户写入字典词）；不限制最大长度
- **Session 超时**：登录 cookie 24h，含 sliding window（每次访问刷新）；HITL token session cookie 30 分钟（不刷新）
- **认证失败时行为**：5xx 时 fail-close（拒绝访问 + 503 错误）—— 比 fail-open 安全
- **多设备登录**：v1 允许（不维护 active session 表，避免复杂度），v2 看安全需求加单点登录约束
- **HMAC 密钥校验**：启动时读 `HMAC_SECRET` env，长度 < 32 字节直接 sys.exit(1) 并打印明确错误（NET-04）
- **多租户隔离的工程实现**：
  1. 所有业务表加 `workspace_id` 列 + 加入复合索引第一列 `(workspace_id, id)` / `(workspace_id, created_at)`
  2. SQLAlchemy `select()` 全部走 `WorkspaceScopedQuery` 抽象，自动注入 `WHERE workspace_id = :current_workspace`
  3. `@event.listens_for(engine, "checkout")` hook 在每次连接借出时 `DISCARD ALL`（防 PgBouncer session-mode 上下文残留）
  4. 集成测试：双 workspace 账号互访 CRUD endpoints，断言 403 / 空集（覆盖 Pitfall 6 防护）

</decisions>

<specifics>
## Specific Ideas

- **首次启动 setup 页参考 [Dify](https://github.com/langgenius/dify) 和 [Gitea](https://github.com/go-gitea/gitea) 的 `/install` 路由模式**：未初始化时强制路由到 setup；初始化完成后该路由返回 404
- **邀请邮件 / 邮箱验证邮件 复用项目本身的 SMTP + JWT token 基础设施**：与 Phase 3 HITL 邮件深链是同一套技术栈（Jinja2 模板 + PyJWT HS256 + jti 一次性消费），相当于 Phase 1 提前打通"邮件 + token"端到端，Phase 3 直接复用
- **不复杂化**：v1 没有用户头像上传、个人主页、密码找回（找回靠 admin 重置即可）、Two-Factor —— 这些都是 v2+

</specifics>

<deferred>
## Deferred Ideas

以下想法在讨论中出现但属于其它 phase / v2 范围，记录避免遗失：

- **跨 workspace guest 协作**：用户 admin 邀请外部 workspace 用户作为 guest 参与某个 workflow → 留 v2 验证真实需求后再做
- **OAuth2 / SAML SSO**（已在 REQUIREMENTS.md AUTH-V2-01 / V2-02）
- **LDAP / AD 集成** → v2+
- **IM SSO**（飞书 / 企微登录直接进 agent-builder）→ Phase 5 完成 IM 双向同步后再考虑
- **Workflow 实例级权限**（谁能看哪个 instance）→ Phase 2 讨论 EXEC 时再细化（v1 默认：同 workspace 全部可见）
- **审计日志查询页**（NET-05 增强版本）→ Phase 7 可观测性
- **密码找回流程**（self-serve forgot password 邮件链接）→ v2，v1 admin 手动重置
- **2FA / TOTP**（Two-Factor Authentication）→ v2+
- **API Key（程序化访问）**→ v2，v1 仅 web cookie 会话

</deferred>

---

*Phase: 01-skeleton*
*Context gathered: 2026-05-16*
