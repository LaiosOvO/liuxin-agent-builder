"""Notification 节点 executor — 独立通知节点（NODE-07 / Plan 03-05 + Plan 04-10）。

设计参考 docs/reading-dify-03-05-notification-node-2026-05-17.md §7
+ docs/reading-dify-04-10-multichannel-2026-05-17.md：
- 与 HITL 节点的核心区别：不创建 hitl_token、不调用 interrupt()、不参与催办
- 失败不阻断 graph：单封失败 → 记录 failed_count + state；graph 继续
- Plan 04-10：channels 多通道分发
  * email channel → enqueue_generic_email（与 03-05 一致）
  * IM channel → enqueue_generic_im_card（Plan 04-10 新增）

为何走 BaseNodeExecutor.execute（而非 override __call__）：
- 本节点不抛 GraphInterrupt（与 HITL 不同）
- 复用 BaseNodeExecutor 的 _render_config（Jinja2 渲染 subject/body/recipients）
- 复用 _has_pointer_context 的状态 pointer 透明集成（input 解引用 + output 写指针）

CLAUDE.md 2.4 多租户：
- 通过 self.workspace_id / self.instance_id（DSLCompiler 注入）维护多租户隔离
- workspace_id 直接写入 notifications.workspace_id

CLAUDE.md immutability：
- execute() 不修改 state；仅返回新 dict（LangGraph 自动 merge）

CLAUDE.md 2.5：
- 本节点不创建 jti / token / callback URL（generic 通知是单向广播）
"""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor, NodeExecutionError

log = logging.getLogger(__name__)

# 简易邮箱格式正则（节点层兜底过滤，service 层不再二次校验）
# 不追求 RFC 5322 完美匹配 — 拦截"明显错误"即可（实际投递由 SMTP 服务器最终校验）
_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Plan 04-10 共享通道分类（与 NotificationService _IM_CHANNELS / _EMAIL_CHANNEL 一致）
_EMAIL_CHANNEL = "email"
_IM_CHANNELS: frozenset[str] = frozenset(
    {"feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"}
)


def _is_valid_email(s: str) -> bool:
    """简易邮箱格式判断（拦截明显错误，详细校验由 SMTP 完成）。"""
    if not isinstance(s, str) or not s:
        return False
    s = s.strip()
    return bool(_EMAIL_REGEX.match(s))


def _normalize_recipients(
    raw: Any, channel: str
) -> list[str]:
    """规范化 recipients 字段为 list[str]，按 channel 类型决定校验策略。

    Plan 04-10：
    - email channel：必须通过 _is_valid_email 邮箱格式校验
    - IM channel：接受任意非空字符串（IM user_id 格式因厂商而异，无统一正则）

    Args:
        raw: 原始 recipients 字段值（str / list[str] / 其他类型）
        channel: 当前通道（'email' / 'feishu' / 'wecom' / ...）

    Returns:
        规范化后的 recipient 字符串列表（已过滤无效项）
    """
    # 1. 转 list
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = [r for r in raw if isinstance(r, str)]
    else:
        items = []

    # 2. strip + 过滤空
    items = [r.strip() for r in items if r and r.strip()]

    # 3. 按 channel 类型校验
    if channel == _EMAIL_CHANNEL:
        return [r for r in items if _is_valid_email(r)]
    # IM channel：接受任意非空字符串
    return items


class NotificationNodeExecutor(BaseNodeExecutor):
    """独立通知节点（NODE-07 / Plan 03-05）。

    生命周期：
    1. ExecutionEngine 调度本节点 → BaseNodeExecutor.__call__ 进入
    2. _render_config(state) 渲染 channels/recipients/subject/body
       - recipients 支持 list[str] 或 str（含 Jinja2 表达式）
    3. execute(rendered_config, state) 入队 + 返回统计
       - 遍历 recipients，对每个调用 NotificationService.enqueue_generic_email
       - 单封失败仅记 failed_count + 1（不阻断）
    4. 返回 {self.node_id: {sent_count, failed_count, notification_ids}}
       - LangGraph 自动 merge 到 state[self.node_id]
       - 下游节点可引用 {{ notif_1.sent_count }} 做条件判断

    与 HITL 节点 9 维度区别详见 reading doc §7。
    """

    # Notification 节点失败不阻断 graph，所以不需要在节点层重试（service / job 已重试）
    def _retryable_exceptions(self) -> tuple[type[Exception], ...]:
        return ()

    async def execute(self, config: dict, state: dict) -> dict[str, Any]:
        """渲染 + 多通道入队 + 返回统计（Plan 04-10 多 channel 分发）。

        Args:
            config: 经 Jinja2 渲染后的节点 config（subject/body/recipients/channels 已渲染）
            state: 当前 LangGraph state（read-only — 不修改）

        Returns:
            统计 dict（sent_count/failed_count/notification_ids[/skipped]）
            - sent_count: 所有 channel 累计成功入队数
            - failed_count: 所有 channel 累计入队失败数
            - notification_ids: 所有 channel 成功入队的 notifications.id 列表
            - skipped: 所有 channel 都无有效 recipient 时为 True（边界容错）

        Plan 04-10 多通道行为：
        - channels=['email']（默认，向后兼容）→ enqueue_generic_email per recipient
        - channels=['email','feishu'] → email recipients 走 email，feishu 走 IM 入队
        - 单 channel 失败不阻塞其他 channel（每 channel try/except 独立）
        - 单 recipient 失败仅 failed_count + 1（不阻塞 channel 内其他 recipient）
        """
        # ── 1. channels 规范化（默认 ['email'] 向后兼容 Phase 3）──────────────
        channels = config.get("channels") or [_EMAIL_CHANNEL]
        if not isinstance(channels, list):
            channels = [channels]
        # 过滤无效 channel（不在 email + IM 列表内）
        valid_channels = [
            c for c in channels
            if c == _EMAIL_CHANNEL or c in _IM_CHANNELS
        ]
        invalid_channels = [c for c in channels if c not in valid_channels]
        if invalid_channels:
            log.warning(
                "Notification 节点 %s 跳过未知 channels=%s（保留 %s）",
                self.node_id,
                invalid_channels,
                valid_channels,
            )
        if not valid_channels:
            log.warning(
                "Notification 节点 %s 所有 channels 都未知 — 返回 skipped=True",
                self.node_id,
            )
            return {
                "sent_count": 0,
                "failed_count": 0,
                "notification_ids": [],
                "skipped": True,
            }

        # ── 2. recipients 解析（保留原始供按 channel 规范化）─────────────────
        raw_recipients = config.get("recipients")
        if raw_recipients is None:
            raise NodeExecutionError(
                self.node_id,
                "Notification 节点配置缺少 recipients（DSL 编辑期 schema 校验应已拦截）",
            )
        if not isinstance(raw_recipients, (str, list)):
            raise NodeExecutionError(
                self.node_id,
                f"recipients 必须是 str 或 list[str]，收到 {type(raw_recipients).__name__}",
            )

        # ── 3. subject / body（已 Jinja 渲染，BaseNodeExecutor._render_config）─
        subject = config.get("subject") or "通知"
        body = config.get("body") or ""

        # ── 4. workspace_id / instance_id 校验（DSLCompiler 注入） ────────────
        if self.workspace_id is None or self.instance_id is None:
            raise NodeExecutionError(
                self.node_id,
                "Notification 节点需要 workspace_id / instance_id 上下文（"
                "应由 DSLCompiler 在 _build_node_executor 时通过 __init__ 注入）",
            )

        # ── 5. 多 channel 分发入队 ───────────────────────────────────────────
        # 副作用归外原则：自建 session 完成入队 + commit；arq worker 也是同模式。
        sent_count = 0
        failed_count = 0
        notification_ids: list[int] = []

        from app.agent_builder.db.engine import async_session_maker
        from app.services.notification_service import NotificationService

        async with async_session_maker() as db:
            # 5a. 解析 node_state_id（runner.upsert_node_state 在节点 execute 之后才创建）
            node_state_id = await self._resolve_node_state_id(db)

            # 5b. 复用 03-04 NotificationService（arq_pool=None — 测试 fallback asyncio）
            svc = NotificationService(db=db, arq_pool=None)

            # 5c. 多 channel 分发：每 channel 独立循环
            # Plan 04-10：channel 失败不阻塞其他 channel（per-channel try/except）
            for channel in valid_channels:
                # 按 channel 规范化 recipients（email 校验邮箱 / IM 接受任意字符串）
                channel_recipients = _normalize_recipients(raw_recipients, channel)
                if not channel_recipients:
                    log.warning(
                        "Notification 节点 %s channel=%s 无有效 recipient — 跳过",
                        self.node_id,
                        channel,
                    )
                    continue

                # 单 channel 内循环 recipients
                for recipient in channel_recipients:
                    try:
                        if channel == _EMAIL_CHANNEL:
                            notif = await svc.enqueue_generic_email(
                                workspace_id=self.workspace_id,
                                instance_id=self.instance_id,
                                node_state_id=node_state_id,
                                recipient_email=recipient,
                                subject=subject,
                                body=body,
                            )
                        else:
                            # IM channel：调 enqueue_generic_im_card
                            notif = await svc.enqueue_generic_im_card(
                                workspace_id=self.workspace_id,
                                instance_id=self.instance_id,
                                node_state_id=node_state_id,
                                recipient=recipient,
                                channel=channel,
                                subject=subject,
                                body=body,
                            )
                        notification_ids.append(notif.id)
                        sent_count += 1
                    except Exception as exc:
                        # CLAUDE.md §错误处理：失败不阻断，仅记 failed_count + 日志
                        log.exception(
                            "Notification 入队失败 node=%s channel=%s recipient=%s: %s",
                            self.node_id,
                            channel,
                            recipient,
                            exc,
                        )
                        # SQLAlchemy 抛错后 session 进入失败状态，必须 rollback 才能继续
                        try:
                            await db.rollback()
                        except Exception:
                            log.exception("rollback 失败 — 节点 %s", self.node_id)
                        failed_count += 1

        return {
            "sent_count": sent_count,
            "failed_count": failed_count,
            "notification_ids": notification_ids,
        }

    async def _resolve_node_state_id(self, db) -> UUID:
        """获取 / 创建当前节点的 node_states 行 UUID（FK 约束需要）。

        runner.run_instance 通常在节点 execute 之后调 upsert_node_state，
        所以本节点 execute 时该行可能尚不存在 — 这里 SELECT or INSERT。

        与 HITL 节点不同：HITL 节点要求 ExecutionEngine 在 enter 时预创建 node_states
        + 注入 _node_state_id 到 state；Notification 节点更宽松，自己处理。
        """
        from app.agent_builder.models.node_state import NodeState

        # 先查（多 worker / 多次进入幂等）
        result = await db.execute(
            select(NodeState).where(
                NodeState.instance_id == self.instance_id,
                NodeState.node_id == self.node_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing.id

        # 没有则创建一行 status='running'（与 runner.upsert_node_state 风格一致）
        from datetime import UTC, datetime

        ns = NodeState(
            workspace_id=self.workspace_id,
            instance_id=self.instance_id,
            node_id=self.node_id,
            node_type=self.node_type,
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(ns)
        await db.flush()
        await db.commit()
        await db.refresh(ns)
        return ns.id
