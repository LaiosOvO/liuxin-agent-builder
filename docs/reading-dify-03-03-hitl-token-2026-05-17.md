# Dify 阅读笔记 — HITL Token JWT 签发与解码（PassportService + Form Controller）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit `e7e6fe88`, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> 本 plan: agent-builder 03-03（HitlTokenService + bot_detector）
> 上游许可: AGPL-3.0（**仅参考设计模式，禁止照抄代码**）

## 项目概述

Dify 的 HITL Form 控制层（`api/controllers/common/human_input.py` + `api/controllers/web/human_input_form.py`）走"短 token 字符串 + DB 反查 Form 元数据"的路线（`access_token VARCHAR(32) UNIQUE`，由 `generate_string(22)` 生成 22 字符 base62 ≈ 130 bit 熵），**并不携带任何业务 payload**。与之并列的是 `api/libs/passport.py` 的 `PassportService` — Dify 的通用 JWT 工具（HS256 签发 / 解码），主要用于 console 登录 / CSRF token / WebApp passport，**未用在 HITL 路径**。

我们 03-03 plan 走的是另一条路线：**HITL token 直接是 JWT，payload 自带 jti + flow_id + node_state_id + actor_id + allowed_actions**，DB 仅作 jti 一次性消费表（03-01 已建 `hitl_tokens`）。本阅读笔记的价值在于：（1）对比两条路线的取舍；（2）抽取 PassportService 的 JWT 风格作为 HitlTokenService 的设计骨架。

## 技术栈（HITL Token 相关）

- **JWT 库**：Dify 用 `pyjwt`（同 PyJWT）— `api/libs/passport.py` 直接 `import jwt`，调用 `jwt.encode/decode(... algorithm="HS256")`。与我们 Phase 1 jwt_service.py 一致（PyJWT 2.12.1，STACK.md 锁定）
- **密钥来源**：Dify 用 `dify_config.SECRET_KEY`（单一密钥服全部 JWT 用途，aud 不区分）
- **异常映射**：Dify 把 `ExpiredSignatureError / InvalidSignatureError / DecodeError / PyJWTError` 全部映射为 `werkzeug.exceptions.Unauthorized` —— 框架级 401。我们走 service-level 异常细分（InvalidSignature / TokenExpired / InvalidAudience）让 FastAPI 路由处理器自行决定 HTTP 状态码
- **短 token 路线（Dify Form）**：`access_token` 字符串 VARCHAR(32) UNIQUE，DB SELECT 反查；优点：token 字符串短适合放 URL；缺点：每次校验需 DB roundtrip
- **JWT 路线（本项目）**：jti + flow_id + node_state_id + actor_id + allowed_actions 全部塞 payload；优点：bot UA 检测 + 签名校验完全无 DB；缺点：token 字符串长（~300 char）

## 架构要点

```
┌──────────────────────────────────────────────────────────────────────┐
│                Dify HITL Form 控制层 (AGPL)                          │
│  POST /api/form/human_input/<form_token>                             │
│    1. _FORM_SUBMIT_RATE_LIMITER.is_rate_limited(ip)                  │
│    2. service.get_form_by_token(form_token)  ← DB SELECT             │
│    3. service.submit_form_by_token(...)                              │
│  GET /api/form/human_input/<form_token>                              │
│    1. _FORM_ACCESS_RATE_LIMITER.is_rate_limited(ip)                  │
│    2. service.get_form_by_token(form_token)  ← DB SELECT             │
│    3. service.ensure_form_active(form)                               │
│    4. 返回 form 定义 + recipient                                     │
│                                                                      │
│  ⚠️ token 字符串本身无 payload，DB 反查决定一切                       │
│  ⚠️ 控制层未做 bot UA 检测，依赖 ensure_form_active 状态机           │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                Dify PassportService (libs/passport.py, AGPL)         │
│  issue(payload) → jwt.encode(payload, sk, algorithm="HS256")         │
│  verify(token)  → jwt.decode(token, sk, algorithms=["HS256"])        │
│  ⚠️ payload 自由（无 aud / iss / require 校验）                     │
│  ⚠️ 异常全映射 Unauthorized（无细分类型）                            │
└──────────────────────────────────────────────────────────────────────┘
```

```
┌──────────────────────────────────────────────────────────────────────┐
│            本项目 HitlTokenService (Apache-2.0)                      │
│  sign(*, jti, instance_id, node_state_id, actor_id, action,         │
│        role, expires_at) → JWT HS256                                 │
│   payload: {iss="agent_builder", aud="hitl", iat, exp, jti,         │
│             flow_id, node_state_id, actor_id, role,                 │
│             allowed_actions: [action]}                              │
│  decode(token) → dict（校签 + exp + aud + iss + require）           │
│   异常: InvalidSignature / TokenExpired / InvalidAudience           │
│  ✅ aud="hitl" 严格区分 Phase 1 session/email-verify/invite token   │
│  ✅ 不消费 jti（消费在 HitlTokenStore.consume，由 03-06 调用）       │
└──────────────────────────────────────────────────────────────────────┘
```

## 可借鉴的设计模式

### 1. PassportService 的 JWT 调用骨架（`api/libs/passport.py:7-25`）

Dify 模式（简化 5 行）：
```python
def issue(self, payload):
    return jwt.encode(payload, self.sk, algorithm="HS256")

def verify(self, token):
    try:
        return jwt.decode(token, self.sk, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Token has expired.")
    ...
```

**借鉴点**：encode/decode 三参数固定 + try/except 按异常类型映射。我们的 HitlTokenService.sign / decode 走同形态，但：
- 强制要求 `audience=` + `issuer=` 参数 + `options={"require": [...]}`（Dify 没用）
- 异常细分为业务级（InvalidSignature / TokenExpired / InvalidAudience），不依赖 HTTP 框架的 Unauthorized
- 引用 Phase 1 `jwt_service._get_jwt_secret()`，不重读 env

### 2. 异常分级处理（Dify 反例 → 改进）

Dify `PassportService.verify` 把全部 PyJWT 异常映射为单一 `Unauthorized` — 调用方无法区分"签名错误"和"过期"，难以做差异化 UX（如过期可重发邮件 / 签名错通常意味着 token 篡改）。

**我们的做法**：service 层抛细分异常 → API 层（03-06 plan）按异常类型决定渲染哪种错误页：
| 业务异常 | 用户友好提示 |
|---|---|
| `TokenExpired` | "链接已过期，请联系管理员重发邮件" |
| `InvalidAudience` | "无效链接（请确认从 agent-builder 邮件复制）" |
| `InvalidSignature` | "无效链接，请勿手动修改邮件链接" |
| `HitlTokenError`（兜底） | "链接格式错误" |

### 3. require 选项 + audience 校验（PyJWT 2.x 内置）

我们的 HitlTokenService.decode 使用 PyJWT `options={"require": ["jti", "exp", "iat", "aud", "iss"]}` —— 缺任一字段直接抛 `MissingRequiredClaimError`（→ 兜底 `HitlTokenError`）。`audience="hitl"` 不匹配自动抛 `InvalidAudienceError`。
这两者 Dify 都没用 — 它依赖业务代码"看到 token 才查 DB"，相对脆弱。

### 4. 不在 HITL 路径上耦合 bot UA 检测

Dify HITL Form Controller（`controllers/web/human_input_form.py:64-138`）的 GET 处理完全没 bot UA 检测 —— 因为它的 token 短字符串本身**不会**被消费（消费动作只发生在 POST submit），所以无所谓 GET 多少次。

**我们的不同**：jti 一次性消费的语义在 DB 层（03-01 `hitl_tokens.used_at`），与 token 自带 payload 设计组合，**必须**在 GET 路径加 bot UA 短路 —— 否则 Outlook Safe Links 等 bot 大量 GET 会触发 session cookie 签发 + 错误 metric 计数。03-03 plan 的 `bot_detector.is_bot_ua` 就是这个短路守门员。CONTEXT.md §Safe Links bot UA 列出 13 + 1 个 pattern（含 Outlook 真实 UA `ac-detector-tool`）。

### 5. Rate limiter on token endpoint（Dify 借鉴）

Dify HITL Form 控制层用 `_FORM_SUBMIT_RATE_LIMITER` + `_FORM_ACCESS_RATE_LIMITER`（独立两个 limiter，按 IP 限流）。

**我们的对应**：Phase 1 已有 slowapi（`backend/app/agent_builder/security/rate_limit.py`），03-06 plan 时把 `/hitl/page/*` 和 `/hitl/action/*` 限流参数化（建议 GET 60/min，POST 10/min；bot UA 命中直接 short-circuit 不计 quota）。本 plan（03-03）暂不涉及。

## 与本项目的关系

本 plan（03-03）写两个文件：
1. `backend/app/services/hitl_token_service.py` — 借鉴 PassportService 的 5 行 encode/decode 骨架；额外补 audience/issuer/require 校验 + 异常细分。**复用** Phase 1 `_get_jwt_secret()`。
2. `backend/app/agent_builder/security/bot_detector.py` — 与 Dify 无对应（HITL 路线差异），实现来源 CLAUDE.md 2.5 + 03-CONTEXT.md §Safe Links bot UA + PITFALLS.md Pitfall 3。

后续 plans 引用：
- 03-02（HITL node executor）调 `HitlTokenService.sign(...)` 批量生成 3 个 action token
- 03-04（Email delivery）把 token 拼成 `f"{PUBLIC_BASE_URL}/hitl/page/{token}"`
- 03-06（公网 API）调 `HitlTokenService.decode(...)` 校签 → bot UA 命中走静态 HTML 分支 → 否则签 30min session cookie 渲染表单

## 与 hr/offboarding-flow 对照（CLAUDE.md 2.7）

hr/PRD.md §7 双通道通知 + §8 LangGraph interrupt 设计本是同源 — hr 项目走"短链 + DB 反查"路线（与 Dify Form 同），未单独实现 JWT 自携 payload 模式。agent-builder 选择 JWT 路线的原因：
1. 公网 API 路径 `/hitl/page/<token>` 需在 bot UA 检测前避免 DB 查询（减小 Safe Links 扫描器流量打 DB 的压力）
2. token 自带 `allowed_actions` 防止"提交后改 action 字段"伪造（短 token 路线需 DB 反查每次校验 action）
3. multi-instance / 高并发场景下，签发 + 校验全无 DB 是更稳健的设计

## §7 GET 不消费 jti 的设计契约（CLAUDE.md 2.5 — 永不可接受 GET 消费）

**契约定义**（项目级硬约束，本 plan 落地服务层基础）：

| 路径 | HTTP | 动作 | 是否动 jti.used_at |
|---|---|---|---|
| `/hitl/page/<token>` | GET | 渲染决策页（含 form_schema 渲染、session cookie 签发） | **否** — 仅 `HitlTokenService.decode(token)` 校签 |
| `/hitl/page/<token>` | GET（bot UA 命中） | 返回静态 HTML "您看到的是邮件扫描" | **否** — 不签 cookie、不动 viewed |
| `/hitl/action/<token>` | POST | 真实消费（写 used_at + advisory lock + 写 action_logs + Command(resume)） | **是** — 调用 `HitlTokenStore.consume(...)` |

**本 plan（03-03）的责任边界**：
1. `HitlTokenService.sign(...)` — 签发 HS256 token（不写 DB；03-02 plan 在批量生成后调 `HitlTokenStore.create_batch` 落表）
2. `HitlTokenService.decode(...)` — 校签 + exp + aud + iss + require 字段。**不读 DB**、**不写 DB**、**不消费 jti**。
3. `bot_detector.is_bot_ua(ua)` — 纯函数，None / 空 / unicode 安全。供 03-06 plan 在 GET 路径短路使用。

**消费动作（不在本 plan）**：03-01 plan 已实现 `HitlTokenStore.consume(jti, ip, ua)` 走"Postgres UPDATE … WHERE used_at IS NULL RETURNING + Redis SET NX + advisory lock"。03-06 plan 公网 API 调用此 store 完成消费。

**回归测试覆盖**：03-10 E2E plan 用 Playwright 模拟 Outlook Safe Links UA 触发 GET（CONTEXT.md §Specific Ideas 给出真实 UA 串），断言：
- 响应是静态 HTML（不是表单页）
- 响应头无 `Set-Cookie`
- 后续真实用户 POST 仍能成功消费（jti 未被预消费）

**外部参考**（Pitfall 3 P0 防护）：
- [Microsoft Defender Email Preview Enables Malicious Links — office365itpros.com, Apr 2025](https://office365itpros.com/2025/04/07/email-preview-defender/)
- [Magic links can end up in Bing search results — rendering them useless](https://medium.com/@ryanbadger/magic-links-can-end-up-in-bing-search-results-rendering-them-useless-37def0fae994)

**违反后果（CLAUDE.md 2.5 原文）**："GET 即消费 jti" 是**永不可接受**的实现 — code review 必须在第一时间打回，不接受任何"先放行后续修"的妥协。

---

## 重写而非照抄声明（许可证合规）

Dify 是 AGPL-3.0，本项目是 Apache-2.0。本笔记记录的 PassportService 5 行 try/except 骨架仅作为**设计模式参考**；HitlTokenService 实现将**自主编写**：
- 使用 keyword-only 参数（`*, jti, ...`）— Dify 用位置参数
- 字符串使用中文注释（`"""签发 HITL token（HS256）。"""`）
- 异常类按业务语义命名（`InvalidAudience`），与 Dify 的 `Unauthorized` 完全不同
- 加入 audience / issuer / require options（Dify 没有这些参数）

任何"看起来类似"的代码段：函数签名、变量命名、注释结构均独立设计。
