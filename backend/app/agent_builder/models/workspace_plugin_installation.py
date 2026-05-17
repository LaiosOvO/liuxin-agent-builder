"""Phase 5.A — workspace_plugin_installations ORM 模型（PLUG-FW-08）。

表：workspace_plugin_installations
用途：per-workspace plugin 安装态持久化 —— Dify-style PlatformPlugin 框架的「Installation」层。

设计参考 docs/reading-dify-05a-01-plugin-architecture-2026-05-17.md：
- 借鉴点 #1（Declaration vs Installation 分离）：本表对应 Installation 层
  · Declaration（manifest YAML，静态共享）由 Plan 03 PlatformManifest 处理
  · Runtime Entity（daemon facade）由 Plan 05+ PlatformPlugin 处理
- 借鉴点 #3（PluginInstallTask 状态机简化）：status enum 三态
  · installed: 装好可用
  · disabled: 临时禁用（凭据失效 / 用户手动停用）
  · error: 启动 daemon 失败 / manifest 校验失败

CLAUDE.md §2.4 多租户：
- workspace_id 显式列 + 复合索引第一列 (workspace_id, status)
- workspace_id × plugin_name 唯一约束 —— 一个 workspace 不能装同名 plugin 两次

CLAUDE.md immutability：
- mapped_column + type annotations
- 不引入 relationship（保持轻量；后续 Service 层显式 JOIN）

字段对照（与 0006 migration 必须完全一致）：
- id UUID PK default gen_random_uuid()
- workspace_id UUID NOT NULL
- plugin_name TEXT NOT NULL（匹配 manifest.name pattern: ^[a-z][a-z0-9_-]{2,31}$）
- plugin_version TEXT NOT NULL（匹配 manifest.version pattern: ^\\d+\\.\\d+\\.\\d+$）
- status TEXT NOT NULL default 'installed' + CheckConstraint
- config_json JSONB NOT NULL default '{}'（per-workspace 配置，对应 manifest.config_schema instance）
- credentials_json JSONB NULL（加密存；Phase 5.C IMCredentialsManager 复用时改 bytea）
- installed_at / updated_at TIMESTAMPTZ default now()
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


class WorkspacePluginInstallation(Base):
    """Per-workspace plugin 安装态记录。

    生命周期：
    1. Plan 04 Registry.install(workspace_id, manifest_path) → INSERT status='installed'
    2. 凭据 / 配置更新 → UPDATE config_json / credentials_json + updated_at=now()
    3. 用户停用 → UPDATE status='disabled'
    4. daemon 启动失败 → UPDATE status='error'
    5. 卸载 → DELETE（不软删，cascade 跟 manifest 同步）

    并发安全：
    - workspace_id × plugin_name 唯一约束防同 workspace 重复装
    - 多 worker install 同 plugin 并发：UNIQUE 约束触发 IntegrityError，由 Service 层翻译为 409 Conflict
    """

    __tablename__ = "workspace_plugin_installations"

    # ── 主键 ────────────────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("gen_random_uuid()"),
        comment="安装记录 UUID（gen_random_uuid 与 DB 端 default 同义，双 default 安全）",
    )

    # ── 多租户 + plugin 标识 ───────────────────────────────────────────────────
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        comment="所属 workspace（CLAUDE.md §2.4 多租户基线第一列）",
    )
    plugin_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="plugin manifest.name（小写蛇形，匹配 ^[a-z][a-z0-9_-]{2,31}$）",
    )
    plugin_version: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="plugin manifest.version（SemVer，匹配 ^\\d+\\.\\d+\\.\\d+$）",
    )

    # ── 状态机（Dify InstallPluginMessage.Event 简化版）─────────────────────────
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="installed",
        comment="状态：installed / disabled / error（CHECK constraint 强校验）",
    )

    # ── 配置 / 凭据（per-workspace）─────────────────────────────────────────────
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        comment="per-workspace 配置（对应 manifest.config_schema 的 instance）",
    )
    credentials_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="加密凭据（Phase 5.C IMCredentialsManager 复用时改 bytea 存密文）",
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
        comment="最后更新时间（status / config / credentials 任意变更）",
    )

    # ── 约束 + 索引 ────────────────────────────────────────────────────────────
    __table_args__ = (
        # workspace_id × plugin_name 唯一约束（per-workspace 隔离）
        UniqueConstraint(
            "workspace_id",
            "plugin_name",
            name="uq_workspace_plugin",
        ),
        # status 三态校验（Dify InstallPluginMessage.Event 简化版）
        CheckConstraint(
            "status IN ('installed', 'disabled', 'error')",
            name="ck_plugin_status",
        ),
        # 索引：(workspace_id, status) — workspace 列出本租户已装 plugin（filter status）
        Index(
            "ix_workspace_plugin_workspace_status",
            "workspace_id",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkspacePluginInstallation ws={self.workspace_id} "
            f"name={self.plugin_name!r} v={self.plugin_version} status={self.status}>"
        )
