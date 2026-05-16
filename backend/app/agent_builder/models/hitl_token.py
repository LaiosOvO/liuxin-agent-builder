"""HITL 决策 token ORM 模型（HITL-01 / HITL-03 / AUTH-05 基础表）。

表：hitl_tokens
用途：每次 HITL 节点 enter 时为当前 actor 的每个 allowed_action 生成独立 JWT，
     jti 写入此表用作"一次性消费"凭证。

设计参考 docs/reading-dify-03-01-hitl-schema-2026-05-17.md：
- Dify HumanInputForm + Delivery + Recipient 三表分离 → 我们简化为单表 hitl_tokens
  统管 jti（Recipient.access_token 概念）+ actor + action + used_*（Form.submitted_*）
- jti = JWT payload 中 jti claim（UUID），用作 PK，UNIQUE 由 PK 天然保证
- 原子消费：`UPDATE ... WHERE used_at IS NULL RETURNING *` 零行返回 = 已被消费（409）
- 索引参考 Dify (status, expiration_time) 模式 → 这里建 3 个复合索引：
  · (node_state_id, used_at) — POST 决策时同 node 其他 token 一并失效
  · (actor_id, expires_at) — 用户审批历史 + 超时 token 列表
  · (instance_id, action) — 流程审计 / 决策回放

CLAUDE.md 2.4 多租户：本表 FK 链路到 flow_instance（FlowInstance.workspace_id 已存），
不再冗余存 workspace_id 列（通过 instance_id JOIN 即可，且查询路径都有 instance_id 入口）。
注：与 audit_log 同步加 workspace_id 是为了直接审计列表过滤；本表查询入口都已是 instance/node_state，无需冗余。

CLAUDE.md 2.5 GET 不消费 jti：本表的 used_at 仅由 POST /hitl/action 路径写入，
GET /hitl/page 仅检查 expires_at + 签名，不动 used_at。

不引入 SQLAlchemy relationship（保持轻量；Service 层显式 JOIN）。
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class HitlToken(Base):
    """HITL 决策 token（jti 一次性消费）。

    生命周期：
    1. node enter 时 service 层 INSERT（每个 allowed_action 一行）
    2. POST /hitl/action/<jwt> 校验签名 + exp + jti 未消费 → 原子 UPDATE used_at
    3. 同 node_state_id 下其他 jti 一并 used_at=NOW()（HITL-01 防止重复决策）
    """

    __tablename__ = "hitl_tokens"

    # ── 主键（jti = JWT payload.jti claim） ────────────────────────────────────
    jti: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="JWT jti claim（UUID），用作一次性消费凭证 PK",
    )

    # ── 关联（FK 不冗余存 workspace_id，通过 instance 路径已隔离） ──────────────
    instance_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("flow_instances.id", ondelete="CASCADE"),
        nullable=False,
        comment="流程实例 UUID（ON DELETE CASCADE，实例删除时 token 一并清理）",
    )
    node_state_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("node_states.id", ondelete="CASCADE"),
        nullable=False,
        comment="节点状态 UUID（ON DELETE CASCADE）",
    )
    actor_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="决策人 user_id（ON DELETE RESTRICT，保证审计可追溯）",
    )
    action: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="允许的决策动作：submit / approve / return / reject",
    )

    # ── 时间字段 ──────────────────────────────────────────────────────────────
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="token 过期时间（与 JWT exp claim 一致）",
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="消费时间（NULL = 未消费）；POST /hitl/action 路径才写入",
    )

    # ── 审计字段（NET-05 关联） ───────────────────────────────────────────────
    used_ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="消费时的客户端 IP（INET 不用 v4/v6 兼容；NULL = 未消费）",
    )
    used_ua: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="消费时的客户端 User-Agent（截断 256 字符）",
    )

    # ── 创建时间 ──────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        comment="token 签发时间",
    )

    # ── 索引（参考 Dify human_input_forms (status, expiration_time) 模式） ────
    __table_args__ = (
        # 同 node_state 下未消费 token 失效扫描 + 重复提交检测
        Index("ix_hitl_tokens_node_state_used", "node_state_id", "used_at"),
        # 用户审批历史 + 超时 token 列表
        Index("ix_hitl_tokens_actor_exp", "actor_id", "expires_at"),
        # 流程审计 / 决策回放
        Index("ix_hitl_tokens_instance_action", "instance_id", "action"),
    )

    def __repr__(self) -> str:
        consumed = "consumed" if self.used_at else "active"
        return f"<HitlToken jti={self.jti} action={self.action!r} {consumed}>"
