"""实例业务服务层。

职责：
- 创建实例（基于已发布版本；工作流未发布时 409）
- 列出实例（WorkspaceScopedQuery + filter + search + pagination）
- 获取实例详情（含 node_states[]）
- 中止实例（修改状态为 aborted）

Dify 参考：api/services/workflow_run_service.py — paginate_runs / get_run_detail
"""
from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.db.scoped_query import WorkspaceScopedQuery
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.workflow import Workflow
from app.agent_builder.models.workflow_version import WorkflowVersion

_log = logging.getLogger(__name__)


class InstanceService:
    """实例业务逻辑服务。

    注意：v1 不依赖 ExecutionEngine（02-07），只做 CRUD；
    ExecutionEngine 的 start_instance / abort_instance 将在 02-07 提供。
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 创建实例 ──────────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        workflow_id: UUID,
        workspace_id: UUID,
        initial_input: dict[str, Any],
        user_id: UUID,
    ) -> FlowInstance:
        """创建新实例（基于当前发布版本）。

        1. 加载 Workflow，确认已发布
        2. 加载发布版本 DSL 快照
        3. 创建 FlowInstance（status=pending）
        4. 返回实例（实际执行由 ExecutionEngine / arq worker 触发，02-07 实现）

        Args:
            workflow_id: 工作流 ID
            workspace_id: 工作区 ID
            initial_input: 初始输入参数
            user_id: 创建人

        Returns:
            新创建的 FlowInstance

        Raises:
            HTTPException(404): 工作流不存在
            HTTPException(409): 工作流未发布
        """
        wf = await self._load_workflow(workflow_id, workspace_id)

        if not wf.current_published_version_id:
            raise HTTPException(status_code=409, detail="工作流尚未发布，无法创建实例")

        # 加载发布版本 DSL
        ver_result = await self._db.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.id == wf.current_published_version_id
            )
        )
        ver = ver_result.scalar_one_or_none()
        if not ver:
            raise HTTPException(status_code=409, detail="发布版本不存在")

        inst_id = uuid.uuid4()
        thread_id = f"{workspace_id}:{inst_id}"

        inst = FlowInstance(
            id=inst_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            workflow_version_id=ver.id,
            dsl_snapshot=ver.dsl,
            thread_id=thread_id,
            status="pending",
            initial_input=initial_input,
            created_by=user_id,
        )
        self._db.add(inst)
        await self._db.commit()
        await self._db.refresh(inst)
        return inst

    # ── 列出实例 ──────────────────────────────────────────────────────────────

    async def list(
        self,
        *,
        workspace_id: UUID,
        workflow_id: UUID | None = None,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FlowInstance], int]:
        """列出实例（支持过滤 + 分页）。

        Args:
            workspace_id: 工作区 ID
            workflow_id: 按工作流过滤（可选）
            status: 按状态过滤（可选）
            search: 按实例 ID 前缀搜索（可选）
            page: 页码（从 1 开始）
            page_size: 每页条数（默认 20）

        Returns:
            (实例列表, 总数)
        """
        stmt = WorkspaceScopedQuery.select(FlowInstance)

        if workflow_id:
            stmt = stmt.where(FlowInstance.workflow_id == workflow_id)
        if status:
            stmt = stmt.where(FlowInstance.status == status)
        if search:
            # 按实例 ID 字符串前缀搜索（将 UUID 转为字符串进行 ILIKE）
            stmt = stmt.where(
                FlowInstance.id.cast(String).ilike(f"{search}%")
            )

        # 计算总数
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self._db.scalar(count_stmt) or 0

        # 分页
        offset = (page - 1) * page_size
        stmt = stmt.order_by(FlowInstance.created_at.desc()).offset(offset).limit(page_size)

        result = await self._db.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    # ── 获取详情 ──────────────────────────────────────────────────────────────

    async def get(self, *, instance_id: UUID, workspace_id: UUID) -> tuple[FlowInstance, list[NodeState]]:
        """获取实例详情（含 node_states[]）。

        Args:
            instance_id: 实例 ID
            workspace_id: 工作区 ID

        Returns:
            (FlowInstance, node_states 列表)

        Raises:
            HTTPException(404): 实例不存在
        """
        stmt = WorkspaceScopedQuery.select(FlowInstance).where(
            FlowInstance.id == instance_id
        )
        result = await self._db.execute(stmt)
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(status_code=404, detail="实例不存在")

        # 加载 node_states（按 started_at ASC）
        ns_stmt = WorkspaceScopedQuery.select(NodeState).where(
            NodeState.instance_id == instance_id
        ).order_by(NodeState.started_at.asc())
        ns_result = await self._db.execute(ns_stmt)
        node_states = list(ns_result.scalars().all())

        return inst, node_states

    # ── 中止实例 ──────────────────────────────────────────────────────────────

    async def abort(self, *, instance_id: UUID, workspace_id: UUID, user_id: UUID) -> FlowInstance:
        """中止实例（status → aborted）。

        仅允许中止 pending / running 状态的实例。

        Args:
            instance_id: 实例 ID
            workspace_id: 工作区 ID
            user_id: 操作人

        Returns:
            更新后的 FlowInstance

        Raises:
            HTTPException(404): 实例不存在
            HTTPException(409): 实例状态不允许中止
        """
        stmt = WorkspaceScopedQuery.select(FlowInstance).where(
            FlowInstance.id == instance_id
        )
        result = await self._db.execute(stmt)
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(status_code=404, detail="实例不存在")

        if inst.status not in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"实例状态为 {inst.status!r}，只有 pending / running 状态可以中止",
            )

        inst.status = "aborted"
        inst.error_message = f"用户 {user_id} 手动中止"
        from datetime import datetime, timezone
        inst.completed_at = datetime.now(timezone.utc)
        await self._db.commit()
        await self._db.refresh(inst)
        return inst

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    async def _load_workflow(self, workflow_id: UUID, workspace_id: UUID) -> Workflow:
        """加载工作流，不存在时抛 404。"""
        stmt = WorkspaceScopedQuery.select(Workflow).where(Workflow.id == workflow_id)
        result = await self._db.execute(stmt)
        wf = result.scalar_one_or_none()
        if not wf:
            raise HTTPException(status_code=404, detail="工作流不存在")
        return wf
