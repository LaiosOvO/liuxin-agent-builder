"""HITL 节点超时升级服务（Plan 03-09）。

设计参考 docs/reading-dify-03-09-timeout-worker-2026-05-17.md §4：
- Dify 没有"主动升级到上级"逻辑（仅标记 TIMEOUT 让流程走 timeout 分支）
- 本项目独创：超过 72h 时换 actor 为 escalate_to 用户 + 发升级邮件 + 写 audit_log

Phase 3 简化（HITL-04 single 模式部分）：
- node_def.config.escalate_to 直接接收 user_email 字符串
- 找不到 escalate_to 时 fallback 到 workspace super_admin 的 email
- Phase 5 expand: role:admin / dept:HR / dynamic_expr 三态（依赖 IM 目录同步）

CLAUDE.md immutability：
- 不修改入参 payload dict — 用 append_record 风格生成新 dict
- node_state.payload 字段赋值后由 SQLAlchemy ORM 持久化（外层 commit 时落 PG）

CLAUDE.md 2.4 多租户：
- 通过 ns.workspace_id 取 super_admin fallback
- 写入 audit_log 时 workspace_id 显式传入
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.user import User
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.agent_builder.models.role import Role

log = logging.getLogger(__name__)


class EscalationService:
    """节点超时升级服务。

    职责：
    - resolve_escalate_to: 解析升级人 email
    - perform_escalation: 执行升级（发邮件 + 写 records + audit_log + 替换 current_actor）

    用法：
        es = EscalationService(db, arq_pool=arq_redis)
        await es.perform_escalation(node_state)

    注：本类不持有 advisory_lock — 由调用方（scan_hitl_timeouts._trigger_escalation）持有。
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        arq_pool: Any | None = None,
    ) -> None:
        self.db = db
        self.arq = arq_pool

    async def resolve_escalate_to(
        self,
        *,
        node_config: dict[str, Any] | None,
        workspace_id: UUID,
    ) -> str | None:
        """解析升级人 email。

        Phase 3 简化：
        1. 优先：node_config.escalate_to 直接是 email 字符串
        2. fallback: workspace 下 super_admin 的 email
        3. 都没找到：None（调用方决定是否跳过）

        Phase 5 expand（暂不实现）:
        - 'role:admin' → 查询 workspace admin
        - 'dept:HR' → 查询 department='HR' 的用户
        - 'dynamic_expr' → Jinja 模板渲染

        Args:
            node_config: 节点 DSL config（包含 'escalate_to' 字段或缺失）
            workspace_id: 工作区 UUID（fallback 查询用）

        Returns:
            升级人 email 字符串；找不到时返回 None。
        """
        # Phase 3 简化：仅接受 email 字符串
        if node_config:
            escalate_to = node_config.get("escalate_to")
            if isinstance(escalate_to, str) and "@" in escalate_to:
                log.info("resolve_escalate_to: 用 node_config.escalate_to=%s", escalate_to)
                return escalate_to

        # fallback: workspace 下 super_admin email
        # 注意：is_super_admin=True 是 platform 级，不是 workspace 级；
        # 这里取 workspace 下任意 admin 角色用户的 email 作为 fallback
        # Phase 5 expand: 通过 UserWorkspaceRole + Role 关联表查 workspace admin
        admin_email = await self._fallback_workspace_admin_email(workspace_id)
        if admin_email:
            log.info(
                "resolve_escalate_to: fallback 到 workspace admin email=%s",
                admin_email,
            )
            return admin_email

        log.warning(
            "resolve_escalate_to: 节点配置无 escalate_to + workspace=%s 无 admin，无法升级",
            workspace_id,
        )
        return None

    async def _fallback_workspace_admin_email(
        self,
        workspace_id: UUID,
    ) -> str | None:
        """查 workspace 下 admin 角色用户的 email（fallback 用）。

        优先级：admin > super_admin（platform 级）
        """
        # 查 workspace 下 role.code='admin' 的用户
        stmt = (
            select(User.email)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .join(Role, Role.id == UserWorkspaceRole.role_id)
            .where(
                UserWorkspaceRole.workspace_id == workspace_id,
                Role.code == "admin",
                User.status == "active",
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        email = result.scalar_one_or_none()
        if email:
            return str(email)

        # 再 fallback：platform super_admin（不限 workspace）
        sa_stmt = (
            select(User.email)
            .where(User.is_super_admin.is_(True), User.status == "active")
            .limit(1)
        )
        sa_result = await self.db.execute(sa_stmt)
        sa_email = sa_result.scalar_one_or_none()
        return str(sa_email) if sa_email else None

    async def perform_escalation(self, ns: NodeState) -> None:
        """执行升级。

        步骤：
        1. 加载 flow_instance（拿 node config + DSL）
        2. 解析升级人 email
        3. 写 records 加 escalate 记录
        4. （Phase 3 简化）records 添加后，**保留 current_actor 字段**仅追加升级人到记录链
           — Phase 4 多人审批链时才动态切换 current_actor
        5. 入队 NotificationService.enqueue_hitl_email（reminder_round=3，模板用 hitl_escalation.html）
        6. 写 audit_log（NET-05）

        Args:
            ns: NodeState 实例（advisory_lock 由调用方持有）
        """
        # 1. 加载 flow_instance 拿 DSL 中节点 config
        flow_instance = await self.db.get(FlowInstance, ns.instance_id)
        if flow_instance is None:
            log.warning(
                "perform_escalation: instance %s 不存在，跳过升级",
                ns.instance_id,
            )
            return

        node_config = self._extract_node_config(flow_instance, ns.node_id)

        # 2. 解析升级人 email
        escalate_email = await self.resolve_escalate_to(
            node_config=node_config,
            workspace_id=ns.workspace_id,
        )
        if escalate_email is None:
            log.error(
                "perform_escalation: 节点 %s 无法解析升级人，跳过（需 admin 配置）",
                ns.id,
            )
            return

        # 3. 写 records 加 escalate 记录（不可变 append）
        now = datetime.now(timezone.utc)
        old_payload = ns.payload or {}
        old_records = list(old_payload.get("records") or [])
        new_record = {
            "actor_id": None,  # system 触发
            "actor_email": "system",
            "action": "escalate",
            "reason": "timeout_72h",
            "form_data": {},
            "ts": now.isoformat(),
            "ip": "system",
            "ua": "system:hitl_timeout_worker",
            "escalate_to": escalate_email,
        }
        new_records = old_records + [new_record]
        new_payload = dict(old_payload)  # 浅拷贝防修改入参
        new_payload["records"] = new_records
        # Phase 3 简化：保留原 current_actor（Phase 4 多人审批链才动态切换）
        # 但记录 escalate_to 字段以便邮件模板渲染
        new_payload["escalate_to"] = escalate_email
        ns.payload = new_payload

        # 4. 发升级邮件
        await self._send_escalation_email(ns, escalate_email, old_payload)

        # 5. 写 audit_log（NET-05）
        await self._write_audit_log(ns, escalate_email)

        log.info(
            "perform_escalation: 节点 %s 已升级到 %s",
            ns.id,
            escalate_email,
        )

    def _extract_node_config(
        self,
        flow_instance: FlowInstance,
        node_id: str,
    ) -> dict[str, Any] | None:
        """从 instance.dsl_snapshot 取出指定 node 的 config 字段。

        DSL 结构（Phase 2 定义）:
            { "nodes": [{"id": "hitl_1", "type": "hitl", "config": {...}}, ...] }
        """
        dsl = flow_instance.dsl_snapshot or {}
        nodes = dsl.get("nodes") or []
        for n in nodes:
            if n.get("id") == node_id:
                return n.get("config") or {}
        return None

    async def _send_escalation_email(
        self,
        ns: NodeState,
        escalate_email: str,
        old_payload: dict[str, Any],
    ) -> None:
        """发送升级邮件 — 复用 NotificationService.enqueue_hitl_email + reminder_round=3。

        模板路由（email_jobs.py）：reminder_round > 0 → hitl_reminder.html
        本 plan 额外引入 hitl_escalation.html 作为 round=3 专用红色升级模板。

        Phase 3 简化：worker 仅入队，不主动重签发 token —
        升级邮件给的是 admin/super_admin 的"通知"邮件，他们决定下一步处理
        （v1 不要求 admin 在邮件内直接决策，因 admin 通常需先看上下文）。
        """
        from app.agent_builder.models.notification import Notification

        # 直接 INSERT notifications（不走 enqueue_hitl_email — 因升级邮件无 tokens）
        # 模板路径：hitl_escalation.html（reminder_round=3 时 email_jobs.py 会自动选）
        # 这里 payload 不带 tokens（升级邮件不需要决策按钮）— 让 worker 用专用模板渲染
        original_actor = old_payload.get("current_actor") or {}
        original_actor_email = original_actor.get("email", "unknown")
        deadline_at_str = old_payload.get("deadline_at", "")

        # 计算超时时长（用于邮件正文）
        started_at_str = old_payload.get("started_at", "")
        overdue_hours: float = 72.0
        if isinstance(started_at_str, str):
            try:
                started_at = datetime.fromisoformat(started_at_str)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                overdue_hours = (
                    datetime.now(timezone.utc) - started_at
                ).total_seconds() / 3600
            except ValueError:
                pass

        notif_payload = {
            "escalation": True,  # 标识：worker 据此选 hitl_escalation.html
            "flow_title": old_payload.get("flow_title", ""),
            "node_title": old_payload.get("node_title", ""),
            "applicant_name": old_payload.get("applicant_name", ""),
            "original_actor_email": original_actor_email,
            "overdue_hours": round(overdue_hours, 1),
            "deadline_at": deadline_at_str,
            "description": old_payload.get("description", ""),
            "instance_id": str(ns.instance_id),
        }

        notif = Notification(
            workspace_id=ns.workspace_id,
            instance_id=ns.instance_id,
            node_state_id=ns.id,
            channel="email",
            recipient=escalate_email,
            reminder_round=3,  # 升级是第 3 档
            status="pending",
            payload=notif_payload,
        )
        self.db.add(notif)
        try:
            await self.db.flush()
        except sa.exc.IntegrityError:
            # UNIQUE 冲突 — 已发过升级邮件（防多 worker 重发）
            log.info(
                "_send_escalation_email: 节点 %s 升级邮件已发过（UNIQUE 冲突），跳过",
                ns.id,
            )
            await self.db.rollback()
            return

        log.info(
            "_send_escalation_email: 升级邮件已入队 notification_id=%s recipient=%s",
            notif.id,
            escalate_email,
        )

        # 入队 arq job — 复用 send_hitl_email_job worker（payload.escalation 路由到 hitl_escalation.html）
        if self.arq is not None:
            await self.arq.enqueue_job("send_hitl_email_job", str(notif.id))
        else:
            # fallback：测试 / dev 直接 asyncio.create_task
            import asyncio

            from app.jobs.email_jobs import send_hitl_email_job

            asyncio.create_task(send_hitl_email_job(None, str(notif.id)))

    async def _write_audit_log(
        self,
        ns: NodeState,
        escalate_email: str,
    ) -> None:
        """写 audit_log（NET-05 升级审计）。

        action='hitl.escalate'
        decision='escalate'
        meta 含 instance_id / node_state_id / original_actor / escalate_to / reason
        """
        old_payload = ns.payload or {}
        original_actor = old_payload.get("current_actor") or {}
        audit = AuditLog(
            workspace_id=ns.workspace_id,
            actor_user_id=None,  # system 触发
            actor_meta={"system": "hitl_timeout_worker"},
            action="hitl.escalate",
            target_type="node_state",
            target_id=ns.id,
            actor_ip="system",
            actor_ua="hitl_timeout_worker",
            decision="escalate",
            node_state_id=ns.id,
            meta={
                "instance_id": str(ns.instance_id),
                "original_actor_email": original_actor.get("email", "unknown"),
                "escalate_to": escalate_email,
                "reason": "timeout_72h",
            },
        )
        self.db.add(audit)
