"""HITL 决策提交业务逻辑层 — 并发安全核心 + 审批链 4 模式分叉（Plan 03-06 + 04-02）。

设计参考：
- docs/reading-dify-03-06-hitl-api-2026-05-17.md §7 — advisory_lock + jti 消费 + sibling 失效
- docs/reading-dify-04-02-chain-executor-2026-05-17.md — chain 分叉 + invalidate_chain + 补通知

7 步核心流程（保持 Phase 3）+ Phase 4 chain 分叉（step 6a/6b）：
1. 加载 flow_instance → build thread_id
2. pg_advisory_xact_lock(hash(thread_id))（Pitfall 2 防护）
3. 加载 node_state + form_schema 校验 form_data
4. HitlTokenStore.consume(jti) → JtiAlreadyConsumed if None
5. HitlTokenStore.invalidate_siblings(node_state_id, except_jti)
6. **chain 分叉（Phase 4 新增）**：
   - compute_chain_advance → ChainAdvanceResult
   - 6a. parallel_* 终止：invalidate_chain + 补通知（"已被 X 处理 / 已被 X 拒绝"）
   - 6b. sequential approve 推进：batch_create_tokens_for_actors + 发邮件给下一人
7. 写 node_state.payload + status（用 chain_result）
8. LangGraph resume（advisory_lock 内）
9. audit_log（meta 含 chain_mode + invalidated_count）
10. structured log "hitl.chain.advance"（Phase 7 Run Viewer 钩子）
11. commit

CLAUDE.md 2.5（GET 不消费 jti / POST 才消费）：
- 本 service 仅由 POST /hitl/action 路径调用
- 内部走 HitlTokenStore.consume → 原子 UPDATE used_at（Phase 3-01 已落）

CLAUDE.md 2.4 多租户：
- thread_id = "{workspace_id}:{instance_id}" 已含 workspace 前缀（Pitfall 13）
- 所有 DB 查询经 instance_id / node_state_id FK 链路隔离

CLAUDE.md immutability：
- 不修改入参 payload dict（append_record / compute_chain_advance 返回新 dict）
- 通过 SQLAlchemy ORM 字段赋值更新 node_state（事务提交后 ORM 自动同步）

Phase 4 chain 模式（compute_chain_advance 在 04-01 已建）：
- single: Phase 3 既有 — 一人决策即终态
- sequential: A → B → C 链式 — approve 推进；reject/return 立即终止
- parallel_all: 全员同意才推进；任一拒绝/退回 → invalidate_chain + 补通知
- parallel_any: 任一同意即推进；任一拒绝/退回 → invalidate_chain + 补通知
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from jsonschema import ValidationError as JsonSchemaError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.services.hitl_service import HitlService
from app.agent_builder.workflow.checkpoint import build_thread_id
from app.agent_builder.workflow.hitl_payload import (
    ChainAdvanceResult,
    append_record,
    compute_chain_advance,
    compute_next_status,
    validate_form_data,
)
from app.agent_builder.workflow.hitl_token_store import HitlTokenStore
from app.services.notification_service import NotificationService

log = logging.getLogger(__name__)


# ── 业务异常类（API 层据此差异化错误响应） ─────────────────────────────────────


class JtiAlreadyConsumed(Exception):
    """jti 已被消费（409 — 重复提交 / 伪造 jti）。"""


class FormDataValidationError(Exception):
    """form_data 不符合 form_schema（422 — 校验失败）。

    Attributes:
        errors: 错误消息列表（前端可逐条展示）
    """

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class FlowInstanceNotFound(Exception):
    """关联的 flow_instance 不存在（404）。"""


class NodeStateNotFound(Exception):
    """关联的 node_state 不存在（404）。"""


class ChainActorNotAuthorized(Exception):
    """actor_id 不在 approval_chain.approvers 内（403 — 越权决策）。

    由 compute_chain_advance 抛出 ValueError 时翻译；API 层应转 403。
    """


# ── HitlActionService ────────────────────────────────────────────────────────


class HitlActionService:
    """HITL 决策提交业务逻辑层。

    入口：`submit_action(payload, action, reason, form_data, ip, ua)`

    完整流程（11 步，详见模块 docstring）：
    1-5. Phase 3 原有：load → lock → validate → consume → invalidate_siblings
    6. **Phase 4 chain 分叉**：compute_chain_advance + parallel_* 失效 + sequential 推进
    7. 写 node_state.payload + status（用 chain_result）
    8. LangGraph resume（advisory_lock 内）
    9. audit_log（含 chain_mode + invalidated_count）
    10. structured log "hitl.chain.advance"
    11. commit
    """

    def __init__(
        self,
        db: AsyncSession,
        redis,
        graph_resumer=None,
        *,
        notification_service: NotificationService | None = None,
    ) -> None:
        """构造函数。

        Args:
            db: SQLAlchemy AsyncSession（事务包裹）
            redis: redis.asyncio.Redis 客户端（HitlTokenStore 加速 + sibling pipeline）
            graph_resumer: 可选 — 注入 LangGraph resume 函数（测试用 mock；生产用 _default_graph_resumer）
                          签名：async (flow_instance, db, redis, *, resume_args, thread_id) -> bool
                          内部应当持有 checkpointer 生命周期（async with get_checkpointer()）
                          + 编译 DSL + ainvoke(Command(resume=...))，返回 True 表示成功推进
            notification_service: 可选 — 注入 NotificationService（测试可 mock 入队行为）
                          默认 None 时按需 lazy 构造（chain 模式才需要）
        """
        self.db = db
        self.redis = redis
        self._graph_resumer = graph_resumer
        self._notification_service = notification_service

    async def submit_action(
        self,
        *,
        payload: dict,
        action: str,
        reason: str,
        form_data: dict,
        ip: str,
        ua: str,
    ) -> dict[str, Any]:
        """完整提交链路 — 详见类 docstring。

        Args:
            payload: HitlTokenService.decode 返回的 JWT payload dict
                     必含字段：jti / flow_id / node_state_id / actor_id / actor_email(可选)
            action: 决策动作（submit/approve/return/reject）
            reason: 决策原因（可选文本）
            form_data: 表单数据（jsonschema 校验后写入 record）
            ip: 客户端 IP（审计 + token consume 写入）
            ua: 客户端 User-Agent

        Returns:
            {
                "status": "ok",
                "new_node_status": <new_status>,
                "instance_id": <str>,
                "invalidated_siblings": <int>,
                "chain_mode": <str>,           # Phase 4 新增
                "invalidated_chain": <int>,    # Phase 4 新增
                "next_approvers": <list[str]>, # Phase 4 新增（sequential approve 时非空）
            }

        Raises:
            JtiAlreadyConsumed: 重复提交 / 伪造 jti（→ 409）
            FormDataValidationError: form_data 不符合 schema（→ 422）
            FlowInstanceNotFound / NodeStateNotFound: FK 链路失效（→ 404）
            ChainActorNotAuthorized: actor 不在 approvers（→ 403）
        """
        # 解析 payload 字段（payload 来自 JWT decode，已校验签名 + aud + exp）
        jti = UUID(payload["jti"])
        node_state_id = UUID(payload["node_state_id"])
        instance_id = UUID(payload["flow_id"])
        actor_id = UUID(payload["actor_id"])
        actor_email = payload.get("actor_email", "")

        # ── 1. 加载 flow_instance（拿 workspace_id 构 thread_id）────────────
        flow_instance = await self.db.get(FlowInstance, instance_id)
        if flow_instance is None:
            raise FlowInstanceNotFound(f"instance_id={instance_id} 不存在")

        thread_id = build_thread_id(flow_instance.workspace_id, instance_id)

        # ── 2. PG advisory_xact_lock（Pitfall 2 防护）─────────────────────
        # 锁 key = hash(thread_id) & 0x7FFFFFFFFFFFFFFF
        # 事务结束时 PG 自动释放（_xact_ 后缀语义）
        lock_key = hash(thread_id) & 0x7FFFFFFFFFFFFFFF
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(:k)"),
            {"k": lock_key},
        )

        # ── 3. 加载 node_state + form_schema 校验 form_data ───────────────
        node_state = await self.db.get(NodeState, node_state_id)
        if node_state is None:
            raise NodeStateNotFound(f"node_state_id={node_state_id} 不存在")

        ns_payload = node_state.payload or {}
        form_schema = ns_payload.get("form_schema", {})
        # 空 schema {} 视为不约束（hitl_payload.validate_form_data 内已处理）
        # 非空 schema 必须校验 form_data（即使 form_data 为空 dict，required 字段缺失也要报）
        if form_schema:
            try:
                validate_form_data(form_schema, form_data or {})
            except JsonSchemaError as e:
                # 不消费 jti，让用户修改后重试
                raise FormDataValidationError([str(e.message)]) from e

        # ── 4. 原子消费 jti（HitlTokenStore.consume）──────────────────────
        store = HitlTokenStore(self.db, self.redis)
        token_row = await store.consume(jti, ip=ip, ua=ua)
        if token_row is None:
            raise JtiAlreadyConsumed(
                f"jti={jti} 已被消费 / 不存在（重复提交或伪造）"
            )

        # ── 5. 失效同节点其他 token（HITL-01）─────────────────────────────
        # 注意：parallel_* 模式下「同 node_state_id」也有其他 actor 的 token，不应一并失效
        # 因此仅在 single/sequential 模式下调 invalidate_siblings
        # （sequential 模式下同 node_state 内只有当前 idx 的 actor 有 token，等效于 single）
        chain = ns_payload.get("approval_chain") or {}
        chain_mode = chain.get("mode", "single")

        if chain_mode in ("single", "sequential"):
            invalidated_count = await store.invalidate_siblings(
                node_state_id, except_jti=jti
            )
            log.info(
                "invalidated %d sibling tokens for node_state_id=%s",
                invalidated_count,
                node_state_id,
            )
        else:
            # parallel_* 模式：仅失效当前 actor 自己的其他 action token（防 actor 后续点 reject）
            # 用 actor_id 过滤的精准失效（不直接调 invalidate_siblings）
            invalidated_count = await self._invalidate_self_other_actions(
                store=store,
                node_state_id=node_state_id,
                actor_id=actor_id,
                except_jti=jti,
            )
            log.info(
                "invalidated %d own-actor sibling tokens for actor=%s node_state_id=%s",
                invalidated_count,
                actor_id,
                node_state_id,
            )

        # ── 6. Phase 4 chain 分叉 ─────────────────────────────────────────
        # 决策依据 04-CONTEXT.md §审批链 4 模式语义；04-01 已建 compute_chain_advance
        chain_advance_result, invalidated_chain = await self._advance_chain(
            ns_payload=ns_payload,
            actor_id=actor_id,
            action=action,
            chain_mode=chain_mode,
            instance_id=instance_id,
            node_state_id=node_state_id,
            except_jti=jti,
            store=store,
            flow_instance=flow_instance,
            actor_email=actor_email,
            reason=reason,
        )

        # ── 7. 写 node_state.payload + status ─────────────────────────────
        # chain_result 已包含 immutable 新 payload（含 approval_chain.decisions 更新）
        # 但 records 字段需 append（chain_advance 不处理 records）
        new_payload = append_record(
            chain_advance_result.new_payload,
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,  # type: ignore[arg-type]
            reason=reason,
            form_data=form_data,
            ip=ip,
            ua=ua,
        )

        # chain_mode='single' 路径走 Phase 3 既有状态机（防破坏 Phase 3 行为）
        # 其他模式用 chain_advance_result.new_status
        if chain_mode == "single":
            current_phase = ns_payload.get("phase", "submit")
            new_status = compute_next_status(action, current_phase)  # type: ignore[arg-type]
        else:
            new_status = chain_advance_result.new_status

        node_state.payload = new_payload
        node_state.status = new_status

        # ── 8. LangGraph resume（在 advisory_lock 持有期间执行）────────────
        # 注意：必须在锁内 ainvoke，否则 Pitfall 2 仍会触发
        # resumer 内部负责 checkpointer 生命周期 + compile + ainvoke
        resume_args = {
            "action": action,
            "reason": reason,
            "form_data": form_data,
            "actor_id": str(actor_id),
            "ip": ip,
            "ua": ua,
            "jti": str(jti),
        }
        await self._resume_graph(
            flow_instance,
            resume_args=resume_args,
            thread_id=thread_id,
        )

        # ── 9. audit_log（NET-05 决策审计 + Phase 4 chain_mode/invalidated_chain）─
        audit = AuditLog(
            workspace_id=flow_instance.workspace_id,
            actor_user_id=actor_id,
            action="hitl.decision",
            target_type="node_state",
            target_id=node_state_id,
            actor_ip=ip,
            actor_ua=ua,
            decision=action,
            node_state_id=node_state_id,
            meta={
                "jti": str(jti),
                "instance_id": str(instance_id),
                "reason": reason,
                "invalidated_siblings": invalidated_count,
                # Phase 4 新增字段（Phase 7 Run Viewer / 审计回放用）
                "chain_mode": chain_mode,
                "invalidated_count": len(invalidated_chain),
                "next_approvers": [str(a) for a in chain_advance_result.next_approvers],
            },
        )
        self.db.add(audit)

        # ── 10. structured log（Phase 7 Run Viewer 钩子）─────────────────
        # logger.info 'hitl.chain.advance' + extra={...} — caplog 可捕获 record
        log.info(
            "hitl.chain.advance",
            extra={
                "chain_mode": chain_mode,
                "actor_id": str(actor_id),
                "action": action,
                "new_status": new_status,
                "next_approvers_count": len(chain_advance_result.next_approvers),
                "invalidated_count": len(invalidated_chain),
                "instance_id": str(instance_id),
                "node_state_id": str(node_state_id),
            },
        )

        # ── 11. 提交事务（advisory_lock 在此刻释放）─────────────────────
        await self.db.commit()

        return {
            "status": "ok",
            "new_node_status": new_status,
            "instance_id": str(instance_id),
            "invalidated_siblings": invalidated_count,
            # Phase 4 新增返回字段
            "chain_mode": chain_mode,
            "invalidated_chain": len(invalidated_chain),
            "next_approvers": [str(a) for a in chain_advance_result.next_approvers],
        }

    # ── Phase 4 内部 helper ───────────────────────────────────────────────────

    async def _advance_chain(
        self,
        *,
        ns_payload: dict,
        actor_id: UUID,
        action: str,
        chain_mode: str,
        instance_id: UUID,
        node_state_id: UUID,
        except_jti: UUID,
        store: HitlTokenStore,
        flow_instance: FlowInstance,
        actor_email: str,
        reason: str,
    ) -> tuple[ChainAdvanceResult, list[tuple[UUID, UUID]]]:
        """chain 推进主入口：算 ChainAdvanceResult + 触发副作用。

        副作用顺序（必须在 advisory_lock 持有期间）：
        1. parallel_* 终止 → invalidate_chain（失效全 instance 其他未消费 token）
        2. parallel_* 终止 → _supplement_notify（发"已被 X 处理"补通知）
        3. sequential approve → batch_create_tokens_for_actors（给下一人创建 token）
        4. sequential approve → _enqueue_chain_notifications（给下一人发邮件）

        Args:
            ns_payload: 当前 node_state.payload
            actor_id: 提交决策的人
            action: 决策动作
            chain_mode: 'single' / 'sequential' / 'parallel_all' / 'parallel_any'
            instance_id: 流程实例 UUID
            node_state_id: 节点状态 UUID
            except_jti: 当前合法消费的 jti（不要失效）
            store: HitlTokenStore 实例（复用同 session）
            flow_instance: 当前 flow_instance ORM
            actor_email: 当前 actor 邮箱（补通知用作"被 X 处理"中的 X）
            reason: 决策原因

        Returns:
            (chain_advance_result, invalidated_chain_list)
            invalidated_chain_list: list[(jti, actor_id)] — parallel_* 终止时失效的 token

        Raises:
            ChainActorNotAuthorized: compute_chain_advance ValueError 时翻译
        """
        # single 模式：包装 Phase 3 既有行为（next_approvers=[], invalidate_others=False）
        # 不调 compute_chain_advance 以避免 actor_id 校验冲突（single 模式 actor 不一定在 approvers）
        if chain_mode == "single":
            # 构造一个 placeholder ChainAdvanceResult（与既有 Phase 3 流程兼容）
            empty_result = ChainAdvanceResult(
                new_status="in_review",  # 仅占位；实际 new_status 由 compute_next_status 决定
                new_payload={**ns_payload},
                next_approvers=[],
                invalidate_others=False,
                supplement_notify=[],
            )
            return empty_result, []

        # Phase 4: sequential / parallel_all / parallel_any 走 compute_chain_advance
        try:
            chain_result = compute_chain_advance(
                ns_payload, actor_id, action  # type: ignore[arg-type]
            )
        except ValueError as e:
            # actor 不在 approvers / 越权 / 非法 chain_mode → 翻译为 403
            raise ChainActorNotAuthorized(str(e)) from e

        invalidated_chain: list[tuple[UUID, UUID]] = []

        # 6a. parallel_* 终止：invalidate_chain + 补通知
        if chain_result.invalidate_others:
            invalidated_chain = await store.invalidate_chain(
                instance_id=instance_id,
                except_jti=except_jti,
            )
            if invalidated_chain:
                await self._supplement_notify(
                    invalidated_chain=invalidated_chain,
                    action=action,
                    actor_email=actor_email,
                    flow_instance=flow_instance,
                    node_state_id=node_state_id,
                )

        # 6b. sequential approve 推进：给下一人创建 token + 通知
        if chain_result.next_approvers:
            hitl_svc = HitlService(self.db)
            new_tokens = await hitl_svc.batch_create_tokens_for_actors(
                instance_id=instance_id,
                node_state_id=node_state_id,
                actor_ids=chain_result.next_approvers,
                # chain 中所有非首发审批人无 submit 权（只能 approve/return/reject）
                allowed_actions=["approve", "return", "reject"],
            )
            await self._enqueue_chain_notifications(
                new_tokens=new_tokens,
                ns_payload=ns_payload,
                chain_result=chain_result,
                flow_instance=flow_instance,
                node_state_id=node_state_id,
                instance_id=instance_id,
            )

        return chain_result, invalidated_chain

    async def _invalidate_self_other_actions(
        self,
        *,
        store: HitlTokenStore,
        node_state_id: UUID,
        actor_id: UUID,
        except_jti: UUID,
    ) -> int:
        """parallel_* 模式：仅失效当前 actor 的其他 action token。

        理由（决策依据 04-CONTEXT.md §并行会签 / 或签）：
        - parallel_* 模式下「同 node_state」有多 actor 的 token；不能一并失效
        - 但当前 actor 的其他 action（approve/return/reject）应该失效（防同一人后续翻牌）

        Args:
            store: HitlTokenStore（复用 session）
            node_state_id: 节点状态 UUID
            actor_id: 当前提交决策的 actor（仅失效此人的其他 token）
            except_jti: 当前合法消费的 jti

        Returns:
            被失效的 token 数量（0~2）

        Notes:
            直接 SQL UPDATE — 不走 invalidate_siblings（避免误伤其他 actor）；
            used_ip='system:self-other-actions' 标识来源。
        """
        from datetime import datetime, timezone
        from sqlalchemy import update as sa_update

        from app.agent_builder.models.hitl_token import HitlToken

        now = datetime.now(timezone.utc)
        stmt = (
            sa_update(HitlToken)
            .where(
                HitlToken.node_state_id == node_state_id,
                HitlToken.actor_id == actor_id,
                HitlToken.jti != except_jti,
                HitlToken.used_at.is_(None),
            )
            .values(
                used_at=now,
                used_ip="system:self-other-actions",
            )
            .returning(HitlToken.jti)
        )
        result = await self.db.execute(stmt)
        invalidated = list(result.scalars().all())

        if invalidated:
            # Redis 同步标记
            from app.agent_builder.workflow.hitl_token_store import (
                _REDIS_TTL_SECONDS,
                _redis_key,
            )

            async with store.redis.pipeline(transaction=False) as pipe:
                for jti in invalidated:
                    pipe.set(_redis_key(jti), "consumed", ex=_REDIS_TTL_SECONDS)
                await pipe.execute()

        return len(invalidated)

    async def _supplement_notify(
        self,
        *,
        invalidated_chain: list[tuple[UUID, UUID]],
        action: str,
        actor_email: str,
        flow_instance: FlowInstance,
        node_state_id: UUID,
    ) -> int:
        """parallel_* 终止时发"已被 X 处理 / 已被 X 拒绝"补通知（generic email）。

        典型场景：
        - parallel_all reject by A → B/C/D 收到补通知"申请已被 X 拒绝"
        - parallel_any approve by A → B/C/D 收到补通知"申请已被 X 处理"

        Args:
            invalidated_chain: list[(jti, actor_id)] — invalidate_chain 返回值
            action: 当前决策动作（决定 subject 文案）
            actor_email: 当前 actor 邮箱（subject 中的 X）
            flow_instance: 当前流程实例
            node_state_id: 节点状态 UUID（FK 约束 — 补通知需引用）

        Returns:
            实际入队的补通知数量（去重 actor_id 后；同 actor 多 token 只发 1 封）

        Notes:
            - 同 actor 失效多 token 仅发 1 封补通知（按 actor_id 去重）
            - 收件人 email 通过 actor_id JOIN users 表查询；查不到的 actor 跳过
            - 失败入队不阻塞主流程（log.warning 即可；fire-and-forget）
        """
        # 去重 actor_id（同 actor 多 token 仅 1 封补通知）
        unique_actor_ids = list({actor_id for _, actor_id in invalidated_chain})
        if not unique_actor_ids:
            return 0

        # 主题文案：reject → "已被 X 拒绝"；approve/return → "已被 X 处理"
        if action == "reject":
            subject = f"申请已被 {actor_email or '审批人'} 拒绝"
            body = (
                f"您之前收到的审批邀请已失效。\n\n"
                f"操作人: {actor_email or '审批人'}\n"
                f"决策: 拒绝\n"
                f"原因: 申请已被其他审批人决策"
            )
        else:
            subject = f"申请已被 {actor_email or '审批人'} 处理"
            body = (
                f"您之前收到的审批邀请已失效。\n\n"
                f"操作人: {actor_email or '审批人'}\n"
                f"决策: {action}\n"
                f"原因: 申请已被其他审批人决策"
            )

        # JOIN users 查 email
        from app.agent_builder.models.user import User
        from sqlalchemy import select as sa_select

        rows = (
            await self.db.execute(
                sa_select(User.id, User.email).where(User.id.in_(unique_actor_ids))
            )
        ).all()
        actor_email_map = {row[0]: row[1] for row in rows}

        notify_svc = self._get_notification_service()
        sent_count = 0
        for actor_id in unique_actor_ids:
            email = actor_email_map.get(actor_id)
            if not email:
                log.warning(
                    "supplement_notify: actor_id=%s 无 email 跳过（补通知）",
                    actor_id,
                )
                continue
            try:
                await notify_svc.enqueue_generic_email(
                    workspace_id=flow_instance.workspace_id,
                    instance_id=flow_instance.id,
                    node_state_id=node_state_id,
                    recipient_email=email,
                    subject=subject,
                    body=body,
                )
                sent_count += 1
            except Exception as e:  # noqa: BLE001 — fire-and-forget 防阻塞主流程
                log.warning(
                    "supplement_notify enqueue 失败 actor=%s email=%s: %s",
                    actor_id,
                    email,
                    e,
                )
        return sent_count

    async def _enqueue_chain_notifications(
        self,
        *,
        new_tokens: list[HitlToken],
        ns_payload: dict,
        chain_result: ChainAdvanceResult,
        flow_instance: FlowInstance,
        node_state_id: UUID,
        instance_id: UUID,
    ) -> int:
        """sequential approve 推进：给 next_approvers 发邮件通知。

        简化版（Phase 4 04-02 范围）：用 enqueue_generic_email 发通用邮件，
        body 含审批链接（前端拼装）。完整 enqueue_hitl_email + 表单渲染留 04-12 plan
        （HITL 节点 executor 集成）。

        Args:
            new_tokens: batch_create_tokens_for_actors 返回的 token 列表
            ns_payload: 当前 payload（取 flow_title / node_title 渲染）
            chain_result: ChainAdvanceResult（含 next_approvers）
            flow_instance: 当前流程实例
            node_state_id: 节点状态 UUID
            instance_id: 流程实例 UUID

        Returns:
            实际入队的通知数量（按 actor 去重）
        """
        # 按 actor 分组 token（每 actor 多 token 仅发 1 封邮件）
        tokens_by_actor: dict[UUID, list[HitlToken]] = {}
        for t in new_tokens:
            tokens_by_actor.setdefault(t.actor_id, []).append(t)

        # JOIN users 查 email
        from app.agent_builder.models.user import User
        from sqlalchemy import select as sa_select

        actor_ids = list(tokens_by_actor.keys())
        rows = (
            await self.db.execute(
                sa_select(User.id, User.email).where(User.id.in_(actor_ids))
            )
        ).all()
        actor_email_map = {row[0]: row[1] for row in rows}

        # subject/body 简化：通用通知
        flow_title = ns_payload.get("flow_title", "工作流")
        node_title = ns_payload.get("node_title", "审批节点")
        subject = f"[{flow_title}] {node_title} - 需要您审批"
        body_template = (
            f"流程: {flow_title}\n"
            f"节点: {node_title}\n\n"
            f"请前往审批页面处理。"
        )

        notify_svc = self._get_notification_service()
        sent_count = 0
        for actor_id in actor_ids:
            email = actor_email_map.get(actor_id)
            if not email:
                log.warning(
                    "_enqueue_chain_notifications: actor_id=%s 无 email 跳过",
                    actor_id,
                )
                continue
            try:
                await notify_svc.enqueue_generic_email(
                    workspace_id=flow_instance.workspace_id,
                    instance_id=instance_id,
                    node_state_id=node_state_id,
                    recipient_email=email,
                    subject=subject,
                    body=body_template,
                )
                sent_count += 1
            except Exception as e:  # noqa: BLE001 — fire-and-forget
                log.warning(
                    "_enqueue_chain_notifications enqueue 失败 actor=%s: %s",
                    actor_id,
                    e,
                )
        return sent_count

    def _get_notification_service(self) -> NotificationService:
        """Lazy 构造 NotificationService（chain 模式才用；single 模式不构造）。"""
        if self._notification_service is None:
            self._notification_service = NotificationService(self.db)
        return self._notification_service

    async def _resume_graph(
        self,
        flow_instance: FlowInstance,
        *,
        resume_args: dict,
        thread_id: str,
    ) -> bool:
        """触发 LangGraph Command(resume) — 用于推进中断的 HITL 节点。

        生产环境：调用 _default_graph_resumer（持 AsyncPostgresSaver context + compile + ainvoke）
        测试环境：注入 graph_resumer（mock），可返回 True/False 测试不同分支

        Args:
            flow_instance: 当前实例 ORM 行
            resume_args: Command(resume=...) 的 payload
            thread_id: LangGraph checkpoint thread_id（含 workspace 前缀）

        Returns:
            True: 成功 ainvoke；False: resumer 不可用或 DSL 缺失（不阻塞 node_state 写入）
        """
        if self._graph_resumer is None:
            return False
        return await self._graph_resumer(
            flow_instance,
            self.db,
            self.redis,
            resume_args=resume_args,
            thread_id=thread_id,
        )
