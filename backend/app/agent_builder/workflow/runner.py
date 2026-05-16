"""工作流实例执行器 — 实际跑 graph.astream 的 runner。

本模块为纯业务函数，可被：
1. arq worker（生产环境，后台进程）
2. asyncio.create_task（开发/测试 fast path）

执行流程（参考 Dify WorkflowAppRunner.run()）：
1. 加载 FlowInstance 和 WorkflowVersion
2. 标记 instance.status = 'running'
3. 编译 DSL → CompiledGraph（附 AsyncPostgresSaver checkpointer）
4. 调用 graph.astream(input, config, stream_mode='updates')
5. 每个节点完成：EventBus.publish("node.complete", ...) + upsert_node_state
6. 全部节点完成：标记 instance.status = 'completed' + publish instance.complete
7. 捕获 NodeExecutionError：标记失败 + publish node.error + instance.failed
8. 捕获其他异常：兜底失败处理

设计决策：
- stream_mode="updates"：每节点完成返回 {node_id: state_delta}（不是 Dify 的 GraphEngine 事件流）
- node.start 事件：在 BaseNodeExecutor.__call__ 入口手动发（astream 无内置 start 事件）
- 重启恢复：LangGraph checkpoint 自动续，无需额外逻辑
- 状态持久化：每步更新 node_states 表
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.workflow.checkpoint import build_thread_id, get_checkpointer
from app.agent_builder.workflow.compiler import DSLCompiler
from app.agent_builder.workflow.event_bus import (
    EVENT_INSTANCE_COMPLETE,
    EVENT_INSTANCE_FAILED,
    EVENT_NODE_COMPLETE,
    EVENT_NODE_ERROR,
    EventBus,
)
from app.agent_builder.workflow.nodes.base import NodeExecutionError

logger = logging.getLogger(__name__)


async def _load_instance(db: AsyncSession, instance_id: UUID):
    """从 DB 加载 FlowInstance（不过 WorkspaceScopedQuery，runner 进程无 workspace context）。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    result = await db.execute(
        select(FlowInstance).where(FlowInstance.id == instance_id)
    )
    return result.scalar_one_or_none()


async def _mark_running(db: AsyncSession, instance_id: UUID) -> None:
    """标记 instance.status = 'running' + started_at。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    await db.execute(
        update(FlowInstance)
        .where(FlowInstance.id == instance_id)
        .values(status="running", started_at=func.now())
    )
    await db.commit()


async def _mark_completed(db: AsyncSession, instance_id: UUID) -> None:
    """标记 instance.status = 'completed' + completed_at。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    await db.execute(
        update(FlowInstance)
        .where(FlowInstance.id == instance_id)
        .values(status="completed", completed_at=func.now())
    )
    await db.commit()


async def _mark_failed(db: AsyncSession, instance_id: UUID, error_message: str) -> None:
    """标记 instance.status = 'failed' + completed_at + error_message。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    await db.execute(
        update(FlowInstance)
        .where(FlowInstance.id == instance_id)
        .values(
            status="failed",
            completed_at=func.now(),
            error_message=error_message[:4096],  # 截断防超长
        )
    )
    await db.commit()


async def upsert_node_state(
    db: AsyncSession,
    instance_id: UUID,
    workspace_id: UUID,
    node_id: str,
    node_type: str,
    status: str,
    error_message: str | None = None,
    output_summary: dict | None = None,
) -> None:
    """创建或更新 node_states 记录。

    - 'running' 状态：创建新行或 UPDATE started_at
    - 'completed' / 'failed' 状态：UPDATE completed_at + status + output_summary / error_message
    """
    from app.agent_builder.models.node_state import NodeState

    # 查找已有记录（同一 instance + node_id）
    result = await db.execute(
        select(NodeState).where(
            NodeState.instance_id == instance_id,
            NodeState.node_id == node_id,
        )
    )
    existing = result.scalar_one_or_none()

    now = datetime.now(UTC)

    if existing is None:
        # 新建
        node_state = NodeState(
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_id=node_id,
            node_type=node_type,
            status=status,
            started_at=now if status == "running" else None,
            completed_at=now if status in ("completed", "failed") else None,
            error_message=error_message,
            output_summary=output_summary,
        )
        db.add(node_state)
    else:
        # 更新现有记录（不可变更新：只更新非空字段）
        if status == "running":
            existing.status = status
            existing.started_at = existing.started_at or now
        elif status in ("completed", "failed"):
            existing.status = status
            existing.completed_at = now
            if error_message is not None:
                existing.error_message = error_message
            if output_summary is not None:
                existing.output_summary = output_summary

    await db.commit()


async def run_instance(instance_id: UUID) -> None:
    """运行工作流实例的核心逻辑。

    入口：
    - arq worker（生产环境）：run_instance_arq → run_instance
    - asyncio.create_task（开发/测试 fast path）

    Args:
        instance_id: 要运行的 FlowInstance UUID

    Raises:
        RuntimeError: instance 不存在
    """
    from app.agent_builder.db.engine import async_session_maker
    from app.agent_builder.workflow.redis_client import get_redis

    redis = get_redis()
    bus = EventBus(redis)
    start_time = time.monotonic()

    # 加载 instance
    async with async_session_maker() as db:
        instance = await _load_instance(db, instance_id)
        if instance is None:
            raise RuntimeError(f"FlowInstance {instance_id} 不存在")
        workspace_id = instance.workspace_id
        dsl_snapshot = instance.dsl_snapshot
        initial_input = instance.initial_input or {}
        thread_id = build_thread_id(workspace_id, instance_id)

    # 标记 running
    async with async_session_maker() as db:
        await _mark_running(db, instance_id)

    logger.info("run_instance: 开始执行实例 %s (thread_id=%s)", instance_id, thread_id)

    try:
        async with get_checkpointer() as checkpointer:
            compiler = DSLCompiler(
                workspace_id=workspace_id,
                instance_id=instance_id,
                redis=redis,
                event_bus=bus,
            )
            compiled = compiler.compile(dsl_snapshot, checkpointer=checkpointer)
            cfg = {"configurable": {"thread_id": thread_id}}

            node_type_map: dict[str, str] = {
                n["id"]: n.get("type", "unknown")
                for n in dsl_snapshot.get("nodes", [])
            }

            async for chunk in compiled.graph.astream(
                initial_input, cfg, stream_mode="updates"
            ):
                # chunk = {node_id: state_delta_dict}
                for node_id, _delta in chunk.items():
                    node_type = node_type_map.get(node_id, "unknown")
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)

                    # 更新节点状态表
                    async with async_session_maker() as db:
                        await upsert_node_state(
                            db,
                            instance_id=instance_id,
                            workspace_id=workspace_id,
                            node_id=node_id,
                            node_type=node_type,
                            status="completed",
                            output_summary={"duration_ms": elapsed_ms},
                        )

                    # 发布节点完成事件（node.start 由 BaseNodeExecutor.__call__ 发送）
                    await bus.publish(
                        instance_id,
                        EVENT_NODE_COMPLETE,
                        {
                            "node_id": node_id,
                            "node_type": node_type,
                            "duration_ms": elapsed_ms,
                            "output_summary": {},
                        },
                    )

            # 全部节点完成
            total_ms = int((time.monotonic() - start_time) * 1000)
            async with async_session_maker() as db:
                await _mark_completed(db, instance_id)

            await bus.publish(
                instance_id,
                EVENT_INSTANCE_COMPLETE,
                {"final_status": "completed", "duration_ms": total_ms},
            )
            logger.info(
                "run_instance: 实例 %s 完成，耗时 %dms", instance_id, total_ms
            )

    except NodeExecutionError as e:
        # 节点执行失败（重试耗尽）
        error_msg = str(e)
        logger.error("run_instance: 节点 %s 执行失败: %s", e.node_id, error_msg)

        async with async_session_maker() as db:
            await upsert_node_state(
                db,
                instance_id=instance_id,
                workspace_id=workspace_id,
                node_id=e.node_id,
                node_type=node_type_map.get(e.node_id, "unknown") if "node_type_map" in dir() else "unknown",
                status="failed",
                error_message=error_msg,
            )
            await _mark_failed(db, instance_id, error_msg)

        await bus.publish(
            instance_id,
            EVENT_NODE_ERROR,
            {
                "node_id": e.node_id,
                "node_type": node_type_map.get(e.node_id, "unknown") if "node_type_map" in dir() else "unknown",
                "error_message": error_msg,
                "retries": 0,
            },
        )
        await bus.publish(
            instance_id,
            EVENT_INSTANCE_FAILED,
            {"error_message": error_msg, "failed_node_id": e.node_id},
        )

    except Exception as e:
        # 兜底异常（编译错误 / 系统异常等）
        error_msg = f"unexpected: {e}"
        logger.exception("run_instance: 实例 %s 异常终止: %s", instance_id, error_msg)

        async with async_session_maker() as db:
            await _mark_failed(db, instance_id, error_msg)

        await bus.publish(
            instance_id,
            EVENT_INSTANCE_FAILED,
            {"error_message": error_msg, "failed_node_id": None},
        )
