"""Phase 3 HITL schema 初始化。

2 张新表：hitl_tokens / notifications
audit_logs ALTER ADD COLUMN x4（NET-05 决策审计字段）

设计参考：
- docs/reading-dify-03-01-hitl-schema-2026-05-17.md
  · Dify human_input_forms (status, expiration_time) 索引模式 → 我们的
    notifications (status, created_at) 索引
  · jti UUID PK + UPDATE...WHERE used_at IS NULL RETURNING 原子消费

设计要点：
- hitl_tokens.jti UUID PRIMARY KEY（一次性消费凭证）
- notifications UNIQUE (instance_id, node_state_id, channel, recipient, reminder_round)
  保证 NOTI-09 催办去重
- audit_logs ALTER ADD COLUMN nullable（向后兼容，Phase 1 已写入的行不需要回填）

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 Phase 3 HITL 相关的 2 张表 + audit_logs alter。"""

    # ── 1. hitl_tokens ───────────────────────────────────────────────────────
    op.create_table(
        "hitl_tokens",
        sa.Column(
            "jti",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="JWT jti claim（UUID），用作一次性消费凭证 PK",
        ),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_instances.id", ondelete="CASCADE"),
            nullable=False,
            comment="流程实例 UUID（ON DELETE CASCADE）",
        ),
        sa.Column(
            "node_state_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("node_states.id", ondelete="CASCADE"),
            nullable=False,
            comment="节点状态 UUID（ON DELETE CASCADE）",
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            comment="决策人 user_id（ON DELETE RESTRICT，审计可追溯）",
        ),
        sa.Column(
            "action",
            sa.String(16),
            nullable=False,
            comment="允许的决策动作：submit / approve / return / reject",
        ),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="token 过期时间（与 JWT exp claim 一致）",
        ),
        sa.Column(
            "used_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="消费时间（NULL = 未消费）",
        ),
        sa.Column(
            "used_ip",
            sa.String(64),
            nullable=True,
            comment="消费时的客户端 IP（NULL = 未消费）",
        ),
        sa.Column(
            "used_ua",
            sa.String(256),
            nullable=True,
            comment="消费时的客户端 User-Agent",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="token 签发时间",
        ),
    )
    # 同 node_state 下未消费 token 失效扫描 + 重复提交检测
    op.create_index(
        "ix_hitl_tokens_node_state_used",
        "hitl_tokens",
        ["node_state_id", "used_at"],
    )
    # 用户审批历史 + 超时 token 列表
    op.create_index(
        "ix_hitl_tokens_actor_exp",
        "hitl_tokens",
        ["actor_id", "expires_at"],
    )
    # 流程审计 / 决策回放
    op.create_index(
        "ix_hitl_tokens_instance_action",
        "hitl_tokens",
        ["instance_id", "action"],
    )

    # ── 2. notifications ─────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            sa.BigInteger,
            primary_key=True,
            autoincrement=True,
            comment="自增 ID（BIGSERIAL，时序有序）",
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
            comment="流程实例 UUID（ON DELETE CASCADE）",
        ),
        sa.Column(
            "node_state_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("node_states.id", ondelete="CASCADE"),
            nullable=False,
            comment="节点状态 UUID（ON DELETE CASCADE）",
        ),
        sa.Column(
            "channel",
            sa.String(32),
            nullable=False,
            comment="通道：email / feishu / wechat / dingtalk / slack / mattermost / webhook",
        ),
        sa.Column(
            "recipient",
            sa.String(256),
            nullable=False,
            comment="收件人：email 邮箱 / IM user_id / webhook URL",
        ),
        sa.Column(
            "reminder_round",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="催办轮次：0=首次发送，1=首催，2=二催，3=升级",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
            comment="状态：pending / sending / sent / failed",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
            comment="渲染后内容（subject/body_html/body_text/buttons）",
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
            comment="错误信息（status=failed 时记录）",
        ),
        sa.Column(
            "sent_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="实际发送时间",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="创建时间（入队时间）",
        ),
    )
    # NOTI-09 催办去重 UNIQUE 约束
    op.create_unique_constraint(
        "uq_notifications_dedup",
        "notifications",
        ["instance_id", "node_state_id", "channel", "recipient", "reminder_round"],
    )
    # NOTI-10 重试 worker 扫描（参考 Dify (status, expiration_time) 模式）
    op.create_index(
        "ix_notifications_status_created",
        "notifications",
        ["status", "created_at"],
    )
    # 实例详情页通知列表
    op.create_index(
        "ix_notifications_workspace_instance",
        "notifications",
        ["workspace_id", "instance_id"],
    )

    # ── 3. audit_logs ALTER（NET-05 决策审计字段） ────────────────────────────
    op.add_column(
        "audit_logs",
        sa.Column(
            "actor_ip",
            sa.String(64),
            nullable=True,
            comment="HITL 决策的客户端 IP（NET-05）",
        ),
    )
    op.add_column(
        "audit_logs",
        sa.Column(
            "actor_ua",
            sa.String(256),
            nullable=True,
            comment="HITL 决策的 User-Agent（NET-05）",
        ),
    )
    op.add_column(
        "audit_logs",
        sa.Column(
            "decision",
            sa.String(32),
            nullable=True,
            comment="决策动作：submit / approve / return / reject（NET-05）",
        ),
    )
    op.add_column(
        "audit_logs",
        sa.Column(
            "node_state_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="关联节点状态 UUID（NET-05）",
        ),
    )
    op.create_index(
        "ix_audit_logs_node_state",
        "audit_logs",
        ["node_state_id"],
    )


def downgrade() -> None:
    """按 FK 依赖逆序删除 Phase 3 表 + 回滚 audit_logs alter。"""

    # ── audit_logs 回滚（先删 index 再 drop column） ──────────────────────────
    op.drop_index("ix_audit_logs_node_state", table_name="audit_logs")
    op.drop_column("audit_logs", "node_state_id")
    op.drop_column("audit_logs", "decision")
    op.drop_column("audit_logs", "actor_ua")
    op.drop_column("audit_logs", "actor_ip")

    # ── notifications 删除（先 drop index/uq 再 drop table） ─────────────────
    op.drop_index("ix_notifications_workspace_instance", table_name="notifications")
    op.drop_index("ix_notifications_status_created", table_name="notifications")
    op.drop_constraint("uq_notifications_dedup", "notifications", type_="unique")
    op.drop_table("notifications")

    # ── hitl_tokens 删除 ──────────────────────────────────────────────────────
    op.drop_index("ix_hitl_tokens_instance_action", table_name="hitl_tokens")
    op.drop_index("ix_hitl_tokens_actor_exp", table_name="hitl_tokens")
    op.drop_index("ix_hitl_tokens_node_state_used", table_name="hitl_tokens")
    op.drop_table("hitl_tokens")
