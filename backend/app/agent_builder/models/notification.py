"""通知投递记录 ORM 模型（NOTI-01 邮件 + NOTI-09 催办 + 后续 IM 通用基础）。

表：notifications
用途：每次通知投递（首次发送 + 催办 + 升级）创建一条记录。
     UNIQUE 约束保证 (instance_id, node_state_id, channel, recipient, reminder_round) 不重复，
     防多 worker 并发抢锁时重复发送（NOTI-09 催办场景）。

设计参考 docs/reading-dify-03-01-hitl-schema-2026-05-17.md：
- Dify HumanInputDelivery + HumanInputFormRecipient 合并为一张表
- (status, created_at) 复合索引参考 Dify (status, expiration_time) 模式 → 加速重试 worker 扫描
- payload JSONB 存渲染后的内容（subject/body_html/body_text/buttons），方便 03-09 催办 worker 直接重发同模板

CLAUDE.md 2.4 多租户：workspace_id 第一列（复合索引主键）;
列表查询 workspace_id 必须出现在 WHERE 第一条件。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


class Notification(Base):
    """通知投递记录。

    生命周期：
    1. node enter 时为每个 recipient + reminder_round=0 INSERT 一条（status=pending）
    2. arq worker 取出 → status=sending → 发送 → status=sent / failed
    3. 催办 worker 创建 reminder_round=1/2/3 新记录（UNIQUE 保证不会重复）

    设计取舍：
    - id 用 BIGSERIAL（高频写入 + 时序有序），与 audit_log 一致风格
    - status 用 VARCHAR(16)（参考 Dify EnumText 模式，可读性优于 ENUM）
    - payload JSONB 存渲染后内容，重试 / 催办时直接 re-send 同样模板
    """

    __tablename__ = "notifications"

    # ── 主键 ──────────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="自增 ID（BIGSERIAL，时序有序）",
    )

    # ── 多租户隔离（必须出现在索引第一列） ────────────────────────────────────
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属工作区（ON DELETE CASCADE）",
    )

    # ── 关联 ──────────────────────────────────────────────────────────────────
    instance_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("flow_instances.id", ondelete="CASCADE"),
        nullable=False,
        comment="流程实例 UUID（ON DELETE CASCADE）",
    )
    node_state_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("node_states.id", ondelete="CASCADE"),
        nullable=False,
        comment="节点状态 UUID（ON DELETE CASCADE）",
    )

    # ── 通道 + 收件人 ─────────────────────────────────────────────────────────
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="通道：email / feishu / wechat / dingtalk / slack / mattermost / webhook",
    )
    recipient: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="收件人地址：email 邮箱 / IM user_id / webhook URL",
    )
    reminder_round: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="催办轮次：0=首次发送，1=首催，2=二催，3=升级（NOTI-09）",
    )

    # ── 状态 + 内容 ──────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="pending",
        comment="状态：pending / sending / sent / failed",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
        comment="渲染后的内容（subject/body_html/body_text/buttons），debug + 重试用",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息（status=failed 时记录）",
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="实际发送时间（status=sent 时写入）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        comment="创建时间（入队时间）",
    )

    # ── 约束 + 索引 ──────────────────────────────────────────────────────────
    __table_args__ = (
        # NOTI-09 催办去重：同 (instance, node_state, channel, recipient, round) 唯一
        UniqueConstraint(
            "instance_id",
            "node_state_id",
            "channel",
            "recipient",
            "reminder_round",
            name="uq_notifications_dedup",
        ),
        # NOTI-10 重试 worker 扫描：(status, created_at) 复合索引（参考 Dify 模式）
        Index("ix_notifications_status_created", "status", "created_at"),
        # 工作区 + 实例（实例详情页通知列表）
        Index("ix_notifications_workspace_instance", "workspace_id", "instance_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} "
            f"channel={self.channel!r} "
            f"status={self.status!r} "
            f"round={self.reminder_round}>"
        )
