# Pitfalls Research

**Domain:** 可视化拖拽式 LangGraph 工作流编排平台 + 多通道 HITL 审批 + 公网回调系统
**Researched:** 2026-05-16
**Confidence:** HIGH（来源：官方 GitHub Issue、生产事故分析文章、安全研究报告）

---

## Critical Pitfalls

### Pitfall 1: LangGraph Checkpoint 表膨胀（写入放大）

**What goes wrong:**
LangGraph 的 PostgresSaver 在每个节点执行后写入完整状态快照（追加模式，不更新）。如果 state payload 包含大文本块（LLM 输出、用户上传数据、RAG 文档），每次 graph 执行就会触发 TOAST 膨胀。实测：15 步执行 × 100KB state = 1.5MB/次；100 并发时 WAL 生成速率约 150MB/s，导致复制延迟 3-5 秒，磁盘 I/O 饱和。

**Why it happens:**
框架设计决策：checkpoint 是 append-only 的不可变快照，用于支持 time-travel debugging。开发者往往把"重型"数据（文档内容、LLM 响应全文、IM 卡片 raw JSON）直接塞进 state。

**How to avoid:**
1. **Pointer State Pattern**：重型数据写 Redis（TTL = 实例最长运行时间 × 1.2），state 只存指针 `__ptr__:redis:state:{uuid}`，可使 checkpoint 体积减少 99.8%（来源：azguards.com 生产分析）
2. 明确定义 state schema 中哪些字段是"传引用"：DSL 内容、LLM 原始输出、attachment bytes → 均走引用
3. 设置 checkpoint TTL 清理任务（PostgresSaver 无内置 TTL），用 pg_cron 定时 `DELETE FROM checkpoints WHERE created_at < NOW() - INTERVAL '30 days'`
4. 生产监控：`checkpoints` 表行数告警阈值 = 预期实例数 × 平均步骤数 × 2（buffer）

**Warning signs:**
- `checkpoints` 表大小超过 workflow 业务数据总和
- Postgres replication lag > 500ms
- `pg_stat_user_tables` 中 `checkpoints` 的 `n_dead_tup` 持续高涨
- 实例恢复（resume）耗时 > 2 秒

**Phase to address:** M2（DSL + 引擎）— 设计 state schema 时强制约定哪些字段走指针

**References:**
- [The Checkpoint Bloat: Mitigating Write-Amplification in LangGraph Postgres Savers](https://azguards.com/distributed-systems/the-checkpoint-bloat-mitigating-write-amplification-in-langgraph-postgres-savers/)
- [GitHub Issue #1138 langchain-ai/langgraphjs: Postgres checkpointer unbounded growth](https://github.com/langchain-ai/langgraphjs/issues/1138)

---

### Pitfall 2: interrupt/resume 并发竞争（同一 thread 多次提交）

**What goes wrong:**
并行工具节点（Parallel FanOut）中每个工具调用 `interrupt()`，LangGraph 会给两个 interrupt 分配相同 ID，resume 时值会路由到错误的工具（Issue #6533，langgraph 1.0.4 + langgraph-prebuilt 1.0.5 复现）。更危险的是：审批人点击邮件中两个不同 action 按钮（如先点"通过"、卡顿中又点"拒绝"），双重提交触发两次 `graph.invoke(Command(resume=...))`，后到的调用在 checkpoint 读到已恢复的 state，行为不可预测。

**Why it happens:**
1. `ToolNode` 用 `asyncio.gather` 并行执行工具，第一个 `GraphInterrupt` 传播时其他协程被取消，interrupt ID 不唯一
2. 应用层没有对 `flow_instance_id` 做分布式互斥锁，两个请求同时读到 `waiting_interrupt` 状态都触发 resume

**How to avoid:**
1. **应用层 Advisory Lock**（项目已规划）：在 `POST /hitl/action/<token>` handler 里用 `pg_advisory_xact_lock(flow_instance_id_hash)` + 事务包裹，保证同一实例同一时刻只有一个 resume 在飞
2. Parallel FanOut 节点本期不使用 LangGraph 内置 ToolNode 的并行 interrupt，而是在应用层维护 `pending_approvers` 列表（HITL-03 决策已锁定"单 interrupt + 自管审批链状态"）
3. jti 消费加 DB 唯一约束：`hitl_tokens.used_at` 用 `UPDATE ... WHERE used_at IS NULL RETURNING *`，零行则拒绝（幂等性保证）
4. 前端决策页：提交后立即 disable 所有按钮，给出 "处理中…" 状态

**Warning signs:**
- 同一 `node_state_id` 下 `action_logs` 出现两条同类决策记录
- `flow_instances.status` 跳到 `running` 但下游节点没进
- 实例 status 变成 `running` 后又变回 `paused`（LangGraph 内部重置）

**Phase to address:** M3（HITL 四态）— Token 消费逻辑和 Advisory Lock 必须在 M3 首日设计到位

**References:**
- [GitHub Issue #6533: Interrupt resume values misrouted between tools when using a ToolNode](https://github.com/langchain-ai/langgraph/issues/6533)
- [GitHub Issue #6624: ToolNode doesn't collect all interrupts from parallel tool execution](https://github.com/langchain-ai/langgraph/issues/6624)
- [GitHub Issue #7259: AsyncPostgresSaver instance-level threading.Lock() bottleneck](https://github.com/langchain-ai/langgraph/issues/7259)

---

### Pitfall 3: 邮件深链 Token 被邮件安全扫描器自动消费

**What goes wrong:**
Microsoft Defender / Outlook Online 的 Safe Links 机制会在邮件送达时对所有 URL 发送 GET 请求（用于安全扫描）。如果 token 被设计为"GET 即消费"，扫描器在用户看邮件前就已消费 jti，审批人点击时看到"链接已失效"。此场景在 2025 年 4 月 Microsoft Defender 的 email preview 功能中被记录为已知回归（office365itpros.com）。

**Why it happens:**
设计者混淆了"访问决策页（GET）"和"提交决策（POST）"的语义，把 GET 请求本身当作消费动作。

**How to avoid:**
1. **GET 不消费，POST 才消费**（项目已在 §6.2 设计正确）：GET `/hitl/page/<token>` 只校验签名 + exp + jti 未消费，签发 30min session cookie，**不动** `used_at`；POST `/hitl/action/<token>` 才消费 jti
2. 双重检测：通过 User-Agent 和请求特征区分爬虫（`Googlebot`、`facebookexternalhit`、`Twitterbot` 等）→ 对已知扫描器直接返回 200 空页，不签发 session cookie
3. 可选：GET 链接不携带 token，而是展示"点击查看审批"按钮，按钮带 token；但这会增加一次跳转，影响 UX
4. 在通知记录中区分"viewed_by_scanner"和"viewed_by_human"（UA 特征 heuristic）

**Warning signs:**
- `notifications.status` 变为 `viewed` 但 `action_logs` 无对应记录且时间差 < 5 秒
- 大量来自 `40.94.*`（Microsoft） / `66.220.*`（Facebook）IP 的 token GET 请求

**Phase to address:** M3（HITL 四态）— token 生命周期设计阶段必须覆盖此场景；集成测试加邮件扫描器模拟用例

**References:**
- [Microsoft Defender Email Preview Enables Malicious Links (office365itpros.com, Apr 2025)](https://office365itpros.com/2025/04/07/email-preview-defender/)
- [Magic links can end up in Bing search results — rendering them useless](https://medium.com/@ryanbadger/magic-links-can-end-up-in-bing-search-results-rendering-them-useless-37def0fae994)
- [Do email security software solutions click hyperlinks in emails? (Suped KB)](https://www.suped.com/knowledge/email-deliverability/technical/do-email-security-software-solutions-click-hyperlinks-in-emails)

---

### Pitfall 4: HMAC 密钥泄漏导致任意伪造 Token

**What goes wrong:**
HMAC 密钥（`HMAC_SECRET`）一旦泄漏（env 文件提交 git、docker inspect、日志打印），攻击者可以伪造任意 `actor_id`、`allowed_actions` 的合法 Token，绕过全部审批节点。

**Why it happens:**
1. `.env` 文件未加入 `.gitignore`（fork 仓库时常见）
2. FastAPI 的 debug 模式把 `settings` 对象序列化到 `/docs` 或 error response
3. Docker Compose 的 `env_file` 内容通过 `docker inspect` 可见

**How to avoid:**
1. 启动时校验：`len(HMAC_SECRET) < 32` → 拒绝启动（项目已规划 NET-04）
2. `.gitignore` 全局加 `.env`，`.env.example` 只放占位值（`HMAC_SECRET=CHANGE_ME_AT_LEAST_32_CHARS`）
3. FastAPI `app = FastAPI(docs_url=None)` 在生产环境关闭 /docs
4. 日志 scrubbing：在 logging filter 里检测并掩码包含 `SECRET/KEY/TOKEN/PASSWORD` 的字段
5. 密钥轮换策略：支持双 HMAC 密钥（旧密钥 grace period = token max TTL = 24h）

**Warning signs:**
- 出现 `actor_id` 不在 `users` 表的有效 token 请求
- `action_logs` 出现同一 jti 被消费两次（说明系统外的伪造 token 碰撞到真实 jti）
- git log 中 `.env` 文件历史有 SECRET 明文

**Phase to address:** M1（Skeleton + 账号体系）— 密钥管理规范在项目第一天就要到位；M3 完成时做安全审计

**References:**
- [Magic Link Security: Best Practices & Advanced Techniques (guptadeepak.com)](https://guptadeepak.com/mastering-magic-link-security-a-deep-dive-for-developers/)
- [Protecting OTP & Magic Link Endpoints from Abuse (SecurityBoulevard, 2026)](https://securityboulevard.com/2026/03/protecting-otp-magic-link-endpoints-from-abuse-ip-reputation-rate-limiting-and-suspicious-ip-throttling/)

---

### Pitfall 5: 审批链部分回退状态不一致（并行会签 partial reject）

**What goes wrong:**
`parallel_all` 模式（全员同意才通过）下，A 同意、B 拒绝。B 的拒绝触发 `TERMINATE`，LangGraph resume 把流程推进到 `rejected` 终态。但 A 的 token 仍有效，A 之后点了"同意"，触发第二次 resume，导致已终止的实例再次运行或 state 损坏。`parallel_any` 或签时情况反转：第一个同意立即 DONE，其余人 token 还能提交。

**Why it happens:**
审批链终态产生后，没有及时失效其余未使用的 token，也没有在 `POST /hitl/action/<token>` 处校验实例当前状态。

**How to avoid:**
1. 终态写入时批量 mark：同一 `node_state_id` 的所有 `hitl_tokens` 均设 `used_at = NOW()`, `reason = 'superseded'`，原子操作
2. `POST /hitl/action` 开头加两层检查：① jti 未消费 ② `node_state.status IN (waiting_human, in_review)`，否则返回 409 + "该节点已结束"
3. 会签人员变更（业务运营需求）：新增成员发新 token + 新 `node_state_id`，旧 token 全部失效；不允许原地改 `approval_chain.approvers`（防止 state 不一致）

**Warning signs:**
- `action_logs` 中同一 `node_state_id` 出现 TERMINATE 后还有新记录
- 实例 status 从 `completed/rejected` 变回 `running`

**Phase to address:** M3（单节点 HITL）设计终态失效逻辑；M4（审批链）集成测试全覆盖 4 种模式的 edge case

---

### Pitfall 6: 多租户跨租户数据泄漏（连接池上下文污染）

**What goes wrong:**
PgBouncer 等连接池在事务模式（transaction mode）下，`SET LOCAL app.workspace_id = '...'` 在事务结束后被重置，但在会话模式（session mode）下 `SET`（非 `SET LOCAL`）会持久化。若代码漏掉 `SET LOCAL` 或发生异常未清理，下一个请求从池中拿到同一连接时继承了上一个租户的上下文，RLS 策略失效，返回他人数据（CVE-2024-10976 类似场景）。

**Why it happens:**
1. ORM/SQLAlchemy 生命周期与连接池生命周期不对齐
2. 异常路径未执行 `DISCARD ALL` / `RESET`
3. 误用 `SET` 而非 `SET LOCAL`

**How to avoid:**
1. 所有租户查询强制走 `workspace_id` 显式过滤（不依赖 `current_setting()`），双保险
2. SQLAlchemy `@event.listens_for(engine, "checkout")` 钩子：连接从池取出时 `DISCARD ALL`
3. 表设计：`workspace_id` 加在所有业务表的 PK 复合索引第一列（`(workspace_id, id)`），强制查询必须带
4. 集成测试：每个 CRUD API 测试用双租户账号互相访问，断言 403/空集

**Warning signs:**
- 查询日志中出现无 `workspace_id` 条件的 `SELECT *`
- 慢查询（missing index）出现在 `workspace_id = ?` 过滤列
- 异常发生后下一请求返回异常用户的数据（需要跨租户测试账号）

**Phase to address:** M1（Skeleton 改造时就要建立 workspace 隔离底线）；M2 补充租户隔离集成测试

**References:**
- [Multi-Tenant Leakage: When Row-Level Security Fails in SaaS](https://medium.com/@instatunnel/multi-tenant-leakage-when-row-level-security-fails-in-saas-da25f40c788c)
- [CVE-2024-10976: PostgreSQL row security policies below subqueries](https://www.techbuddies.io/2026/01/01/how-to-implement-postgresql-row-level-security-for-multi-tenant-saas/)

---

## Moderate Pitfalls

### Pitfall 7: IM Access Token 并发刷新竞态（飞书/企微/钉钉）

**What goes wrong:**
飞书 `tenant_access_token` 有效期 7200 秒，企微 `access_token` 有效期同样 7200 秒。多进程 worker（Uvicorn worker=4）同时检测到 token 即将过期，并发发起刷新请求，所有 worker 拿到不同的新 token，相互覆盖导致部分 worker 使用已失效 token。企微还对刷新频率有硬限制（同一 App 每天 2000 次），过度并发刷新会触发限流。

**How to avoid:**
1. **Token 写 Redis + distributed lock**：用 `SET NX PX 5000` 抢锁刷新，抢不到则等待并读缓存值
2. 刷新提前量：token 剩余 < 10 分钟（不是 0）时触发，避免刷新时间窗口内的请求失败
3. 每个 IM 适配器封装统一的 `TokenManager`，不允许直接使用 IM client 的 token 字段
4. 飞书特有：`user_access_token` 与 `tenant_access_token` 功能域不同，混用会得到 `99991663` 错误

**Warning signs:**
- IM 推送间歇性 `invalid access token` 错误，重试成功
- Redis 中 IM token 键同时出现多个版本
- 企微 API 返回 `errcode 42001`（access_token expired）频率上升

**Phase to address:** M4（IM 通知卡片）— TokenManager 应在 M4 第一个适配器接入时就要实现

---

### Pitfall 8: 飞书卡片版本碎片化 + 企微 open_id vs userid 混淆

**What goes wrong:**
飞书卡片 API 存在 1.0 和 2.0 schema，新建 Bot 默认用 v2，但文档中大量示例仍是 v1 语法，混用导致卡片渲染失败（静默失败，只收到 `ok` 响应但用户看不到卡片）。企微同时存在 `userid`（企业内部）和 `openid`（第三方 App），两者不互通；钉钉有 `unionid` / `userid` / `open_conversation_id` 三套 ID，assignee resolver 写错 ID 类型会导致消息投递到错误用户或静默失败。

**How to avoid:**
1. 飞书适配器：统一用卡片 2.0 SDK（`feishu-python-sdk` 最新版），不手写 raw JSON
2. 企微：存储 `im_directory` 时同时存 `userid` 和 `openid`，发消息 vs 拉群分别用对应字段
3. 钉钉：仅用 `userid` 发工作通知，`unionid` 用于跨 App 同一人识别
4. 每个 IM 适配器写独立的 integration test（mock IM API），覆盖"用户不存在"、"token 无效"、"卡片格式错误"三类错误场景
5. IM 同步时记录 `external_id_type`（feishu_open_id / wecom_userid 等），不混存

**Warning signs:**
- IM 推送返回 200 但用户报告没收到卡片
- `im_directory` 表中同一用户的 `external_id` 与 IM 官方 API 返回的 ID 格式不一致
- 卡片消息发送成功但点击按钮 URL 无效（open_id 用到了需要 userid 的 API）

**Phase to address:** M4（IM 通知）

---

### Pitfall 9: 画布 DSL 并行节点死锁 + 循环节点无限循环

**What goes wrong:**
用户在画布上把 FanIn 节点的上游连到 FanIn 自身（形成环），或者 Loop 节点的 exit 条件引用了还未赋值的变量（悬空引用），导致执行器无限循环。Dify 社区也有相同 Issue：`#9011 When using parallel execution of nodes in workflows, can it wait for all nodes are finished`（2024）表明 FanIn 等待逻辑难以在可视化编辑器中校验。

**How to avoid:**
1. **DSL 编译器静态检查**（validator.py）：
   - `detect_cycles()`：拓扑排序，有环则拒绝编译
   - `validate_fanin()`：每个 FanIn 节点必须有且仅有对应的 FanOut 节点作为所有上游
   - `validate_variables()`：节点 config 中引用的变量路径（`$.xxx`）在 state schema 中已定义
2. Loop 节点强制配置 `max_iterations`（硬限制，不可为 0 或空），执行器检查计数超限则抛 `LoopLimitExceeded`
3. 画布前端实时检测成环：连线操作后立即在前端 React Flow 图上做 DFS，成环则禁止保存并高亮错误路径
4. FanOut/FanIn 节点在 DSL 中互相引用（`fanout_ref`），允许检查配对完整性

**Warning signs:**
- 实例 `running` 状态超过预期时间 3 倍以上
- `flow_instances.updated_at` 不再更新但状态仍 `running`
- Worker CPU 出现某个 `thread_id` 持续占用

**Phase to address:** M2（DSL + 引擎）— validator 是 M2 核心交付物之一；画布成环检测 M2 同步实现

---

### Pitfall 10: 公网入口暴露面蔓延 + 回调路径被扫描枚举

**What goes wrong:**
nginx 配置被错误修改后，`/api/v1/*` 意外对公网可达，攻击者可枚举工作流列表、实例 ID、用户信息。`/hitl/action/<token>` 路径结构固定，安全扫描工具可对 token 做暴力枚举（尤其是 token 使用 UUID v4 但攻击者知道 `node_state_id`）。

**How to avoid:**
1. **nginx allow list 方式**（非 deny all + 例外）：默认 `return 403`，只 `location /hitl/page/`、`location /hitl/action/`、`location /api/im/webhook/` 放行
2. Token 路径加随机后缀（项目已用 UUID jti）+ HMAC 签名：暴力枚举 token 等价于破解 HMAC-SHA256
3. Rate limit 分层：① Nginx 层：每 IP /hitl/* 每分钟 30 次；② FastAPI 层：每 jti 每分钟 5 次 GET（防扫描器高频探测）
4. `/api/im/webhook/*` 端点加 HMAC 签名验证（飞书 v3 签名、企微 msg_signature、钉钉 sign），未验证的请求直接 403
5. 回调路径用 UUID 路由（如 `/api/im/webhook/{workspace_token}`），每个 workspace 独立，无法从一个 workspace 推测另一个

**Warning signs:**
- Nginx access log 出现大量 403 集中在 `/api/v1/` 或 `/admin/`（意味着攻击者在探测）
- `/hitl/action/<token>` 出现 token 不在 DB 中的 400 错误高频出现
- IM webhook 收到非法 HMAC 签名请求

**Phase to address:** M1（Skeleton + nginx 配置）先建立最小暴露面；M3（公网 token 回调）完成后做渗透测试

**References:**
- [Webhook Security Best Practices for Production 2025-2026 (DEV Community)](https://dev.to/digital_trubador/webhook-security-best-practices-for-production-2025-2026-384n)
- [OpenClaw CVE: Webhook Rate Limiting Bypass via Pre-Authentication Secret Validation](https://www.vulncheck.com/advisories/openclaw-webhook-rate-limiting-bypass-via-pre-authentication-secret-validation-2)

---

### Pitfall 11: Fork 上游（Onelevenvy/flock）改动散布导致无法 merge

**What goes wrong:**
Fork 后为了快速实现功能，直接在 flock 原有文件（`app/core/graph_manager.py`、`web/src/components/nodes/`）里堆砌新逻辑。3 个月后上游发布重大重构，cherry-pick 时每个文件都有冲突，最终选择放弃跟进上游，成为永久性 divergent fork，丧失安全 patch 和新特性。

**Why it happens:**
Fork 初期没有架构纪律，"改哪里方便改哪里"，核心文件成为改动的交汇点。

**How to avoid:**
1. **改动隔离策略**（项目设计文档已提到）：新功能放 `adapters/`、`api/core/hitl/`、`api/core/auth/`，尽量不动 flock 的 `app/core/graph/`、`web/src/components/flow/`
2. 建立"flock 原生文件"清单：在项目根 `UPSTREAM.md` 记录哪些文件来自上游不可随意修改，CI 检查该列表文件的改动需要 special review label
3. 每月一次 `git fetch upstream && git log upstream/main..HEAD` 确认 drift，超过 50 个 commit 未 cherry-pick 则启动 merge sprint
4. 必要的上游文件修改：用 monkey-patch / override 方式在新文件中扩展，不改原文件（Python 的 `__init_subclass__`、FastAPI 的 include_router 等）

**Warning signs:**
- flock 原生文件 git blame 显示超过 30% 行由本项目修改
- `git merge upstream/main` 产生超过 20 个冲突文件
- 本项目的 bug 修复已有上游 patch 但无法直接应用

**Phase to address:** M1（Fork 建立时制定规范）；每个 milestone 结束时检查 upstream drift

**References:**
- [Being friendly: Strategies for friendly fork management (GitHub Blog)](https://github.blog/developer-skills/github/friend-zone-strategies-friendly-fork-management/)
- [Forking is not free; the hidden costs (nickdesaulniers.github.io)](https://nickdesaulniers.github.io/blog/2023/02/01/forking-is-not-free-the-hidden-costs/)

---

### Pitfall 12: 插件沙箱 Python 对象层级逃逸 + 网络白名单绕过

**What goes wrong:**
即使用 subprocess 隔离插件，Python 内部对象层级可通过 `().__class__.__bases__[0].__subclasses__()` 枚举到 `BuiltinImporter`，从而在沙箱内 `load_module('os')` 执行任意代码（Checkmarx "Glass Sandbox" 研究）。网络白名单依赖路径前缀过滤，可被 symlink 或 DNS rebinding 绕过。

**How to avoid:**
1. **多层纵深防御**（不要只靠 subprocess）：
   - OS 层：Linux `seccomp-bpf` 白名单只允许 `read/write/mmap/open`，禁止 `execve/fork/clone`
   - 网络层：squid proxy + ACL，只放行 `manifest.permissions.network` 声明的 host（精确匹配，非前缀）
   - 文件系统：`pivot_root` 到只读 chroot，只挂载 `requirements.txt` 安装目录和 `/tmp`（每次执行新建，执行后删除）
2. Dify Plugin Daemon 的沙箱实现值得直接借鉴（`/Users/admin/ai/ref/dify/repo/` 已有 clone）
3. `requirements.txt` 白名单：包名 + 版本范围必须在平台维护的允许列表中，不允许 `git+https://` 和 `file://`
4. macOS 开发环境：用 `resource.setrlimit(RLIMIT_AS, ...)` 限内存，`signal.alarm()` 限时；生产 Linux 用 cgroups v2
5. dry-run 阶段（安装流程第 2 步）：空白输入执行一次，检测是否尝试网络连接或文件系统越权

**Warning signs:**
- 沙箱进程 CPU 持续 100% 超过 `timeout_sec`
- 沙箱进程尝试 `open(/etc/passwd)` 或 DNS 查询非白名单域名（seccomp 会 kill 并记录）
- `requirements.txt` 包含不在白名单中的依赖

**Phase to address:** M6（插件机制）— 沙箱安全是 M6 的 P0 验收条件，干运行测试必须包括逃逸 POC

**References:**
- [The Glass Sandbox - The Complexity of Python Sandboxing (Checkmarx)](https://checkmarx.com/zero-post/glass-sandbox-complexity-of-python-sandboxing/)
- [Agent Sandboxing and Secure Code Execution (tianpan.co, 2026)](https://tianpan.co/blog/2026-03-09-agent-sandboxing-secure-code-execution)
- [Python + Wasmtime: Safe Sandbox for Untrusted UDFs at Near-Native Speed](https://medium.com/@2nick2patel2/python-wasmtime-in-servers-safe-sandbox-for-untrusted-udfs-at-near-native-speed-ed858be1c48e)

---

## Minor Pitfalls

### Pitfall 13: thread_id 设计不携带 workspace 前缀

**What goes wrong:**
LangGraph checkpoint 的 `thread_id` 只用 `flow_instance_id`（UUID），两个不同租户的实例恰好 UUID 相同（概率极低，但 checkpoint 表无租户字段时无法排查）；或者 checkpoint 查询接口无意间跨租户可见。

**How to avoid:**
`thread_id = f"{workspace_id}:{flow_instance_id}"`，checkpoint 天然带租户前缀，排查日志也方便。LangGraph PostgresSaver 的 `thread_id` 是普通 varchar，无限制。

**Phase to address:** M2

---

### Pitfall 14: DSL 版本锁定后实例无法迁移

**What goes wrong:**
项目设计已锁定"实例锁定创建时的 DSL 版本"（Out of Scope）。但运营中常见诉求：流程发布后发现某节点配错，想把运行中实例迁到新版 DSL。如果不设计迁移路径，运维只能手动 kill 并重建实例。

**How to avoid:**
v1 在 `flow_instances` 的 `context` 字段里记录"已完成节点列表"，管理员在 UI 上手动触发"迁移实例到新版 DSL + 跳过已完成节点"（半自动迁移，v2 做自动）。v1 在文档中明确"正在运行的实例不自动迁移，需手动操作"。

**Phase to address:** M7（可观测性 + 运维工具）

---

### Pitfall 15: IM 双向同步循环触发（IM → 本地 → IM）

**What goes wrong:**
IM Directory 同步写入本地 `im_directory` 表 → 触发 SQLAlchemy event → 触发"用户信息变更通知" → 通过 IM 发消息 → IM Bot 收到自己的消息事件 → 再次触发同步。

**How to avoid:**
1. 同步任务用独立 flag（`sync_in_progress = True`）屏蔽 ORM event
2. IM webhook handler 检查消息来源：若 `sender.type == 'bot'` 且 `sender.bot_id == self.bot_id`，直接 ignore
3. 同步与通知走不同的 DB session，避免事件传播

**Phase to address:** M5（IM 目录同步）

---

## Technical Debt Patterns

| 快捷方式 | 短期收益 | 长期代价 | 可接受条件 |
|----------|----------|----------|-----------|
| State 里直接存大文本（LLM 输出、DSL JSON） | 代码简单 | Checkpoint 膨胀，WAL 暴增，恢复变慢 | 永不可接受（M2 就要治） |
| Token 过期后才刷新（而非提前刷新） | 逻辑简单 | IM 推送在 token 刚过期的窗口内失败，需重试 | 仅可接受于 MVP 单 worker 场景 |
| 使用 `SET` 而非 `SET LOCAL` 设置租户上下文 | 少写一个单词 | 连接池复用时跨租户泄漏 | 永不可接受 |
| 忽略邮件扫描器 auto-click，GET 即消费 jti | 代码简单 | 正式企业用户（Microsoft Defender）100% 触发 | 永不可接受 |
| 在 flock 原生文件里直接加功能 | 快速实现 | 无法 merge 上游，安全 patch 需要手动移植 | 仅接受 hotfix，需同时开 issue 计划重构 |

---

## Integration Gotchas

| 集成方 | 常见错误 | 正确做法 |
|--------|----------|----------|
| 飞书 | 用 v1 卡片语法（JSON 模板）接 v2 Bot | 明确检查 Bot 创建时间，新 Bot 默认 v2，用官方 SDK |
| 飞书 | 混用 `open_id` / `user_id` / `union_id` | 消息发送用 `open_id`，联系人查询用 `user_id`，跨 App 匹配用 `union_id` |
| 企微 | `access_token` 并发刷新导致竞态 | Redis SETNX 抢锁 + 写共享 token；过期前 10 分钟刷新 |
| 企微 | `openid`（第三方应用）与 `userid`（自建应用）混用 | 自建应用用 `userid`，区别记录在 `im_directory.external_id_type` |
| 钉钉 | 推送到 `unionid` 而非 `userid` | 工作通知 API 必须用 `userid`；`unionid` 仅用于跨 App 身份映射 |
| Slack | Slash command 超 3 秒未响应触发超时 | 立即返回 `{"response_type": "in_channel"}`，异步处理后用 `response_url` 推送结果 |
| Microsoft Outlook | Safe Links 扫描器 GET token URL | GET 不消费 jti，POST 才消费；UA 检测屏蔽已知爬虫 |
| PgBouncer | session 模式下 `SET` 跨连接泄漏 | 用 transaction 模式 + `SET LOCAL`；连接 checkout 时 `DISCARD ALL` |

---

## Performance Traps

| 陷阱 | 症状 | 预防措施 | 临界规模 |
|------|------|----------|---------|
| Checkpoint 写入放大 | Postgres WAL 暴增，复制延迟 > 1s | Pointer State Pattern，重型数据走 Redis | ~10 并发实例 × 10 步 × 50KB state |
| IM token 并发刷新 | 间歇性 IM 推送失败，redis 中 token 版本不一致 | Redis SETNX 分布式锁 | 4+ worker 进程同时运行 |
| 未索引的 `workspace_id` 过滤 | 大表全扫（`node_states`、`action_logs`） | 复合索引 `(workspace_id, instance_id)` | 10k+ 实例 |
| 插件 subprocess 无超时 | Worker hang，请求队列堆积 | `signal.alarm()` + asyncio `wait_for()` 双保险 | 第一个恶意/有 bug 插件 |
| checkpoint 无 TTL 清理 | `checkpoints` 表无限增长，查询变慢 | pg_cron 定时清理已完成实例的旧 checkpoint | 1k 已完成实例 |

---

## Security Mistakes

| 错误 | 风险 | 预防 |
|------|------|------|
| GET 请求消费 jti | 邮件扫描器预消费，审批人收到"链接已失效" | GET 只校验 + 签发 session，POST 才消费 jti |
| HMAC_SECRET 写入 .env 提交 git | 任意 token 伪造，全部审批节点被绕过 | `.gitignore` 覆盖 `.env`；CI 加 secret 扫描（gitleaks） |
| `/api/v1/*` 对公网暴露 | 工作流/用户信息枚举，实例状态篡改 | nginx 默认 403 + 白名单放行；内网 / VPN 访问管理端 |
| IM webhook 不验签 | 攻击者可伪造 IM 事件触发决策 | 飞书 v3 签名 / 企微 msg_signature / 钉钉 sign 全部强验 |
| Python 插件沙箱仅靠 subprocess | 对象层级逃逸（`__subclasses__`） | seccomp-bpf + network ACL + chroot 三层纵深 |
| Token 走 query string 而非 path | Referrer 头 / nginx access log 泄漏 token | 路径形如 `/hitl/action/<jti>`，无 query string |
| 单 HMAC 密钥无轮换策略 | 密钥泄漏后无法快速失效已颁发 token | 支持双密钥（新/旧），旧密钥 grace period = TOKEN_TTL |

---

## "Looks Done But Isn't" Checklist

- [ ] **邮件深链**：已测试 Outlook Safe Links 扫描器不消费 jti — 验证：用 curl 模拟 SafeLinksBot UA 发 GET，jti 状态不变
- [ ] **并行会签终态**：已测试第一个人拒绝后其余人 token 全部失效 — 验证：数据库 `hitl_tokens` 该 node_state_id 全部有 `used_at`
- [ ] **Checkpoint 体积**：已测试 50 步执行后 `checkpoints` 表大小 < 10MB — 验证：`SELECT pg_size_pretty(pg_total_relation_size('checkpoints'))`
- [ ] **跨租户隔离**：已测试 workspace A 的 token 无法访问 workspace B 的实例 — 验证：集成测试双租户互访返回 403
- [ ] **IM token 竞态**：已测试 4 个 worker 并发刷新飞书 token 只调用一次 API — 验证：mock 飞书 API，断言调用次数 = 1
- [ ] **DSL 成环检测**：已测试画布连成环后保存被拒绝 — 验证：前端阻止 + 后端 validator 拒绝
- [ ] **插件沙箱逃逸**：已测试 `__subclasses__` 遍历在沙箱内抛出 seccomp violation — 验证：提供 POC 插件跑 dry-run 被拒
- [ ] **公网暴露面**：已验证 nginx 只放行 3 条路径 — 验证：扫描工具（nmap/nikto）对公网 IP 显示只有 HITL 和 IM webhook 路径可达

---

## Recovery Strategies

| 坑 | 恢复代价 | 恢复步骤 |
|----|----------|---------|
| Checkpoint 膨胀（已发生） | MEDIUM | 1. 停 worker；2. 备份 DB；3. 上线 Pointer Pattern；4. 写一次性迁移脚本清理历史大 checkpoint；5. 验证后重启 |
| HMAC 密钥泄漏 | HIGH | 1. 立即换 HMAC_SECRET；2. 所有未到期 token 强制失效（批量 `UPDATE hitl_tokens SET used_at = NOW()`）；3. 通知所有待审批节点重发邮件 |
| 跨租户数据泄漏被发现 | CRITICAL | 1. 下线服务；2. 审计所有 action_logs + access_log 确认泄漏范围；3. 通知受影响租户；4. 修复 + RLS 补测 |
| 上游 fork diverge 无法 merge | HIGH | 1. 新开 fork-resync 分支；2. 逐文件 diff 上游改动，手动移植安全 patch；3. 对改动较大的文件重写为"覆盖"模式（新文件 import 上游类再 override） |
| 插件沙箱逃逸 | HIGH | 1. 立即 disable 所有第三方插件；2. 审计逃逸插件的执行日志；3. 加 seccomp/chroot；4. 重新走安全审核流程 |

---

## Pitfall-to-Phase Mapping

| 坑 | 预防阶段 | 验收方式 |
|----|----------|---------|
| Checkpoint 写入放大 | **M2**（DSL + 引擎） | State schema 审查；压测 50 步执行后表大小 |
| interrupt/resume 并发竞态 | **M3**（HITL 四态） | Advisory lock 集成测试；双击按钮不产生重复 action_log |
| 邮件扫描器预消费 jti | **M3**（HITL 四态） | 模拟 SafeLinksBot UA 集成测试 |
| HMAC 密钥泄漏 | **M1**（Skeleton） | gitleaks pre-commit hook；CI secret scan |
| 审批链终态 token 未批量失效 | **M3**（单节点）→ **M4**（审批链） | 并行会签 edge case 测试套件 |
| 多租户跨租户泄漏 | **M1**（Skeleton 改造） | 双租户互访集成测试 |
| IM token 并发刷新竞态 | **M4**（IM 通知） | TokenManager 分布式锁压测 |
| 飞书卡片版本碎片化 | **M4**（IM 通知） | 每个 IM 适配器 mock 集成测试 |
| DSL 并行死锁 + 无限循环 | **M2**（DSL + 引擎） | validator 单元测试；前端成环检测 E2E |
| 公网暴露面蔓延 | **M1**（nginx 配置） + **M3**（公网回调） | nmap 扫描验证 |
| Fork 上游 diverge | **M1**（Fork 建立时） | UPSTREAM.md + CI 检查；每 milestone 末 upstream drift 审查 |
| 插件沙箱逃逸 | **M6**（插件机制） | seccomp POC 测试；dry-run 逃逸检测 |
| thread_id 无租户前缀 | **M2** | Code review checklist |
| DSL 版本锁定无迁移路径 | **M7**（运维工具） | 半自动迁移 UI 文档 |
| IM 双向同步循环 | **M5**（IM 目录同步） | Bot 消息来源过滤单元测试 |

---

## Sources

**LangGraph / Checkpoint**
- [The Checkpoint Bloat: Mitigating Write-Amplification in LangGraph Postgres Savers](https://azguards.com/distributed-systems/the-checkpoint-bloat-mitigating-write-amplification-in-langgraph-postgres-savers/)
- [GitHub Issue #1138: langgraph-checkpoint-postgres unbounded growth](https://github.com/langchain-ai/langgraphjs/issues/1138)
- [GitHub Issue #6533: Interrupt resume values misrouted between tools when using a ToolNode (langgraph 1.0.4)](https://github.com/langchain-ai/langgraph/issues/6533)
- [GitHub Issue #6624: ToolNode doesn't collect all interrupts from parallel tool execution](https://github.com/langchain-ai/langgraph/issues/6624)
- [GitHub Issue #7259: AsyncPostgresSaver instance-level threading.Lock() bottleneck](https://github.com/langchain-ai/langgraph/issues/7259)
- [Mastering LangGraph Checkpointing: Best Practices for 2025 (sparkco.ai)](https://sparkco.ai/blog/mastering-langgraph-checkpointing-best-practices-for-2025)

**邮件 Token 安全**
- [Microsoft Defender Email Preview Enables Malicious Links (office365itpros.com, Apr 2025)](https://office365itpros.com/2025/04/07/email-preview-defender/)
- [Magic links can end up in Bing search results — rendering them useless](https://medium.com/@ryanbadger/magic-links-can-end-up-in-bing-search-results-rendering-them-useless-37def0fae994)
- [Magic Link Security: Best Practices & Advanced Techniques (guptadeepak.com)](https://guptadeepak.com/mastering-magic-link-security-a-deep-dive-for-developers/)
- [Protecting OTP & Magic Link Endpoints from Abuse (SecurityBoulevard, 2026)](https://securityboulevard.com/2026/03/protecting-otp-magic-link-endpoints-from-abuse-ip-reputation-rate-limiting-and-suspicious-ip-throttling/)

**多租户安全**
- [Multi-Tenant Leakage: When Row-Level Security Fails in SaaS (InstaTunnel)](https://medium.com/@instatunnel/multi-tenant-leakage-when-row-level-security-fails-in-saas-da25f40c788c)
- [CVE-2024-10976: PostgreSQL RLS bypass below subqueries](https://www.techbuddies.io/2026/01/01/how-to-implement-postgresql-row-level-security-for-multi-tenant-saas/)
- [Postgres RLS Implementation Guide - Common Pitfalls (permit.io)](https://www.permit.io/blog/postgres-rls-implementation-guide)

**公网安全**
- [Webhook Security Best Practices for Production 2025-2026 (DEV Community)](https://dev.to/digital_trubador/webhook-security-best-practices-for-production-2025-2026-384n)
- [OpenClaw CVE: Webhook Rate Limiting Bypass via Pre-Authentication Secret Validation](https://www.vulncheck.com/advisories/openclaw-webhook-rate-limiting-bypass-via-pre-authentication-secret-validation-2)

**插件沙箱**
- [The Glass Sandbox - The Complexity of Python Sandboxing (Checkmarx)](https://checkmarx.com/zero-post/glass-sandbox-complexity-of-python-sandboxing/)
- [Agent Sandboxing and Secure Code Execution (tianpan.co, 2026)](https://tianpan.co/blog/2026-03-09-agent-sandboxing-secure-code-execution)
- [Python + Wasmtime: Safe Sandbox for Untrusted UDFs](https://medium.com/@2nick2patel2/python-wasmtime-in-servers-safe-sandbox-for-untrusted-udfs-at-near-native-speed-ed858be1c48e)

**Fork 策略**
- [Being friendly: Strategies for friendly fork management (GitHub Blog)](https://github.blog/developer-skills/github/friend-zone-strategies-friendly-fork-management/)
- [Forking is not free; the hidden costs (nickdesaulniers.github.io)](https://nickdesaulniers.github.io/blog/2023/02/01/forking-is-not-free-the-hidden-costs/)

**工作流 DSL**
- [Dify Issue #9011: parallel execution wait-for-all behavior](https://github.com/langgenius/dify/issues/9011)
- [Visual workflow loops causing resource drain (Latenode Community)](https://community.latenode.com/t/visual-workflow-loops-causing-resource-drain-how-to-break-infinite-processes/43114)

---
*Pitfalls research for: LangGraph 可视化工作流编排 + HITL 多通道审批*
*Researched: 2026-05-16*
