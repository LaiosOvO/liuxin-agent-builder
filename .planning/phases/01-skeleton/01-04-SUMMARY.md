---
phase: 01-skeleton
plan: "04"
subsystem: auth
tags: [jwt, argon2, rbac, setup-wizard, email, audit, multi-tenant]
dependency_graph:
  requires: ["01-02", "01-03"]
  provides: [auth-api, setup-wizard, invite-flow, rbac-middleware]
  affects: [all-api-routes]
tech_stack:
  added:
    - PyJWT 2.12.1（HS256 三类 token：session/email-verify/invite）
    - pwdlib[argon2] 0.3.0（Argon2id password hashing）
    - aiosmtplib 5.1.0 + Jinja2 3.1.6（邮件发送 + HTML 模板）
    - slowapi 0.1.9（rate limiting，memory:// 测试存储）
  patterns:
    - module-level cache（_setup_complete: bool | None）避免每请求查 DB
    - jti one-time consumption（UPDATE...SET used_at=NOW() WHERE used_at IS NULL RETURNING *）
    - RBAC Depends 工厂（require_role(*codes)）+ 独立 session 写 audit
    - autouse pytest fixture 跨测试清零 slowapi 计数器
key_files:
  created:
    - backend/app/services/jwt_service.py
    - backend/app/services/password.py
    - backend/app/services/email_service.py
    - backend/app/services/setup_service.py
    - backend/app/services/registration_service.py
    - backend/app/services/invite_service.py
    - backend/app/services/rbac.py
    - backend/app/services/audit.py
    - backend/app/agent_builder/api/setup.py
    - backend/app/agent_builder/api/auth.py
    - backend/app/agent_builder/api/invites.py
    - backend/app/agent_builder/api/me.py
    - backend/app/agent_builder/api/deps.py
    - backend/app/agent_builder/main.py
    - backend/app/agent_builder/middleware/setup_redirect.py
    - backend/app/schemas/auth.py
    - backend/app/schemas/setup.py
    - backend/app/schemas/invite.py
    - backend/app/schemas/me.py
    - backend/app/templates/email/verification.html
    - backend/app/templates/email/invitation.html
    - backend/app/templates/email/welcome.html
    - backend/tests/test_setup_flow.py
    - backend/tests/test_registration_flow.py
    - backend/tests/test_invite_flow.py
    - backend/tests/test_login_flow.py
    - backend/tests/test_rbac.py
    - backend/tests/test_workspace_isolation_api.py
  modified:
    - backend/app/agent_builder/security/rate_limit.py（SLOWAPI_STORAGE_URI env 支持）
    - backend/app/agent_builder/security/startup_checks.py（移除 logging.basicConfig）
    - backend/app/agent_builder/api/deps.py（rbac.denied 改用独立 session 提交）
    - backend/tests/conftest.py（autouse rate_limiter reset、db_session engine.dispose）
    - backend/tests/test_smoke.py（健康检查端点改为 /api/setup/state）
    - backend/tests/test_startup_checks.py（caplog 改为 mock.patch）
    - backend/pyproject.toml（asyncio_mode=auto、asyncio_default_fixture_loop_scope=function）
    - docker-compose.yml（新增 mailhog 服务）
decisions:
  - "PyJWT 而非 python-jose（plan lock-in）"
  - "pwdlib[argon2] 而非 passlib（plan lock-in）"
  - "GET verify-email 消费 jti（与 HITL 不同，明确注释区分）"
  - "SetupRedirectMiddleware 路由隐藏策略：未初始化→503，初始化后→404"
  - "rbac.denied 审计用独立 session（HTTPException 回滚主 session 后还能写审计）"
  - "autouse fixture 重置 slowapi 计数：避免 importlib.reload 后新旧 limiter 不一致"
metrics:
  duration_minutes: ~180
  tasks_completed: 3
  files_created: 30
  files_modified: 8
  tests_written: 119
  coverage: 70.82%
  completed_date: "2026-05-16"
---

# Phase 01 Plan 04: 认证骨架 Summary

JWT auth 三类 token（session/email-verify/invite）+ setup 向导 + 邀请注册 + RBAC 中间件 + 审计日志，全流程集成测试 119 个用例通过，覆盖率 70.82%。

## 完成内容

### Task 1：服务层（commit 10a57bd）

8 个服务模块：
- `password.py`：pwdlib[argon2] Argon2id hash/verify/强度校验（中文错误信息）
- `jwt_service.py`：三类 token（Session/EmailVerification/Invite），jti 一次性消费，decode_verify_only（GET 用）vs decode_consume_jti（POST 用）
- `audit.py`：append-only audit_log 写入，自动从 Request 提取 IP/UA
- `email_service.py`：aiosmtplib + Jinja2，3 个发送函数，失败时写 audit
- `setup_service.py`：module-level 缓存 + initialize_first_admin（超级管理员初始化）
- `registration_service.py`：邀请制注册 + 邮箱验证（GET 消费 jti，有注释说明与 HITL 区别）
- `invite_service.py`：创建邀请/预览/接受（POST 消费 jti）
- `rbac.py`：4 角色权限矩阵 + require_role 工厂

### Task 2：API 路由 + 中间件（commit 57d296c）

14 个端点：
- `GET/POST /api/setup/state|initialize`（setup 向导）
- `POST /api/auth/register|login|logout`，`GET /api/auth/verify-email`，`GET /api/auth/me`
- `POST/GET /api/invites`，`GET/POST /api/invites/accept`，`POST /api/invites/list`
- `POST /api/me/workspaces/{workspace_id}/switch`

中间件：`SetupRedirectMiddleware`（未初始化→503，初始化后 setup 路由→404）
新主应用：`agent_builder_app`（独立于 flock，fork discipline 严格遵守）

### Task 3：集成测试（commit e244b92）

119 个测试用例，6 个测试文件，覆盖率 70.82%（超过 60% 要求）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] rbac.denied 审计日志丢失**
- 发现于：Task 3 集成测试 test_editor_cannot_create_invite
- 原因：require_role 在 HTTPException 前调用 audit_log(db, ...)，但 get_db 遇到异常会 rollback，audit 写入被回滚
- 修复：改用独立 `async_session_maker()` session 写审计，commit 后再 raise HTTPException
- 文件：`backend/app/agent_builder/api/deps.py`
- Commit：e244b92

**2. [Rule 1 - Bug] startup_checks.py 的 logging.basicConfig 污染测试**
- 发现于：Task 3 集成测试运行时 caplog 在异步测试后失效
- 原因：库模块不应调用 basicConfig（它是 entry point 专属配置，会阻止 pytest 的 log capture handler 生效）
- 修复：移除 startup_checks.py 中的 logging.basicConfig() 调用
- 文件：`backend/app/agent_builder/security/startup_checks.py`
- Commit：e244b92

**3. [Rule 1 - Bug] importlib.reload 后新旧 limiter 不一致导致速率限制误触发**
- 发现于：test_rate_limit.py::TestRateLimitModuleImport::test_limiter_singleton_exists 调用 reload 后，agent_builder_app.state.limiter 仍是旧对象，reset_rate_limiter fixture 只重置了新对象
- 修复：autouse fixture 同时重置 rl_module.limiter._storage 和 agent_builder_app.state.limiter._storage
- 文件：`backend/tests/conftest.py`
- Commit：e244b92

**4. [Rule 2 - 缺失功能] asyncio 跨事件循环连接池冲突**
- 发现于：pytest-asyncio asyncio_mode=function 场景下，module-level engine singleton 的连接被绑定到第一个事件循环
- 修复：db_session fixture 每次调用 engine.dispose() 释放旧连接，允许新连接在当前事件循环建立
- 文件：`backend/tests/conftest.py`
- Commit：e244b92

## Self-Check: PASSED

所有 119 个测试用例在单次全量运行中通过，覆盖率 70.82%（要求 ≥ 60%）。

关键 commits：
- 10a57bd：Task 1 服务层
- 57d296c：Task 2 API 路由
- e244b92：Task 3 集成测试 + 3 个 Bug 修复
