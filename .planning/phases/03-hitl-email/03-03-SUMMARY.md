---
phase: 03-hitl-email
plan: "03"
subsystem: auth
tags: [jwt, hitl, pyjwt, hs256, safe-links, bot-detection, security]

# Dependency graph
requires:
  - phase: 01-skeleton
    provides: jwt_service._get_jwt_secret() + startup_checks JWT_SECRET ≥ 32 字节校验
  - phase: 03-hitl-email
    provides: 03-01 hitl_tokens 表（jti 一次性消费表）+ HitlTokenStore
provides:
  - HitlTokenService.sign(*, jti, instance_id, node_state_id, actor_id, action, role, expires_at) → HS256 JWT
  - HitlTokenService.decode(token) → payload dict（仅校签 + 不消费 jti）
  - 异常细分体系：InvalidSignature / TokenExpired / InvalidAudience / HitlTokenError
  - aud='hitl' 常量（与 Phase 1 session/email-verify/invite token 隔离）
  - BOT_UA_PATTERNS（15 个：13 个 CONTEXT 列出 + safelinks 通用前缀 + ac-detector-tool Outlook 真实 UA）
  - is_bot_ua(ua) → bool 纯函数（None/空/unicode 鲁棒）
affects: [03-02 HITL node executor, 03-04 Email delivery, 03-06 HITL public API, 03-10 E2E gate]

# Tech tracking
tech-stack:
  added: []  # 复用 Phase 1 PyJWT 2.12.1，无新依赖
  patterns:
    - "service 层细分业务异常 → API 层差异化错误页（vs Dify PassportService 单一 Unauthorized）"
    - "aud 显式隔离 — 同密钥多 audience 路线，靠 audience+require 字段防 cross-token 滥用"
    - "GET/POST 职责分离 — 服务层只做无副作用的 sign/decode，消费由独立 Store 完成"

key-files:
  created:
    - backend/app/services/hitl_token_service.py
    - backend/app/agent_builder/security/bot_detector.py
    - backend/tests/test_hitl_token_service.py
    - backend/tests/test_bot_detector.py
    - docs/reading-dify-03-03-hitl-token-2026-05-17.md
  modified: []

key-decisions:
  - "BOT_UA_PATTERNS 15 项 = CONTEXT 13 + 'safelinks' 通用前缀 + 'ac-detector-tool' Outlook 真实 UA（覆盖 §Specific Ideas 提供的真实测试 UA 字符串）"
  - "复用 Phase 1 _get_jwt_secret() 而非新增 HMAC_SECRET 入口 — 单一密钥多 aud 隔离比双密钥简单且无需 startup_checks 改动"
  - "异常细分 InvalidSignature/TokenExpired/InvalidAudience（vs Dify 单一 Unauthorized）便于 API 层针对不同失败原因渲染不同错误文案"
  - "options.require=['jti','exp','iat','aud','iss'] 强制 PyJWT 校验关键字段，缺一即 HitlTokenError（防伪造 token 缺字段绕过）"
  - "Phase 1 session token（无 aud）用 HitlTokenService.decode 必抛 HitlTokenError（隔离测试覆盖）"

patterns-established:
  - "audience 隔离模式：sign 时 aud='hitl'，decode 时 audience='hitl' + require=['aud',...]，PyJWT 自动校验 mismatch"
  - "Bot UA 检测纯函数 + 元组常量：避免运行时编译正则，直接 substring lower() 匹配；O(n*m) 但 m 小（15）且仅在 GET 请求路径调用"
  - "服务层不做 I/O：sign/decode 全无 DB/Redis 调用，便于单元测试不依赖容器"

requirements-completed: [AUTH-04, AUTH-05, HITL-03]

# Metrics
duration: 6min
completed: 2026-05-17
---

# Phase 3 Plan 03: HitlTokenService JWT + Safe Links Bot Detector Summary

**HITL token HS256 签发 / 解码服务（aud='hitl' 隔离） + 15 模式 Safe Links Bot UA 检测器（覆盖 Outlook AC-Detector-Tool 真实 UA），全部单元测试通过、不依赖 DB**

## Performance

- **Duration:** 6min
- **Started:** 2026-05-17 (epoch 1778952785 / UTC ~17:33Z)
- **Completed:** 2026-05-17 (UTC ~17:39Z)
- **Tasks:** 3 (Task 0 reading doc + Task 1 HitlTokenService + Task 2 bot_detector)
- **Files created:** 5

## Accomplishments

- **HitlTokenService.sign / decode** — PyJWT 2.12.1 HS256，payload 含 iss/aud='hitl'/iat/exp/jti/flow_id/node_state_id/actor_id/role/allowed_actions
- **细分异常体系** — InvalidSignature / TokenExpired / InvalidAudience / HitlTokenError 兜底；API 层（03-06 plan）可按异常类型决定 HTTP 状态码与文案
- **audience 严格隔离** — 用 Phase 1 sign_session 签的 token 走 HitlTokenService.decode 必抛 HitlTokenError（隔离测试覆盖）
- **Safe Links Bot UA 检测器** — 15 个 pattern 元组，case-insensitive substring 匹配；CONTEXT.md §Specific Ideas 给出的 Outlook AC-Detector-Tool 真实 UA 字符串通过测试
- **鲁棒性保证** — None / 空字符串 / unicode（中文 + emoji）/ 超长 UA 均不崩溃，遵循 CLAUDE.md 编码风格"never trust external data"
- **复用 Phase 1 基础设施** — _get_jwt_secret 直接 import，未新增 env 入口、未改动 startup_checks
- **44 单元测试通过** — 13 HitlTokenService + 31 bot_detector（含 15 parametrize 全 pattern 覆盖）

## Task Commits

按 task 原子提交：

1. **Task 0: Reading doc gate** — `b31b90b` (docs)
2. **Task 1: HitlTokenService.sign / decode + 异常类** — `3f8aabe` (feat)
3. **Task 2: bot_detector + Safe Links UA 测试** — `8d7e16b` (feat)

**Plan metadata:** 本 SUMMARY commit 由 final_commit 步骤创建。

## Files Created/Modified

- `backend/app/services/hitl_token_service.py` — HitlTokenService 类 + 4 异常类 + JWT_AUD/ISS/ALG 常量（116 行）
- `backend/app/agent_builder/security/bot_detector.py` — BOT_UA_PATTERNS 元组 + is_bot_ua 纯函数（71 行）
- `backend/tests/test_hitl_token_service.py` — 13 测试 / 3 测试类（235 行）
- `backend/tests/test_bot_detector.py` — 31 测试 / 4 测试类（含 parametrize 15 patterns，174 行）
- `docs/reading-dify-03-03-hitl-token-2026-05-17.md` — Dify PassportService 阅读笔记 + GET 不消费 jti 设计契约（173 行）

## Decisions Made

- **BOT_UA_PATTERNS 扩到 15 项**（CONTEXT 13 + 'safelinks' 通用前缀 + 'ac-detector-tool'）：'safelinks' 通用前缀同时命中 'outlook-safelinks' 和 'microsoftdefender' 的潜在变体（防御性）；'ac-detector-tool' 来自 CONTEXT.md §Specific Ideas 显式给出的 Outlook 真实 UA，必须命中。
- **沿用 Phase 1 _get_jwt_secret**：CLAUDE.md 2.3 fork discipline 倾向不重复入口点；JWT_SECRET 已在 startup_checks 强校验（≥ 32 字节），再加一层 HMAC_SECRET 入口会引入不必要的双重维护。
- **service 层异常细分** vs Dify PassportService 单一 Unauthorized：业务可观测性（监控可分类计数 expired vs forged）+ 用户体验差异化（过期可重发邮件 / 签名错通常意味恶意篡改 → 提示不同）。
- **decode 强制 require=['jti','exp','iat','aud','iss']**：缺任一字段直接 HitlTokenError，让 Phase 1 session token（无 aud/iss/jti）走 HitlTokenService.decode 时**必然失败**，强制 audience 隔离生效。
- **JWT payload 不放敏感字段**：actor_id、flow_id、node_state_id 均为 UUID 引用，无业务敏感数据（无 email / 用户名 / 真实姓名）。如调试需要可解码 payload 不泄漏 PII。

## Dify 参考点

详见 `docs/reading-dify-03-03-hitl-token-2026-05-17.md`。核心借鉴/对比：

| 维度 | Dify (AGPL) | 本项目 (Apache-2.0) |
|---|---|---|
| Token 路线 | 短字符串 access_token VARCHAR(32) UNIQUE + DB 反查 | JWT payload 自携 + DB 仅 jti 一次性表 |
| JWT 工具 | `libs/passport.py` PassportService（5 行 try/except）| HitlTokenService（细分 4 异常 + audience/issuer/require）|
| 异常处理 | 全映射 `werkzeug.exceptions.Unauthorized` | 业务级细分 → API 层按类型差异化 |
| Bot UA 检测 | **无**（短 token 不消费，GET 多次无副作用）| 必需（JWT + jti 一次性，GET bot UA 短路保护）|
| audience 隔离 | 无（单一 SECRET_KEY 服全部 JWT 用途）| 强校验（aud='hitl' + options.require）|

借鉴的 5 行 PassportService.issue/verify 骨架已在 HitlTokenService 中**重写**（中文注释 / keyword-only 参数 / 业务异常类），不存在源码 copy。

## Deviations from Plan

None - plan executed exactly as written.

PLAN 的 `<bot_detector>` 代码块列出 14 个 pattern（实际编号 13 + 'safelinks' 前缀 + 'ac-detector-tool'）；本实现照搬未做任何修改。PLAN 测试用例描述 "test_all_13_patterns_each_has_test_case" 通过 parametrize(BOT_UA_PATTERNS) 自动覆盖所有 15 个（向上兼容），无需额外测试。

## Issues Encountered

- **pytest coverage threshold 60% 报警**：项目 `pyproject.toml` 配置 `--cov=app/agent_builder` 仅追踪 agent_builder 子包，本 plan 的 `hitl_token_service.py` 位于 `app/services/`（与 jwt_service.py 同目录），不在 coverage 路径内。这是 pre-existing 限制（与 Phase 1 jwt_service 测试相同），用 `--no-cov` 验证 44/44 测试通过。后续 Phase 7 可考虑统一 coverage 范围到 `app/`。

## User Setup Required

None - 复用 Phase 1 JWT_SECRET 环境变量，无新增配置。

## Next Phase Readiness

- **03-02（并行 Wave 2 同行）**：HITL node executor 可调用 `HitlTokenService.sign(...)` 批量生成 3 个 action token（submit/return/reject 或 approve/return/reject）；jti UUID 来源由 03-02 自行 `uuid.uuid4()` 生成，传入 HitlTokenStore.create_batch 落表后传入 sign。
- **03-04（Wave 3）**：Email delivery 可拼装 `f"{PUBLIC_BASE_URL}/hitl/page/{token}"` 链接，token 字符串直接来自 `HitlTokenService.sign(...)` 返回。
- **03-06（Wave 4）**：公网 API
  - GET `/hitl/page/<token>` 路径调 `is_bot_ua(request.headers.get('User-Agent', ''))` 短路 → 静态 HTML 返回（不签 cookie）
  - POST `/hitl/action/<token>` 路径先调 `HitlTokenService.decode(token)` 拿 payload → 再调 `HitlTokenStore.consume(jti, ip, ua)` 消费
- **03-10（E2E Wave 6）**：Playwright 用 CONTEXT §Specific Ideas 的 `Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; +safelinks.protection.outlook.com)` UA 模拟 GET，断言响应是静态 HTML + 后续真实用户 POST 仍能消费（jti 未被预消费）。

## Self-Check

- [x] `backend/app/services/hitl_token_service.py` 存在
- [x] `backend/app/agent_builder/security/bot_detector.py` 存在
- [x] `backend/tests/test_hitl_token_service.py` 存在
- [x] `backend/tests/test_bot_detector.py` 存在
- [x] `docs/reading-dify-03-03-hitl-token-2026-05-17.md` 存在
- [x] 44 单元测试全部通过（13 + 31）
- [x] 3 task commits 存在（b31b90b, 3f8aabe, 8d7e16b）

---
*Phase: 03-hitl-email*
*Completed: 2026-05-17*
