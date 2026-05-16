"""Phase 3 — node_states 加 payload JSONB 列（HITL 节点状态持久化）。

设计参考：
- 03-CONTEXT.md §HITL 节点状态机 — payload schema (phase / current_actor / approval_chain
  / records / pending_approvers / started_at / deadline_at / form_schema)
- 03-02-PLAN hitl_payload.build_initial_payload 返回值需要持久化到 node_state.payload
- 03-06-PLAN GET /hitl/page 与 POST /hitl/action 都从此列读取 form_schema / records / deadline_at

为什么不放 output_summary：
- output_summary 是节点 *输出* 摘要（用于实例详情页展示）
- payload 是节点 *运行时状态*（HITL 节点跨 interrupt / resume 持久化）
- 语义不同，分开两列

不引入新索引：
- HITL 节点 payload 查询入口都是 node_state_id 主键 + workspace_id 多租户隔离已有索引
- 不做基于 payload 内字段的二级索引（v1 无相关查询场景）

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """node_states 加 payload JSONB 列。"""
    op.add_column(
        "node_states",
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=True,
            comment="节点运行时状态 payload（HITL: phase/current_actor/records/form_schema/deadline_at）",
        ),
    )


def downgrade() -> None:
    """删除 payload 列。"""
    op.drop_column("node_states", "payload")
