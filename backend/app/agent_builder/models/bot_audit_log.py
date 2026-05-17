"""Phase 4.5 — bot_audit_logs ORM 模型（R-IM-11 dispatch 审计日志）。

表：bot_audit_logs
用途：bot dispatcher 每次 dispatch 入库（who / cmd / args / outcome / latency / route source）

设计参考：
- audit_logs 0001 模式（BIGSERIAL PK 时序有序 + JSONB meta）
- docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md §可借鉴的设计模式 #5 + #6
- Phase 3 NET-05 schema 模式

字段语义：
- outcome：dispatch 结果（5 值 CHECK）
    · success         — handler 正常返回
    · permission_denied — 角色不在 allowed_roles
    · rate_limited      — 触发 RateLimitSpec.per_user_per_minute 闸
    · parse_failed      — parser 解析参数失败 / LLM router timeout
    · handler_error     — handler 抛异常被 dispatcher try/except 兜住

- routed_via：本次 dispatch 是从哪条路径路由到 handler 的（4 值 CHECK）
    · slash_command — 显式 slash 命令（如 "@bot start it.charlie"）
    · keyword       — 关键词短路（如 "我要离职"）
    · llm_intent    — LLM 兜底路由
    · ai_qa         — LLM 自由问答兜底（routed_via=ai_qa 不对应 commands.name）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agent_builder.db.base import Base


# CHECK 约束的合法值集合（与 dispatcher 业务代码必须保持一致）
_OUTCOME_VALUES: tuple[str, ...] = (
    "success",
    "permission_denied",
    "rate_limited",
    "parse_failed",
    "handler_error",
)

_ROUTED_VIA_VALUES: tuple[str, ...] = (
    "slash_command",
    "keyword",
    "llm_intent",
    "ai_qa",
)


def _quoted_values(values: tuple[str, ...]) -> str:
    """生成 CHECK 约束 SQL 字符串：('a', 'b', 'c')。"""
    return ", ".join(f"'{v}'" for v in values)


class BotAuditLog(Base):
    """bot dispatch 审计日志（R-IM-11，append-only）。

    BIGSERIAL PK 保证时序有序，写入频率高（每条 IM 消息 1 条审计），
    BIGINT 比 UUID 索引空间小、scan 顺序友好。

    workspace_id NOT NULL：bot dispatch 永远在 workspace 内，与 audit_logs 表
    （workspace_id nullable 支持系统级事件如 setup）语义不同。
    """

    __tablename__ = "bot_audit_logs"

    # ── 主键 ────────────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="自增 ID（BIGSERIAL，时序有序）",
    )

    # ── 多租户 + bot 标识 ──────────────────────────────────────────────────────
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        comment="所属 workspace（多租户基线第一列）",
    )
    bot_name: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="bot.yaml.name（dispatch 早期阶段就能确定）",
    )

    # ── sender 身份 ────────────────────────────────────────────────────────────
    sender_name: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="IM sender 用户名（mm_username / lark_open_id 等）",
    )
    sender_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=True,
        comment="对齐到 agent-builder users.id 后的 UUID（身份对齐失败则 NULL）",
    )

    # ── 命令 + 参数 ───────────────────────────────────────────────────────────
    cmd_name: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="命令名（命中 commands.name；ai_qa 等无命令时 NULL）",
    )
    cmd_args_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="命令参数（JSONB，校验通过后的 args dict）",
    )
    raw_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="原始 IM 消息（最长 4096 字符；dispatcher 入口截断防 OOM）",
    )

    # ── 结果 + 错误 ───────────────────────────────────────────────────────────
    outcome: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="dispatch 结果（5 值：success/permission_denied/rate_limited/parse_failed/handler_error）",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="错误摘要（最长 1024 字符；outcome != success 时一般非空）",
    )

    # ── 性能 + 路由元数据 ────────────────────────────────────────────────────
    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="dispatch 总耗时（毫秒；从 listener 收消息到 handler 返回）",
    )
    routed_via: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="路由来源（slash_command / keyword / llm_intent / ai_qa）",
    )
    llm_confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="LLM intent router 输出 confidence（仅 routed_via=llm_intent 有值）",
    )

    # ── 时间字段 ───────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="审计记录写入时间",
    )

    # ── 约束 + 索引 ────────────────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            f"outcome IN ({_quoted_values(_OUTCOME_VALUES)})",
            name="ck_bot_audit_outcome",
        ),
        CheckConstraint(
            f"routed_via IN ({_quoted_values(_ROUTED_VIA_VALUES)})",
            name="ck_bot_audit_routed_via",
        ),
        CheckConstraint(
            "char_length(raw_message) <= 4096",
            name="ck_bot_audit_raw_message_length",
        ),
        CheckConstraint(
            "char_length(error_message) <= 1024",
            name="ck_bot_audit_error_message_length",
        ),
        # 索引 1：workspace 视角时序查询（最常用）
        Index(
            "ix_bot_audit_workspace_created",
            "workspace_id",
            "created_at",
        ),
        # 索引 2：错误告警 / 监控按 outcome 过滤
        Index(
            "ix_bot_audit_outcome_created",
            "outcome",
            "created_at",
        ),
        # 索引 3：bot 级监控（按 bot_name 过滤时序）
        Index(
            "ix_bot_audit_bot_name_created",
            "bot_name",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<BotAuditLog id={self.id} ws={self.workspace_id} "
            f"bot={self.bot_name!r} cmd={self.cmd_name!r} outcome={self.outcome}>"
        )
