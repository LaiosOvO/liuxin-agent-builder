---
phase: 02-dsl
plan: "01"
subsystem: langgraph-upgrade
tags: [langgraph, checkpoint-postgres, psycopg3, sqlalchemy, alembic, typescript, workflow]
dependency_graph:
  requires: ["01-04"]
  provides: ["langgraph-1.2", "checkpoint-postgres-3.1", "phase2-db-schema", "workflow-typeddict-factory"]
  affects: ["02-02", "02-03", "02-04", "02-05", "02-06", "02-07", "02-08", "02-09", "02-10"]
tech_stack:
  added:
    - "langgraph==1.2.0（从 0.3.5 升级）"
    - "langgraph-checkpoint-postgres==3.1.0（从 <=2.0.9 升级）"
    - "psycopg[binary]==3.3.4（psycopg3 驱动，checkpoint 专用）"
    - "redis==7.4.0（从 >=5.0.7 升级）"
    - "pwdlib[argon2]==0.3.0（Phase 1 遗漏依赖，补全）"
    - "aiosmtplib==5.1.0（Phase 1 遗漏依赖，补全）"
    - "greenlet==3.5.0（SQLAlchemy asyncio Python 3.13 需要）"
  patterns:
    - "AsyncPostgresSaver.from_conn_string() context manager（psycopg3 连接）"
    - "TypedDict(name, fields, total=False) 动态工厂（DSL state_schema → 运行时 Python 类型）"
    - "FastAPI lifespan 异步初始化（ensure_checkpoint_tables 幂等调用）"
    - "include_object Alembic 钩子排除 LangGraph checkpoint 表"
key_files:
  created:
    - "backend/app/agent_builder/workflow/__init__.py"
    - "backend/app/agent_builder/workflow/checkpoint.py（AsyncPostgresSaver 工厂）"
    - "backend/app/agent_builder/workflow/types.py（TypedDict 动态工厂）"
    - "backend/app/agent_builder/models/workflow.py"
    - "backend/app/agent_builder/models/workflow_version.py"
    - "backend/app/agent_builder/models/flow_instance.py"
    - "backend/app/agent_builder/models/node_state.py"
    - "backend/migrations/versions/0002_phase2_workflows.py"
    - "backend/tests/test_langgraph_upgrade.py（7 个测试）"
    - "backend/tests/test_checkpoint_postgres.py（6 个集成测试）"
    - "backend/tests/test_workflow_state_typeddict.py（7 个单元测试）"
    - "backend/tests/test_phase2_db_schema.py（5 个集成测试）"
    - "docs/reading-langgraph-1.2-checkpoint-3.1.md（升级阅读笔记）"
    - "backend/uv.lock（依赖锁文件）"
  modified:
    - "backend/pyproject.toml（langgraph + checkpoint-postgres + redis 版本升级 + 遗漏依赖补全）"
    - "backend/app/agent_builder/models/__init__.py（注册 Phase 2 模型）"
    - "backend/migrations/env.py（include_object hook + Phase 2 模型导入）"
    - "backend/app/agent_builder/main.py（添加 FastAPI lifespan）"
    - ".env.example（Phase 2 注释更新）"
decisions:
  - "langchain-sandbox 与 langgraph 1.2.0 冲突 → 注释移除，Phase 6 插件机制替代（flock 代码节点 Phase 2 隐藏）"
  - "greenlet 需显式添加依赖（Python 3.13 + SQLAlchemy asyncio 必须）"
  - "checkpoint 表由 AsyncPostgresSaver.setup() 管理，include_object 排除 Alembic autogenerate"
  - "FastAPI lifespan 用于异步初始化（checkpoint 表创建），失败记 warning 不阻断启动"
  - "thread_id 含 workspace 前缀（格式 workspace_id:instance_id，防 Pitfall 13）"
metrics:
  duration: "约 28 分钟"
  completed: "2026-05-16"
  tasks: 3
  files_created: 14
  files_modified: 5
  tests_added: 25
  coverage: "N/A（本 plan 无 --cov 选项，Phase 1 覆盖率 70.82%）"
---

# Phase 2 Plan 01 Summary — LangGraph 1.2.0 升级 + Checkpoint 3.1 + Phase 2 业务表

一句话：langgraph 0.3.5 → 1.2.0 + langgraph-checkpoint-postgres 2.0.9 → 3.1.0（psycopg3 驱动）升级完成，AsyncPostgresSaver 工厂 + TypedDict 动态工厂就位，4 张 Phase 2 业务表 migration 三循环通过，共 25 个测试全部通过。

---

## 主要交付

### 1. 依赖升级（pyproject.toml）

| 包 | 旧版本 | 新版本 | 原因 |
|---|---|---|---|
| langgraph | >=0.3.5 | ==1.2.0 | Phase 2 引擎基础，所有后续 plan 依赖 |
| langgraph-checkpoint-postgres | <=2.0.9 | ==3.1.0 | psycopg3 驱动，AsyncPostgresSaver 稳定 API |
| redis | >=5.0.7 | ==7.4.0 | Redis Stream API（Phase 2 SSE 用）|
| langchain-sandbox | >=0.0.6 | 注释移除 | 与 langgraph 1.2 langchain-core>=1.4 冲突 |
| pwdlib[argon2] | （遗漏）| >=0.3.0 | Phase 1 auth 模块依赖，补入 |
| aiosmtplib | （遗漏）| >=5.1.0 | Phase 1 email 模块依赖，补入 |
| greenlet | （遗漏）| >=3.5.0 | SQLAlchemy asyncio + Python 3.13 依赖 |

### 2. workflow/checkpoint.py（公共 API）

```python
# 异步 context manager 提供 AsyncPostgresSaver
async with get_checkpointer() as saver:
    app = graph.compile(checkpointer=saver)

# 幂等创建 checkpoint 表（启动时调用）
await ensure_checkpoint_tables()

# thread_id 含 workspace 前缀（防 Pitfall 13）
thread_id = build_thread_id(workspace_id, instance_id)
# → "550e8400-...:6ba7b810-..."

ws_id, inst_id = parse_thread_id(thread_id)
```

### 3. workflow/types.py（TypedDict 工厂）

```python
# 从 DSL state_schema 动态构造 TypedDict
StateType = build_state_typeddict({
    "employee_id": "str",
    "score": "float",
    "approved": "bool"
})
# 等价于：class StateType(TypedDict, total=False): ...

app = StateGraph(StateType)  # 直接用于 LangGraph
```

### 4. Phase 2 业务表（0002 migration）

| 表 | 用途 | 关键约束 |
|---|---|---|
| workflows | 工作流主表 | workspace_id FK CASCADE + ix_workflows_ws_status_created |
| workflow_versions | DSL 版本快照 | UNIQUE(workflow_id, version_no, kind) |
| flow_instances | 运行实例 | UNIQUE(thread_id) + workspace_id 索引 |
| node_states | 节点状态 | instance_id FK CASCADE DELETE |

### 5. LangGraph Checkpoint 表（由 ensure_checkpoint_tables() 创建）

| 表 | 说明 |
|---|---|
| checkpoints | 完整状态快照（append-only）|
| checkpoint_blobs | 大型 blob 分离存储（3.1 新增）|
| checkpoint_writes | 节点 pending writes |
| checkpoint_migrations | 迁移版本追踪 |

### 6. 测试覆盖（25 个，全部通过）

| 文件 | 测试数 | 类型 |
|---|---|---|
| test_langgraph_upgrade.py | 7 | 单元（import + 版本验证）|
| test_checkpoint_postgres.py | 6 | 集成（DB + psycopg3）|
| test_workflow_state_typeddict.py | 7 | 单元（TypedDict 工厂）|
| test_phase2_db_schema.py | 5 | 集成（DB 结构验证）|
| test_smoke.py（Phase 1 回归） | 3 | 集成（不破坏）|
| test_db_schema.py（Phase 1 回归）| 5 | 集成（不破坏）|

---

## 升级兼容性验证

### flock 代码不破坏

```
from langchain_community.chat_models import ChatLiteLLM  → ok
import langchain                                          → ok
import langchain_community                                → ok
import langchain_openai                                   → ok
import litellm                                            → ok
from langgraph.graph import StateGraph                   → ok
```

### 两个 Postgres 驱动共存

- asyncpg（`postgresql+asyncpg://`）：SQLAlchemy ORM 业务数据
- psycopg3（`postgresql://`）：LangGraph checkpoint
- 两个驱动同时连同一 DB，连接池独立，不冲突

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 阻断] langchain-sandbox 与 langgraph 1.2.0 冲突**
- **Found during:** Task 1（uv sync 失败）
- **Issue:** `langchain-sandbox==0.0.6` 依赖 `langchain-core<0.4.0`，但 `langgraph==1.2.0` 依赖 `langchain-core>=1.4.0`
- **Fix:** 在 pyproject.toml 中注释 langchain-sandbox，说明原因（flock 代码节点 Phase 2 隐藏，Phase 6 插件机制替代）
- **Files modified:** `backend/pyproject.toml`
- **Commit:** 6fd0c88

**2. [Rule 3 - 阻断] pwdlib / aiosmtplib 遗漏依赖**
- **Found during:** Task 1（Phase 1 smoke 测试运行时 ModuleNotFoundError）
- **Issue:** Phase 1 auth/email 代码依赖 pwdlib + aiosmtplib，但这两个包未在 pyproject.toml 中声明，旧 venv 已有但新 venv 不含
- **Fix:** 添加 `pwdlib[argon2]>=0.3.0` + `aiosmtplib>=5.1.0` 到 pyproject.toml
- **Files modified:** `backend/pyproject.toml`
- **Commit:** 6fd0c88

**3. [Rule 3 - 阻断] greenlet 遗漏依赖（Python 3.13 环境）**
- **Found during:** Task 1（smoke 测试 ValueError: the greenlet library is required）
- **Issue:** SQLAlchemy 2.0 async 模式依赖 greenlet，Python 3.13 不随包自动安装
- **Fix:** `uv add greenlet`，将 `greenlet>=3.5.0` 添加到 pyproject.toml
- **Files modified:** `backend/pyproject.toml`
- **Commit:** 6fd0c88

## Self-Check: PASSED

- 所有 14 个关键文件确认存在
- Task 1 commit `6fd0c88`、Task 2 commit `a13a3a7`、Task 3 commit `3c04026` 均已确认
- 25 个测试通过（7 升级 + 6 checkpoint + 7 TypedDict + 5 DB schema）
- 4 张 Phase 2 业务表 + 4 张 LangGraph checkpoint 表在 PostgreSQL 中可查询
- Alembic 三循环（upgrade/downgrade base/upgrade head）全部成功
- Phase 1 全部测试不破坏（smoke + db_schema 通过）
- flock 原有文件未修改（fork discipline 遵守）
