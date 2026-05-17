"""通知服务 — HITL 邮件 + IM（Phase 4+）的入队 + 状态管理（Plan 03-04 / Plan 04-10）。

设计参考 docs/reading-dify-03-04-email-delivery-2026-05-17.md §7
+ docs/reading-dify-04-10-multichannel-2026-05-17.md：
- 简化 Dify 三层 ORM（Form / Delivery / Recipient）为 notifications 单表
- arq queue 替代 Celery shared_task（CLAUDE.md §3 技术栈锁定）
- 入队时写 notifications.status=pending 一行 + 通过 arq enqueue_job 派发到 worker

NOTI-08 多通道扩展（Plan 04-10）：
- enqueue_hitl_multichannel：channels=['email', 'feishu', ...] → fan-out 每 channel 一行 notifications
  + 入队对应 job（email_jobs.send_hitl_email_job 或 im_jobs.send_hitl_card_job）
- enqueue_generic_im_card：Notification 节点 IM 通道入口（与 enqueue_generic_email 平行）
- im_bindings 解析：用户 users.im_bindings JSONB 查 {channel: im_user_id} 映射；未配置 → 跳过 + warn
- 失败容错：单 channel 失败不阻塞其他（per-notification status 独立）
- idempotent fan-out：notifications UNIQUE (instance, node_state, channel, recipient, round)
- 事务边界（Pitfall 2 + Dify mode 2）：所有 INSERT commit 后才循环 enqueue_job

CLAUDE.md immutability：service 写 DB 但不修改入参 dict（tokens / form_schema 不可变副本）。
CLAUDE.md 2.4 多租户：workspace_id 显式传入并写入 notifications.workspace_id（防漏配）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.notification import Notification

log = logging.getLogger(__name__)

# Plan 04-10 多通道：channels 参数允许的值（与 schema enum 一致）
# email 走 send_hitl_email_job；其他走 send_hitl_card_job（Plan 04-05 IM 抽象层）
_EMAIL_CHANNEL = "email"
_IM_CHANNELS: frozenset[str] = frozenset(
    {"feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"}
)
_ALL_KNOWN_CHANNELS: frozenset[str] = frozenset({_EMAIL_CHANNEL}) | _IM_CHANNELS


class NotificationService:
    """通知入队 + 状态管理服务。

    用法：
        svc = NotificationService(db, arq_pool=arq_redis)
        notif = await svc.enqueue_hitl_email(
            workspace_id=...,
            instance_id=...,
            node_state_id=...,
            recipient_email='user@example.com',
            tokens=[HitlToken, ...],     # 3 个 action token（submit/return/reject）
            form_schema={...},
            deadline_at=datetime(...),
            actor_name='李四',
            flow_title='员工入职流程',
            node_title='HR 审批',
            applicant_name='张三',
            description='请审批...',
        )
        # notif.status == 'pending'，arq worker 异步消费 send_hitl_email_job(notif.id)

    设计要点：
    - arq_pool 可选：测试 / dev 模式下走 asyncio.create_task 直接调用 job（无 Redis 依赖）
    - 写 notifications 行后立即 commit（保证 worker 可见 + 避免事务持久后 enqueue 但写入未提交）
    - reminder_round 区分首次发送（0）vs 催办（1/2/3），UNIQUE 约束防重发
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        arq_pool: Any | None = None,
    ) -> None:
        self.db = db
        self.arq = arq_pool

    async def enqueue_hitl_email(
        self,
        *,
        workspace_id: UUID,
        instance_id: UUID,
        node_state_id: UUID,
        recipient_email: str,
        tokens: Sequence[HitlToken],
        form_schema: dict[str, Any],
        deadline_at: datetime,
        actor_name: str,
        flow_title: str,
        node_title: str,
        applicant_name: str,
        description: str,
        reminder_round: int = 0,
    ) -> Notification:
        """写 notifications.status=pending + 入队 arq send_hitl_email_job。

        Args:
            workspace_id: 工作区 UUID（多租户隔离）
            instance_id: 流程实例 UUID
            node_state_id: 节点状态 UUID
            recipient_email: 收件人邮箱（不做格式校验 — 假定上游已校验）
            tokens: HITL token 列表（每个含 jti + action，由 HitlService.batch_create_tokens 生成）
            form_schema: 决策表单 schema（JSON Schema 子集）
            deadline_at: 审批截止时间（timezone-aware datetime）
            actor_name: 审批人姓名（邮件正文渲染用）
            flow_title: 流程名称
            node_title: 节点名称
            applicant_name: 申请人姓名
            description: 节点描述（来自 form_schema.description）
            reminder_round: 0=首次发送，1/2=催办（默认 0）

        Returns:
            创建的 Notification 行（status='pending'，已 commit）

        Raises:
            sqlalchemy.exc.IntegrityError: UNIQUE 约束冲突
                （instance_id, node_state_id, channel='email', recipient, reminder_round 重复）
        """
        # 构造不可变 payload（NotificationService.payload JSONB）— 不修改入参
        token_records = [
            {"jti": str(t.jti), "action": t.action} for t in tokens
        ]
        payload: dict[str, Any] = {
            "tokens": token_records,
            "form_schema": dict(form_schema),  # 浅拷贝防外部修改
            "deadline_at": deadline_at.isoformat(),
            "actor_name": actor_name,
            "flow_title": flow_title,
            "node_title": node_title,
            "applicant_name": applicant_name,
            "description": description,
        }

        notif = Notification(
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_state_id=node_state_id,
            channel="email",
            recipient=recipient_email,
            reminder_round=reminder_round,
            status="pending",
            payload=payload,
        )
        self.db.add(notif)
        await self.db.flush()
        await self.db.commit()
        # commit 后 notif.id 已落地（BIGSERIAL 自增），refresh 读取 server defaults
        await self.db.refresh(notif)

        log.info(
            "已入队 HITL 邮件通知 notification_id=%s recipient=%s round=%s",
            notif.id,
            recipient_email,
            reminder_round,
        )

        if self.arq is not None:
            # 生产路径：通过 arq pool 入队
            await self.arq.enqueue_job("send_hitl_email_job", str(notif.id))
        else:
            # 测试 / dev fallback：直接 asyncio.create_task（不依赖 Redis）
            # 注意：测试中如果不需要立即触发，可传 arq_pool=None 并手动调 job
            from app.jobs.email_jobs import send_hitl_email_job

            asyncio.create_task(send_hitl_email_job(None, str(notif.id)))

        return notif

    async def enqueue_generic_email(
        self,
        *,
        workspace_id: UUID,
        instance_id: UUID,
        node_state_id: UUID,
        recipient_email: str,
        subject: str,
        body: str,
    ) -> Notification:
        """通用邮件入队（Plan 03-05 / NODE-07 独立 Notification 节点用）。

        与 enqueue_hitl_email 的区别：
        - 不携带 tokens / form_schema / deadline_at（无回调）
        - 不参与催办循环：reminder_round 恒为 0
        - payload 仅 {subject, body, recipient_email}（极简）

        channel='email' + reminder_round=0，与 enqueue_hitl_email 走同一 send_hitl_email_job
        worker；worker 根据 payload 字段决定模板（含 tokens=有 → hitl_decision.html，
        含 generic=True → generic_notification.html）。

        Args:
            workspace_id: 工作区 UUID（多租户隔离）
            instance_id: 流程实例 UUID
            node_state_id: 节点状态 UUID（必须已存在；FK 约束）
            recipient_email: 收件人邮箱（已经 Jinja 渲染 + 格式校验过）
            subject: 邮件主题（已经 Jinja 渲染）
            body: 邮件正文（已经 Jinja 渲染 + autoescape）

        Returns:
            Notification 行（status='pending'，已 commit）

        Raises:
            sqlalchemy.exc.IntegrityError: UNIQUE 约束冲突
                （相同 instance + node_state + email + recipient + round=0 重复入队）
        """
        # 极简 payload（vs HITL 邮件 payload 含 tokens/form_schema/deadline 等 8 字段）
        payload: dict[str, Any] = {
            "generic": True,  # 标识：worker 据此选择 generic_notification.html 模板
            "subject": subject,
            "body": body,
            "recipient_email": recipient_email,
        }

        notif = Notification(
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_state_id=node_state_id,
            channel="email",
            recipient=recipient_email,
            reminder_round=0,  # 通用通知节点：不参与催办，恒为 0
            status="pending",
            payload=payload,
        )
        self.db.add(notif)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(notif)

        log.info(
            "已入队通用通知 notification_id=%s recipient=%s",
            notif.id,
            recipient_email,
        )

        if self.arq is not None:
            await self.arq.enqueue_job("send_hitl_email_job", str(notif.id))
        else:
            # 测试 / dev fallback：直接 asyncio.create_task（不依赖 Redis）
            from app.jobs.email_jobs import send_hitl_email_job

            asyncio.create_task(send_hitl_email_job(None, str(notif.id)))

        return notif

    async def mark_sent(self, notification_id: int, sent_at: datetime) -> None:
        """标记通知发送成功。

        由 send_hitl_email_job 在 _send_email 成功后调用。
        """
        notif = await self.db.get(Notification, notification_id)
        if notif is None:
            log.error("mark_sent: notification %s 不存在", notification_id)
            return
        notif.status = "sent"
        notif.sent_at = sent_at
        notif.error_message = None
        await self.db.commit()

    async def mark_failed(self, notification_id: int, error: str) -> None:
        """标记通知发送失败（NOTI-10 重试耗尽后）。

        由 send_hitl_email_job 在 tenacity 3 次重试均失败后调用。
        """
        notif = await self.db.get(Notification, notification_id)
        if notif is None:
            log.error("mark_failed: notification %s 不存在", notification_id)
            return
        notif.status = "failed"
        notif.error_message = error[:1000]  # 截断防超长
        await self.db.commit()

    # ── Plan 04-10 多通道 fan-out（NOTI-08）─────────────────────────────────────

    def _build_hitl_payload(
        self,
        *,
        tokens: Sequence[HitlToken],
        form_schema: dict[str, Any],
        deadline_at: datetime,
        actor_name: str,
        flow_title: str,
        node_title: str,
        applicant_name: str,
        description: str,
    ) -> dict[str, Any]:
        """构造 HITL 通知 payload（enqueue_hitl_email + enqueue_hitl_multichannel 共用）。

        CLAUDE.md immutability：
        - tokens 列表新建（不共享原列表引用）
        - form_schema 浅拷贝（防外部修改）
        - 返回新 dict（caller 不应修改）
        """
        token_records = [
            {"jti": str(t.jti), "action": t.action} for t in tokens
        ]
        return {
            "tokens": token_records,
            "form_schema": dict(form_schema),
            "deadline_at": deadline_at.isoformat(),
            "actor_name": actor_name,
            "flow_title": flow_title,
            "node_title": node_title,
            "applicant_name": applicant_name,
            "description": description,
        }

    async def enqueue_hitl_multichannel(
        self,
        *,
        workspace_id: UUID,
        instance_id: UUID,
        node_state_id: UUID,
        recipient_email: str,
        recipient_im_bindings: dict[str, str] | None,
        tokens: Sequence[HitlToken],
        form_schema: dict[str, Any],
        deadline_at: datetime,
        actor_name: str,
        flow_title: str,
        node_title: str,
        applicant_name: str,
        description: str,
        channels: list[str],
        reminder_round: int = 0,
    ) -> list[Notification]:
        """多通道 fan-out 入队（NOTI-08）。

        每个 channel 写一行 notifications.status=pending + 入队一个 job：
        - email → send_hitl_email_job（Phase 3 03-04）
        - feishu/wecom/dingtalk/slack/mattermost/webhook → send_hitl_card_job（Phase 4 04-05）

        recipient 解析（参考 reading doc §模式 1）：
        - email channel: 用 recipient_email
        - IM channel: recipient_im_bindings[channel]
          - 未配置 → 跳过该 channel + warn 日志（不抛错，与其他 channel 独立）
          - bindings=None → 仅 email 走通，IM 全跳过

        事务边界（参考 reading doc §模式 2，防 Pitfall 2）：
        - 所有 INSERT 在一个事务内 commit
        - commit 之后才循环 enqueue_job
        - 避免 worker 抢跑事务未提交的行

        Args:
            workspace_id: 工作区 UUID（多租户隔离）
            instance_id: 流程实例 UUID
            node_state_id: 节点状态 UUID
            recipient_email: 收件人邮箱（即使 channels 不含 email 也作为 binding 解析时的 actor 标识用）
            recipient_im_bindings: {"feishu": "ou_xxx", "wecom": "WuPing"} 映射；None 视为无 IM binding
            tokens: HITL token 列表（每个含 jti + action）
            form_schema: 决策表单 schema
            deadline_at: 审批截止时间
            actor_name: 审批人姓名
            flow_title: 流程名称
            node_title: 节点名称
            applicant_name: 申请人姓名
            description: 节点描述
            channels: 通知通道列表（如 ["email", "feishu"]）
            reminder_round: 0=首次发送，1/2=催办（默认 0）

        Returns:
            创建的 Notification 列表（已 commit + refresh），每行对应一个成功入队的 channel
            （缺 binding 的 IM channel 不在返回列表中）

        Raises:
            ValueError: channels 为空
            sqlalchemy.exc.IntegrityError: UNIQUE 约束冲突
        """
        if not channels:
            raise ValueError("channels 必须至少包含一个通道")

        # 校验 channels 都是已知值（防 typo）
        unknown = [c for c in channels if c not in _ALL_KNOWN_CHANNELS]
        if unknown:
            raise ValueError(
                f"未知 channels: {unknown}；允许值: {sorted(_ALL_KNOWN_CHANNELS)}"
            )

        # 构造 payload 一次（多 channel 共享 — _build_hitl_payload 返回新 dict）
        # 每个 notif 独立 dict 副本，防止后续 worker 修改污染其他 channel
        base_payload = self._build_hitl_payload(
            tokens=tokens,
            form_schema=form_schema,
            deadline_at=deadline_at,
            actor_name=actor_name,
            flow_title=flow_title,
            node_title=node_title,
            applicant_name=applicant_name,
            description=description,
        )

        created: list[Notification] = []
        for channel in channels:
            # 解析 recipient（reading doc §模式 1）
            if channel == _EMAIL_CHANNEL:
                recipient = recipient_email
            else:
                # IM channel：bindings 缺失 → 跳过该 channel + warn（不阻塞其他）
                recipient = (recipient_im_bindings or {}).get(channel)
                if not recipient:
                    log.warning(
                        "im_bindings 缺 %s（actor_email=%s instance_id=%s）— 跳过该 channel",
                        channel,
                        recipient_email,
                        instance_id,
                    )
                    continue

            # 每行独立 payload dict 副本（immutability — worker 写回 im_message_id 不污染其他）
            notif = Notification(
                workspace_id=workspace_id,
                instance_id=instance_id,
                node_state_id=node_state_id,
                channel=channel,
                recipient=recipient,
                reminder_round=reminder_round,
                status="pending",
                payload=dict(base_payload),
            )
            self.db.add(notif)
            created.append(notif)

        if not created:
            log.warning(
                "enqueue_hitl_multichannel: 所有 channel 都缺 binding，未创建任何 notification "
                "(instance=%s channels=%s)",
                instance_id,
                channels,
            )
            return []

        # 事务边界：先 commit 所有 notifications 行，再 enqueue jobs
        # （reading doc §模式 2 — 防 worker 抢跑事务未提交行）
        await self.db.flush()
        await self.db.commit()
        for notif in created:
            await self.db.refresh(notif)

        # commit 之后才 enqueue jobs（per-job 失败不影响已 commit 的行）
        for notif in created:
            job_name = (
                "send_hitl_email_job"
                if notif.channel == _EMAIL_CHANNEL
                else "send_hitl_card_job"
            )
            if self.arq is not None:
                await self.arq.enqueue_job(job_name, str(notif.id))
            else:
                await self._fallback_dispatch(notif, job_name)

        log.info(
            "notification.multichannel.enqueued",
            extra={
                "channels": [n.channel for n in created],
                "notification_ids": [n.id for n in created],
                "instance_id": str(instance_id),
                "node_state_id": str(node_state_id),
                "reminder_round": reminder_round,
                "skipped_count": len(channels) - len(created),
            },
        )

        return created

    async def enqueue_generic_im_card(
        self,
        *,
        workspace_id: UUID,
        instance_id: UUID,
        node_state_id: UUID,
        recipient: str,
        channel: str,
        subject: str,
        body: str,
    ) -> Notification:
        """Notification 节点 IM 通道入口（与 enqueue_generic_email 平行）。

        通用通知节点：不携带 tokens / form_schema / deadline（无回调），不参与催办。

        与 enqueue_generic_email 的区别：
        - channel != 'email'（必须是 IM channel）
        - recipient 是 IM user_id（如飞书 open_id），不是 email
        - payload 极简 {generic, subject, body, recipient_im}
        - 入队 send_hitl_card_job（而非 send_hitl_email_job）

        Args:
            workspace_id: 工作区 UUID
            instance_id: 流程实例 UUID
            node_state_id: 节点状态 UUID
            recipient: IM user_id（飞书 open_id / 企微 userid / Slack U... / 等）
            channel: 必须是 IM channel（feishu/wecom/dingtalk/slack/mattermost/webhook）
            subject: 通知主题
            body: 通知正文

        Returns:
            Notification 行（status='pending'，已 commit）

        Raises:
            ValueError: channel='email' 或 channel 不在 IM channel 列表
            sqlalchemy.exc.IntegrityError: UNIQUE 约束冲突
        """
        if channel not in _IM_CHANNELS:
            raise ValueError(
                f"enqueue_generic_im_card 仅支持 IM channel；收到 '{channel}'；"
                f"允许值: {sorted(_IM_CHANNELS)}（email 请用 enqueue_generic_email）"
            )

        payload: dict[str, Any] = {
            "generic": True,  # 标识：worker 据此选择简化模板（不渲染 deeplinks）
            "subject": subject,
            "body": body,
            "recipient_im": recipient,
        }

        notif = Notification(
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_state_id=node_state_id,
            channel=channel,
            recipient=recipient,
            reminder_round=0,  # 通用通知节点不参与催办
            status="pending",
            payload=payload,
        )
        self.db.add(notif)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(notif)

        log.info(
            "已入队通用 IM 通知 notification_id=%s channel=%s recipient=%s",
            notif.id,
            channel,
            recipient,
        )

        if self.arq is not None:
            await self.arq.enqueue_job("send_hitl_card_job", str(notif.id))
        else:
            await self._fallback_dispatch(notif, "send_hitl_card_job")

        return notif

    async def _fallback_dispatch(
        self, notif: Notification, job_name: str
    ) -> None:
        """arq_pool=None 时的 fallback 派发（测试 / dev 模式）。

        通过 asyncio.create_task 在后台直接驱动 worker function；
        测试场景下通常不强依赖 task 完成（mock worker 验证 enqueue 调用即可）。
        """
        if job_name == "send_hitl_email_job":
            from app.jobs.email_jobs import send_hitl_email_job

            asyncio.create_task(send_hitl_email_job(None, str(notif.id)))
        elif job_name == "send_hitl_card_job":
            from app.jobs.im_jobs import send_hitl_card_job

            asyncio.create_task(send_hitl_card_job(None, str(notif.id)))
        else:
            log.warning("未知 job_name=%s，跳过 fallback 派发", job_name)
