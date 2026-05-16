"""通知服务 — HITL 邮件 + IM（Phase 4+）的入队 + 状态管理（Plan 03-04）。

设计参考 docs/reading-dify-03-04-email-delivery-2026-05-17.md §7：
- 简化 Dify 三层 ORM（Form / Delivery / Recipient）为 notifications 单表
- arq queue 替代 Celery shared_task（CLAUDE.md §3 技术栈锁定）
- 入队时写 notifications.status=pending 一行 + 通过 arq enqueue_job 派发到 worker

NOTI-08 多通道扩展点：Phase 3 仅 email 实现，Phase 4 加 IM 时新增 enqueue_hitl_notifications
接受 channels=['email', 'feishu', ...]，并为每个 channel 创建一行 + 入队对应 job。

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
