"""Phase 4 — hitl_tokens 加 (instance_id, used_at) partial index 加速 invalidate_chain 扫描。

设计参考：
- docs/reading-dify-04-01-chain-payload-2026-05-17.md §3 invalidate_chain 性能要求
- 04-RESEARCH.md §六 invalidate_chain 跨 instance 失效扫描

Why partial index `WHERE used_at IS NULL`：
- invalidate_chain 仅扫描未消费 token（`used_at IS NULL`）
- partial index 体积更小（已消费 token 不入索引），更新代价更低
- 与 Phase 3 0003 migration 中其他 hitl_tokens 索引风格保持一致（节约空间）

Why 不放 0004：
- 现有 0004 migration（0004_phase3_node_state_payload.py）已占用 revision='0004'
- 本 migration 沿用顺序号 0005，down_revision='0004'

不破坏既有索引：
- 现有 ix_hitl_tokens_node_state_used (node_state_id, used_at) — invalidate_siblings 用
- 新增 ix_hitl_tokens_instance_used (instance_id, used_at) WHERE used_at IS NULL — invalidate_chain 用
- 两个索引并存，相互独立，覆盖不同 scope（节点级 vs 实例级）

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加 partial index 加速 invalidate_chain 跨 instance 扫描未消费 token。"""
    # partial index：仅索引 used_at IS NULL 的行（即未消费 token）
    # invalidate_chain 的查询条件：
    #   WHERE instance_id = :iid AND used_at IS NULL AND jti != :except_jti
    # → 该索引直接命中前两个条件，jti != ... 通过堆扫描过滤（基数小，可接受）
    op.create_index(
        "ix_hitl_tokens_instance_used",
        "hitl_tokens",
        ["instance_id", "used_at"],
        postgresql_where=sa.text("used_at IS NULL"),
    )


def downgrade() -> None:
    """回滚：删除 partial index。"""
    op.drop_index("ix_hitl_tokens_instance_used", table_name="hitl_tokens")
