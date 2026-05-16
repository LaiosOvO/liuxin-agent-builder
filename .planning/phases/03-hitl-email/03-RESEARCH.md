# Phase 3: HITL 单节点 + Email 审批 - 技术研究

**Researched:** 2026-05-17
**Confidence:** HIGH（基于 STACK.md 锁定版本 + 03-CONTEXT.md 16 条决策 + PITFALLS.md Pitfall 2/3/4 P0 + Phase 1/2 已交付基础设施盘点）
**Phase Requirement IDs:** HITL-01, HITL-03, HITL-05, HITL-07, NOTI-01, NOTI-08, NOTI-09, NOTI-10, AUTH-04, AUTH-05, NET-05, NODE-02, NODE-07

---

## 一、User Constraints（来自 03-CONTEXT.md，逐字搬运，已锁不可重新讨论）

### 1.1 HITL 节点状态机 + interrupt payload

- **node_states.payload schema**（CONTEXT.md §HITL 节点状态机）：
  ```python
  {
    "phase": "submit" | "review",
    "current_actor": {"id": "u_xxx", "email": "...", "role": "executor|reviewer"},
    "approval_chain": {"mode": "single", "approvers": [user_ids], "current_idx": 0},
    "records": [...],
    "pending_approvers": [user_ids],
    "started_at": "ISO8601",
    "deadline_at": "ISO8601",
    "form_schema": {...}
  }
  ```

- **LangGraph 1.2 interrupt + Command(resume)**：HITL 节点函数调用 `interrupt({...})` 暂停 graph；`/hitl/action` 端点用 `graph.invoke(Command(resume={action, reason, form_data}), config={"configurable": {"thread_id": instance_id}})` 恢复

- **节点 status 5 态 → 3 终态**：`pending → waiting_human → in_review → done | rejected | returned`（与 Phase 2 02-CONTEXT.md §5.1 一致；本 phase 单人模式：submit 直接走 in_review，approve = done）

- **Deadline 默认 24h**：节点 enter 时 `payload.deadline_at = now() + node_config.timeout_seconds`；超时 worker 每分钟扫一次

### 1.2 Token 4-action 设计 + 安全细节

- **批量生成**：节点 enter 时为 current_actor 的每个 allowed_action 生成独立 JWT token（执行人阶段 3 个：submit/return/reject；审核人阶段 3 个：approve/return/reject）

- **JWT payload**：`{iss, aud:"hitl", iat, exp, jti, flow_id, node_state_id, actor_id, role, allowed_actions:[ACTION]}`；HMAC HS256（HMAC_SECRET ≥ 32 字节 — Phase 1 已落 NET-04）

- **hitl_tokens 表 schema**（CONTEXT.md §Token 4-action 设计）：
  ```sql
  hitl_tokens (
    jti UUID PK,
    instance_id UUID,
    node_state_id UUID,
    actor_id UUID,
    action VARCHAR(16),
    expires_at TIMESTAMP,
    used_at TIMESTAMP NULL,
    used_ip VARCHAR(64) NULL,
    used_ua VARCHAR(256) NULL
  )
  ```
  Postgres 权威，Redis (TTL 24h) 加速缓存（`SET NX agent_builder:jti:<id> 24h`）

- **Safe Links Bot UA 白名单**（CLAUDE.md 2.5 + Pitfall 3 P0）：
  ```python
  BOT_UA_PATTERNS = (
      "microsoftdefender", "outlook-safelinks", "slackbot-linkexpanding",
      "twitterbot", "facebookexternalhit", "linkedinbot", "whatsapp",
      "googlebot", "telegrambot", "discordbot", "duckduckbot",
      "baiduspider", "bingbot",
  )
  ```
  GET 检测到 bot UA → 静态 HTML，不签 cookie / 不动 jti / 不写 viewed

- **Token 生命周期**（4 步）：见 CONTEXT.md §Token 生命周期 1-4 步

- **公网仅暴露 `/hitl/page/*` + `/hitl/action/*` + `/api/im/webhook/*`**（Phase 1 NET-02 nginx 已锁定）

### 1.3 决策页 UI / UX

- **表单模式**（不直接消费按钮 GET）：显示当前 actor / phase / 申请详情 / 流程上下文 / 历史 records / 表单字段（action 必选 + reason 可选 + form_data 动态）
- **附件上传** v1 不做 / **撤销提交** v1 不可撤销 / **超时显示** 倒计时（前端 setInterval，不轮询）

### 1.4 申请人追踪页（HITL-07）

- 路径：`/dashboard/instances/<id>/tracking`
- 信息：实例当前阶段 + 完整 records 时间线 + 当前节点截止时间
- 隐私：申请人只能看姓名+决策+时间（无 IP/UA）；admin 看全
- 路由权限：`applicant_id == current_user.id` 才放行

### 1.5 邮件模板 + 超时催办

- Jinja2 HTML 模板（品牌头 + 申请上下文 + 截止时间 + 3 按钮 + 明文 fallback）
- 中文 only（i18n v2）
- **NOTI-10 SMTP 重试**：arq queue `notifications` + tenacity 3 次指数退避（1s/2s/4s）→ 全失败写 status=failed + admin 告警
- **NOTI-09 催办**：24h 首催办 / 48h 二催办 / 72h 升级到 admin（escalate_to 节点配置 + records 加 escalate 记录）
- **去重**：`(instance_id, node_state_id, channel, recipient, reminder_round)` UNIQUE 约束

### 1.6 Claude's Discretion（CONTEXT 中已划定）

- Workflow Trigger v1 用 REST API（不做 IM trigger）
- form_schema 用 JSON Schema 子集（type/properties/required）
- 前端 form 渲染：**RJSF 或 react-hook-form + zod**（本研究 §三 选型）
- Sentry / 监控 v1 不接

---

## 二、技术栈细节（从 STACK.md 验证）

### 2.1 已确认锁定

| 技术 | 版本 | 用途 | 来源 |
|---|---|---|---|
| LangGraph | 1.2.0 | interrupt + Command(resume) | Phase 2 02-01 已落 |
| langgraph-checkpoint-postgres | 3.1.0 | AsyncPostgresSaver | Phase 2 02-01 已落 |
| PyJWT | 2.12.1 | HITL token HS256 签发 / 校验 | Phase 1 01-04 已落 backend/app/services/jwt_service.py |
| aiosmtplib | 5.1.0 | 异步 SMTP | Phase 1 01-04 已落 backend/app/services/email_service.py |
| Jinja2 | 3.1.6 | 邮件模板 + Jinja sandbox | Phase 1/2 已落 |
| arq | 0.28+ | 异步任务队列 | Phase 1 worker.py 已落 |
| tenacity | (随 arq) | 重试（指数退避） | Phase 2 已落 BaseNodeExecutor |
| jsonschema | 4.x | form_schema 校验（拉新依赖） | 本 phase 需新增 |

### 2.2 前端 form 渲染选型（CONTEXT §Claude's Discretion 留待选型）

| 方案 | 优点 | 缺点 | 决策 |
|---|---|---|---|
| **RJSF**（react-jsonschema-form 5.x） | 直接吃 JSON Schema、内置 UI Schema 控件 | bundle 90KB+；定制 Tailwind 主题需要 widget overrides | **采用** — v1 字段类型简单（text/number/select/textarea），RJSF 直接 generate 表单 |
| react-hook-form + zod | 灵活度最高、bundle 小 | 需要为每个 schema 手写 zod 解析，违背"配置即表单"理念 | 备选 |
| 自研 | 完全可控 | 维护成本高，v1 无必要 | 不采用 |

**决策**：用 **@rjsf/core 5.x + @rjsf/validator-ajv8 + @rjsf/utils**（已是社区主流）；UI 风格用 `@rjsf/core` 默认 widgets + Tailwind 重写（覆盖 label / input border 类）。

### 2.3 后端 form_schema 校验

用 **jsonschema 4.x** Python 库做 server-side double-check：用户 submit form_data 时验一遍（防前端绕过）；返回 422 + errors 数组。

---

## 三、Dify 参考实现盘点（CLAUDE.md 2.7 Reading-First）

**Dify HITL 模块文件清单**（已 ls 验证 `/Users/admin/ai/ref/dify/repo/api`）：

| 模块 | Dify 文件路径 | 借鉴点 |
|---|---|---|
| HITL 数据模型 | `api/models/human_input.py`（HumanInputForm + HumanInputDelivery + HumanInputFormRecipient） | 表单 / 投递 / 收件人三表分离；状态机字段命名；token 生成函数 `generate_string(_token_length)` |
| HITL 服务层 | `api/services/human_input_service.py` | 表单创建 / 投递 / 提交流程 |
| HITL Workflow 适配器 | `api/core/workflow/human_input_adapter.py` | EmailDeliveryConfig + EmailRecipients + Bound/External Recipient 三态 |
| HITL Form 类型 | `api/core/workflow/human_input_forms.py` | form_schema 字段类型定义 |
| HITL 策略 | `api/core/workflow/human_input_policy.py` | timeout + escalation 策略类 |
| Email Delivery | `api/tasks/mail_human_input_delivery_task.py` | Celery shared_task；`_build_form_link(token)`；`_load_email_jobs`；递归处理 recipients |
| HITL Controller | `api/controllers/web/human_input_form.py` | GET / POST 表单端点；token 验证 |
| HITL Common | `api/controllers/common/human_input.py` | 公共校验逻辑（签名 / exp） |
| HITL Repository | `api/core/repositories/human_input_repository.py` | DB 访问层 |
| Timeout Task | `api/tasks/human_input_timeout_tasks.py` | 超时扫描 worker |
| Email Renderer | `api/libs/email_template_renderer.py` + `api/libs/email_i18n.py` | Jinja 模板 + i18n 注入 |

### 3.1 Dify 设计模式（可借鉴 / 不可照抄 AGPL → 重写）

1. **三层数据模型**（Form / Delivery / Recipient）：表单元数据 + 通道投递 + 收件人。我们简化为两层（hitl_tokens 一表统管 jti+actor+action，notifications 表统管投递）
2. **token 生成**：Dify 用 `generate_string(22)` 字符串；我们用 PyJWT HS256（含 payload）
3. **Email Job 数据类**：`@dataclass(frozen=True) _EmailDeliveryJob` 把 form_id / subject / body / recipients 打包；arq job 借鉴
4. **expiration_time 索引**：`Index("...status_expiration_time_idx")` 加速超时扫描
5. **submission 字段命名**：`submitted_data / submitted_at / submission_user_id` 三字段；我们直接合并到 hitl_tokens.used_*
6. **build_form_link(token)**：`f"{base_url.rstrip('/')}/form/{token}"`；我们对应 `f"{PUBLIC_BASE_URL}/hitl/page/{token}"`

### 3.2 hr/offboarding-flow 参考（PRD 同源）

- `hr/PRD.md §7 双通道通知 + §8 LangGraph interrupt + Postgres saver` 与本 phase 设计同源
- 已实现的 email + Mattermost notification 路径 → 借鉴 message 格式

---

## 四、关键技术决策（基于 PITFALLS）

### 4.1 Pitfall 2 防护：interrupt/resume 并发竞争

- **应用层 advisory lock**：`POST /hitl/action/<token>` handler 用 `await session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": hash(thread_id) & 0x7FFFFFFFFFFFFFFF})` + 事务包裹
- **jti 消费原子性**：`UPDATE hitl_tokens SET used_at=NOW(), used_ip=:ip, used_ua=:ua WHERE jti=:jti AND used_at IS NULL RETURNING *` → 零行返回则 409
- **同节点其他 token 同时失效**：`UPDATE hitl_tokens SET used_at=NOW() WHERE node_state_id=:nsid AND used_at IS NULL AND jti != :consumed_jti`
- **Redis 一并失效**：pipeline DEL 同 node_state_id 下所有 jti key

### 4.2 Pitfall 3 防护：邮件 Safe Links

- **GET 不消费 jti**（CLAUDE.md 2.5 永不可接受 GET 消费）：
  ```python
  # /hitl/page/<token>
  payload = jwt.decode(token)  # 仅校签 + exp
  if is_bot_ua(request.headers.get("User-Agent", "")):
      return static_html("您看到的是邮件扫描，未触发任何状态变更")
  # 真实用户：签 30min session cookie + 渲染表单
  ```

- **集成测试模拟 Bot UA**：
  ```
  Outlook Safe Links: Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; +safelinks.protection.outlook.com)
  Microsoft Defender: Mozilla/5.0 (compatible; MicrosoftDefender/...)
  Slackbot: Slackbot-LinkExpanding 1.0
  ```

### 4.3 Pitfall 4 防护：HMAC 密钥

- Phase 1 已落：startup_checks `HMAC_SECRET >= 32`
- Phase 3 新增：日志脱敏（token 字段自动 mask 中间）

---

## 五、Plan 拆分建议（10 plans / 6 waves，已压缩）

```
Wave 1: 03-01 DB schema (hitl_tokens + notifications + audit_log 加固) + Alembic 0003
Wave 2: 03-02 HITL node executor (interrupt + resume integration)
        03-03 HITL Token Service (JWT + Safe Links bot detector)
        [并行：03-02 用 nodes/hitl.py + 03-03 用 services/hitl_token_service.py]
Wave 3: 03-04 Email enhanced (arq queue + Jinja2 HITL templates + NOTI-10 重试)
        [独立 — 创建 notification_service.py 主干，03-05 在 W4 再加 enqueue_generic_email]
Wave 4: 03-05 Notification node executor (NODE-07 独立通知节点)
        03-06 HITL public API (/hitl/page + /hitl/action + cookie session + advisory lock)
        [并行：03-05 改 nodes/__init__.py + notification_service.py 新方法；03-06 用 api/hitl.py + services/hitl_action_service.py 全部新建]
Wave 5: 03-07 决策页前端 (form_schema RJSF render + 3 button)
        03-08 申请人追踪页前端 (HITL-07)
        03-09 超时催办 worker (arq + NOTI-09 escalation)
        [并行：03-07/08 全部 web/* 文件，03-09 全部 backend/jobs + services/escalation_service.py 新建文件]
Wave 6: 03-10 E2E gate (ROADMAP Phase 3 全 5 条 + Safe Links bot regression)
```

依赖图：
- 03-01 → 03-02, 03-03, 03-04, 03-05, 03-06, 03-09
- 03-02 → 03-06, 03-10
- 03-03 → 03-06
- 03-04 → 03-06（邮件实发） + 03-09（催办用同模板）
- 03-05 → 03-10
- 03-06 → 03-07
- 03-07 → 03-10
- 03-08 → 03-10
- 03-09 → 03-10

---

## 六、CLAUDE.md 2.7 Reading-First — Dify 模块映射（每 plan Task 0）

| Plan | Dify 后端必读（≥1） | Dify 前端必读（≥1，仅前端 plan） | Reading doc 命名 |
|---|---|---|---|
| 03-01 | `api/models/human_input.py` | — | `docs/reading-dify-03-01-hitl-schema-2026-05-17.md` |
| 03-02 | `api/core/workflow/human_input_adapter.py` + `api/core/workflow/human_input_policy.py` | — | `docs/reading-dify-03-02-hitl-executor-2026-05-17.md` |
| 03-03 | `api/controllers/common/human_input.py` | — | `docs/reading-dify-03-03-hitl-token-2026-05-17.md` |
| 03-04 | `api/tasks/mail_human_input_delivery_task.py` + `api/libs/email_template_renderer.py` | — | `docs/reading-dify-03-04-email-delivery-2026-05-17.md` |
| 03-05 | `api/core/workflow/nodes/` 中 notification 类节点（如 end_user_input） | — | `docs/reading-dify-03-05-notification-node-2026-05-17.md` |
| 03-06 | `api/controllers/web/human_input_form.py` + `api/services/human_input_service.py` | — | `docs/reading-dify-03-06-hitl-api-2026-05-17.md` |
| 03-07 | `api/core/workflow/human_input_forms.py` | `web/app/components/workflow/nodes/human-input/` | `docs/reading-dify-03-07-decision-page-2026-05-17.md` |
| 03-08 | `api/controllers/console/app/workflow_run.py`（实例详情） | `web/app/components/app/workflow-log/` | `docs/reading-dify-03-08-tracking-page-2026-05-17.md` |
| 03-09 | `api/tasks/human_input_timeout_tasks.py` | — | `docs/reading-dify-03-09-timeout-worker-2026-05-17.md` |
| 03-10 | — (E2E gate，引用前述 reading docs) | — | `docs/reading-dify-03-10-e2e-2026-05-17.md` (引用清单 + 测试模式总结) |

**强制**：每 plan Task 0 是 reading doc 写就 + commit；后续代码 commit 必须在 reading doc commit 之后（CLAUDE.md 2.7 GATE）。

**hr/offboarding-flow 参考**：每个 plan 顺带读 `hr/PRD.md` 对应章节作为业务对照（在 reading doc 中加 §与 hr 项目对照 小节，5-10 行即可）。

---

## 七、测试架构（CLAUDE.md 2.2 三层）

每 plan 必须包含：
1. **单元测试**（pytest）：纯函数 / 类方法 / Jinja 渲染 / 装饰器
2. **集成测试**（pytest + httpx.AsyncClient + 真实 DB）：API endpoint + DB transaction + Redis
3. **E2E**（Phase 3 终结于 03-10）：5 Playwright spec 覆盖 ROADMAP Phase 3 全 5 条 + Safe Links bot regression

**测试隔离**：
- Phase 1/2 conftest 已就绪（pytest-postgresql + Redis testcontainers）
- 邮件用 mailhog (docker-compose 已配)
- arq job 测试用 in-memory enqueue（直接 await job 函数）

---

## 八、Validation Architecture（Nyquist 触发）

**Goal-Backward Verification 链**：

```
ROADMAP Phase 3 success criteria (5 条)
  ↓
Plan must_haves.truths 覆盖
  ↓
Plan tasks 实现 + 单元/集成测试
  ↓
03-10 E2E spec 端到端验证
  ↓
Verifier 闭环
```

5 个 ROADMAP success criteria 对应 5 个 E2E spec：

| ROADMAP # | 表述 | 03-10 E2E spec |
|---|---|---|
| 1 | 审批人收到 4 按钮邮件 | `e2e/hitl_email_delivery.spec.ts` |
| 2 | 点击链接无需登录可决策推进 | `e2e/hitl_token_login.spec.ts` |
| 3 | Safe Links GET 不消费 jti | `e2e/hitl_safe_links_bot.spec.ts` |
| 4 | 同 token 重提交 409 + 同节点其他 token 失效 | `e2e/hitl_token_invalidation.spec.ts` |
| 5 | 申请人追踪页可见 | `e2e/hitl_tracking_page.spec.ts` |

每 spec 头注释 `// ROADMAP Phase 3 #N: <criterion>`。

---

## RESEARCH COMPLETE

10 plans 拆分清晰、6 waves 依赖图无环、Dify reading doc 映射 1:1、3 层测试模式与 Phase 1/2 对齐、Pitfall 2/3/4 P0 防护到位。
