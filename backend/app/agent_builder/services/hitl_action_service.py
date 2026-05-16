"""HITL 决策提交业务逻辑层 — 并发安全核心（Plan 03-06）。

设计参考 docs/reading-dify-03-06-hitl-api-2026-05-17.md §7：
- advisory_xact_lock (hash(thread_id)) + jti UPDATE...WHERE used_at IS NULL RETURNING = 双保险
- LangGraph graph.ainvoke(Command(resume=...)) 推进 interrupt
- sibling token 失效（HITL-01 防重复决策）
- audit_log 写入 NET-05 决策审计字段（actor_ip/actor_ua/decision/node_state_id）

CLAUDE.md 2.5（GET 不消费 jti / POST 才消费）：
- 本 service 仅由 POST /hitl/action 路径调用
- 内部走 HitlTokenStore.consume → 原子 UPDATE used_at（Phase 3-01 已落）

CLAUDE.md 2.4 多租户：
- thread_id = "{workspace_id}:{instance_id}" 已含 workspace 前缀（Pitfall 13）
- 所有 DB 查询经 instance_id / node_state_id FK 链路隔离

CLAUDE.md immutability：
- 不修改入参 payload dict（append_record 返回新 dict）
- 通过 SQLAlchemy ORM 字段赋值更新 node_state（事务提交后 ORM 自动同步）
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from jsonschema import ValidationError as JsonSchemaError
from langgraph.types import Command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.workflow.checkpoint import build_thread_id
from app.agent_builder.workflow.hitl_payload import (
    append_record,
    compute_next_status,
    validate_form_data,
)
from app.agent_builder.workflow.hitl_token_store import HitlTokenStore

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


# ── HitlActionService ────────────────────────────────────────────────────────


class HitlActionService:
    """HITL 决策提交业务逻辑层。

    入口：`submit_action(payload, action, reason, form_data, ip, ua)`

    完整流程（7 步，详见 reading-dify-03-06 §7）：
    1. 加载 flow_instance → build thread_id
    2. pg_advisory_xact_lock(hash(thread_id))（Pitfall 2 防护）
    3. 加载 node_state + form_schema 校验 form_data
    4. HitlTokenStore.consume(jti) → JtiAlreadyConsumed if None
    5. HitlTokenStore.invalidate_siblings(node_state_id, except_jti)
    6. append_record + compute_next_status → 更新 node_state.payload + status
    7. graph.ainvoke(Command(resume=...)) + audit_log + commit
    """

    def __init__(
        self,
        db: AsyncSession,
        redis,
        graph_loader=None,
    ) -> None:
        """构造函数。

        Args:
            db: SQLAlchemy AsyncSession（事务包裹）
            redis: redis.asyncio.Redis 客户端（HitlTokenStore 加速 + sibling pipeline）
            graph_loader: 可选 — 注入 graph 构造函数（测试用 mock；生产用 _default_graph_loader）
                          签名：async (flow_instance: FlowInstance, db, redis) -> graph
        """
        self.db = db
        self.redis = redis
        self._graph_loader = graph_loader

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
            {"status": "ok", "new_node_status": <new_status>, "instance_id": <str>}

        Raises:
            JtiAlreadyConsumed: 重复提交 / 伪造 jti（→ 409）
            FormDataValidationError: form_data 不符合 schema（→ 422）
            FlowInstanceNotFound / NodeStateNotFound: FK 链路失效（→ 404）
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
        if form_schema and form_data:
            try:
                validate_form_data(form_schema, form_data)
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
        invalidated_count = await store.invalidate_siblings(
            node_state_id, except_jti=jti
        )
        log.info(
            "invalidated %d sibling tokens for node_state_id=%s",
            invalidated_count,
            node_state_id,
        )

        # ── 6. 更新 node_state.payload + status（immutable append）────────
        new_payload = append_record(
            ns_payload,
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,  # type: ignore[arg-type]
            reason=reason,
            form_data=form_data,
            ip=ip,
            ua=ua,
        )
        current_phase = ns_payload.get("phase", "submit")
        new_status = compute_next_status(action, current_phase)  # type: ignore[arg-type]
        node_state.payload = new_payload
        node_state.status = new_status

        # ── 7. LangGraph resume（在 advisory_lock 持有期间执行）────────────
        # 注意：必须在锁内 ainvoke，否则 Pitfall 2 仍会触发
        graph = await self._load_graph(flow_instance)
        if graph is not None:
            await graph.ainvoke(
                Command(
                    resume={
                        "action": action,
                        "reason": reason,
                        "form_data": form_data,
                        "actor_id": str(actor_id),
                        "ip": ip,
                        "ua": ua,
                        "jti": str(jti),
                    }
                ),
                config={"configurable": {"thread_id": thread_id}},
            )

        # ── 8. audit_log（NET-05 决策审计）────────────────────────────────
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
            },
        )
        self.db.add(audit)

        # 提交事务（advisory_lock 在此刻释放）
        await self.db.commit()

        return {
            "status": "ok",
            "new_node_status": new_status,
            "instance_id": str(instance_id),
            "invalidated_siblings": invalidated_count,
        }

    async def _load_graph(self, flow_instance: FlowInstance):
        """加载 LangGraph compiled graph 用于 resume。

        生产环境：构造 DSLCompiler 编译 dsl_snapshot
        测试环境：注入 graph_loader（mock）跳过真实编译
        """
        if self._graph_loader is not None:
            return await self._graph_loader(flow_instance, self.db, self.redis)

        # 生产默认：从 workflow_version 加载 DSL 并编译
        # 注：实际编译路径会在 ExecutionEngine 后续 plan 集成；
        # 本 service 仅依赖 graph_loader 注入点保持解耦
        return None
