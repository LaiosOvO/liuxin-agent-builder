"""工作流业务服务层。

职责：
- 创建工作流（自动生成初始空 DSL 草稿）
- 保存草稿（校验 DSL，fatal error 拒绝，warning 通过）
- 发布（全量校验 error-free → 生成新版本号快照）
- 查询列表 / 详情（WorkspaceScopedQuery）
- 删除（物理删除）

Dify 参考：api/services/workflow_service.py — save_draft/publish 双态逻辑
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.db.scoped_query import WorkspaceScopedQuery
from app.agent_builder.models.workflow import Workflow
from app.agent_builder.models.workflow_version import WorkflowVersion
from app.agent_builder.workflow.validator import DSLCompilationError, DSLValidator, ValidationError

_log = logging.getLogger(__name__)

# 初始空 DSL（含 start / end 两个节点）
def _build_initial_dsl(name: str) -> dict[str, Any]:
    """构建初始空 DSL（仅含 start + end）。"""
    return {
        "version": "1.0",
        "name": name,
        "state_schema": {},
        "nodes": [
            {"id": "start", "type": "start", "position": {"x": 100, "y": 200}, "config": {}},
            {"id": "end", "type": "end", "position": {"x": 500, "y": 200}, "config": {}},
        ],
        "edges": [{"id": "e_start_end", "source": "start", "target": "end"}],
    }


class WorkflowService:
    """工作流业务逻辑服务。

    参考 Dify api/services/workflow_service.py 的草稿/发布双态设计。
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._validator = DSLValidator()

    # ── 创建 ──────────────────────────────────────────────────────────────────

    async def create_workflow(
        self,
        *,
        workspace_id: UUID,
        name: str,
        description: str | None,
        user_id: UUID,
    ) -> Workflow:
        """创建新工作流（自动建立初始草稿版本）。

        Args:
            workspace_id: 所属工作区 ID
            name: 工作流名称
            description: 工作流描述（可选）
            user_id: 创建人 ID

        Returns:
            新创建的 Workflow ORM 对象
        """
        wf = Workflow(
            workspace_id=workspace_id,
            name=name,
            description=description,
            created_by=user_id,
            status="draft",
        )
        self._db.add(wf)
        await self._db.flush()

        # 自动创建初始空 DSL 草稿版本（version_no=0, kind="draft"）
        initial_dsl = _build_initial_dsl(name)
        wv = WorkflowVersion(
            workspace_id=workspace_id,
            workflow_id=wf.id,
            version_no=0,
            kind="draft",
            dsl=initial_dsl,
            created_by=user_id,
        )
        self._db.add(wv)
        await self._db.flush()

        wf.current_draft_version_id = wv.id
        await self._db.commit()
        await self._db.refresh(wf)
        return wf

    # ── 草稿 ──────────────────────────────────────────────────────────────────

    async def save_draft(
        self,
        *,
        workflow_id: UUID,
        workspace_id: UUID,
        dsl: dict[str, Any],
        user_id: UUID,
    ) -> tuple[Workflow | None, list[ValidationError]]:
        """保存草稿 DSL。

        校验 DSL：
        - fatal error → 返回 (None, errors)，调用方应返回 422
        - warning 可放行 → 返回 (workflow, errors)，errors 含 warning 列表

        Args:
            workflow_id: 工作流 ID
            workspace_id: 工作区 ID
            dsl: 新的 DSL JSON
            user_id: 操作人 ID

        Returns:
            (Workflow, errors) — Workflow 为 None 表示有 fatal error
        """
        errors = self._validator.validate(dsl)
        fatal = [e for e in errors if e.severity == "error"]
        if fatal:
            return None, errors

        wf = await self._load_workflow(workflow_id, workspace_id)

        # 更新已有草稿版本，或新建
        if wf.current_draft_version_id:
            draft_result = await self._db.execute(
                select(WorkflowVersion).where(WorkflowVersion.id == wf.current_draft_version_id)
            )
            existing_draft = draft_result.scalar_one_or_none()
            if existing_draft:
                # 不能直接更新 JSONB，需要重建对象（SQLAlchemy 2 immutable pattern）
                existing_draft.dsl = dsl
                existing_draft.created_by = user_id
            else:
                wv = WorkflowVersion(
                    workspace_id=workspace_id,
                    workflow_id=workflow_id,
                    version_no=0,
                    kind="draft",
                    dsl=dsl,
                    created_by=user_id,
                )
                self._db.add(wv)
                await self._db.flush()
                wf.current_draft_version_id = wv.id
        else:
            wv = WorkflowVersion(
                workspace_id=workspace_id,
                workflow_id=workflow_id,
                version_no=0,
                kind="draft",
                dsl=dsl,
                created_by=user_id,
            )
            self._db.add(wv)
            await self._db.flush()
            wf.current_draft_version_id = wv.id

        await self._db.commit()
        await self._db.refresh(wf)
        return wf, errors

    # ── 发布 ──────────────────────────────────────────────────────────────────

    async def publish(
        self,
        *,
        workflow_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
    ) -> Workflow:
        """发布工作流（DSL 必须无 fatal error）。

        1. 加载当前草稿版本
        2. 全量校验 DSL（error-free 才允许发布）
        3. 新建发布版本（version_no = 上一发布版本号 + 1）
        4. 更新 Workflow.current_published_version_id + status = 'published'

        Raises:
            HTTPException(409): 没有草稿版本
            DSLCompilationError: DSL 有 fatal error
        """
        wf = await self._load_workflow(workflow_id, workspace_id)

        if not wf.current_draft_version_id:
            raise HTTPException(status_code=409, detail="该工作流没有草稿版本，无法发布")

        draft_result = await self._db.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == wf.current_draft_version_id)
        )
        draft = draft_result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status_code=409, detail="草稿版本不存在")

        errors = self._validator.validate(draft.dsl)
        fatal = [e for e in errors if e.severity == "error"]
        if fatal:
            raise DSLCompilationError(fatal)

        # 计算下一个 version_no（已发布版本中最大 + 1）
        prev_no = await self._max_published_version_no(workflow_id)
        wv = WorkflowVersion(
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            version_no=prev_no + 1,
            kind="published",
            dsl=draft.dsl,
            created_by=user_id,
        )
        self._db.add(wv)
        await self._db.flush()

        wf.current_published_version_id = wv.id
        wf.status = "published"
        await self._db.commit()
        await self._db.refresh(wf)
        return wf

    # ── 列表/详情/删除 ────────────────────────────────────────────────────────

    async def list_workflows(
        self,
        *,
        workspace_id: UUID,
        status: str | None = None,
        search: str | None = None,
    ) -> list[Workflow]:
        """列出工作区下的工作流（WorkspaceScopedQuery）。

        Args:
            workspace_id: 工作区 ID（由 context 注入，这里仅用于文档）
            status: 过滤状态（draft / published / archived）
            search: 按名称模糊搜索

        Returns:
            Workflow 列表（按 created_at DESC）
        """
        stmt = WorkspaceScopedQuery.select(Workflow)
        if status:
            stmt = stmt.where(Workflow.status == status)
        if search:
            stmt = stmt.where(Workflow.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(Workflow.created_at.desc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_workflow(self, *, workflow_id: UUID, workspace_id: UUID) -> Workflow:
        """获取工作流详情。

        Raises:
            HTTPException(404): 工作流不存在或不属于当前 workspace
        """
        return await self._load_workflow(workflow_id, workspace_id)

    async def delete_workflow(self, *, workflow_id: UUID, workspace_id: UUID) -> None:
        """删除工作流（物理删除；级联删除版本和实例）。

        Raises:
            HTTPException(404): 工作流不存在
        """
        wf = await self._load_workflow(workflow_id, workspace_id)
        await self._db.delete(wf)
        await self._db.commit()

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    async def _load_workflow(self, workflow_id: UUID, workspace_id: UUID) -> Workflow:
        """加载工作流，不存在时抛 404。"""
        stmt = WorkspaceScopedQuery.select(Workflow).where(Workflow.id == workflow_id)
        result = await self._db.execute(stmt)
        wf = result.scalar_one_or_none()
        if not wf:
            raise HTTPException(status_code=404, detail="工作流不存在")
        return wf

    async def _max_published_version_no(self, workflow_id: UUID) -> int:
        """获取已发布版本中最大版本号（0 表示尚未发布）。"""
        result = await self._db.execute(
            select(func.max(WorkflowVersion.version_no)).where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.kind == "published",
            )
        )
        max_no = result.scalar_one_or_none()
        return max_no if max_no is not None else 0

    async def load_version(self, version_id: UUID) -> WorkflowVersion | None:
        """加载指定版本快照（返回 None 表示不存在）。"""
        result = await self._db.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == version_id)
        )
        return result.scalar_one_or_none()
