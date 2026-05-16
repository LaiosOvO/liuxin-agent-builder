---
phase: 01-skeleton
plan: 02
subsystem: database
tags: [sqlalchemy, alembic, multi-tenant, workspace, schema]
dependency_graph:
  requires: ["01-01"]
  provides: ["db-schema", "workspace-scoped-query", "discard-all-hook"]
  affects: ["01-04", "01-05", "01-06"]
tech_stack:
  added:
    - "SQLAlchemy 2.0.49 (async)"
    - "Alembic 1.18.4"
    - "asyncpg 0.31.0"
    - "psycopg 3.3.4 (migrations sync)"
  patterns:
    - "DeclarativeBase + naming_convention (稳定约束名)"
    - "WorkspaceScopedQuery（ContextVar 注入 workspace_id）"
    - "DISCARD ALL checkout hook（防 PgBouncer 上下文污染）"
    - "testcontainers-postgres fallback to POSTGRES_DSN（Docker 不可用时）"
key_files:
  created:
    - "backend/app/agent_builder/db/base.py (DeclarativeBase + naming_convention)"
    - "backend/app/agent_builder/db/engine.py (AsyncEngine 单例)"
    - "backend/app/agent_builder/db/checkout_hook.py (DISCARD ALL hook)"
    - "backend/app/agent_builder/db/scoped_query.py (WorkspaceScopedQuery)"
    - "backend/app/agent_builder/db/session.py (FastAPI get_db 依赖)"
    - "backend/app/agent_builder/models/workspace.py"
    - "backend/app/agent_builder/models/user.py"
    - "backend/app/agent_builder/models/role.py"
    - "backend/app/agent_builder/models/user_workspace_role.py"
    - "backend/app/agent_builder/models/invite.py"
    - "backend/app/agent_builder/models/email_verification.py"
    - "backend/app/agent_builder/models/audit_log.py"
    - "backend/migrations/versions/0001_phase1_schema.py"
    - "backend/migrations/env.py"
    - "backend/migrations/alembic.ini"
    - "backend/tests/test_db_schema.py"
    - "backend/tests/test_workspace_scoped_query.py"
    - "backend/tests/test_discard_all_hook.py"
  modified:
    - "backend/pyproject.toml (pytest asyncio_mode, coverage path, fail_under)"
decisions:
  - "手写 migration 0001（不用 autogenerate，避免 CITEXT/复合索引出错）"
  - "migrations/ 独立于 flock 原有的 app/alembic，fork discipline 严格遵守"
  - "DISCARD ALL 在 checkout hook 中，ROLLBACK 兜底防 asyncpg 事务内失败"
  - "Docker 不可用时集成测试自动回退到 POSTGRES_DSN 指定的 SSH 隧道 DB"
  - "audit_logs 使用 BIGSERIAL PK（时序有序），而非 UUID"
metrics:
  duration: "约 17 分钟"
  completed: "2026-05-16"
  tasks: 2
  files_created: 19
  files_modified: 1
  tests_added: 12
  coverage: "76%"
---

# Phase 1 Plan 02 Summary — DB 层 + 多租户隔离基础设施

一句话：SQLAlchemy 2.0 async ORM 7 张表 + Alembic 0001 手写 migration + WorkspaceScopedQuery（ContextVar 注入）+ DISCARD ALL checkout hook（防 PgBouncer session 污染）+ 12 个集成测试全过。

---

## 主要交付

### 7 张表（实际列与索引）

**workspaces**
- `id UUID PK`、`name VARCHAR(120)`、`slug VARCHAR(60) UNIQUE`
- `created_by UUID NULL`（首次 setup 为 NULL）
- `created_at / updated_at TIMESTAMPTZ`

**users**
- `id UUID PK`、`email CITEXT UNIQUE`（大小写不敏感）
- `password_hash VARCHAR(255)`、`display_name / department VARCHAR(120) NULL`
- `status VARCHAR(30)` DEFAULT `pending_verification`
- `is_super_admin BOOLEAN DEFAULT false`
- `im_bindings JSONB DEFAULT '{}'`（Phase 5）
- `created_at / updated_at / last_login_at TIMESTAMPTZ`

**roles**（静态种子，4 条）
- `id SMALLINT PK`、`code VARCHAR(20) UNIQUE`、`description VARCHAR(255)`

| id | code | 说明 |
|----|------|------|
| 1 | super_admin | 平台级超级管理员 |
| 2 | admin | 工作区级管理员 |
| 3 | editor | 工作区编辑者 |
| 4 | viewer | 只读用户 |

**user_workspace_roles**
- PK `(workspace_id, user_id)`（workspace_id 第一列）
- FK workspace → workspaces.id ON DELETE CASCADE
- FK user → users.id ON DELETE CASCADE
- FK role → roles.id
- 索引：`ix_user_workspace_roles_user_id_workspace_id (user_id, workspace_id)`（反查）

**invites**
- `id UUID PK`、`workspace_id UUID FK`（第一列，满足多租户索引规则）
- `email CITEXT`、`target_role_code VARCHAR(20)`
- `jti UUID UNIQUE`（与 JWT jti 对齐，一次性消费）
- `token_hash VARCHAR(128)`（SHA256 哈希，审计用）
- `invited_by UUID FK`、`expires_at / used_at TIMESTAMPTZ`
- 索引：`(workspace_id, created_at)`、`(email, workspace_id)`

**email_verifications**
- `id UUID PK`、`user_id UUID FK ON DELETE CASCADE`
- `workspace_id UUID NULL`（setup super_admin 注册时无 workspace）
- `jti UUID UNIQUE`、`token_hash VARCHAR(128)`
- `expires_at / used_at TIMESTAMPTZ`
- 索引：`(user_id, created_at)`

**audit_logs**
- `id BIGSERIAL PK`（时序有序，非 UUID）
- `workspace_id UUID NULL`（系统级事件如 setup）
- `actor_user_id UUID NULL`、`actor_meta JSONB`（external token 操作）
- `action VARCHAR(80)`、`target_type VARCHAR(40)`、`target_id UUID NULL`
- `meta JSONB`、`ip INET`、`user_agent VARCHAR(255)`
- 索引：`(workspace_id, created_at DESC)`、`(actor_user_id, created_at DESC)`、`(action, created_at DESC)`

---

### WorkspaceScopedQuery 使用约定

**必须走 WorkspaceScopedQuery（业务表）：**
- `invites`、`email_verifications`、`audit_logs`（有 workspace_id 的业务数据）
- Phase 2+ 新增的 `workflows`、`instances` 等

**可以绕过（直接 sa_select）：**
- `workspaces`、`users`、`roles`（跨 workspace 可见的全局表）
- super_admin 跨 ws 管理查询

```python
# 正确用法
token = current_workspace_ctx.set(workspace_id)
try:
    stmt = WorkspaceScopedQuery.select(Invite)  # 自动注入 WHERE workspace_id = :ws_id
    result = await session.execute(stmt)
finally:
    current_workspace_ctx.reset(token)

# super_admin 绕过
stmt = sa_select(Invite)  # 不走 WorkspaceScopedQuery
```

---

### DISCARD ALL hook 验证

```
tests/test_discard_all_hook.py::test_hook_registered_on_sync_engine PASSED
tests/test_discard_all_hook.py::test_discard_all_executed_on_mock_conn PASSED
tests/test_discard_all_hook.py::test_session_var_cleared_after_checkin PASSED
tests/test_discard_all_hook.py::test_discard_all_is_executable_on_sync_conn PASSED
```

验证流程：
1. `set_config('app.workspace_id', 'ws-test-123')` → 值为 `'ws-test-123'`
2. `DISCARD ALL` 执行
3. `current_setting('app.workspace_id', true)` → 返回 `''`（已清除）

---

## 完整测试结果

```
tests/test_db_schema.py::test_all_tables_exist PASSED
tests/test_db_schema.py::test_composite_indexes PASSED
tests/test_db_schema.py::test_email_citext_unique_constraint PASSED
tests/test_db_schema.py::test_role_seeds PASSED
tests/test_db_schema.py::test_uq_jti_invites PASSED
tests/test_workspace_scoped_query.py::test_ws_a_cannot_see_ws_b PASSED
tests/test_workspace_scoped_query.py::test_missing_ctx_raises PASSED
tests/test_workspace_scoped_query.py::test_correct_ctx_returns_data PASSED
tests/test_discard_all_hook.py::test_hook_registered_on_sync_engine PASSED
tests/test_discard_all_hook.py::test_discard_all_executed_on_mock_conn PASSED
tests/test_discard_all_hook.py::test_session_var_cleared_after_checkin PASSED
tests/test_discard_all_hook.py::test_discard_all_is_executable_on_sync_conn PASSED

12 passed in 5.32s | coverage 76%
```

---

## Alembic 三循环验证

```bash
alembic -c migrations/alembic.ini upgrade head    # INFO: Running upgrade -> 0001
alembic -c migrations/alembic.ini downgrade base  # INFO: Running downgrade 0001 ->
alembic -c migrations/alembic.ini upgrade head    # INFO: Running upgrade -> 0001
```

三次全过，无错误。

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 阻断] Docker daemon 不可用，testcontainers 无法启动**
- **Found during:** Task 2（集成测试运行时）
- **Issue:** macOS 环境无 Docker daemon，`testcontainers.postgres.PostgresContainer` 连接 socket 失败
- **Fix:** 所有集成测试 fixture 先尝试 testcontainers，Docker 不可用时自动回退到 `POSTGRES_DSN` 环境变量指定的 SSH 隧道 DB（localhost:15432）
- **Files modified:** `tests/test_db_schema.py`, `tests/test_workspace_scoped_query.py`, `tests/test_discard_all_hook.py`
- **Commit:** 1435287

**2. [Rule 1 - Bug] DISCARD ALL 在 asyncpg 事务内执行失败**
- **Found during:** Task 2（test_session_var_cleared_after_checkin 报 `ActiveSQLTransactionError`）
- **Issue:** asyncpg 的 SQLAlchemy 适配器在每次 execute 前自动开启事务，`DISCARD ALL cannot run inside a transaction block`
- **Fix:** checkout hook 加 ROLLBACK 兜底；集成测试改用原生 asyncpg 连接（`statement_cache_size=0`）和 psycopg3 同步连接验证
- **Files modified:** `app/agent_builder/db/checkout_hook.py`, `tests/test_discard_all_hook.py`
- **Commit:** 1435287

**3. [Rule 2 - 缺失] migration 0001 索引创建方式需要调整**
- **Found during:** Task 1（`op.create_index` 不支持 `sa.text("created_at DESC")` 直接传入）
- **Fix:** 使用 `sa.text()` wrapper 传入 DESC 排序表达式（PostgreSQL 支持 functional index）
- **Commit:** bc5cd41

## Self-Check: PASSED

所有 20 个关键文件确认存在，Task 1 commit `bc5cd41` 和 Task 2 commit `1435287` 均已确认，7 张表 + 4 条 role 种子在 PostgreSQL 中可查询。
