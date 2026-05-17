"""ExecutionEngine — 工作流实例生命周期管理。

职责：
- start_instance()：创建 FlowInstance DB 行 + enqueue arq 任务（或 asyncio.create_task）
- abort_instance()：标记 instance.status = 'aborted'（v1 不中断 worker）
- restart_pending_instances_on_startup()：启动时扫描 pending/running 实例重 enqueue
- _on_hitl_enter()：HITL 节点 enter 钩子（Plan 04-11）— 创建 NodeState + chain payload
  + 按 chain_mode 分发 token 创建 + 多通道通知 fan-out + 结构化日志

设计决策（CONTEXT.md + PLAN 02-07 + PLAN 04-11）：
- thread_id = '{workspace_id}:{instance_id}'（防 Pitfall 13 跨租户 checkpoint 碰撞）
- arq.enqueue_job() 为主要触发方式（生产环境）
- arq_pool = None 时降级为 asyncio.create_task（测试/开发环境 fast path）
- WorkspaceScopedQuery 用于所有 flow_instances 查询（防 Pitfall 6）
- abort v1：只标记 DB，worker 自然完成当前节点后看 status 退出（Phase 3 增强）
- _on_hitl_enter（04-11）：单一 enter 钩子集中处理副作用（建 NodeState + 建 tokens + 发通知）
  → 节点 fn __call__ 仅读 state + interrupt（重跑 idempotent，符合 LangGraph 1.2 重跑语义）

参考来源：
- docs/reading-dify-02-07-execution-sse-2026-05-16.md：WorkflowAppRunner resume 机制
- docs/reading-dify-04-11-hitl-node-chain-2026-05-17.md：HITL enter 钩子设计（vs Dify 单 actor）
- PLAN 02-07 execution_engine.py 规格
- PLAN 04-11 _on_hitl_enter 设计
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

    # ── Plan 04-11: HITL 节点 enter 钩子 ────────────────────────────────────────

    async def _on_hitl_enter(
        self,
        *,
        node_def: dict,
        instance_id: UUID,
        workspace_id: UUID,
        db: Any,  # AsyncSession（用 Any 避免顶层导入）
    ) -> UUID:
        """HITL 节点首次 enter 时调（在 interrupt 之前）。

        职责（Plan 04-11，参考 docs/reading-dify-04-11-hitl-node-chain-2026-05-17.md §节点 enter 流程）：
        1. 解析 node_def.config.chain_mode / assignees / notify_channels
        2. resolve_assignees → list[UUID] approver_uuids
        3. 创建 NodeState 行（status='waiting_human'）
        4. build_initial_payload(chain_mode, approvers) → NodeState.payload
        5. 按 chain_mode 分发创建 token：
           - single / sequential: 仅给 approvers[0] 创建 token
           - parallel_all / parallel_any: 给所有 approvers 创建 token
        6. for actor in target_actors: enqueue_hitl_multichannel(channels=notify_channels)
        7. 结构化日志 'hitl.node.entered'（Phase 7 Run Viewer 钩子）

        Args:
            node_def: DSL 节点定义 dict（含 'id', 'type', 'config'）
            instance_id: 流程实例 UUID
            workspace_id: 工作区 UUID（多租户隔离）
            db: AsyncSession（已开始事务；本方法内 commit）

        Returns:
            node_state_id（调用方应将其注入 LangGraph state['_node_state_id']）

        Raises:
            NodeExecutionError: assignees 解析后为空（无法找到任何 active 用户）
            NotImplementedError: dept: 表达式（Phase 5 实现）
        """
        from datetime import UTC, datetime, timedelta

        from app.agent_builder.models.flow_instance import FlowInstance
        from app.agent_builder.models.node_state import NodeState
        from app.agent_builder.models.user import User
        from app.agent_builder.services.hitl_service import HitlService
        from app.agent_builder.workflow.hitl_payload import build_initial_payload
        from app.agent_builder.workflow.nodes.base import NodeExecutionError
        from app.services.notification_service import NotificationService

        config = node_def.get("config") or {}
        chain_mode = config.get("chain_mode", "single")
        assignees = config.get("assignees") or []
        notify_channels = list(config.get("notify_channels") or ["email"])
        timeout_seconds = int(config.get("timeout_seconds", 86400))
        form_schema = config.get("form_schema") or {}
        description = config.get("description", "")

        # ── 1. 解析 assignees → list[UUID] ───────────────────────────────────
        hitl_svc = HitlService(db)
        approver_uuids = await hitl_svc.resolve_assignees(assignees, workspace_id)
        if not approver_uuids:
            raise NodeExecutionError(
                node_def["id"],
                f"无法解析 assignees={assignees!r} → 任何 active 用户 "
                f"(workspace={workspace_id})",
            )

        # ── 2. 创建 NodeState 行（status='waiting_human'）─────────────────────
        now = datetime.now(UTC)
        node_state = NodeState(
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_id=node_def["id"],
            node_type="hitl",
            status="waiting_human",
            started_at=now,
        )

        # ── 3. 初始 payload（含 chain 字段，build_initial_payload 04-01 扩展）─
        first_actor = await db.get(User, approver_uuids[0])
        if first_actor is None:
            # 不应发生（resolve_assignees 已校验 active），但兜底
            raise NodeExecutionError(
                node_def["id"],
                f"approvers[0]={approver_uuids[0]} 在 DB 中未找到（resolve_assignees 与 DB 不一致？）",
            )

        node_state.payload = build_initial_payload(
            current_actor_id=approver_uuids[0],
            current_actor_email=first_actor.email,
            role="reviewer",  # chain 内全是 reviewer phase
            timeout_seconds=timeout_seconds,
            form_schema=form_schema,
            approvers=approver_uuids,
            chain_mode=chain_mode,
        )
        db.add(node_state)
        await db.flush()

        # ── 4. 按 chain_mode 分发创建 token ───────────────────────────────────
        if chain_mode in ("single", "sequential"):
            target_actors = [approver_uuids[0]]
        else:  # parallel_all / parallel_any
            target_actors = approver_uuids

        # chain mode allowed_actions 统一为 reviewer phase 3 按钮（CONTEXT §审批链 4 模式）
        tokens = await hitl_svc.batch_create_tokens_for_actors(
            instance_id=instance_id,
            node_state_id=node_state.id,
            actor_ids=target_actors,
            allowed_actions=["approve", "return", "reject"],
            expires_in_seconds=timeout_seconds,
        )
        await db.commit()
        # commit 后 NodeState.id 和 tokens 全部落地
        await db.refresh(node_state)

        # ── 5. 多通道通知 fan-out（per actor × per channel）──────────────────
        notif_svc = NotificationService(db=db, arq_pool=self.arq)
        flow_instance = await db.get(FlowInstance, instance_id)
        # FlowInstance 无 title 字段；从 dsl_snapshot.name 或 instance_id 衍生 fallback
        flow_title = (
            (flow_instance.dsl_snapshot or {}).get("name", "")
            if flow_instance is not None
            else ""
        ) or f"流程 {str(instance_id)[:8]}"
        applicant_name = (config.get("applicant_name") or "")
        deadline_at = now + timedelta(seconds=timeout_seconds)
        node_title = node_def.get("name") or node_def["id"]

        for actor_id in target_actors:
            actor = await db.get(User, actor_id)
            if actor is None:
                logger.warning(
                    "_on_hitl_enter: actor %s 不存在（resolve 后被删？），跳过通知",
                    actor_id,
                )
                continue

            actor_tokens = [t for t in tokens if t.actor_id == actor_id]
            actor_name = (
                getattr(actor, "display_name", None) or actor.email
            )
            try:
                await notif_svc.enqueue_hitl_multichannel(
                    workspace_id=workspace_id,
                    instance_id=instance_id,
                    node_state_id=node_state.id,
                    recipient_email=actor.email,
                    recipient_im_bindings=actor.im_bindings or {},
                    tokens=actor_tokens,
                    form_schema=form_schema,
                    deadline_at=deadline_at,
                    actor_name=actor_name,
                    flow_title=flow_title,
                    node_title=node_title,
                    applicant_name=applicant_name,
                    description=description,
                    channels=notify_channels,
                )
            except Exception:
                # 单 actor 通知失败不阻塞其他 actor（per-actor try/except）
                logger.exception(
                    "_on_hitl_enter: actor %s multichannel 通知入队失败，继续其他 actor",
                    actor_id,
                )

        # ── 6. 结构化日志（Phase 7 Run Viewer 钩子）───────────────────────────
        logger.info(
            "hitl.node.entered",
            extra={
                "chain_mode": chain_mode,
                "approvers_count": len(approver_uuids),
                "target_actors_count": len(target_actors),
                "notify_channels": notify_channels,
                "instance_id": str(instance_id),
                "node_state_id": str(node_state.id),
                "node_id": node_def["id"],
                "workspace_id": str(workspace_id),
            },
        )

        return node_state.id
