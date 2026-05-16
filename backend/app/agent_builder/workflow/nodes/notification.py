"""Notification 节点 executor — 独立通知节点（NODE-07 / Plan 03-05）。

设计参考 docs/reading-dify-03-05-notification-node-2026-05-17.md §7：
- 与 HITL 节点的核心区别：不创建 hitl_token、不调用 interrupt()、不参与催办
- 失败不阻断 graph：单封失败 → 记录 failed_count + state；graph 继续

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


def _is_valid_email(s: str) -> bool:
    """简易邮箱格式判断（拦截明显错误，详细校验由 SMTP 完成）。"""
    if not isinstance(s, str) or not s:
        return False
    s = s.strip()
    return bool(_EMAIL_REGEX.match(s))


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
        """渲染 + 入队 + 返回统计。

        Args:
            config: 经 Jinja2 渲染后的节点 config（subject/body/recipients 已渲染）
            state: 当前 LangGraph state（read-only — 不修改）

        Returns:
            统计 dict（sent_count/failed_count/notification_ids[/skipped]）
        """
        # ── 1. channels 校验（Phase 3 仅支持 email）──────────────────────────
        channels = config.get("channels") or ["email"]
        if not isinstance(channels, list):
            channels = [channels]
        if "email" not in channels:
            log.warning(
                "Notification 节点 %s 的 channels=%s 不含 email，Phase 3 仅支持 email — 跳过",
                self.node_id,
                channels,
            )
            return {
                "sent_count": 0,
                "failed_count": 0,
                "notification_ids": [],
                "skipped": True,
            }

        # ── 2. recipients 规范化（支持 str / list[str]） ────────────────────
        raw_recipients = config.get("recipients")
        if raw_recipients is None:
            raise NodeExecutionError(
                self.node_id,
                "Notification 节点配置缺少 recipients（DSL 编辑期 schema 校验应已拦截）",
            )
        if isinstance(raw_recipients, str):
            recipients_list: list[str] = [raw_recipients]
        elif isinstance(raw_recipients, list):
            recipients_list = [r for r in raw_recipients if isinstance(r, str)]
        else:
            raise NodeExecutionError(
                self.node_id,
                f"recipients 必须是 str 或 list[str]，收到 {type(raw_recipients).__name__}",
            )

        # 过滤无效邮箱（节点层兜底；CLAUDE.md §安全 — 不信任外部数据）
        valid_recipients = [r.strip() for r in recipients_list if _is_valid_email(r)]
        invalid_count = len(recipients_list) - len(valid_recipients)
        if invalid_count > 0:
            log.warning(
                "Notification 节点 %s 过滤了 %d 个无效邮箱（共 %d 个）",
                self.node_id,
                invalid_count,
                len(recipients_list),
            )

        if not valid_recipients:
            log.warning("Notification 节点 %s 无有效 recipient — 直接返回 0/0", self.node_id)
            return {
                "sent_count": 0,
                "failed_count": 0,
                "notification_ids": [],
            }

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

        # ── 5. 入队（自管 DB session — 与 send_hitl_email_job 同模式） ──────
        # 副作用归外原则：节点函数不复用 ExecutionEngine 的 session（避免事务耦合），
        # 而是自建 session 完成入队 + commit；arq worker 也是同模式。
        sent_count = 0
        failed_count = 0
        notification_ids: list[int] = []

        from app.agent_builder.db.engine import async_session_maker
        from app.services.notification_service import NotificationService

        async with async_session_maker() as db:
            # 5a. 解析 node_state_id（runner.upsert_node_state 在节点 execute 之后才创建，
            # 这里如果尚不存在，则提前创建一行 status='running' 以满足 FK 约束）
            node_state_id = await self._resolve_node_state_id(db)

            # 5b. 复用 03-04 NotificationService（不实例化时传入 arq_pool；
            # 入队 fallback 走 asyncio.create_task 直接驱动 send_hitl_email_job —
            # 测试 / dev 路径与 03-04 一致）
            svc = NotificationService(db=db, arq_pool=None)

            for recipient in valid_recipients:
                try:
                    notif = await svc.enqueue_generic_email(
                        workspace_id=self.workspace_id,
                        instance_id=self.instance_id,
                        node_state_id=node_state_id,
                        recipient_email=recipient,
                        subject=subject,
                        body=body,
                    )
                    notification_ids.append(notif.id)
                    sent_count += 1
                except Exception as exc:
                    # CLAUDE.md §错误处理：失败不阻断，仅记 failed_count + 日志
                    log.exception(
                        "Notification 入队失败 node=%s recipient=%s: %s",
                        self.node_id,
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
