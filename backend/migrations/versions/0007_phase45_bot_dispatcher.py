"""Phase 4.5 — workspace_bot_installations + bot_audit_logs 两表。

新增表：
1. workspace_bot_installations — per-workspace bot 安装态（仿 0006 plugin 模式）
   字段：id / workspace_id / bot_name / yaml_path / status / config_snapshot_json /
        last_error / installed_at / updated_at
   约束：UNIQUE (workspace_id, bot_name) + CHECK status / 两索引

2. bot_audit_logs — bot dispatcher 审计日志（仿 0001 audit_logs BIGSERIAL 模式）
   字段：id (BIGSERIAL) / workspace_id (NOT NULL) / bot_name / sender_name /
        sender_user_id / cmd_name / cmd_args_json / raw_message / outcome /
        error_message / latency_ms / routed_via / llm_confidence / created_at
   约束：CHECK outcome (5 值) + CHECK routed_via (4 值) + 长度 CHECK / 三索引

CHECK 值集合（与 ORM 模型 / dispatcher 业务代码保持一致）：
- outcome: success | permission_denied | rate_limited | parse_failed | handler_error
- routed_via: slash_command | keyword | llm_intent | ai_qa

设计依据：
- docs/plans/2026-05-17-im-bot-abstraction-design.md §3 R-IM-11/R-IM-12
- .planning/phases/04_5-bot-triggers/04_5-RESEARCH.md Architecture Patterns Pattern 6
- 与 Phase 5.A 0006 migration 同结构（gen_random_uuid() / JSONB / TIMESTAMPTZ）

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 workspace_bot_installations + bot_audit_logs 双表 + 约束 + 索引。"""

    # ─── 表 1: workspace_bot_installations ──────────────────────────────────
    op.create_table(
        "workspace_bot_installations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="安装记录 UUID",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属 workspace（多租户基线第一列）",
        ),
        sa.Column(
            "bot_name",
            sa.Text(),
            nullable=False,
            comment="bot.yaml.name（小写蛇形 + 连字符）",
        ),
        sa.Column(
            "yaml_path",
            sa.Text(),
            nullable=False,
            comment="bot.yaml 文件路径",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="enabled",
            comment="状态：enabled / disabled / error",
        ),
        sa.Column(
            "config_snapshot_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="bot.yaml 加载时的快照",
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
            comment="最近一次启动 / dispatch 失败的错误摘要",
        ),
        sa.Column(
            "installed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="首次安装时间",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="最后更新时间",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "bot_name",
            name="uq_workspace_bot",
        ),
        sa.CheckConstraint(
            "status IN ('enabled', 'disabled', 'error')",
            name="ck_bot_installation_status",
        ),
    )

    op.create_index(
        "ix_workspace_bot_workspace_status",
        "workspace_bot_installations",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_workspace_bot_status_updated",
        "workspace_bot_installations",
        ["status", "updated_at"],
    )

    # ─── 表 2: bot_audit_logs ───────────────────────────────────────────────
    # 设计说明：
    #   outcome 5 值含义：
    #     - success: handler 正常返回
    #     - permission_denied: 角色不在 allowed_roles
    #     - rate_limited: 触发 per_user_per_minute 闸
    #     - parse_failed: parser 解析参数失败 / LLM router timeout
    #     - handler_error: handler 抛异常被 dispatcher try/except 兜住
    #   routed_via 4 值含义：
    #     - slash_command: 显式 slash 命令
    #     - keyword: 关键词短路
    #     - llm_intent: LLM 兜底路由
    #     - ai_qa: LLM 自由问答兜底
    op.create_table(
        "bot_audit_logs",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            comment="自增 ID（BIGSERIAL）",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属 workspace（多租户基线第一列）",
        ),
        sa.Column(
            "bot_name",
            sa.Text(),
            nullable=True,
            comment="bot.yaml.name",
        ),
        sa.Column(
            "sender_name",
            sa.Text(),
            nullable=True,
            comment="IM sender 用户名",
        ),
        sa.Column(
            "sender_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="对齐到 agent-builder users.id 后的 UUID",
        ),
        sa.Column(
            "cmd_name",
            sa.Text(),
            nullable=True,
            comment="命令名（命中 commands.name 时非空）",
        ),
        sa.Column(
            "cmd_args_json",
            postgresql.JSONB,
            nullable=True,
            comment="命令参数（校验通过后的 args dict）",
        ),
        sa.Column(
            "raw_message",
            sa.Text(),
            nullable=True,
            comment="原始 IM 消息（最长 4096 字符，CHECK 强校验）",
        ),
        sa.Column(
            "outcome",
            sa.Text(),
            nullable=False,
            comment="dispatch 结果（5 值 CHECK 约束）",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="错误摘要（最长 1024 字符，CHECK 强校验）",
        ),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="dispatch 总耗时（毫秒）",
        ),
        sa.Column(
            "routed_via",
            sa.Text(),
            nullable=False,
            comment="路由来源（4 值 CHECK 约束）",
        ),
        sa.Column(
            "llm_confidence",
            sa.Float(),
            nullable=True,
            comment="LLM intent router confidence（仅 routed_via=llm_intent 有值）",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="审计记录写入时间",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'permission_denied', 'rate_limited', "
            "'parse_failed', 'handler_error')",
            name="ck_bot_audit_outcome",
        ),
        sa.CheckConstraint(
            "routed_via IN ('slash_command', 'keyword', 'llm_intent', 'ai_qa')",
            name="ck_bot_audit_routed_via",
        ),
        sa.CheckConstraint(
            "char_length(raw_message) <= 4096",
            name="ck_bot_audit_raw_message_length",
        ),
        sa.CheckConstraint(
            "char_length(error_message) <= 1024",
            name="ck_bot_audit_error_message_length",
        ),
    )

    op.create_index(
        "ix_bot_audit_workspace_created",
        "bot_audit_logs",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_bot_audit_outcome_created",
        "bot_audit_logs",
        ["outcome", "created_at"],
    )
    op.create_index(
        "ix_bot_audit_bot_name_created",
        "bot_audit_logs",
        ["bot_name", "created_at"],
    )


def downgrade() -> None:
    """回滚：反向删除索引 → 删除表（CHECK / UNIQUE 随表删）。"""
    # bot_audit_logs
    op.drop_index("ix_bot_audit_bot_name_created", table_name="bot_audit_logs")
    op.drop_index("ix_bot_audit_outcome_created", table_name="bot_audit_logs")
    op.drop_index("ix_bot_audit_workspace_created", table_name="bot_audit_logs")
    op.drop_table("bot_audit_logs")

    # workspace_bot_installations
    op.drop_index(
        "ix_workspace_bot_status_updated",
        table_name="workspace_bot_installations",
    )
    op.drop_index(
        "ix_workspace_bot_workspace_status",
        table_name="workspace_bot_installations",
    )
    op.drop_table("workspace_bot_installations")
