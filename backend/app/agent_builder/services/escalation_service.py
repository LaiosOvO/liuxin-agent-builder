"""HITL 节点超时升级服务（Phase 3 03-09 + Phase 4 04-04 扩展）。

设计参考 docs/reading-dify-03-09-timeout-worker-2026-05-17.md §4
+ docs/reading-dify-04-04-escalation-expressions-2026-05-17.md：
- Dify 没有"主动升级到上级"逻辑（仅标记 TIMEOUT 让流程走 timeout 分支）
- 本项目独创：超过 72h 时换 actor 为 escalate_to 用户 + 发升级邮件 + 写 audit_log
- 本项目独创：4 表达式 prefix 路由（email / user:<uuid> / role:<code> / dept:<name>）

Phase 4 04-04 扩展（HITL-04 完整 4 表达式）:
- email: 'user@example.com' 或 'manager@company.com' （Phase 3 兼容）
- user:<uuid> — 解析为单个用户 email（同 workspace + active）
- role:<code> — 解析为 workspace 内 role.code 用户 emails（可能多人）
- dept:<name> — 抛 NotImplementedError（Phase 5 IM 目录双向同步后实现）

返回类型变更（向后兼容）:
- Phase 3: str | None（单 email）
- Phase 4: list[str] | None（兼容 role: 多匹配；email/user: 仍返回单元素 list）

CLAUDE.md immutability：
- 不修改入参 payload dict — 用 append_record 风格生成新 dict
- node_state.payload 字段赋值后由 SQLAlchemy ORM 持久化（外层 commit 时落 PG）

CLAUDE.md 2.4 多租户：
- 所有 helper 查询显式 workspace_id WHERE 注入（防越权拿其他 ws 用户 email）
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
from app.agent_builder.models.role import Role
from app.agent_builder.models.user import User
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole

log = logging.getLogger(__name__)


class EscalationExprError(Exception):
    """超时升级表达式解析错误（非配置错误时使用，目前未使用 — 保留扩展位）。"""


class EscalationService:
    """节点超时升级服务（Phase 3 落地 + Phase 4 4 表达式扩展）。

    职责：
    - resolve_escalate_to: 解析升级人 email 列表（4 表达式路由）
    - perform_escalation: 执行升级（多 email fan-out 发邮件 + 多条 audit_log）

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
    ) -> list[str] | None:
        """解析升级人 email 列表（Phase 4 4 表达式路由）。

        优先级：dept: (raise) > user: > role: > email > fallback workspace admin

        Args:
            node_config: 节点 DSL config（可能含 'escalate_to' 字段）
            workspace_id: 工作区 UUID（fallback 查询 + 越权防护）

        Returns:
            list[email] — 升级人 email 列表（可能 1 个或多个）
            None — 表达式无法解析 + fallback 也无 admin

        Raises:
            NotImplementedError: dept:<name> 表达式（Phase 5 IM 目录同步后实现）
        """
        # 1. 无 node_config：直接 fallback
        if not node_config:
            emails = await self._fallback_workspace_admin_emails(workspace_id)
            return emails or None

        expr = node_config.get("escalate_to")
        # 2. 空表达式或非字符串：fallback
        if not expr or not isinstance(expr, str):
            emails = await self._fallback_workspace_admin_emails(workspace_id)
            return emails or None

        expr = expr.strip()

        # 3. dept:<name> — Phase 5 实现
        if expr.startswith("dept:"):
            raise NotImplementedError(
                f"dept: 表达式（{expr}）将于 Phase 5（IM 目录双向同步）实现",
            )

        # 4. user:<uuid>
        if expr.startswith("user:"):
            uid_raw = expr[5:].strip()
            try:
                uid = UUID(uid_raw)
            except ValueError:
                log.warning(
                    "resolve_escalate_to: 非法 user: 表达式 %r（UUID parse fail）",
                    expr,
                )
                return None
            email = await self._get_user_email(uid, workspace_id)
            if email is None:
                log.warning(
                    "resolve_escalate_to: user:%s 在 workspace %s 未找到 active 用户",
                    uid,
                    workspace_id,
                )
                return None
            log.info("resolve_escalate_to: 解析 user: → %s", email)
            return [email]

        # 5. role:<code>
        if expr.startswith("role:"):
            role_code = expr[5:].strip()
            emails = await self._get_emails_by_role(role_code, workspace_id)
            if not emails:
                log.warning(
                    "resolve_escalate_to: role:%s 在 workspace %s 未匹配任何 active 用户 → 走 fallback",
                    role_code,
                    workspace_id,
                )
                # role: 未命中 → fallback admin（与 Phase 3 一致行为）
                fb_emails = await self._fallback_workspace_admin_emails(workspace_id)
                return fb_emails or None
            log.info(
                "resolve_escalate_to: 解析 role:%s → %d 人",
                role_code,
                len(emails),
            )
            return emails

        # 6. email (含 @ 且不含 :) — Phase 3 兼容
        if "@" in expr and ":" not in expr:
            log.info("resolve_escalate_to: 解析 email → %s", expr)
            return [expr]

        # 7. 都不匹配 → fallback
        log.warning(
            "resolve_escalate_to: 未识别表达式 %r，走 fallback admin",
            expr,
        )
        emails = await self._fallback_workspace_admin_emails(workspace_id)
        return emails or None

    async def _get_user_email(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> str | None:
        """查 user_id 用户的 email（必须属于 workspace_id + active）。

        多租户隔离：JOIN UserWorkspaceRole 强制 workspace_id 匹配，
        防止 attacker 配置 user:<其他 ws uuid> 越权拿到他人 email。
        """
        stmt = (
            select(User.email)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .where(
                User.id == user_id,
                UserWorkspaceRole.workspace_id == workspace_id,
                User.status == "active",
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        email = result.scalar_one_or_none()
        return str(email) if email else None

    async def _get_emails_by_role(
        self,
        role_code: str,
        workspace_id: UUID,
    ) -> list[str]:
        """查 workspace 内具有 role_code 的所有 active 用户 email 列表。

        distinct() 防同一 user 多角色重复（PK 约束已防，distinct 是兜底）。
        """
        stmt = (
            select(User.email)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .join(Role, Role.id == UserWorkspaceRole.role_id)
            .where(
                UserWorkspaceRole.workspace_id == workspace_id,
                Role.code == role_code,
                User.status == "active",
            )
            .distinct()
        )
        result = await self.db.execute(stmt)
        return [str(e) for e in result.scalars().all()]

    async def _fallback_workspace_admin_emails(
        self,
        workspace_id: UUID,
    ) -> list[str]:
        """fallback：workspace 下 admin 角色用户 emails；空时再 fallback platform super_admin。

        Phase 4 改造（vs Phase 3 单 email 版本）：
        - 不再 limit(1)，返回全部 admin
        - 二级 fallback 仍保留 super_admin（单元素列表）

        Returns:
            list[email] — 可能空列表（无 admin 也无 super_admin 时）
        """
        # 第一级：workspace 下 role.code='admin' 的全部 active 用户
        stmt = (
            select(User.email)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .join(Role, Role.id == UserWorkspaceRole.role_id)
            .where(
                UserWorkspaceRole.workspace_id == workspace_id,
                Role.code == "admin",
                User.status == "active",
            )
            .distinct()
        )
        result = await self.db.execute(stmt)
        emails = [str(e) for e in result.scalars().all()]
        if emails:
            return emails

        # 第二级 fallback：platform super_admin（不限 workspace）
        sa_stmt = (
            select(User.email)
            .where(
                User.is_super_admin.is_(True),
                User.status == "active",
            )
            .limit(1)
        )
        sa_result = await self.db.execute(sa_stmt)
        sa_email = sa_result.scalar_one_or_none()
        return [str(sa_email)] if sa_email else []

    async def perform_escalation(self, ns: NodeState) -> None:
        """执行升级（Phase 4 多 email fan-out 适配）。

        步骤：
        1. 加载 flow_instance（拿 node config + DSL）
        2. 解析升级人 email 列表（resolve_escalate_to）
           - dept: → catch NotImplementedError 跳过升级（配置错误不阻断 worker）
        3. 写 records 加 escalate 记录（escalate_to 改为 list；新增 escalate_count）
        4. 对每个 email 独立发邮件 + 独立 audit_log（多人各自审计行）
        5. 结构化日志 hitl.escalation.resolved（含 expression / matched_count）

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

        # 2. 解析升级人 email 列表
        try:
            escalate_emails = await self.resolve_escalate_to(
                node_config=node_config,
                workspace_id=ns.workspace_id,
            )
        except NotImplementedError as e:
            # dept: 表达式 — Phase 5 才实现；Phase 4 catch 后跳过升级（配置错误不阻断）
            log.error(
                "perform_escalation: 节点 %s 配置了 Phase 5 表达式（%s），跳过升级",
                ns.id,
                e,
            )
            return

        if not escalate_emails:
            log.error(
                "perform_escalation: 节点 %s 无法解析升级人（resolve 返回 None），跳过",
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
            "escalate_to": list(escalate_emails),  # Phase 4: list
            "escalate_count": len(escalate_emails),
        }
        new_records = old_records + [new_record]
        new_payload = dict(old_payload)  # 浅拷贝防修改入参
        new_payload["records"] = new_records
        # Phase 4 简化：保留原 current_actor（Phase 4 多人审批链才动态切换 actor）
        # 记录 escalate_to list 以便邮件模板渲染（兼容数组 Jinja for-loop）
        new_payload["escalate_to"] = list(escalate_emails)
        ns.payload = new_payload

        # 4. 对每个 email 独立发邮件 + 独立 audit_log（多人各自审计行）
        successful_emails: list[str] = []
        for email in escalate_emails:
            try:
                await self._send_escalation_email(ns, email, old_payload)
                await self._write_audit_log(ns, email)
                successful_emails.append(email)
            except Exception:
                # 单 email 失败不阻塞其他升级人 — 借鉴 Dify timeout task try/except 包住单条
                log.exception(
                    "perform_escalation: 单 email %s 升级失败（节点 %s），继续其他",
                    email,
                    ns.id,
                )

        # 5. 结构化日志（Phase 4 新增 — 表达式命中可观测性）
        log.info(
            "hitl.escalation.resolved",
            extra={
                "expression": (node_config or {}).get("escalate_to"),
                "matched_count": len(escalate_emails),
                "successful_count": len(successful_emails),
                "workspace_id": str(ns.workspace_id),
                "node_state_id": str(ns.id),
                "instance_id": str(ns.instance_id),
            },
        )
        log.info(
            "perform_escalation: 节点 %s 已升级到 %d 人：%s",
            ns.id,
            len(escalate_emails),
            ", ".join(escalate_emails),
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
        """发送单封升级邮件 — 复用 NotificationService.enqueue_hitl_email + reminder_round=3。

        模板路由（email_jobs.py）：payload.escalation=True → hitl_escalation.html

        Phase 4 多 email 适配：
        - 每个 email 独立 INSERT notifications 行（UNIQUE 约束按 recipient 区分）
        - 失败抛异常，由调用方 catch 不阻塞其他 email
        """
        from app.agent_builder.models.notification import Notification

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
            "escalation": True,
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
            # UNIQUE 冲突 — 已发过升级邮件给此 recipient（防多 worker 重发）
            log.info(
                "_send_escalation_email: 节点 %s recipient=%s 升级邮件已发过（UNIQUE 冲突），跳过",
                ns.id,
                escalate_email,
            )
            await self.db.rollback()
            return

        log.info(
            "_send_escalation_email: 升级邮件已入队 notification_id=%s recipient=%s",
            notif.id,
            escalate_email,
        )

        # 入队 arq job
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
        """写单条 audit_log（每个升级人独立一行 NET-05 审计）。

        action='hitl.escalate'
        decision='escalate'
        meta 含 instance_id / node_state_id / original_actor / escalate_to / reason
        """
        old_payload = ns.payload or {}
        original_actor = old_payload.get("current_actor") or {}
        # 计算 escalate_count（基于 records 中最新一条 escalate 的 list 长度）
        escalate_to_list = old_payload.get("escalate_to")
        if isinstance(escalate_to_list, list):
            escalate_count = len(escalate_to_list)
        else:
            escalate_count = 1
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
                "escalate_to": escalate_email,  # 单行只记本人，便于多人审计聚合
                "escalate_count": escalate_count,  # 总人数
                "reason": "timeout_72h",
            },
        )
        self.db.add(audit)
