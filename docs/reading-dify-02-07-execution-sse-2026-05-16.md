# Dify 阅读笔记 — Execution Engine + SSE 实时推送

> 日期: 2026-05-16
> 仓库: https://github.com/langgenius/dify (commit e7e6fe88, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k

## 项目概述（一句话）

Dify 用 GraphEngine（graphon 库）驱动工作流节点执行，通过 AppQueueManager 把每步事件放入内存队列，再由 WorkflowAppGenerateTaskPipeline 消费事件流并转换为 SSE/HTTP chunk 推送到客户端。

## 技术栈（关键技术选择）

- **执行引擎**: `graphon.GraphEngine` — 同步迭代器，`run()` 生成 `GraphEngineEvent` 对象
- **事件桥接**: `AppQueueManager` — 内存队列 + `CommandChannel`（InMemoryChannel / RedisChannel）
- **流式输出**: Flask streaming response + `generate_task_pipeline.py` 消费队列事件
- **任务执行**: 同步 + Celery worker（不是 arq），线程级 context 隔离
- **持久化**: SQLAlchemy ORM（同步），workflow_runs 表 + node_execution 表
- **SSE/暂停**: `CommandChannel` 允许外部向 GraphEngine 发送 pause/resume/stop 命令

## 架构要点（核心架构模式，用简图说明）

```
┌─ Flask HTTP 线程 ─────────────────────────────────────────────┐
│  POST /run → WorkflowAppGenerator                             │
│  → celery.delay(run_workflow_task)                            │
│  ← 返回 task_id + SSE streaming response                      │
│                                                                │
│  GET /stream (SSE) → AppQueueManager.listen()                 │
│  → 消费 queue events → generate_task_pipeline.process()      │
│  → yield SSE text chunks                                       │
└────────────────────────────────────────────────────────────────┘
                  │
                  ▼ Celery Task
┌─ Celery Worker ───────────────────────────────────────────────┐
│  WorkflowAppRunner.run()                                       │
│  → WorkflowEntry → GraphEngine.run()                          │
│  → 每个节点完成 → queue_manager.publish(QueueNodeSucceeded)   │
│  → 实例结束 → queue_manager.publish(QueueWorkflowSucceeded)   │
└────────────────────────────────────────────────────────────────┘
```

**核心区别（Dify vs 本项目）**:
- Dify: 同步 Celery + 内存队列 → Flask SSE
- 本项目: 异步 arq + Redis pub/sub + Redis Stream → FastAPI SSE（更适合 async）

**Dify 的事件命名规范**（完全参考借鉴）:
```python
# api/core/app/entities/queue_entities.py
QueueNodeStartedEvent     # ↔ 我们: node.start
QueueNodeSucceededEvent   # ↔ 我们: node.complete
QueueNodeFailedEvent      # ↔ 我们: node.error
QueueWorkflowSucceededEvent  # ↔ 我们: instance.complete
QueueWorkflowFailedEvent     # ↔ 我们: instance.failed
QueueWorkflowStartedEvent    # ↔ 我们: state.update (启动时)
```

**WorkflowEntry 设计**（`api/core/workflow/workflow_entry.py`）:
- 不直接调用节点，通过 GraphEngine 执行
- CommandChannel 允许外部注入 pause/resume/abort 命令
- graph_runtime_state 从 GraphRuntimeState 初始化，支持从已有状态恢复
- `call_depth` 防止子工作流无限递归

**WorkflowAppGenerateTaskPipeline 设计**（`api/core/app/apps/workflow/generate_task_pipeline.py`）:
- 消费 AppQueueManager 的事件流，转换成 SSE 事件
- 处理 `QueueWorkflowPausedEvent`（HITL 暂停），返回 `WorkflowAppPausedBlockingResponse`
- 每个 SSE 事件都包含完整数据结构（非增量）

**WorkflowAppRunner 的 resume 机制**（`api/core/app/apps/workflow/app_runner.py`）:
```python
# 检查 resume_state 决定是否从 checkpoint 恢复
if self._resume_graph_runtime_state is not None:
    graph_runtime_state = resume_state
    # 直接复用已有的 VariablePool（保留节点上下文）
    graph = self._init_graph(...)
```
借鉴：resume 时传入 graph_runtime_state，LangGraph checkpointer 做类似事情。

## 可借鉴的设计模式（具体文件路径 + 模式名 + 一句话说明）

### 1. 事件类型命名规范（`api/core/app/entities/queue_entities.py`）
完整的事件类型枚举（`node.start` / `node.complete` / `node.error` / `state.update` / `instance.complete` / `instance.failed`）命名逻辑与 Dify `Queue*Event` 对齐，易于调试和类比。

### 2. CommandChannel 外部控制（`api/core/workflow/workflow_entry.py`）
Dify 用 CommandChannel 实现 pause/resume/abort，不在节点内轮询状态。
**本项目 v1 简化**：abort 只标记 DB status，不真正中断 worker；Phase 3 再引入 CommandChannel。

### 3. 事件 payload 结构（`generate_task_pipeline.py`）
Dify 每个 SSE 事件包含 `event`, `task_id`, `workflow_run_id`, `data`（包含节点时间戳、输出摘要等）。
**本项目直接参考**：`{id, event, instance_id, timestamp, data}` 结构与此对齐。

### 4. 持久化与事件解耦（`app_runner.py` + `generate_task_pipeline.py`）
Dify 的 `PersistenceWorkflowInfo` 通过独立的 layer 处理 DB 写入，不在 runner 主循环里做 ORM。
**本项目** 在 runner 的 chunk 循环里直接调用 `upsert_node_state`，可以接受（规模小），但遇到慢 DB 时考虑 Dify 的异步 layer 模式。

### 5. SSE 断连补发（`app_queue_manager.py` 的 listen 模式）
Dify 用内存队列，不支持断连补发。本项目用 Redis Stream + `Last-Event-ID` 补发，是超越 Dify 的改进。

### 6. Worker 崩溃恢复（`app_runner.py` resume_state）
Dify 通过 `GraphRuntimeState` 实例传入支持恢复，本项目通过 LangGraph `AsyncPostgresSaver` checkpoint 自动实现，原理相同但更自动化。

## 与本项目的关系（如何应用到当前 plan 02-07）

| Dify 设计 | 本项目应用 |
|-----------|------------|
| `QueueNodeStartedEvent` → pub/sub → SSE | `EventBus.publish("node.start", ...)` → Redis pub/sub → FastAPI SSE |
| `AppQueueManager.publish()` 线程安全 | `EventBus.publish()` async-safe (asyncio + aioredis) |
| `WorkflowAppRunner.run()` → GraphEngine | `runner.run_instance()` → `graph.astream()` |
| `graph_runtime_state` 重启恢复 | LangGraph `AsyncPostgresSaver` checkpoint thread_id 恢复 |
| CommandChannel pause/abort | v1: 仅 DB status=aborted，worker 自然完成当前节点后退出 |
| SSE endpoint 鉴权 (session) | `GET /v1/instances/<id>/events` 复用 Phase 1 session cookie Depends |
| Dify 无断连补发 | **改进**: Redis Stream + Last-Event-ID → 重连补发历史事件 |
| `WorkflowRun` DB 记录 | `FlowInstance` + `NodeState` 二表（已在 02-03 创建） |

**关键 Pitfall（从 Dify 代码中发现的坑，我们要规避）**:
1. **节点开始事件**：Dify 的 GraphEngine 在节点调用前手动发 `QueueNodeStartedEvent`；我们在 `BaseNodeExecutor.__call__` 开头发 `node.start` 事件（已有 event_bus 注入接口）
2. **thread_id 唯一性**：Dify 用 `workflow_run_id` 隔离，我们用 `workspace_id:instance_id` 防跨租户碰撞（Pitfall 13）
3. **stream_mode="updates"**：LangGraph 每个节点完成返回 `{node_id: state_delta}`，不是 Dify 的 GraphEngine 事件流，需要手工重建事件语义
