---
phase: 05a-platform-plugin-framework
plan: 01
subsystem: platforms/plugin-framework
tags: [platform, plugin, dify-reference, alembic, orm, test-infrastructure, multi-tenant]
provides:
  - WorkspacePluginInstallation ORM 模型
  - Alembic migration 0006（workspace_plugin_installations 表）
  - tests/platforms/ + tests/platforms_integration/ 测试目录骨架
  - 共享 fixture（workspace_id / db_session / clean_plugin_registry / free_port）
requires:
  - Phase 1 alembic + Base + naming convention
  - Phase 1 async_session_maker + engine 复用模式
  - Postgres pgcrypto extension（gen_random_uuid()）
affects:
  - 后续 Wave 2-7 所有 plan 依赖此表 + fixture
tech-stack:
  added: []
  patterns: [Dify Declaration/Installation 三层分离, Dify InstallPluginMessage 状态机 enum]
key-files:
  created:
    - docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md
    - backend/app/agent_builder/models/workspace_plugin_installation.py
    - backend/migrations/versions/0006_phase5a_plugin_installations.py
    - backend/tests/platforms/__init__.py
    - backend/tests/platforms/conftest.py
    - backend/tests/platforms/test_migration_0006.py
    - backend/tests/platforms_integration/__init__.py
    - backend/tests/platforms_integration/conftest.py
  modified:
    - backend/app/agent_builder/models/__init__.py
    - backend/migrations/env.py
decisions:
  - "Migration revision 用纯数字 '0006'（与 0001..0005 风格一致），不用长形式 '0006_phase5a_plugin_installations'"
  - "ORM model 不引入 relationship 到 workspaces 表 — 避免循环 import + workspace_id 字符串 JOIN 已足够"
  - "config_json 默认 '{}'::jsonb / credentials_json nullable — config 总有结构 vs 凭据可暂未配"
  - "status CHECK constraint 强校验（DB 层兜底）— Service 层不可绕过"
  - "tests 测试目录与 plan 中路径 tests/platforms/ 实际对应 backend/tests/platforms/（pyproject.toml testpaths=tests）"
  - "smoke test 16 个（plan 要求 2 个/critical_rules 10+），覆盖表存在 / 唯一约束 / workspace 隔离 / CHECK / server_default / JSONB round-trip / 索引 / ORM 一致性"
metrics:
  duration: "~22 minutes"
  tasks_completed: 3
  files_created: 8
  files_modified: 2
  tests_added: 16
  tests_passing: 16
  phase4_regression: 0
  completed_date: "2026-05-17"
---

# Phase 5.A Plan 01: PlatformPlugin 框架工程底座 Summary

> 一句话：Dify 阅读文档 + Alembic migration 0006（workspace_plugin_installations 表，含 workspace × plugin_name 唯一约束 + status enum CHECK + JSONB config/credentials）+ tests/platforms 测试目录骨架（含双 workspace fixture 和 16 个 smoke 测试），为 Phase 5.A Wave 2-7 后续 plan 建立工程基础。

---

## 任务执行明细

### Task 0: Dify plugin 架构阅读文档（CLAUDE.md §2.7 硬性 gate）

**文档**：`docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md`（181 行）
**Commit**：`67b293d` — `docs(05a-01): Dify plugin architecture 阅读文档（Task 0 硬性 gate）`

阅读范围：
- `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/{plugin,bundle,endpoint,plugin_daemon}.py`
- `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py`

5 借鉴点（每条标注 Dify source file → 5.A target module，可机械化对照）：

| # | Dify 源文件 | 借鉴模式 | 5.A target | Status |
| - | --- | --- | --- | --- |
| 1 | `plugin.py` (PluginDeclaration vs PluginInstallation) | Declaration vs Installation 分离 | `workspace_plugin_installation.py` | ✅ 本 plan |
| 2 | `plugin_daemon.py` (PluginDaemonBasicResponse 泛型) | RPC envelope 泛型约束 | `daemon_client.py` | ⏸ Plan 06 |
| 3 | `plugin_daemon.py` (InstallPluginMessage.Event) | Install 状态机 enum | `migrations/0006` (status CHECK) | ✅ 本 plan |
| 4 | `endpoint.py` (EndpointProviderDeclaration) | Capability 按 type 分组 | `manifest.py` | ⏸ Plan 03 |
| 5 | `bundle.py` (PluginBundleDependency) | 跨 plugin 依赖（YAGNI v1 不做） | `bundle.py` | ⏭ Phase 6 |

**License attribution**: Dify AGPL-3.0 vs 本项目 Apache-2.0 — 仅借鉴设计模式 / 数据结构思路，严禁拷贝源代码。每条借鉴点已明确独立创作。

### Task 1: Alembic migration 0006 + WorkspacePluginInstallation ORM

**Commit**：`4aefa6f` — `feat(05a-01): workspace_plugin_installations 表 + ORM 模型（PLUG-FW-08）`

**Migration `0006_phase5a_plugin_installations.py`**:
- `revision = "0006"`, `down_revision = "0005"`
- Table `workspace_plugin_installations` 9 字段：
  - `id UUID PK default gen_random_uuid()`
  - `workspace_id UUID NOT NULL`
  - `plugin_name TEXT NOT NULL`
  - `plugin_version TEXT NOT NULL`
  - `status TEXT NOT NULL default 'installed'` + CHECK `IN ('installed','disabled','error')`
  - `config_json JSONB NOT NULL default '{}'::jsonb`
  - `credentials_json JSONB NULL`
  - `installed_at TIMESTAMPTZ default now()`
  - `updated_at TIMESTAMPTZ default now()`
- UniqueConstraint `(workspace_id, plugin_name)` — `uq_workspace_plugin`
- CheckConstraint `status IN (...)` — `ck_plugin_status`
- Index `(workspace_id, status)` — `ix_workspace_plugin_workspace_status`

**ORM `WorkspacePluginInstallation`**：
- 9 mapped_column 与 migration 字段类型一致
- `__table_args__` 含 UniqueConstraint + CheckConstraint + Index（与 migration 镜像）
- 不引入 relationship（避免 workspaces 循环 import；后续 service 层显式 JOIN）

**Migration round-trip 验证**：
```
upgrade 0005 → 0006 ✓
downgrade 0006 → 0005 ✓
upgrade 0005 → 0006 ✓（再次）
```

**env.py 修改**：将 `WorkspacePluginInstallation` 加入 import 让 Alembic autogenerate 可见。

### Task 2: tests 目录骨架 + 共享 fixture + 16 smoke 测试

**Commit**：`703a64e` — `test(05a-01): tests/platforms 目录骨架 + conftest fixture + migration 0006 smoke 测试`

**目录骨架**：
- `backend/tests/platforms/__init__.py`
- `backend/tests/platforms_integration/__init__.py`

**共享 fixture（`tests/platforms/conftest.py`）**：
- `workspace_id_a / workspace_id_b` — 每次独立 uuid，双租户隔离场景
- `db_session` — 复用 async_session_maker + 自动 rollback（与 root conftest 等价，子目录显式声明）
- `clean_plugin_registry` — 占位（Plan 04 PluginRegistry 实现后改真清空）

**集成测共享 fixture（`tests/platforms_integration/conftest.py`）**：
- `free_port` — `socket.bind("127.0.0.1", 0)` OS 分配，mock huly server 监听用

**Smoke 测试（`tests/platforms/test_migration_0006.py`）—— 16 个测试覆盖 8 类契约**：

| # | 测试 | 验证 |
| - | --- | --- |
| 1 | `test_table_exists_in_db` | information_schema 表存在 |
| 2 | `test_table_has_all_required_columns` | 9 字段名集合一致 |
| 3 | `test_unique_workspace_plugin_name_constraint` | UNIQUE (ws, name) 拒绝重复 |
| 4 | `test_workspace_isolation_same_plugin_different_ws` | 不同 ws 可装同名 plugin |
| 5-7 | `test_check_status_accepts_allowed_values[installed/disabled/error]` | CHECK 允许三态（parametrize）|
| 8 | `test_check_status_rejects_invalid_value` | status='running' 触发 IntegrityError |
| 9 | `test_status_default_is_installed` | server_default='installed' |
| 10 | `test_config_json_default_is_empty_dict` | server_default='{}'::jsonb |
| 11 | `test_installed_at_and_updated_at_auto_set` | 时间戳 server_default=now() |
| 12 | `test_credentials_json_is_nullable` | credentials_json 默认 NULL |
| 13 | `test_jsonb_config_round_trip` | 嵌套 JSONB（dict + list）read-after-write |
| 14 | `test_workspace_status_index_exists` | pg_indexes 索引存在 |
| 15 | `test_orm_model_tablename` | ORM `__tablename__` 一致 |
| 16 | `test_orm_model_has_all_fields` | ORM mapped_column 集合一致 |

**测试结果**：
```
tests/platforms/test_migration_0006.py
============================== 16 passed in 4.76s ==============================
```

---

## 验收准则对照

| Plan 验证段 | 状态 | 证据 |
| --- | --- | --- |
| Reading doc commit hash 早于 Task 1-2 commit hash | ✅ | Task 0 `67b293d` 在 Task 1 `4aefa6f` 之前 |
| `alembic upgrade head` 后 `workspace_plugin_installations` 含 9 字段 + 1 unique + 1 check + 1 index | ✅ | inspect 验证 9 cols / uq_workspace_plugin / ck_plugin_status / ix_workspace_plugin_workspace_status |
| `pytest tests/platforms/test_migration_0006.py -v` 全 pass | ✅ | 16/16 passed |
| Phase 4 既有 `pytest tests/test_im_provider_*.py` 0 regression | ✅ | 70/70 IM 测试 pass（test_im_provider_protocol + test_im_credentials_loader + test_feishu_provider + test_dingtalk_provider）|

## Phase 4 Regression 验证

```
$ pytest tests/test_im_provider_protocol.py tests/test_im_credentials_loader.py \
  tests/test_feishu_provider.py tests/test_dingtalk_provider.py --no-cov -q
============================== 70 passed in 9.80s ==============================
```

0 regression — 本 plan 仅新增表 + 模块，未触碰 Phase 4 既有代码。

## Migration Round-Trip 截图

```
$ alembic -c migrations/alembic.ini upgrade head
INFO  [alembic.runtime.migration] Running upgrade 0005 -> 0006, Phase 5.A — workspace_plugin_installations 表（PLUG-FW-08）。

$ alembic -c migrations/alembic.ini downgrade -1
INFO  [alembic.runtime.migration] Running downgrade 0006 -> 0005, Phase 5.A — workspace_plugin_installations 表（PLUG-FW-08）。

$ alembic -c migrations/alembic.ini upgrade head
INFO  [alembic.runtime.migration] Running upgrade 0005 -> 0006, Phase 5.A — workspace_plugin_installations 表（PLUG-FW-08）。
```

---

## Dify 参考点（详见 reading doc）

每条借鉴点对应 reading doc 章节锚点：

| # | 借鉴点 | Reading doc 锚点 | 本 plan 应用 |
| - | --- | --- | --- |
| 1 | Declaration vs Installation 分离 | `## 可借鉴的设计模式 ### 1. Declaration vs Installation 分离` | `WorkspacePluginInstallation` ORM 对应 Installation 层；workspace_id × plugin_name 唯一约束保证 per-tenant 隔离 |
| 2 | PluginDaemonBasicResponse 泛型 envelope | `### 2. PluginDaemonBasicResponse 泛型 envelope` | 留 Plan 06 daemon client 实现，本 plan 未涉及 |
| 3 | PluginInstallTask 状态机 enum | `### 3. PluginInstallTask 状态机 enum` | migration 0006 `CheckConstraint("status IN ('installed','disabled','error')")` 简化 Dify Event enum |
| 4 | EndpointProviderDeclaration capability 按 type 分组 | `### 4. EndpointProviderDeclaration capability 按 type 分组` | 留 Plan 03 manifest 实现，本 plan `config_json` JSONB 设计为容纳各 capability 配置 |
| 5 | PluginBundleDependency 跨 plugin 依赖 | `### 5. PluginBundleDependency 跨 plugin 依赖` | YAGNI v1 不做，留 Phase 6 marketplace |

---

## 决策清单（按 STATE.md 累积）

- **Migration revision 用纯数字 `'0006'`** — 与 0001..0005 风格一致；alembic 文件名长形式 `0006_phase5a_plugin_installations` 仅文件名，revision ID 不含 slug
- **ORM model 不引入 `relationship` 到 workspaces 表** — 避免循环 import + workspace_id 字符串 JOIN 已足够（与 hitl_token 同模式）
- **`config_json` 默认 `'{}'`::jsonb / `credentials_json` nullable** — config 总有结构（即使空 dict）vs 凭据可暂未配（待用户首次配置时 UPDATE）
- **`status` CHECK constraint 强校验** — DB 层兜底，Service 层不可绕过（防 Dify-style "在 migration 之外引入 status 软枚举" 的 typo）
- **tests 测试目录路径** — plan 中写 `tests/platforms/`，实际对应 `backend/tests/platforms/`（pyproject.toml `testpaths = ["tests"]` 已配置）
- **smoke test 数量 16 > critical_rules 10 要求** — 覆盖 8 类契约：表存在 / UNIQUE / 多租户隔离 / CHECK enum / server_default / nullable / JSONB round-trip / 索引 / ORM 一致性
- **`free_port` 用 `socket.bind(0)` + 立即 close** — 释放后 OS 端口理论可被抢用但窗口极短可接受（Plan 07 mock huly server 仅本机测试用）

---

## 文件清单

**新增（9 个）**：
- `docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md`（181 行）
- `backend/app/agent_builder/models/workspace_plugin_installation.py`
- `backend/migrations/versions/0006_phase5a_plugin_installations.py`
- `backend/tests/platforms/__init__.py`
- `backend/tests/platforms/conftest.py`
- `backend/tests/platforms/test_migration_0006.py`
- `backend/tests/platforms_integration/__init__.py`
- `backend/tests/platforms_integration/conftest.py`

**修改（2 个）**：
- `backend/app/agent_builder/models/__init__.py`（加 `WorkspacePluginInstallation` 到 imports + `__all__`）
- `backend/migrations/env.py`（加 `WorkspacePluginInstallation` 到 imports 让 autogenerate 可见）

---

## Commit 记录

| 顺序 | Hash | 类型 | 消息 |
| --- | --- | --- | --- |
| 1 | `67b293d` | docs | Dify plugin architecture 阅读文档（Task 0 硬性 gate）|
| 2 | `4aefa6f` | feat | workspace_plugin_installations 表 + ORM 模型（PLUG-FW-08）|
| 3 | `703a64e` | test | tests/platforms 目录骨架 + conftest fixture + migration 0006 smoke 测试 |

---

## 后续 Plan 依赖关系（Wave 2-7 解锁）

| Plan | 依赖本 plan 产出 | 用途 |
| --- | --- | --- |
| 05a-02 (Capability Protocols) | `tests/platforms/conftest.py` workspace_id fixture | 6 Capability 单元测试 |
| 05a-03 (Manifest schema) | `WorkspacePluginInstallation.config_json` | manifest 解析后写入此列 |
| 05a-04 (PluginRegistry) | `WorkspacePluginInstallation` 表 + `clean_plugin_registry` fixture | install / list / get_capability 读写此表 |
| 05a-05 (LegacyIMAdapter) | `tests/platforms/conftest.py` | 单元测试 |
| 05a-06 (PlatformDaemonClient + Mock) | `tests/platforms/conftest.py` | 单元测试 |
| 05a-07 (HulyPlugin acid test) | `tests/platforms_integration/conftest.py` free_port fixture | mock huly server 端口分配 + daemon subprocess spawn |

---

## Deviations from Plan

**None** — 本 plan 完全按 PLAN.md 执行：
- Task 0 reading doc 先 commit ✓
- Task 1 migration + ORM 字段类型 / 约束 / 索引 100% 按 PLAN 规格
- Task 2 conftest fixture + smoke test 按 PLAN 规格 + critical_rules "10+ tests" 要求加码到 16 个

**唯一微调**：smoke test 从 PLAN 要求的 2 个扩展为 16 个（覆盖 8 类契约），满足 critical_rules "10+ tests pass" 硬性要求且测试更充分。

---

## Self-Check: PASSED

**Files created (9):**
- ✓ docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md
- ✓ backend/app/agent_builder/models/workspace_plugin_installation.py
- ✓ backend/migrations/versions/0006_phase5a_plugin_installations.py
- ✓ backend/tests/platforms/__init__.py
- ✓ backend/tests/platforms/conftest.py
- ✓ backend/tests/platforms/test_migration_0006.py
- ✓ backend/tests/platforms_integration/__init__.py
- ✓ backend/tests/platforms_integration/conftest.py

**Commits exist:**
- ✓ 67b293d (Task 0 reading doc)
- ✓ 4aefa6f (Task 1 ORM + migration)
- ✓ 703a64e (Task 2 tests)

**Tests pass:**
- ✓ 16/16 platforms smoke tests pass
- ✓ 70/70 Phase 4 IM regression tests pass (0 regression)
- ✓ alembic upgrade ↔ downgrade ↔ upgrade round-trip clean
