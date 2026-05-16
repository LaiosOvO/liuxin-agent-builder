# LangGraph 1.2 + langgraph-checkpoint-postgres 3.1 升级阅读笔记

> 日期: 2026-05-16
> 仓库: https://github.com/langchain-ai/langgraph
> 版本: langgraph==1.2.0 / langgraph-checkpoint-postgres==3.1.0

---

## 项目概述

LangGraph 是 LangChain 生态下的工作流编排引擎，支持 StateGraph（有向图）+ 持久化 checkpoint（Postgres/SQLite/Redis）+ HITL（人工介入）模式。

本笔记聚焦两个升级：
1. langgraph 0.3.5 → 1.2.0（主引擎大版本）
2. langgraph-checkpoint-postgres 2.0.9 → 3.1.0（Postgres checkpoint 驱动）

---

## 技术栈差异

| 维度 | 旧版（0.3.5 / 2.0.9） | 新版（1.2.0 / 3.1.0） |
|------|---------------------|---------------------|
| checkpoint 驱动 | psycopg2 | **psycopg3（psycopg）** |
| checkpoint 入口 | `PostgresSaver(conn)` | `AsyncPostgresSaver.from_conn_string(dsn)` |
| checkpoint 表 | checkpoints + checkpoint_writes | checkpoints + checkpoint_writes + checkpoint_blobs |
| HITL 恢复 | `graph.invoke(Command(resume=...))` | 同，但 interrupt() 语义收紧 |
| State 类型 | TypedDict / dict | TypedDict（推荐），dict 仍支持 |
| 异步 API | AsyncPostgresSaver 已有 | AsyncPostgresSaver 稳定，context manager 模式 |

---

## 架构要点

### 1. langgraph 1.2 关键变化

**StateGraph API（向后兼容）**：
```python
# 1.2 写法（与 0.3 兼容）
from langgraph.graph import StateGraph
from typing import TypedDict

class WorkflowState(TypedDict, total=False):
    field_a: str
    field_b: int

graph = StateGraph(WorkflowState)
graph.add_node("node_a", node_fn_a)
graph.add_edge("node_a", "node_b")
graph.set_entry_point("node_a")
app = graph.compile(checkpointer=checkpointer)
```

**interrupt() 语义收紧**：
- 1.2 中 `interrupt()` 必须在节点内同步调用（不能在异步上下文外调用）
- `Command(resume=value)` 是标准恢复方式，对应 Phase 3 HITL
- 单节点单 interrupt 是稳定路径；多 interrupt 在 ToolNode 并行场景有已知 Bug（#6533）
- 本项目采用「单 interrupt + 自管审批链状态」绕过此 Bug

**stream_mode 枚举稳定化**：
```python
async for event in app.astream(input, config, stream_mode="updates"):
    # event: {node_id: state_delta}
    ...
```

### 2. langgraph-checkpoint-postgres 3.1 关键变化

**驱动切换（psycopg2 → psycopg3）**：
```python
# 2.0.x（旧，不再支持）
import psycopg2
conn = psycopg2.connect(dsn)
saver = PostgresSaver(conn)

# 3.1.x（新）
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

# Context manager 模式（推荐）
async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
    await saver.setup()  # 幂等，创建 3 张表
    app = graph.compile(checkpointer=saver)
    result = await app.ainvoke(input, config)
```

**DSN 格式**：
- psycopg3 格式：`postgresql://user:pass@host:port/db`（无驱动后缀）
- asyncpg 格式：`postgresql+asyncpg://user:pass@host:port/db`（SQLAlchemy 用）
- 两者共存于同一进程，连接池各自独立

**自动创建的 3 张表**（`setup()` 调用后）：
```sql
-- checkpoints: 完整状态快照（每步追加写入）
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BYTEA NOT NULL,
    metadata BYTEA NOT NULL DEFAULT '\x7b7d',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

-- checkpoint_blobs: 大型 blob 分离存储（3.1 新增）
CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

-- checkpoint_writes: 节点 pending writes（中间状态）
CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

-- checkpoint_migrations: 迁移版本追踪
CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);
```

注意：`setup()` 是幂等的（IF NOT EXISTS），启动时调用安全。

**与 Alembic 的隔离**：
- checkpoint 表由 `AsyncPostgresSaver.setup()` 管理，Alembic 不应感知
- 在 `migrations/env.py` 中加 `include_object` 钩子排除这 4 张表

### 3. thread_id 设计（Pitfall 13 防护）

```python
# 正确：含 workspace 前缀
thread_id = f"{workspace_id}:{flow_instance_id}"

# 错误：单纯 UUID（无租户隔离）
thread_id = str(flow_instance_id)
```

`thread_id` 是 checkpoint 的分区 key，带 workspace 前缀可：
1. 日志中快速定位实例所属租户
2. 即使 UUID 极低概率碰撞，也不会跨租户

### 4. 两个 Postgres 驱动共存

项目同时使用：
- **asyncpg**（`postgresql+asyncpg://`）：SQLAlchemy ORM + 业务数据读写
- **psycopg3**（`postgresql://`）：LangGraph checkpoint 持久化

两个驱动连接同一 DB 完全没问题，各自维护独立连接池：

```python
# SQLAlchemy engine（asyncpg）
from sqlalchemy.ext.asyncio import create_async_engine
engine = create_async_engine("postgresql+asyncpg://user:pass@host:5432/db")

# checkpoint（psycopg3）
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
async with AsyncPostgresSaver.from_conn_string("postgresql://user:pass@host:5432/db") as saver:
    ...
```

---

## 可借鉴的设计模式

### 1. AsyncPostgresSaver 单例工厂模式

```python
# backend/app/agent_builder/workflow/checkpoint.py
from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

@asynccontextmanager
async def get_checkpointer():
    """异步 context manager，每次使用后自动释放连接。"""
    async with AsyncPostgresSaver.from_conn_string(_get_postgres_dsn()) as saver:
        yield saver

async def ensure_checkpoint_tables() -> None:
    """启动时调用一次，创建 checkpoint 表（幂等）。"""
    async with AsyncPostgresSaver.from_conn_string(_get_postgres_dsn()) as saver:
        await saver.setup()
```

### 2. thread_id 工厂函数

```python
from uuid import UUID

def build_thread_id(workspace_id: UUID, instance_id: UUID) -> str:
    """构造含 workspace 前缀的 thread_id（防 Pitfall 13 跨租户碰撞）。"""
    return f"{workspace_id}:{instance_id}"

def parse_thread_id(thread_id: str) -> tuple[UUID, UUID]:
    """解析 thread_id，返回 (workspace_id, instance_id)。"""
    ws, inst = thread_id.split(":", 1)
    return UUID(ws), UUID(inst)
```

### 3. Postgres Advisory Lock（Phase 3 用）

LangGraph #7259 指出 AsyncPostgresSaver 内部有 threading.Lock 竞态。Phase 3 HITL resume 需在应用层加 pg_advisory_xact_lock 防并发：

```sql
-- Phase 3 实现时参考
SELECT pg_advisory_xact_lock(
    hashtext(flow_instance_id::text)
);
-- 在事务中执行 resume，锁自动随事务释放
```

---

## 与本项目的关系

### Phase 2（本 Plan）

1. `pyproject.toml`：`langgraph==1.2.0` + `langgraph-checkpoint-postgres==3.1.0` + `redis==7.4.0`
2. `backend/app/agent_builder/workflow/checkpoint.py`：AsyncPostgresSaver 工厂
3. `backend/app/agent_builder/workflow/types.py`：TypedDict 动态构造
4. `backend/migrations/env.py`：`include_object` 排除 checkpoint 表
5. `backend/migrations/versions/0002_phase2_workflows.py`：4 张业务表

### Phase 3（HITL）

1. 使用 `interrupt()` + `Command(resume=value)` 实现人工审批节点
2. 应用层 `pg_advisory_xact_lock` 防并发双提交（Pitfall 2）
3. `get_checkpointer()` context manager 提供 saver，传入 `graph.compile(checkpointer=saver)`

---

## 兼容性注意事项

1. **langchain-sandbox 不兼容**：`langchain-sandbox==0.0.6` 依赖 `langchain-core<0.4.0`，与 `langgraph 1.2.0` 依赖的 `langchain-core>=1.4.0` 冲突。flock 的代码节点（`code_node.py`）在 Phase 2 隐藏，Phase 6 用插件机制替代。
2. **langchain-core 版本跳跃**：langgraph 1.2 要求 `langchain-core>=1.4.0`，uv 会自动将 `langchain-core` 从 0.3.x 升级到 1.4.x。flock 原有的 langchain 用法（ChatLiteLLM 等）在此版本下验证兼容。
3. **greenlet 依赖**：SQLAlchemy 异步模式需要 `greenlet`，在 Python 3.13 环境中需显式添加到 pyproject.toml。

---

*阅读笔记作者: Claude（agent-builder Phase 2 执行阶段）*
*日期: 2026-05-16*
