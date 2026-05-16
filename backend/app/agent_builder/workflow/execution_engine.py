"""ExecutionEngine — 工作流实例生命周期管理。

职责：
- start_instance()：创建 FlowInstance DB 行 + enqueue arq 任务（或 asyncio.create_task）
- abort_instance()：标记 instance.status = 'aborted'（v1 不中断 worker）
- restart_pending_instances_on_startup()：启动时扫描 pending/running 实例重 enqueue

设计决策（CONTEXT.md + PLAN 02-07）：
- thread_id = '{workspace_id}:{instance_id}'（防 Pitfall 13 跨租户 checkpoint 碰撞）
- arq.enqueue_job() 为主要触发方式（生产环境）
- arq_pool = None 时降级为 asyncio.create_task（测试/开发环境 fast path）
- WorkspaceScopedQuery 用于所有 flow_instances 查询（防 Pitfall 6）
- abort v1：只标记 DB，worker 自然完成当前节点后看 status 退出（Phase 3 增强）

参考来源：
- docs/reading-dify-02-07-execution-sse-2026-05-16.md：WorkflowAppRunner resume 机制
- PLAN 02-07 execution_engine.py 规格
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _build_thread_id(workspace_id: UUID, instance_id: UUID) -> str:
    """构造 thread_id = '{workspace_id}:{instance_id}'（防 Pitfall 13）。"""
    from app.agent_builder.workflow.checkpoint import build_thread_id
    return build_thread_id(workspace_id, instance_id)


class ExecutionEngine:
    """工作流实例生命周期管理器。

    构造参数：
        db: AsyncSession（FastAPI 请求级别，用于创建 instance / 权限检查）
        redis: Redis async 客户端（EventBus 用）
        arq_pool: arq.ArqRedis 连接池（生产环境任务队列）；None 时降级为 asyncio.create_task
    """

    def __init__(
        self,
        db: AsyncSession,
        redis: Any,  # redis.asyncio.Redis
        arq_pool: Any | None = None,  # arq.ArqRedis
    ) -> None:
        self.db = db
        self.redis = redis
        self.arq = arq_pool

    async def start_instance(
        self,
        *,
        workflow_version_id: UUID,
        initial_input: dict,
        user_id: UUID | None,
        workspace_id: UUID,
    ):
        """创建 FlowInstance 并触发执行。

        Args:
            workflow_version_id: 工作流版本 UUID
            initial_input: 初始输入 dict（start 节点接收）
            user_id: 触发用户 UUID（可为 None，系统触发时）
            workspace_id: 调用方工作区 UUID

        Returns:
            创建的 FlowInstance ORM 对象

        Raises:
            PermissionError: workflow_version.workspace_id 与 workspace_id 不匹配
            ValueError: workflow_version 不存在
        """
        from app.agent_builder.models.flow_instance import FlowInstance
        from app.agent_builder.models.workflow_version import WorkflowVersion

        # 1. 加载 WorkflowVersion + 权限校验
        result = await self.db.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == workflow_version_id)
        )
        wv = result.scalar_one_or_none()
        if wv is None:
            raise ValueError(f"WorkflowVersion {workflow_version_id} 不存在")
        if wv.workspace_id != workspace_id:
            raise PermissionError(
                f"workspace mismatch: wv.workspace_id={wv.workspace_id} vs {workspace_id}"
            )

        # 2. 创建 FlowInstance（先 flush 获取 id，再填 thread_id）
        instance = FlowInstance(
            workspace_id=workspace_id,
            workflow_id=wv.workflow_id,
            workflow_version_id=wv.id,
            dsl_snapshot=wv.dsl,
            status="pending",
            initial_input=initial_input,
            thread_id="placeholder",  # 先占位，flush 后替换
            created_by=user_id,
        )
        self.db.add(instance)
        await self.db.flush()  # 获取 instance.id

        # 3. 填写真实 thread_id（含 instance.id，防 Pitfall 13）
        instance.thread_id = _build_thread_id(workspace_id, instance.id)
        await self.db.commit()

        # 4. 触发执行
        await self._enqueue(instance.id)

        logger.info(
            "ExecutionEngine.start_instance: 创建实例 %s (thread_id=%s)",
            instance.id, instance.thread_id,
        )
        return instance

    async def abort_instance(
        self,
        instance_id: UUID,
        *,
        user_id: UUID | None,
        workspace_id: UUID,
    ) -> None:
        """标记 instance.status = 'aborted'。

        v1 不实际中断 worker（worker 自然完成当前节点后检查 status 退出）。
        Phase 3 增强：引入 CommandChannel 真正中断执行。

        Args:
            instance_id: 要中止的实例 UUID
            user_id: 操作用户 UUID（审计用）
            workspace_id: 调用方工作区（权限校验）

        Raises:
            PermissionError: instance 不属于该 workspace
            ValueError: instance 不存在
        """
        from app.agent_builder.models.flow_instance import FlowInstance

        result = await self.db.execute(
            select(FlowInstance).where(FlowInstance.id == instance_id)
        )
        instance = result.scalar_one_or_none()
        if instance is None:
            raise ValueError(f"FlowInstance {instance_id} 不存在")
        if instance.workspace_id != workspace_id:
            raise PermissionError(
                f"workspace mismatch: instance.workspace_id={instance.workspace_id} vs {workspace_id}"
            )

        await self.db.execute(
            update(FlowInstance)
            .where(FlowInstance.id == instance_id)
            .values(status="aborted", completed_at=func.now())
        )
        await self.db.commit()
        logger.info("ExecutionEngine.abort_instance: 实例 %s 已标记为 aborted", instance_id)

    async def restart_pending_instances_on_startup(self) -> int:
        """启动时扫描 pending / running 实例，重新 enqueue。

        用途：
        - 服务崩溃重启后，恢复未完成的实例
        - LangGraph AsyncPostgresSaver checkpoint 自动续跑

        Returns:
            重新 enqueue 的实例数量
        """
        from app.agent_builder.models.flow_instance import FlowInstance

        result = await self.db.execute(
            select(FlowInstance).where(
                FlowInstance.status.in_(["pending", "running"])
            )
        )
        instances = result.scalars().all()

        count = 0
        for inst in instances:
            await self._enqueue(inst.id)
            count += 1

        if count > 0:
            logger.info(
                "ExecutionEngine.restart_pending_instances_on_startup: 重新 enqueue %d 个实例",
                count,
            )
        return count

    async def _enqueue(self, instance_id: UUID) -> None:
        """将实例 ID 推入 arq 队列，或降级为 asyncio.create_task。

        Args:
            instance_id: 要执行的实例 UUID
        """
        if self.arq is not None:
            # 生产环境：arq 任务队列
            await self.arq.enqueue_job("run_instance_arq", str(instance_id))
            logger.debug("ExecutionEngine._enqueue: arq 任务已提交 %s", instance_id)
        else:
            # 开发/测试 fast path：asyncio 后台任务
            import asyncio
            from app.agent_builder.workflow.runner import run_instance
            asyncio.create_task(run_instance(instance_id))
            logger.debug(
                "ExecutionEngine._enqueue: asyncio.create_task 已提交 %s", instance_id
            )
