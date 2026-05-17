"""HITL 节点 executor — LangGraph 1.2 interrupt + Command(resume) 集成。

设计参考 docs/reading-dify-03-02-hitl-executor-2026-05-17.md
+ docs/reading-dify-04-11-hitl-node-chain-2026-05-17.md (Plan 04-11)：
- Dify human_input_adapter EmailDeliveryConfig 模式 → 我们用 node_def.config.email_recipients
- LangGraph 1.2 interrupt 返回值在 resume 后注入，节点函数前后两段执行
- 节点函数会在 resume 时**从头重跑**（langgraph/types.py:801-890 docstring）
  → 副作用归外（ExecutionEngine 注入 __node_state_id），纯函数归内（__call__）

为何**不**复用 BaseNodeExecutor.__call__ 的重试装饰器：
- interrupt() 会 raise GraphInterrupt 跳出 ainvoke，外层 graph runner 会 ainvoke(Command(resume=...))
- 重试装饰器会把 GraphInterrupt 当 normal exception 吞掉
- 因此 override __call__，跳过 retry/timeout 包装，直接调 interrupt

CLAUDE.md 2.4 多租户：
- thread_id = {workspace_id}:{instance_id}（02-01 已落，本节点不重复包装）

CLAUDE.md 2.5：
- 本节点不直接消费 jti（GET 不消费 + POST /hitl/action 才消费 — 03-06）
- 本节点的 interrupt payload 仅描述决策上下文，不携带任何 token / 已生效凭证

Plan 04-11 chain 集成：
- interrupt_payload 加 4 chain 字段（chain_mode / approvers / current_idx / notify_channels）
- 前端决策页据此渲染参与人列表 + 当前轮次进度
- chain_mode 默认 'single'，approvers 默认 []，notify_channels 默认 ['email']
  → Phase 3 旧 DSL 无任何 chain 字段时仍走 single 模式 100% 向后兼容
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langgraph.types import interrupt

from app.agent_builder.workflow.hitl_payload import validate_form_data
from app.agent_builder.workflow.nodes.base import BaseNodeExecutor, NodeExecutionError

log = logging.getLogger(__name__)


class HITLNodeExecutor(BaseNodeExecutor):
    """HITL 节点：四态决策（HITL-01）+ 单 interrupt + 自管审批链状态（HITL-03）。

    v1（Phase 3）支持 single 模式（mode=single, 1 个 approver）；
    sequential / parallel_all / parallel_any → Phase 4。

    生命周期：
    1. ExecutionEngine 注入 __node_state_id 到 state（一次性副作用：写 hitl_tokens + 入队邮件）
    2. __call__(state) → interrupt({...}) → raise GraphInterrupt 暂停 graph
    3. (graph 暂停期间，DB checkpoint 已写完整 state；hitl_tokens 已 INSERT；邮件已发)
    4. 用户点邮件 → POST /hitl/action/<jwt>（03-06）→ ainvoke(Command(resume={...}))
    5. __call__(state) 第二次执行 → interrupt() 直接返回 resume 值 → validate + 返回 decision
    """

    # interrupt 不能被 tenacity 重试包装，所以不暴露 retryable_exceptions
    def _retryable_exceptions(self) -> tuple[type[Exception], ...]:
        return ()

    async def __call__(self, state: dict) -> dict[str, dict[str, Any]]:
        """LangGraph node fn 入口。

        override BaseNodeExecutor.__call__ 跳过 retry/timeout 装饰器
        （因为 interrupt 会 raise GraphInterrupt，必须直接传递到 LangGraph runner）。

        State Pointer 和 EventBus 仍走简化版本（本节点不写 raw 大字段）。

        Args:
            state: 当前 LangGraph state dict（含 __node_state_id，由 ExecutionEngine 注入）

        Returns:
            {self.node_id: decision_dict}，LangGraph 自动 merge

        Raises:
            GraphInterrupt: 第一次执行时由 interrupt() 抛出（不算异常，是控制流）
            NodeExecutionError: 缺少 __node_state_id / form_data 校验失败
        """
        # ── 0. EventBus node.start 事件（与 BaseNodeExecutor 对齐） ──────────
        if self.event_bus is not None and self.instance_id is not None:
            from app.agent_builder.workflow.event_bus import EVENT_NODE_START

            await self.event_bus.publish(
                self.instance_id,
                EVENT_NODE_START,
                {"node_id": self.node_id, "node_type": self.node_type},
            )

        # ── 1. Pre-interrupt：组装 interrupt payload ────────────────────────
        # 注意：本节点函数在 resume 时会从头重跑（LangGraph 1.2 interrupt 语义），
        # 所以这里只能做幂等只读操作，不能写 DB / 发邮件。
        rendered_config = self._render_config(state)

        # 注意：LangGraph 会把 dunder（__xxx）前缀字段视为内部保留并剥离，
        # 因此 ExecutionEngine 注入 node_state_id 时统一用单下划线前缀 `_node_state_id`。
        node_state_id = state.get("_node_state_id")
        if not node_state_id:
            raise NodeExecutionError(
                self.node_id,
                "缺少 _node_state_id（应由 ExecutionEngine 在节点 enter 时注入到 state）",
            )

        # ── Plan 04-11: chain 元数据（前端决策页据此渲染参与人列表 + 进度）─
        # 默认值保证 Phase 3 旧 DSL 无任何 chain 字段时仍走 single 模式 100% 向后兼容。
        # 数据来源：ExecutionEngine._on_hitl_enter 通过 node_def.config 注入这些字段
        # （chain_mode 已存进 node_state.payload.approval_chain，节点 enter 完成后 config 透传到 rendered_config）。
        chain_mode = rendered_config.get("chain_mode", "single")
        approvers_raw = rendered_config.get("approvers") or []
        # approvers 序列化为 str list（UUID → str）便于 LangGraph checkpoint JSON 编码
        approvers_serialized = [str(a) for a in approvers_raw]
        current_idx = int(rendered_config.get("current_idx", 0))
        notify_channels = list(rendered_config.get("notify_channels") or ["email"])

        interrupt_payload: dict[str, Any] = {
            "node_state_id": str(node_state_id),
            # Phase 3 single 模式：从 config / state 取 phase，默认 "submit"
            "phase": rendered_config.get("phase", "submit"),
            "form_schema": rendered_config.get("form_schema", {}),
            "deadline_at": rendered_config.get("deadline_at"),
            "current_actor": rendered_config.get("current_actor"),
            # ── Plan 04-11 chain 元数据 ──────────────────────────────────────
            "chain_mode": chain_mode,
            "approvers": approvers_serialized,
            "current_idx": current_idx,
            "notify_channels": notify_channels,
        }

        # ── 2. interrupt() — 暂停 graph 或读取 resume value ─────────────────
        # 首次执行：raise GraphInterrupt 跳出（LangGraph 处理 + 写 checkpoint）
        # 二次执行（resume 后）：直接返回 Command(resume=...) 注入的 value
        decision = interrupt(interrupt_payload)

        # 校验 resume value 必须是 dict（防止 ainvoke(Command(resume="str")) 误用）
        if not isinstance(decision, dict):
            raise NodeExecutionError(
                self.node_id,
                f"resume value 必须是 dict, 收到 {type(decision).__name__}",
            )

        log.info(
            "HITL node %s resumed with action=%s actor_id=%s",
            self.node_id,
            decision.get("action"),
            decision.get("actor_id"),
        )

        # ── 3. 校验 form_data 是否符合 form_schema（HITL-05） ───────────────
        form_schema = rendered_config.get("form_schema") or {}
        form_data = decision.get("form_data") or {}
        if form_schema:
            # 抛 jsonschema.ValidationError，调用方（03-06 API）应捕获返回 422
            # 此处不捕获 — 让上层处理（资源校验失败不是节点 execute 失败）
            validate_form_data(form_schema, form_data)

        # ── 4. EventBus node.complete 事件 ──────────────────────────────────
        if self.event_bus is not None and self.instance_id is not None:
            from app.agent_builder.workflow.event_bus import EVENT_NODE_COMPLETE

            await self.event_bus.publish(
                self.instance_id,
                EVENT_NODE_COMPLETE,
                {
                    "node_id": self.node_id,
                    "node_type": self.node_type,
                    "action": decision.get("action"),
                },
            )

        # ── 5. 返回 decision dict 写入 state（LangGraph 自动 merge） ────────
        return {
            self.node_id: {
                "action": decision["action"],
                "reason": decision.get("reason", ""),
                "form_data": form_data,
                "actor_id": decision.get("actor_id"),
                "jti": decision.get("jti"),
                "ip": decision.get("ip"),
                "ua": decision.get("ua"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        }

    async def execute(self, config: dict, state: dict) -> dict | Any:
        """HITL 节点不通过 execute() 走（已 override __call__）。

        BaseNodeExecutor.execute 是 abstract，必须实现。
        这里抛 NodeExecutionError 防止误用（外部直接调 executor.execute() 时）。
        """
        raise NodeExecutionError(
            self.node_id,
            "HITLNodeExecutor 不实现 execute()，请通过 __call__(state) 调用",
        )
