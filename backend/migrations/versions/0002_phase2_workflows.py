"""Phase 2 工作流表 schema 初始化。

4 张新表：workflows / workflow_versions / flow_instances / node_states

包含：
- 4 张表建表 SQL（含 workspace_id 复合索引）
- 全部外键约束
- downgrade() 完整反向（按 FK 依赖顺序 drop）

注意：LangGraph checkpoint 表（checkpoints / checkpoint_writes / checkpoint_blobs）
由 AsyncPostgresSaver.setup() 自动创建，不在此 migration 中管理（Alembic env.py 已排除）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 Phase 2 工作流相关的 4 张表和索引。"""

    # ── 1. workflows ─────────────────────────────────────────────────────────
    op.create_table(
        "workflows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="工作流主键 UUID",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属工作区（ON DELETE CASCADE）",
        ),
        sa.Column("name", sa.String(120), nullable=False, comment="工作流名称"),
        sa.Column("description", sa.Text, nullable=True, comment="工作流描述（可空）"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
            comment="状态：draft / published / archived",
        ),
        sa.Column(
            "current_draft_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="当前草稿版本 UUID",
        ),
        sa.Column(
            "current_published_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="当前发布版本 UUID",
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            comment="创建人 UUID",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="最后更新时间（UTC）",
        ),
    )
    # 工作区 + 状态 + 时间降序（列表页主查询路径）
    op.create_index(
        "ix_workflows_ws_status_created",
        "workflows",
        ["workspace_id", "status", sa.text("created_at DESC")],
    )

    # ── 2. workflow_versions ──────────────────────────────────────────────────
    op.create_table(
        "workflow_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="版本 UUID",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属工作区（ON DELETE CASCADE）",
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属工作流 UUID",
        ),
        sa.Column("version_no", sa.Integer, nullable=False, comment="版本号（草稿=0，发布=1/2/3...）"),
        sa.Column("kind", sa.String(10), nullable=False, comment="版本类型：draft | published"),
        sa.Column("dsl", postgresql.JSONB, nullable=False, comment="完整 DSL JSON"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            comment="创建人 UUID",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="创建时间（UTC）",
        ),
        # 唯一约束：同一工作流的 version_no + kind 唯一
        sa.UniqueConstraint(
            "workflow_id",
            "version_no",
            "kind",
            name="uq_workflow_versions_wf_version_kind",
        ),
    )
    # 工作区 + 工作流查询
    op.create_index(
        "ix_workflow_versions_ws_wf",
        "workflow_versions",
        ["workspace_id", "workflow_id"],
    )

    # ── 3. flow_instances ─────────────────────────────────────────────────────
    op.create_table(
        "flow_instances",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="实例 UUID",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属工作区（ON DELETE CASCADE）",
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id"),
            nullable=False,
            comment="触发的工作流 UUID",
        ),
        sa.Column(
            "workflow_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
            comment="锁定的工作流版本 UUID",
        ),
        sa.Column("dsl_snapshot", postgresql.JSONB, nullable=False, comment="实例创建时锁定的 DSL 副本"),
        sa.Column(
            "thread_id",
            sa.String(120),
            nullable=False,
            unique=True,
            comment="LangGraph thread_id（格式：workspace_id:instance_id）",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="状态：pending / running / completed / failed / aborted",
        ),
        sa.Column("initial_input", postgresql.JSONB, nullable=True, comment="初始输入"),
        sa.Column("final_output", postgresql.JSONB, nullable=True, comment="最终输出"),
        sa.Column("error_message", sa.Text, nullable=True, comment="错误信息"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
            comment="触发用户 UUID（NULL = 系统触发）",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="创建时间（UTC）",
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="开始执行时间"),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="完成时间"),
    )
    # 工作区 + 工作流 + 状态 + 时间（实例列表过滤主查询）
    op.create_index(
        "ix_flow_instances_ws_wf_status_created",
        "flow_instances",
        ["workspace_id", "workflow_id", "status", sa.text("created_at DESC")],
    )
    # 工作区 + 状态 + 时间（跨工作流实例列表）
    op.create_index(
        "ix_flow_instances_ws_status_created",
        "flow_instances",
        ["workspace_id", "status", sa.text("created_at DESC")],
    )

    # ── 4. node_states ────────────────────────────────────────────────────────
    op.create_table(
        "node_states",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="节点状态 UUID",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属工作区（ON DELETE CASCADE）",
        ),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_instances.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属流程实例（ON DELETE CASCADE）",
        ),
        sa.Column("node_id", sa.String(80), nullable=False, comment="DSL 节点 ID（如 'llm_1'）"),
        sa.Column(
            "node_type",
            sa.String(20),
            nullable=False,
            comment="节点类型：start / end / llm / tool / if_else",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            comment="状态：pending / running / completed / failed",
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="节点开始执行时间"),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="节点完成时间"),
        sa.Column("error_message", sa.Text, nullable=True, comment="错误信息"),
        sa.Column(
            "retries",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="重试次数",
        ),
        sa.Column(
            "output_summary",
            postgresql.JSONB,
            nullable=True,
            comment="节点输出摘要（非 raw output，防 checkpoint 膨胀）",
        ),
    )
    # 工作区 + 实例 + 开始时间（节点列表查询主路径）
    op.create_index(
        "ix_node_states_ws_instance_created",
        "node_states",
        ["workspace_id", "instance_id", "started_at"],
    )


def downgrade() -> None:
    """按 FK 依赖逆序删除 Phase 2 的 4 张表。"""
    # 按依赖顺序删除（leaf → root）
    op.drop_table("node_states")
    op.drop_table("flow_instances")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
