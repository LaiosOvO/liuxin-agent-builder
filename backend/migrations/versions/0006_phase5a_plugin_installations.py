"""Phase 5.A — workspace_plugin_installations 表（PLUG-FW-08）。

Dify-style PlatformPlugin 框架的 per-workspace 安装态持久化表。

设计参考 docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md：
- 借鉴点 #1（Declaration vs Installation 分离）：本表对应 Installation 层
  · workspace_id × plugin_name 唯一约束保证 per-tenant 隔离
- 借鉴点 #3（PluginInstallTask 状态机）：status enum 简化为 installed/disabled/error
  · CHECK constraint 强校验（DB 层兜底，service 层不可绕过）

字段设计：
- id UUID PK（DB 端 gen_random_uuid() default）
- workspace_id UUID NOT NULL（CLAUDE.md §2.4 多租户基线第一列）
- plugin_name / plugin_version TEXT NOT NULL
- status TEXT NOT NULL default 'installed' + CHECK
- config_json JSONB NOT NULL default '{}'（per-workspace 配置实例）
- credentials_json JSONB NULL（Phase 5.C 改 bytea 存密文）
- installed_at / updated_at TIMESTAMPTZ default now()

约束：
- UNIQUE (workspace_id, plugin_name) — 同 workspace 不能装同名 plugin 两次
- CHECK status IN ('installed', 'disabled', 'error') — Dify install 状态机简化
- INDEX (workspace_id, status) — workspace 列 plugin 时按状态过滤

不引入：
- FK 到 workspaces 表（避免循环依赖；workspace 删除时由 service 层主动清理）
- payload / settings 等额外列（YAGNI；Phase 5.B/5.C 真需要时再加列）

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 workspace_plugin_installations 表 + 唯一约束 + CHECK + 索引。"""
    op.create_table(
        "workspace_plugin_installations",
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
            "plugin_name",
            sa.Text(),
            nullable=False,
            comment="plugin manifest.name（小写蛇形）",
        ),
        sa.Column(
            "plugin_version",
            sa.Text(),
            nullable=False,
            comment="plugin manifest.version（SemVer）",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="installed",
            comment="状态：installed / disabled / error",
        ),
        sa.Column(
            "config_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="per-workspace 配置（对应 manifest.config_schema instance）",
        ),
        sa.Column(
            "credentials_json",
            postgresql.JSONB,
            nullable=True,
            comment="加密凭据（Phase 5.C 改 bytea）",
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
        # workspace_id × plugin_name 唯一约束（per-workspace 隔离）
        sa.UniqueConstraint(
            "workspace_id",
            "plugin_name",
            name="uq_workspace_plugin",
        ),
        # status 三态 CHECK 约束（DB 层兜底）
        sa.CheckConstraint(
            "status IN ('installed', 'disabled', 'error')",
            name="ck_plugin_status",
        ),
    )

    # 复合索引：workspace 列出本租户 plugin 时按状态过滤
    op.create_index(
        "ix_workspace_plugin_workspace_status",
        "workspace_plugin_installations",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    """回滚：删除索引 → 删除表（CHECK / UNIQUE / PK 随表自动删）。"""
    op.drop_index(
        "ix_workspace_plugin_workspace_status",
        table_name="workspace_plugin_installations",
    )
    op.drop_table("workspace_plugin_installations")
