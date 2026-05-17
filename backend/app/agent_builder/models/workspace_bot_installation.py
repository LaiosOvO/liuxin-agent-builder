"""Phase 4.5 — workspace_bot_installations ORM 模型。

表：workspace_bot_installations
用途：per-workspace bot 安装态持久化 —— bot.yaml + workspace 绑定的 hybrid 模式。

设计参考 docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md §可借鉴的设计模式 #5
（tenant_id 注入 + 资源隔离），与 Phase 5.A workspace_plugin_installations
（0006）保持一致结构。

生命周期：
1. Service 层 install(workspace_id, yaml_path) → INSERT status='enabled'
2. 配置 / 凭据更新 → UPDATE config_snapshot_json + updated_at=now()
3. 用户停用 → UPDATE status='disabled'
4. 启动 listener 失败 → UPDATE status='error' + last_error=...
5. 卸载 → DELETE（不软删）

CLAUDE.md §2.4 多租户：
- workspace_id 显式列 + 复合索引第一列
- workspace_id × bot_name 唯一约束 —— 一个 workspace 不能装同 bot 两次
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class WorkspaceBotInstallation(Base):
    """Per-workspace bot 安装态记录。

    并发安全：
    - workspace_id × bot_name 唯一约束防同 workspace 重复装
    - 多 worker install 同 bot 并发：UNIQUE 触发 IntegrityError，由 Service 层翻译为 409
    """

    __tablename__ = "workspace_bot_installations"

    # ── 主键 ────────────────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("gen_random_uuid()"),
        comment="安装记录 UUID（gen_random_uuid() 由 DB 端生成；ORM default 双保险）",
    )

    # ── 多租户 + bot 标识 ──────────────────────────────────────────────────────
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        comment="所属 workspace（CLAUDE.md §2.4 多租户基线第一列）",
    )
    bot_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="bot.yaml 中 name 字段（匹配 ^[a-z][a-z0-9_-]{2,31}$）",
    )
    yaml_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="bot.yaml 文件路径（相对 plugins/bots/ 或绝对路径）",
    )

    # ── 状态机（与 0006 workspace_plugin_installations 一致策略）───────────────
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="enabled",
        comment="状态：enabled / disabled / error（CHECK 强校验）",
    )

    # ── 配置快照 + 错误信息 ────────────────────────────────────────────────────
    config_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        comment="bot.yaml 加载时的快照（防 YAML 文件被改后 listener 与 DB 不一致）",
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="最近一次 listener 启动 / handler dispatch 失败的错误摘要（status=error 必填）",
    )

    # ── 时间字段 ───────────────────────────────────────────────────────────────
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        comment="首次安装时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        comment="最后更新时间（status / config / last_error 任意变更）",
    )

    # ── 约束 + 索引 ────────────────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "bot_name",
            name="uq_workspace_bot",
        ),
        CheckConstraint(
            "status IN ('enabled', 'disabled', 'error')",
            name="ck_bot_installation_status",
        ),
        # 索引：(workspace_id, status) — workspace 列出本租户已装 bot（filter status）
        Index(
            "ix_workspace_bot_workspace_status",
            "workspace_id",
            "status",
        ),
        # 索引：(status, updated_at) — 错误 bot 巡检 / 监控告警
        Index(
            "ix_workspace_bot_status_updated",
            "status",
            "updated_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkspaceBotInstallation ws={self.workspace_id} "
            f"name={self.bot_name!r} status={self.status}>"
        )
