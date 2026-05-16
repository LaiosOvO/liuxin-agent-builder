"""实例业务服务层。

职责：
- 创建实例（基于已发布版本；工作流未发布时 409）
- 列出实例（WorkspaceScopedQuery + filter + search + pagination）
- 获取实例详情（含 node_states[]）
- 中止实例（修改状态为 aborted）
- 获取申请人追踪信息（HITL-07：仅 applicant/admin 可见 + records 脱敏）

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
from app.agent_builder.models.role import Role
from app.agent_builder.models.user import User
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.agent_builder.models.workflow import Workflow
from app.agent_builder.models.workflow_version import WorkflowVersion

_log = logging.getLogger(__name__)


# 当前节点的 "active" 状态集合（节点正在等待人/LLM/工具完成）。
_ACTIVE_NODE_STATUSES = {"pending", "waiting_human", "in_review", "running"}

# admin 视角允许看到完整的 IP/UA 字段（NET-05 审计需要）。
_ADMIN_VIEW_ROLE_CODES = {"admin", "super_admin"}


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

    # ── 申请人追踪（HITL-07） ─────────────────────────────────────────────────

    async def get_tracking_for_applicant(
        self,
        *,
        instance_id: UUID,
        workspace_id: UUID,
        current_user: User,
    ) -> dict[str, Any]:
        """获取实例追踪信息（HITL-07 申请人追踪页）。

        权限规则（CONTEXT §申请人追踪页隐私）：
        1. 跨 workspace（WorkspaceScopedQuery 过滤后找不到）→ 404
        2. 同 workspace 但 applicant_id != current_user.id 且非 admin → 403
        3. 申请人本人或 admin → 200

        数据脱敏规则：
        - admin / super_admin：records 含完整 IP / UA
        - 申请人本人（非 admin）：records 中 ip / ua 置 None

        Args:
            instance_id: 实例 ID
            workspace_id: 当前工作区
            current_user: 当前登录用户（用于权限校验 + 角色判定脱敏）

        Returns:
            dict 含 instance_id / status / applicant / current_node / records / created_at / completed_at

        Raises:
            HTTPException(404): 实例不存在或跨 workspace 不可访问
            HTTPException(403): 非 applicant 且非 admin
        """
        # 1. WorkspaceScopedQuery 过滤后加载实例（跨 workspace → 404）
        stmt = WorkspaceScopedQuery.select(FlowInstance).where(
            FlowInstance.id == instance_id
        )
        result = await self._db.execute(stmt)
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(status_code=404, detail="实例不存在")

        # 2. 权限检查：applicant 或 admin 才放行
        is_admin = await self._user_has_admin_view(
            user=current_user, workspace_id=workspace_id
        )
        is_applicant = inst.created_by is not None and inst.created_by == current_user.id

        if not (is_applicant or is_admin):
            raise HTTPException(status_code=403, detail="您不是该实例的申请人")

        # 3. 加载所有 node_states（按 started_at ASC 时间线排序，
        #    started_at IS NULL 排到最前以便和创建时间一致）
        ns_stmt = (
            WorkspaceScopedQuery.select(NodeState)
            .where(NodeState.instance_id == instance_id)
            .order_by(
                NodeState.started_at.asc().nullsfirst(),
                NodeState.id.asc(),
            )
        )
        ns_result = await self._db.execute(ns_stmt)
        node_states = list(ns_result.scalars().all())

        # 4. 解析 applicant 信息
        applicant_info = await self._resolve_applicant(inst.created_by)

        # 5. 找当前正在等待的节点（active），优先 HITL 节点
        current_node = self._build_current_node(node_states)

        # 6. 聚合所有 node_state.payload.records → 时间线 + 脱敏
        records = self._aggregate_records(node_states=node_states, expose_audit=is_admin)

        return {
            "instance_id": inst.id,
            "status": inst.status,
            "workflow_id": inst.workflow_id,
            "applicant": applicant_info,
            "current_node": current_node,
            "records": records,
            "created_at": inst.created_at,
            "completed_at": inst.completed_at,
        }

    # ── 申请人追踪辅助 ──────────────────────────────────────────────────────────

    async def _user_has_admin_view(self, *, user: User, workspace_id: UUID) -> bool:
        """判断用户是否拥有 admin 视角（看到完整 IP/UA）。

        - super_admin 全局放行
        - 当前 workspace 内 role.code == 'admin' 放行
        - 其它角色（editor / viewer）和外部用户不放行
        """
        if user.is_super_admin:
            return True

        # 查当前 workspace 角色
        uwr_stmt = (
            select(Role.code)
            .join(UserWorkspaceRole, UserWorkspaceRole.role_id == Role.id)
            .where(
                UserWorkspaceRole.user_id == user.id,
                UserWorkspaceRole.workspace_id == workspace_id,
            )
        )
        code = await self._db.scalar(uwr_stmt)
        return code in _ADMIN_VIEW_ROLE_CODES

    async def _resolve_applicant(self, created_by: UUID | None) -> dict[str, Any]:
        """加载申请人显示信息（name 缺失时回退 email 前缀）。"""
        if created_by is None:
            return {"id": None, "name": "system"}

        result = await self._db.execute(select(User).where(User.id == created_by))
        user = result.scalar_one_or_none()
        if user is None:
            # 用户被删除等极端情况；保留 ID 以便审计追溯
            return {"id": created_by, "name": "unknown"}

        name = user.display_name or (user.email.split("@", 1)[0] if user.email else None)
        return {"id": user.id, "name": name}

    def _build_current_node(self, node_states: list[NodeState]) -> dict[str, Any] | None:
        """从 node_states 中找当前正在等待的节点。

        优先级：
        1. HITL 节点（status in waiting_human/in_review）— 申请人最关心
        2. 其它 active 节点（pending/running）
        3. 没有 active 节点 → 实例已终态 → None
        """
        active: list[NodeState] = [
            ns for ns in node_states if ns.status in _ACTIVE_NODE_STATUSES
        ]
        if not active:
            return None

        # HITL 优先（按 started_at DESC，最近的优先）
        hitl_active = [ns for ns in active if ns.node_type == "hitl"]
        chosen = (hitl_active or active)[-1]

        payload = chosen.payload or {}
        actor_raw = payload.get("current_actor") if isinstance(payload, dict) else None
        actor: dict[str, Any] | None = None
        if isinstance(actor_raw, dict):
            actor = {
                "email": actor_raw.get("email"),
                "name": actor_raw.get("name") or actor_raw.get("display_name"),
            }

        # title 优先从 payload.title 取，否则用 node_id 兜底
        title = None
        if isinstance(payload, dict):
            title = payload.get("title") or payload.get("node_title")

        deadline_at = payload.get("deadline_at") if isinstance(payload, dict) else None

        return {
            "id": chosen.node_id,
            "title": title,
            "status": chosen.status,
            "node_type": chosen.node_type,
            "actor": actor,
            "deadline_at": deadline_at,
            "started_at": chosen.started_at.isoformat() if chosen.started_at else None,
        }

    def _aggregate_records(
        self,
        *,
        node_states: list[NodeState],
        expose_audit: bool,
    ) -> list[dict[str, Any]]:
        """聚合 node_state.payload.records → 时间线，按 ts ASC 排序。

        Args:
            node_states: 实例下所有节点状态
            expose_audit: True 时保留 ip/ua（admin）；False 时置 None（申请人脱敏）

        Returns:
            records 列表，每条含 actor_email/actor_name/action/reason/ts/ip/ua
        """
        all_records: list[dict[str, Any]] = []
        for ns in node_states:
            payload = ns.payload or {}
            if not isinstance(payload, dict):
                continue
            raw_records = payload.get("records") or []
            if not isinstance(raw_records, list):
                continue
            for raw in raw_records:
                if not isinstance(raw, dict):
                    continue
                record = self._normalize_record(raw, expose_audit=expose_audit)
                all_records.append(record)

        # 按 ts ASC 排序（空 ts 排到最后保持稳定）
        all_records.sort(key=lambda r: r.get("ts") or "")
        return all_records

    @staticmethod
    def _normalize_record(raw: dict[str, Any], *, expose_audit: bool) -> dict[str, Any]:
        """单条 record 字段规范化 + 脱敏。

        Service 层完成脱敏，OpenAPI 文档统一；前端无需角色分支。
        """
        ip = raw.get("ip") or raw.get("actor_ip") if expose_audit else None
        ua = raw.get("ua") or raw.get("actor_ua") if expose_audit else None
        return {
            "actor_email": raw.get("actor_email") or raw.get("email") or "",
            "actor_name": raw.get("actor_name") or raw.get("name"),
            "action": raw.get("action") or "",
            "reason": raw.get("reason") or "",
            "ts": raw.get("ts") or raw.get("at") or "",
            "ip": ip,
            "ua": ua,
        }

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    async def _load_workflow(self, workflow_id: UUID, workspace_id: UUID) -> Workflow:
        """加载工作流，不存在时抛 404。"""
        stmt = WorkspaceScopedQuery.select(Workflow).where(Workflow.id == workflow_id)
        result = await self._db.execute(stmt)
        wf = result.scalar_one_or_none()
        if not wf:
            raise HTTPException(status_code=404, detail="工作流不存在")
        return wf
