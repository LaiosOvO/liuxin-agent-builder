# Dify 阅读笔记 — HITL 公网 API (controllers/web/human_input_form.py + services/human_input_service.py)

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k

---

## 1. 项目概述（一句话）

Dify 用 Flask-RESTX 把 HITL 表单暴露为 `GET / POST /api/form/human_input/<form_token>` 双端点；token 是一次性使用的短字符串（生成于 Recipient 表），DB 反查取得 Form + Definition + Recipient 三表关联状态后渲染或提交，决策提交后通过 Celery `apply_async` 触发 `resume_app_execution` 推进 LangGraph workflow_run。

---

## 2. 技术栈

| 维度 | Dify | agent-builder 03-06 落地 |
|---|---|---|
| Web 框架 | Flask + Flask-RESTX `@web_ns.route` | FastAPI + APIRouter `@router.get/post` |
| Token 实现 | 短字符串 `generate_string(22)` + DB 反查 | JWT (HS256 + jti UUID) 自携 payload，DB 仅查 jti 一次性消费表 |
| Auth 模式 | 显式 `unauthenticated on purpose` 注释（基于 token 即认证）| Token-as-login + 30min HMAC session cookie（双重凭证） |
| Rate Limit | `RateLimiter(prefix=..., max_attempts=...)` 自研 | slowapi `@limiter.limit("60/minute")` |
| Bot 防护 | **无**（短 token 多次 GET 无副作用，不需要 bot 检测）| `is_bot_ua(ua)` 短路 — JWT + jti 一次性消费需要 bot 防护（Pitfall 3） |
| Resume Workflow | Celery `apply_async(resume_app_execution)` | LangGraph `graph.ainvoke(Command(resume=...))` 直接同步触发 |
| 并发控制 | DB `mark_submitted` 假设单一 worker（无显式 advisory_lock）| `pg_advisory_xact_lock(hash(thread_id))` + jti `UPDATE WHERE used_at IS NULL RETURNING` 双保险 |
| 异常状态 | 412 Submitted / 412 Expired / 404 NotFound / 400 InvalidForm | 401 InvalidSignature / 410 Expired / 409 JtiConsumed / 422 FormDataInvalid |
| Form Validation | `validate_human_input_submission(definition, ...)` 业务对象级 | `jsonschema.Draft7Validator(schema).validate(data)` schema 驱动 |

---

## 3. 架构要点

```
Dify 流程（GET）：
  GET /api/form/human_input/<token>
    → RateLimiter.is_rate_limited(ip)
    → HumanInputService.get_form_by_token(token)
    → service.ensure_form_active(form)
      ├─ form.submitted? raise FormSubmittedError(412)
      ├─ form.status in {TIMEOUT, EXPIRED}? raise FormExpiredError(412)
      ├─ form.expiration_time <= now? raise FormExpiredError(412)
      └─ _is_globally_expired(form, now)? raise FormExpiredError(412)
    → _get_app_site_from_form(form)  # 应用 + 站点元数据
    → _jsonify_form_definition(form, site)  # 返回 JSON 表单定义

Dify 流程（POST）：
  POST /api/form/human_input/<token>
    → HumanInputFormSubmitPayload.model_validate(body)
    → RateLimiter.is_rate_limited(ip) (submit 限频)
    → service.get_form_by_token(token)
    → service.submit_form_by_token(...)
      ├─ ensure_form_active(form)  # 同 GET
      ├─ _validate_submission(form, action_id, form_data)  # 422 if invalid
      ├─ form_repository.mark_submitted(...)  # 原子标记
      └─ if RUNTIME + workflow_run_id: enqueue_resume(run_id)
    → return {}, 200

我们的流程（GET）：
  GET /hitl/page/<token>
    → @limiter.limit("60/minute")
    → ua = headers["User-Agent"]
    → if is_bot_ua(ua): return bot_scan.html (200, 不签 cookie, 不动 jti)  ← Pitfall 3 防护
    → HitlTokenService.decode(token)
      ├─ TokenExpired → 410 + error.html
      ├─ InvalidSignature/Audience → 401 + error.html
    → store.is_consumed(jti)?  # 仅查不写
      └─ True → 410 + error.html "决策已提交"
    → 加载 node_state + flow_instance
    → 签 30min HMAC session cookie: hitl_session_<jti>=<jti>:<HMAC(jti)>
    → 返回 page.html + Set-Cookie

我们的流程（POST）：
  POST /hitl/action/<token>
    → @limiter.limit("10/minute")
    → HitlTokenService.decode(token)
    → verify cookie hitl_session_<jti> 与 jti 一致 + HMAC sig 匹配
      └─ 失败 → 401 + error.html
    → HitlActionService.submit_action(...)
      ├─ load flow_instance → build thread_id
      ├─ pg_advisory_xact_lock(hash(thread_id))  ← Pitfall 2 防护
      ├─ form_data validate (jsonschema Draft-7) → 422 if invalid
      ├─ HitlTokenStore.consume(jti, ip, ua) → JtiAlreadyConsumed if None
      ├─ HitlTokenStore.invalidate_siblings(node_state_id, except_jti)
      ├─ update node_state.payload (append record + new status)
      ├─ graph.ainvoke(Command(resume=...), config={"thread_id": thread_id})
      └─ AuditLog(action='hitl.decision', actor_ip, actor_ua, decision, node_state_id)
    → 返回 success.html (200)
```

---

## 4. 可借鉴的设计模式

### 4.1 GET / POST 分离 + 同一 service 入口

Dify `/api/form/human_input/<token>` 的 Resource 类同时挂 `get` 和 `post`，两个端点共享 `HumanInputService.get_form_by_token`，再分别走 `ensure_form_active`（仅校验）和 `submit_form_by_token`（带状态修改）。这种"GET 只读 / POST 才修改"的关注点分离，正是我们 CLAUDE.md 2.5 "GET 不消费 jti / POST 才消费 jti" 的合理化前置基础。

**我们的对应**：
- `api/hitl.py` 同一 `router = APIRouter(prefix="/hitl")` 挂 2 个端点
- 服务层 `HitlTokenService.decode`（无副作用）→ GET / POST 通用
- 服务层 `HitlActionService.submit_action`（有副作用）→ POST 专属

### 4.2 ensure_form_active 状态机校验集中化

Dify `ensure_form_active(form)` 把 5 种异常情况（submitted / TIMEOUT / EXPIRED status / expiration_time / global_timeout）集中到一处，POST 和 GET 都调用，避免散落各处的判断遗漏。

**我们的对应**：
- GET 路径：`HitlTokenService.decode` + `store.is_consumed(jti)`（两步分别判 token 自身过期 vs 已消费）
- POST 路径：`HitlActionService.submit_action` 内部完成 advisory_lock + jti 消费 + sibling invalidate + node_state update + audit + resume 一系列原子操作

### 4.3 RateLimiter 双前缀 (access + submit)

Dify 把 form 访问 (GET) 和提交 (POST) 分两个独立的 RateLimiter（`_FORM_ACCESS_RATE_LIMITER` 50/min / `_FORM_SUBMIT_RATE_LIMITER` 50/min）。这避免一个 token 频繁 GET 影响真正提交。

**我们的对应**：用 slowapi key_func 区分：
- GET `/hitl/page/<token>`: `@limiter.limit("60/minute")` （按 IP 默认 + path 维度 token）
- POST `/hitl/action/<token>`: `@limiter.limit("10/minute")` （更严格防 POST 暴力）

### 4.4 Resume 解耦 — 服务层 enqueue 而非直接 invoke

Dify `enqueue_resume` 通过 Celery `apply_async` 把 LangGraph resume 解耦到 worker；HTTP 端口返回立即响应，不阻塞用户。但代价是 resume 失败用户不可见。

**我们的取舍**：直接在 POST handler 内同步 `await graph.ainvoke(Command(resume=...))`。理由：
- LangGraph 1.2 interrupt resume 本身是异步 + 非阻塞（DB 已写完整 state，可恢复执行直接返回）
- 同步执行可立即拿到 resume 是否成功，便于 UX 错误页友好渲染
- v1 单人审批流程不会卡在 resume 期间太久（典型 LLM 节点也 <5s）
- 后续 phase 实例间高并发时可改 enqueue（保留扩展位）

### 4.5 _validate_submission 抽出 service 层

Dify 把 form 校验逻辑放在 `_validate_submission` 私有方法里，controller 只调 `submit_form_by_token` 单一入口。这让 controller 极薄、易测。

**我们的对应**：`api/hitl.py` 仅做 cookie 解析 / 异常翻译 / 模板渲染；所有业务逻辑（form_schema 校验 / advisory_lock / jti consume / sibling invalidate / node_state update / graph resume / audit log）在 `HitlActionService.submit_action` 一处。Controller ~120 行，Service ~150 行。

### 4.6 InvalidFormDataError + FormSubmittedError 异常细分

Dify 4 个细分异常：`FormSubmittedError(412)` / `FormNotFoundError(404)` / `FormExpiredError(412)` / `InvalidFormDataError(400)`。controller 层根据异常返回不同 HTTP 状态。

**我们的对应**（覆盖 HTTP 4xx 全谱）：
- `InvalidSignature` → 401
- `TokenExpired` → 410
- `JtiAlreadyConsumed` → 409
- `FormDataValidationError` → 422 + 重新渲染 page.html 含 errors
- 通用 HitlTokenError → 400

---

## 5. 与本项目的关系（如何应用到 03-06 plan）

### 5.1 直接对应（按 Dify 模式实现）

| Dify | agent-builder | 文件 |
|---|---|---|
| `class HumanInputService` | `class HitlActionService` | backend/app/agent_builder/services/hitl_action_service.py |
| `get_form_by_token` | `HitlTokenService.decode` (Phase 3-03 已落) | backend/app/services/hitl_token_service.py |
| `submit_form_by_token` | `HitlActionService.submit_action` | (本 plan 新建) |
| `_validate_submission` | `validate_form_data` (Phase 3-02 已落) | backend/app/agent_builder/workflow/hitl_payload.py |
| `enqueue_resume` | `graph.ainvoke(Command(resume=...))` (同步) | (本 plan 新建) |
| `RateLimiter` 双前缀 | slowapi `@limiter.limit()` GET/POST 分别 | backend/app/agent_builder/api/hitl.py |

### 5.2 反向取舍（不照搬 Dify）

1. **JWT vs 短 token**：我们 JWT 自携 payload 让 GET 路径**无需 DB 查询**就能拿到 node_state_id / flow_id / actor_id，避免 bot 频繁 GET 打满 DB。Dify 短 token 每次 GET 必查 DB 反查 form，碰到 Outlook Safe Links 类扫描器会 DB 风暴。
2. **Bot UA 检测**：我们必须做（Pitfall 3 P0）。Dify 短 token GET 多次无副作用所以不需要。**这是本 plan 与 Dify 最大差异点之一。**
3. **同步 resume vs 异步 enqueue**：见 §4.4。
4. **三表 ORM (Form/Delivery/Recipient) → 单表 hitl_tokens**：v1 简化（已在 03-01 实现）。

### 5.3 Token-as-login Cookie 设计（Dify 完全没有，独立创新）

**契约**：
- GET 通过 bot 检测后，签 `hitl_session_<jti>` cookie，value 是 `<jti>:<HMAC-SHA256(jti, HMAC_SECRET)>`
- POST 必须携带该 cookie + 用 hmac.compare_digest 校验 HMAC sig
- 防御**钓鱼场景**：攻击者拿到 token 但不能直接 POST（需先访问 GET 获得 cookie），bot UA 路径不发 cookie 即阻断 bot 直接 POST 路径
- 30min 过期 — 用户必须在 30 分钟内决策
- `httpOnly + secure + SameSite=Lax` 防 XSS / CSRF

---

## 6. 与 hr 项目对照

hr/offboarding-flow 实现使用 Mattermost bot **双向**通道 + email 通道。HITL 决策走 hr/webhooks/mattermost_callback.py（接收 Mattermost 卡片点击）+ hr/webhooks/email_callback.py（GET / POST 邮件深链）。

hr 实现细节（对我们的启发）：
- Email callback 走 Flask + token 自携 (HS256)，符合本 plan JWT 路线
- 没有 advisory_lock — 这是 hr 单租户单 worker 部署的取巧；我们多租户多 worker 必须加 PG advisory_lock 防 Pitfall 2
- hr/PRD.md §7.3 提到 "GET 不消费 jti" 设计契约 — 与本 plan 完全对齐

---

## 7. advisory_lock + jti 原子消费的并发安全模型

### 7.1 三层并发防护

```
Layer 1: HTTP slowapi rate limit
  └─ 限制单个 IP / token 的 POST 频次（10/min）
     防止暴力同 jti 多次并发提交

Layer 2: PG advisory_xact_lock (key = hash(thread_id) & 2^63-1)
  └─ 保证同一 LangGraph thread 内两个并发 POST 串行处理
     防止 LangGraph checkpoint 内部状态机被并发 resume 撕裂（Pitfall 2 P0）
     事务提交后自动释放（不需要 finally unlock）

Layer 3: PG row lock via UPDATE...WHERE used_at IS NULL RETURNING
  └─ jti 一次性消费的最后一道防线
     即使 Layer 1+2 被绕过，PG 行锁保证 RETURNING 仅 1 行成功
     落败 POST 拿到 None → 抛 JtiAlreadyConsumed → 409
```

### 7.2 advisory_lock 关键点

```python
# build_thread_id 输出 "{workspace_id}:{instance_id}"
lock_key = hash(thread_id) & 0x7FFFFFFFFFFFFFFF  # 64-bit signed positive
await self.db.execute(
    text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key}
)
# 后续 jti consume + node_state update + audit log 都在锁内
# 事务 COMMIT 后 PG 自动 ROLLBACK lock（_xact_ 后缀含义）
```

**为什么是 advisory_xact_lock 而不是 advisory_lock**：
- `pg_advisory_lock` 是会话级锁，需要显式 `pg_advisory_unlock` 释放；忘记 unlock 会泄漏
- `pg_advisory_xact_lock` 是事务级锁，事务提交/回滚时自动释放；天然 RAII

**为什么用 hash(thread_id) 而不是 thread_id 字符串**：
- PG advisory lock 接收 int8 (64-bit) 或 (int4, int4) 元组作为锁 key
- thread_id 是字符串需要先 hash 到 int8
- 用 Python hash() 在单进程内一致；跨进程时 PYTHONHASHSEED 可能不同，这是已知 caveat
- v1 单实例不受影响；多实例时考虑改用 PG 内置 hash 函数（`hashtext(thread_id)`）

### 7.3 双重消费保护示意

```
两个并发请求拿同一 jti：

Request A                    Request B
───────────────             ───────────────
BEGIN TRAN                   BEGIN TRAN
advisory_xact_lock(k=42)     advisory_xact_lock(k=42)  [waits]
SELECT node_state            (waits)
UPDATE hitl_tokens
  SET used_at=now()          (waits)
  WHERE jti=X
  AND used_at IS NULL
  RETURNING *                (waits)
  → returns 1 row            (waits)
COMMIT  ← lock released      (still waits)
                             ← gets lock
                             UPDATE hitl_tokens ...
                              WHERE used_at IS NULL
                              → returns 0 rows (because A set it)
                             COMMIT
                             ↑ B: JtiAlreadyConsumed
                                → HTTP 409
```

### 7.4 同节点 sibling 失效保证

```sql
-- 在 advisory_lock 持有期间执行（A 的事务内）：
UPDATE hitl_tokens
   SET used_at=now(),
       used_ip='system:sibling-invalidate'
 WHERE node_state_id=:nsid
   AND jti != :consumed_jti
   AND used_at IS NULL
RETURNING jti;
-- 同节点 2 个 sibling token (return / reject) 一并失效
-- 防止用户先点 submit 再追点 return 触发 LangGraph 二次 resume

-- 同时 Redis pipeline 写 consumed 标志（加速 is_consumed 查询）
```

### 7.5 LangGraph Command(resume) 调用约束

```python
await graph.ainvoke(
    Command(resume={
        "action": action,           # ← HITLNodeExecutor 期望的字段
        "reason": reason,
        "form_data": form_data,
        "actor_id": str(actor_id),
        "ip": ip,
        "ua": ua,
        "jti": str(jti),
    }),
    config={"configurable": {"thread_id": thread_id}},
)
```

**关键点**：
- `thread_id` 必须与节点 interrupt 时的 thread_id 完全一致；否则 LangGraph 找不到 checkpoint
- `Command(resume=...)` 的 value 必须是 dict（HITLNodeExecutor `__call__` 内已校验）
- ainvoke 会跑到下一个 interrupt 或工作流结束；中间节点失败抛 NodeExecutionError 由我们捕获写 audit
- 此调用必须在 advisory_lock 内执行；若放锁外 → Pitfall 2 仍会触发（其他 worker 可能同时 ainvoke）

### 7.6 audit_log 字段映射（NET-05）

| audit_log 列 | 来源 | 用途 |
|---|---|---|
| action | hardcoded "hitl.decision" | 决策事件类型 |
| workspace_id | flow_instance.workspace_id | 多租户隔离查询 |
| actor_user_id | payload.actor_id (从 JWT 解码) | 哪个用户做的决策 |
| target_type | hardcoded "node_state" | 决策目标对象类型 |
| target_id | node_state_id | 决策目标对象 ID（也可冗余到 node_state_id 列） |
| actor_ip | request.client.host | NET-05 决策 IP |
| actor_ua | request.headers["User-Agent"] | NET-05 决策 UA |
| decision | action ("submit"/"approve"/...) | NET-05 决策动作 |
| node_state_id | node_state_id | 关联到节点 |
| meta | {jti, instance_id, reason} | 完整上下文 |

---

## 8. CLAUDE.md 2.7 Attribution

未拷贝 Dify 源码（AGPL-3.0 → Apache-2.0 不兼容）。本笔记借鉴的设计模式：
1. GET / POST 分离 + service 层集中校验（§4.1, §4.2）
2. RateLimiter 双前缀（§4.3）
3. 异常细分体系（§4.6）
4. controller 层薄 + service 层厚（§4.5）

我们的独立创新（与 Dify 不同）：
1. Bot UA 检测 + bot_scan.html 静态返回（Pitfall 3 P0）
2. JWT + jti 自携 vs 短 token DB 反查
3. Token-as-login HMAC cookie（30min session）
4. 三层并发防护（slowapi + advisory_xact_lock + UPDATE RETURNING）
5. 同步 graph.ainvoke(Command(resume)) vs 异步 enqueue
6. NET-05 决策审计字段（actor_ip / actor_ua / decision / node_state_id）

---

*Phase: 03-hitl-email Plan: 06*
*Reading completed: 2026-05-17*
