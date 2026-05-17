---
phase: 05a-platform-plugin-framework
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md
  - backend/migrations/versions/0006_phase5a_plugin_installations.py
  - backend/app/models/workspace_plugin_installation.py
  - tests/platforms/__init__.py
  - tests/platforms/conftest.py
  - tests/platforms_integration/__init__.py
  - tests/platforms_integration/conftest.py
  - tests/platforms/test_migration_0006.py
autonomous: true
requirements:
  - PLUG-FW-08
must_haves:
  truths:
    - "Dify plugin architecture 阅读文档已 commit（Task 0 硬性 gate）"
    - "workspace_plugin_installations 表存在于 PostgreSQL，含 workspace_id × plugin_name 唯一约束"
    - "tests/platforms/ + tests/platforms_integration/ 目录可被 pytest 发现"
  artifacts:
    - path: "docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md"
      provides: "Dify plugin 架构阅读笔记（5 节标准模板，含 5 个借鉴点 + attribution）"
      min_lines: 80
    - path: "backend/migrations/versions/0006_phase5a_plugin_installations.py"
      provides: "Alembic migration: workspace_plugin_installations 表"
      contains: "workspace_plugin_installations"
    - path: "backend/app/models/workspace_plugin_installation.py"
      provides: "SQLAlchemy ORM 模型（workspace_id × plugin_name 唯一 / status enum / JSONB config）"
      exports: ["WorkspacePluginInstallation"]
    - path: "tests/platforms/conftest.py"
      provides: "共享 fixture: workspace fixture / clean_plugin_registry / mock_daemon"
  key_links:
    - from: "backend/migrations/versions/0006_phase5a_plugin_installations.py"
      to: "backend/app/models/workspace_plugin_installation.py"
      via: "table schema 必须与 ORM model 字段一致（workspace_id / plugin_name / status / config_json / credentials_json）"
      pattern: "WorkspacePluginInstallation.__tablename__ == 'workspace_plugin_installations'"
    - from: "tests/platforms/conftest.py"
      to: "backend/migrations/versions/0006_phase5a_plugin_installations.py"
      via: "fixture 调 alembic upgrade head 准备表"
      pattern: "alembic.command.upgrade"
---

<objective>
建立 Phase 5.A 工程底座：Dify reading doc（Task 0 硬性 gate）+ Alembic migration 0006（workspace_plugin_installations 表）+ tests/ 目录骨架 + 共享 fixture。

Purpose: CLAUDE.md §2.7 要求实现 plugin framework 前必须先有 Dify 阅读文档 commit；后续 6 个 plan 都依赖此表存在 + tests fixture 可用。
Output: reading doc + migration + ORM model + 2 个 tests 目录 + conftest fixture。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05a-platform-plugin-framework/05a-CONTEXT.md
@.planning/phases/05a-platform-plugin-framework/05a-RESEARCH.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@backend/migrations/versions/0005_phase4_chain_indexes.py

<interfaces>
<!-- 复用现有 SQLAlchemy ORM 风格（参考 Phase 4 chain_indexes） -->

From backend/migrations/versions/0005_phase4_chain_indexes.py:
```python
revision = "0005_phase4_chain_indexes"
down_revision = "0004_phase3_node_state_payload"
```

From backend/app/db/base_class.py（Phase 1）:
```python
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

From CLAUDE.md §2.4 多租户基线：
- 业务表加 `workspace_id` 列 + 复合索引第一列 `(workspace_id, ...)`
- 索引：`ix_workspace_plugin_workspace_status` on `(workspace_id, status)`
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify plugin 架构阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md</files>
  <action>
**STOP — 这是后续所有 commit 的前置 gate**。先 commit 此文档才允许写代码（CLAUDE.md §2.7）。

读以下 Dify 源文件（仅 Read 不 grep，重点理解设计模式）：
1. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py` — PluginDeclaration / PluginEntity / PluginInstallation
2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/bundle.py` — PluginBundleDependency
3. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/endpoint.py` — EndpointDeclaration / EndpointProviderDeclaration
4. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin_daemon.py` — PluginDaemonBasicResponse / PluginInstallTaskStatus / 各 Response 类
5. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — PluginService install / fetch / list 方法

写到 `docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md`，**完全按 CLAUDE.md §2.7 阅读文档模板**：

```markdown
# Dify 阅读笔记 — Plugin Architecture

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> Stars: ~141k

## 项目概述（一句话）
Dify 是国内最成熟的开源 LLM 应用平台；plugin 系统通过 manifest + daemon 进程实现第三方扩展（model / tool / agent / endpoint / datasource）。

## 技术栈（关键技术选择）
- Pydantic BaseModel + ConfigDict（manifest 校验）
- daemon process（dify-plugin-daemon Go 实现，独立仓库）
- HTTP / gRPC envelope（PluginDaemonBasicResponse 泛型）
- 持久化：PostgreSQL `plugin_installations` 表

## 架构要点
…（用文字 + 简图说明 3-4 层结构：declaration / installation / runtime / endpoint）…

## 可借鉴的设计模式
1. **declaration vs installation 分离**（plugin.py PluginDeclaration vs PluginInstallation）— 静态 manifest 与 per-tenant 安装态分离 → 5.A 复用：PlatformManifest（声明）vs WorkspacePluginInstallation（per-workspace）
2. **PluginDaemonBasicResponse 泛型**（plugin_daemon.py）— RPC envelope 用泛型 T 约束 result 类型 → 5.A 借鉴：JSONRPC envelope schema
3. **PluginInstallTaskStatus 枚举**（pending/running/success/failed）— install 异步流程的状态机 → 5.A 借鉴：workspace_plugin_installations.status enum
4. **PluginBundleDependency**（bundle.py）— 跨 plugin 依赖声明 → 5.A 暂不做（Phase 6 marketplace）
5. **EndpointProviderDeclaration**（endpoint.py）— plugin 声明对外暴露的 endpoint → 5.A 借鉴思路：capability declaration 在 manifest 中按 type 分组

## 与本项目的关系
本 plan 实现 workspace_plugin_installations 表（对应 Dify plugin_installations）。后续 plan 02-06 实现 Capability Protocols / Manifest / Registry / Daemon Client — 都借鉴 Dify 的 declaration/installation/runtime 三层分离 + RPC envelope 模式。

**License attribution**: Dify 是 AGPL-3.0；本项目 Apache-2.0；仅借鉴**设计模式 / 数据结构思路**，不拷贝任何源代码。每条借鉴点已明确对应到我们要写的具体模块。
```

文档至少 80 行、5 个借鉴点必须明确写出 source file → target module 的对应关系。**不要**贴 Dify 源代码片段（许可证）。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md && wc -l docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md | awk '{exit ($1 >= 80 ? 0 : 1)}' && grep -q "AGPL\|Apache-2.0" docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md && grep -q "可借鉴的设计模式" docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md</automated>
  </verify>
  <done>Reading doc 存在 ≥ 80 行 + 含 License attribution + 含可借鉴的设计模式 5 节 + git commit hash 可见</done>
</task>

<task type="auto">
  <name>Task 1: Alembic migration 0006 + ORM 模型</name>
  <files>backend/migrations/versions/0006_phase5a_plugin_installations.py,backend/app/models/workspace_plugin_installation.py,backend/app/models/__init__.py</files>
  <action>
Reading doc 已 commit ✓（CLAUDE.md §2.7 gate 通过），才能开始写代码。

1. **Alembic migration** `backend/migrations/versions/0006_phase5a_plugin_installations.py`：
   - `revision = "0006_phase5a_plugin_installations"`
   - `down_revision = "0005_phase4_chain_indexes"`
   - 创建表 `workspace_plugin_installations`：
     - `id UUID PK default gen_random_uuid()`
     - `workspace_id UUID NOT NULL`
     - `plugin_name TEXT NOT NULL`
     - `plugin_version TEXT NOT NULL`
     - `status TEXT NOT NULL default 'installed'` + CheckConstraint `status IN ('installed','disabled','error')`
     - `config_json JSONB NOT NULL default '{}'`
     - `credentials_json JSONB NULL`
     - `installed_at TIMESTAMP WITH TIME ZONE default now()`
     - `updated_at TIMESTAMP WITH TIME ZONE default now()`
     - `UniqueConstraint("workspace_id", "plugin_name", name="uq_workspace_plugin")`
   - 索引：`ix_workspace_plugin_workspace_status` on `(workspace_id, status)`
   - downgrade 函数对称：drop index → drop table

2. **ORM 模型** `backend/app/models/workspace_plugin_installation.py`：
   - `class WorkspacePluginInstallation(Base)`
   - `__tablename__ = "workspace_plugin_installations"`
   - 字段类型与 migration 完全一致（mapped_column + UUID / Text / JSONB / TIMESTAMP）
   - 加 type annotations（PEP 8 + python/coding-style.md）
   - **不要**加 relationship 到 workspaces 表（避免循环 import；用 workspace_id 字符串 join）

3. **__init__.py 注册**：在 `backend/app/models/__init__.py` 加 `from .workspace_plugin_installation import WorkspacePluginInstallation`

代码风格：black + ruff lint 必须通过。
  </action>
  <verify>
    <automated>cd backend && python -c "from app.models import WorkspacePluginInstallation; print(WorkspacePluginInstallation.__tablename__)" && alembic upgrade head && python -c "from sqlalchemy import inspect; from app.db.session import sync_engine; insp = inspect(sync_engine); assert 'workspace_plugin_installations' in insp.get_table_names()" && alembic downgrade -1 && alembic upgrade head</automated>
  </verify>
  <done>Migration 可 upgrade + downgrade + 再 upgrade；ORM model 类可 import 且 tablename 匹配；workspace_plugin_installations 表在 DB 中存在</done>
</task>

<task type="auto">
  <name>Task 2: tests 目录骨架 + 共享 conftest fixture + migration smoke test</name>
  <files>tests/platforms/__init__.py,tests/platforms/conftest.py,tests/platforms_integration/__init__.py,tests/platforms_integration/conftest.py,tests/platforms/test_migration_0006.py</files>
  <action>
1. **创建空 `__init__.py`**：
   - `tests/platforms/__init__.py`
   - `tests/platforms_integration/__init__.py`

2. **`tests/platforms/conftest.py`** 共享 fixture：
```python
"""Phase 5.A platforms 单测共享 fixture。"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.workspace_plugin_installation import WorkspacePluginInstallation


@pytest_asyncio.fixture
async def workspace_id_a() -> uuid.UUID:
    """Test workspace A — 用于双租户隔离测试。"""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def workspace_id_b() -> uuid.UUID:
    """Test workspace B — 用于双租户隔离测试。"""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """复用 Phase 1 async_session_factory + autoflush 关 + 测试后 rollback。"""
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def clean_plugin_registry():
    """每 test 清空 PluginRegistry 模块级 dict（后续 plan 04 用到）。
    
    占位 — 等 plan 04 PluginRegistry 实现后改为真正的 clear。
    """
    yield
```

3. **`tests/platforms_integration/conftest.py`** 集成测共享 fixture：
```python
"""Phase 5.A platforms_integration 集成测共享 fixture。

集成测真实 spawn daemon 子进程 + 起 mock huly server。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest_asyncio


@pytest_asyncio.fixture
async def free_port() -> int:
    """获取可用端口（mock huly server 用）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
```

4. **smoke test** `tests/platforms/test_migration_0006.py`：
```python
"""Phase 5.A migration 0006 smoke test — 表存在 + 唯一约束生效。"""
from __future__ import annotations

import uuid

import pytest

from app.models.workspace_plugin_installation import WorkspacePluginInstallation


@pytest.mark.asyncio
async def test_table_create_and_unique_constraint(db_session, workspace_id_a):
    """workspace_id × plugin_name 唯一约束生效。"""
    ws = workspace_id_a
    p1 = WorkspacePluginInstallation(
        workspace_id=ws, plugin_name="huly", plugin_version="1.0.0",
    )
    db_session.add(p1)
    await db_session.flush()

    # 同 (workspace, name) 再插一行 → IntegrityError
    p2 = WorkspacePluginInstallation(
        workspace_id=ws, plugin_name="huly", plugin_version="1.0.1",
    )
    db_session.add(p2)
    with pytest.raises(Exception):  # IntegrityError on flush
        await db_session.flush()


@pytest.mark.asyncio
async def test_workspace_isolation(db_session, workspace_id_a, workspace_id_b):
    """不同 workspace 可装同名 plugin。"""
    a = WorkspacePluginInstallation(workspace_id=workspace_id_a, plugin_name="huly", plugin_version="1.0.0")
    b = WorkspacePluginInstallation(workspace_id=workspace_id_b, plugin_name="huly", plugin_version="1.0.0")
    db_session.add_all([a, b])
    await db_session.flush()  # OK
```

测试覆盖：表存在性 + 唯一约束 + workspace 隔离。
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms/test_migration_0006.py -v -x 2>&1 | tail -20 && test -f tests/platforms/conftest.py && test -f tests/platforms_integration/conftest.py</automated>
  </verify>
  <done>2 个 smoke test 通过；conftest.py × 2 + __init__.py × 2 文件存在；pytest 能发现 tests/platforms/ 与 tests/platforms_integration/ 目录</done>
</task>

</tasks>

<verification>
Phase gate（plan 01）:
- [ ] Reading doc commit hash 早于 Task 1-2 commit hash（CLAUDE.md §2.7 校验）
- [ ] `alembic upgrade head` 后 `\d workspace_plugin_installations` 含 6 字段 + 1 unique + 1 index
- [ ] `pytest tests/platforms/test_migration_0006.py -v` 2/2 pass
- [ ] Phase 4 既有 `pytest tests/test_im_provider_*.py` 0 regression
</verification>

<success_criteria>
- Dify reading doc ≥ 80 行 + 5 借鉴点明确，commit 在前
- workspace_plugin_installations 表创建（含 PK / 唯一约束 / status check / 索引）
- ORM 模型 import 工作 + 字段类型与 migration 一致
- tests/platforms/ + tests/platforms_integration/ 目录可被 pytest 发现
- 2 smoke test 通过
- 0 regression Phase 4 测试
</success_criteria>

<output>
完成后创建 `.planning/phases/05a-platform-plugin-framework/05a-01-SUMMARY.md`，至少含：
- Reading doc 链接 + commit hash
- Migration upgrade/downgrade 验证截图（pytest 输出）
- Phase 4 regression 截图（pytest tests/test_im_provider_*.py 数字）
- **Dify 参考点** 小节：列出本 plan reading doc 中 5 借鉴点，每条指回 reading doc 章节锚点
</output>
