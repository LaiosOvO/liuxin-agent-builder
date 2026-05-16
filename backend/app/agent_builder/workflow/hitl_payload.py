"""HITL payload 纯函数（无副作用，便于单测）。

提供 HITL 节点状态机的核心 payload 构造 / 变迁 / 校验的纯函数 API：

- build_initial_payload(...)：构造 node_state.payload 初态（phase / current_actor / approval_chain / records / form_schema / 时间字段）
- append_record(...)：immutable 追加一条决策 record（不修改原 payload）
- compute_next_status(...)：根据 action + current_phase 计算节点 status（5 → 3 终态）
- validate_form_data(...)：jsonschema Draft-7 校验 form_data 是否符合 form_schema
- compute_chain_advance(...)：审批链 4 模式（single / sequential / parallel_all / parallel_any）状态机推进（Phase 4 新增）

设计参考 docs/reading-dify-03-02-hitl-executor-2026-05-17.md §7 LangGraph 1.2 interrupt 最佳实践：
- interrupt() 后节点函数从头重跑 → 纯函数必须 idempotent + immutable
- 副作用（DB INSERT / 邮件入队）由 ExecutionEngine 一次性触发，不在此模块

Phase 4 chain 模式参考 docs/reading-dify-04-01-chain-payload-2026-05-17.md：
- Dify 无 approval_chain — 本项目独立设计
- ChainAdvanceResult @dataclass(frozen=True) + Literal["single", "sequential", "parallel_all", "parallel_any"]
- 严格 immutability：所有 helper 用 {**payload, ...} + new list/dict

四态枚举（CLAUDE.md 2.5 + 03-CONTEXT.md §HITL 节点状态机）：
- submit：执行人提交（v1 single 模式直接进 review）
- approve：审核人通过
- return：退回（重新分配 / 回到上一节点）
- reject：拒绝（终止流程）

节点 status 5 → 3 终态：
- pending → waiting_human → in_review → done | rejected | returned
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from jsonschema import Draft7Validator
from jsonschema import ValidationError as JsonSchemaValidationError  # noqa: F401 (re-export)

# ── 类型别名 ──────────────────────────────────────────────────────────────────

NodeStatus = Literal[
    "pending",  # 节点已入 DAG 但 enter 函数还没跑
    "waiting_human",  # 执行人提交前
    "in_review",  # 执行人 submit 后 → 进入审核
    "done",  # 终态：通过
    "rejected",  # 终态：拒绝
    "returned",  # 终态：退回
]
Action = Literal["submit", "approve", "return", "reject"]
Role = Literal["executor", "reviewer"]
Phase = Literal["submit", "review"]

# Phase 4 新增：审批链模式
ChainMode = Literal["single", "sequential", "parallel_all", "parallel_any"]


# ── ChainAdvanceResult: compute_chain_advance 返回值（不可变） ────────────────


@dataclass(frozen=True)
class ChainAdvanceResult:
    """compute_chain_advance 返回值（frozen dataclass，不可变）。

    设计依据见 docs/reading-dify-04-01-chain-payload-2026-05-17.md §6：
    - `frozen=True` 保证调用方不能修改返回值（与 CLAUDE.md immutability 一致）
    - `field(default_factory=list)` 防共享 mutable 默认值陷阱

    Attributes:
        new_status: 节点新 status（in_review / done / rejected / returned）
        new_payload: 新 payload dict（immutable，调用方写入 node_state.payload）
        next_approvers: 下轮需创建 token 的人（仅 sequential approve 给 1 人；其他情况空 list）
        invalidate_others: 是否需调 HitlTokenStore.invalidate_chain（parallel_* reject / parallel_any approve）
        supplement_notify: 需补"已终止/已处理"通知的 actor_id 列表（parallel_* 终止时除发起人外的其他 approvers）
    """

    new_status: NodeStatus
    new_payload: dict[str, Any]
    next_approvers: list[UUID] = field(default_factory=list)
    invalidate_others: bool = False
    supplement_notify: list[UUID] = field(default_factory=list)


# ── 纯函数：构造初态 ──────────────────────────────────────────────────────────


def build_initial_payload(
    *,
    current_actor_id: UUID,
    current_actor_email: str,
    role: Role,
    timeout_seconds: int,
    form_schema: dict[str, Any],
    approvers: list[UUID] | None = None,
    chain_mode: ChainMode = "single",
) -> dict[str, Any]:
    """构造 HITL 节点初始 payload（写入 node_state.payload）。

    Args:
        current_actor_id: 当前决策人 user_id
        current_actor_email: 当前决策人邮箱（邮件发送 + 审计日志用）
        role: 当前阶段角色（executor / reviewer）
        timeout_seconds: 节点超时秒数（决定 deadline_at）
        form_schema: 决策表单 JSON Schema（前端 RJSF 渲染 + 服务端校验用）
        approvers: 审批人列表（v1 single 模式默认 [current_actor_id]）
        chain_mode: 审批链模式（Phase 4 新增）。默认 'single' 保持 Phase 3 向后兼容。
            - single: 单人审批（Phase 3 默认）
            - sequential: 顺序会签（A → B → C，A 同意后才生成 B 的 token）
            - parallel_all: 并行全员同意（所有审批人都同意才推进；任一拒绝即终止）
            - parallel_any: 或签（任一同意即推进；任一拒绝即终止）

    Returns:
        新的 payload dict（immutable，调用方不应原地修改）。

    Notes:
        - 不写 DB，纯函数；调用方负责把返回值写入 node_state.payload
        - 时间字段均为 UTC ISO8601 字符串（含 +00:00 后缀）
        - role=executor → phase=submit；role=reviewer → phase=review（v1 single
          模式：执行人 submit 直接走 review，再 approve = done）
        - Phase 4 parallel_* 模式：decisions 字典 {actor_id: None} 初始化（None = 未决策）
        - Phase 4 sequential 模式：current_idx=0 指向链首
    """
    now = datetime.now(timezone.utc)
    phase: Phase = "submit" if role == "executor" else "review"

    effective_approvers = [str(a) for a in (approvers or [current_actor_id])]

    approval_chain: dict[str, Any] = {
        "mode": chain_mode,
        "approvers": effective_approvers,
        "current_idx": 0,
    }
    # Phase 4: parallel_* 模式初始化 decisions 字典（每个 approver 起始未决策）
    if chain_mode in ("parallel_all", "parallel_any"):
        approval_chain["decisions"] = {a: None for a in effective_approvers}

    return {
        "phase": phase,
        "current_actor": {
            "id": str(current_actor_id),
            "email": current_actor_email,
            "role": role,
        },
        "approval_chain": approval_chain,
        "records": [],
        "pending_approvers": [],
        "started_at": now.isoformat(),
        "deadline_at": (now + timedelta(seconds=timeout_seconds)).isoformat(),
        "form_schema": form_schema,
    }


# ── 纯函数：追加 record（immutable） ─────────────────────────────────────────


def append_record(
    payload: dict[str, Any],
    *,
    actor_id: UUID,
    actor_email: str,
    action: Action,
    reason: str = "",
    form_data: dict[str, Any] | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> dict[str, Any]:
    """immutable 追加一条决策 record，返回新 payload（不修改原 dict）。

    每条 record 字段（参考 03-CONTEXT.md §HITL 节点状态机）：
        {actor_id, actor_email, action, reason, form_data, ts, ip, ua}

    Args:
        payload: 当前 payload（不会被修改）
        actor_id / actor_email: 决策人身份
        action: 决策动作（submit / approve / return / reject）
        reason: 决策原因（可选，建议必填于 return/reject）
        form_data: 表单数据（已通过 validate_form_data 校验）
        ip / ua: 审计字段（NET-05）

    Returns:
        新 payload dict（records 列表已追加一条），原 payload 不变。
    """
    new_record: dict[str, Any] = {
        "actor_id": str(actor_id),
        "actor_email": actor_email,
        "action": action,
        "reason": reason,
        "form_data": form_data or {},
        "ts": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "ua": ua,
    }
    # 用新 dict + 新 list 保证原 payload immutable
    return {
        **payload,
        "records": [*payload.get("records", []), new_record],
    }


# ── 纯函数：计算 next status ─────────────────────────────────────────────────


def compute_next_status(action: Action, current_phase: Phase) -> NodeStatus:
    """根据 action + current_phase 计算节点新 status。

    Phase 3 single 模式状态机：
        - submit phase + action=submit → in_review（单人模式下直接转 review）
        - review phase + action=approve → done（终态）
        - any phase + action=return → returned（终态）
        - any phase + action=reject → rejected（终态）

    Args:
        action: 用户提交的决策动作
        current_phase: 节点当前 phase（submit / review）

    Returns:
        新 status（NodeStatus 之一）

    Raises:
        ValueError: 非法 action / phase 组合（如 approve in submit phase）
    """
    # 终态优先（return / reject 在任何 phase 都可触发）
    if action == "return":
        return "returned"
    if action == "reject":
        return "rejected"
    # 阶段相关的非终态变迁
    if action == "submit" and current_phase == "submit":
        return "in_review"
    if action == "approve" and current_phase == "review":
        return "done"
    raise ValueError(
        f"非法 action={action!r} 在 phase={current_phase!r}（"
        f"合法组合：submit+submit→in_review / approve+review→done / "
        f"return|reject → 终态）"
    )


# ── 纯函数：jsonschema 校验 form_data ─────────────────────────────────────────


def validate_form_data(schema: dict[str, Any], data: dict[str, Any]) -> None:
    """用 jsonschema Draft-7 校验 form_data；失败抛 JsonSchemaValidationError。

    Args:
        schema: form_schema（来自 node_def.config.form_schema，JSON Schema 子集）
        data: 用户提交的 form_data

    Raises:
        jsonschema.ValidationError: data 不符合 schema（如必填字段缺失 / type 不匹配）

    Notes:
        - 用 Draft-7（与前端 RJSF AJV-8 兼容）
        - 空 schema {} 视为 "不约束"，所有 data 都通过（不抛异常）
        - 调用方负责捕获异常并返回 422
    """
    Draft7Validator(schema).validate(data)


# ────────────────────────────────────────────────────────────────────────────
# Phase 4 — 审批链 4 模式状态机（compute_chain_advance + 4 helper）
# ────────────────────────────────────────────────────────────────────────────


def compute_chain_advance(
    payload: dict[str, Any],
    actor_id: UUID,
    action: Action,
) -> ChainAdvanceResult:
    """计算审批链推进结果（纯函数，不修改入参）。

    决策依据见 04-RESEARCH.md §二「审批链 4 模式语义形式化」+ 04-CONTEXT.md §审批链 4 模式语义。

    Args:
        payload: 当前 node_state.payload（含 approval_chain.mode / approvers / current_idx / decisions）
        actor_id: 提交决策的用户 UUID
        action: 决策动作（approve / return / reject；submit 走 compute_next_status 不在此处理）

    Returns:
        ChainAdvanceResult（frozen dataclass）：
            - new_status: 节点新 status
            - new_payload: immutable 新 payload（含 approval_chain.decisions / current_idx 更新）
            - next_approvers: 下轮需创建 token 的 UUID list（仅 sequential approve 时非空）
            - invalidate_others: 是否需调 invalidate_chain
            - supplement_notify: 需发"已终止/已处理"补通知的 actor_id 列表

    Raises:
        ValueError: actor_id 不在 approvers 内、非法 chain_mode、或 single 模式 + submit action 误用

    Notes:
        所有 helper 严格 immutability：用 {**payload, ...} + new list/dict 保证原 payload deep equal。
    """
    chain = payload.get("approval_chain") or {}
    mode_raw = chain.get("mode", "single")

    # 校验 actor_id 在 approvers 内（防伪造）
    approvers_str = list(chain.get("approvers", []))
    approvers = [UUID(a) for a in approvers_str]
    if actor_id not in approvers:
        raise ValueError(
            f"actor_id={actor_id} 不在 approvers={approvers_str} 内（chain_mode={mode_raw}）"
        )

    if mode_raw == "single":
        return _advance_single(payload, actor_id, action)
    if mode_raw == "sequential":
        return _advance_sequential(payload, actor_id, action, approvers)
    if mode_raw == "parallel_all":
        return _advance_parallel_all(payload, actor_id, action, approvers)
    if mode_raw == "parallel_any":
        return _advance_parallel_any(payload, actor_id, action, approvers)

    raise ValueError(f"非法 chain_mode={mode_raw!r}")


# ── 内部 helper：4 种 chain mode 推进 ─────────────────────────────────────────


def _advance_single(
    payload: dict[str, Any],
    actor_id: UUID,
    action: Action,
) -> ChainAdvanceResult:
    """single 模式：Phase 3 既有行为（一人决策即终态）。

    决策依据：Phase 3 03-CONTEXT.md §HITL 节点状态机 — submit/approve/return/reject 单人路径。
    Phase 4 兼容：返回 ChainAdvanceResult 包装，invalidate_others=False。
    """
    if action == "approve":
        new_status: NodeStatus = "done"
    elif action == "return":
        new_status = "returned"
    elif action == "reject":
        new_status = "rejected"
    else:
        # submit 走 compute_next_status，不在 chain_advance 处理
        raise ValueError(
            f"chain_mode=single 不支持 action={action!r}（submit 走 compute_next_status）"
        )

    # immutable copy（即使没字段变化也保持 contract）
    new_payload = {**payload}
    return ChainAdvanceResult(
        new_status=new_status,
        new_payload=new_payload,
        next_approvers=[],
        invalidate_others=False,
        supplement_notify=[],
    )


def _advance_sequential(
    payload: dict[str, Any],
    actor_id: UUID,
    action: Action,
    approvers: list[UUID],
) -> ChainAdvanceResult:
    """sequential 模式：A → B → C 链式触发。

    决策依据 04-CONTEXT.md §顺序会签：
    - A approve → 若 A 是最后一人则 done；否则 current_idx+=1，next_approvers=[next]
    - A reject → 立即 rejected，不创建 B/C 的 token，不发补通知（B/C 从未被骚扰）
    - A return → returned 终态（链式回滚由上层 Command(goto) 处理）

    Args:
        payload: 当前 payload
        actor_id: 提交决策的人（必须 == approvers[current_idx]）
        action: 决策动作
        approvers: 审批人 UUID list

    Returns:
        ChainAdvanceResult
    """
    chain = payload["approval_chain"]
    current_idx = int(chain.get("current_idx", 0))

    # 防越权：sequential 模式下只有当前 idx 的 approver 能决策
    if current_idx >= len(approvers) or approvers[current_idx] != actor_id:
        raise ValueError(
            f"sequential 模式下 actor_id={actor_id} 不是当前轮的 approver "
            f"(current_idx={current_idx}, expected={approvers[current_idx] if current_idx < len(approvers) else 'none'})"
        )

    if action == "return":
        # returned 终态，链式回滚由上层 LangGraph Command(goto=...) 处理
        return ChainAdvanceResult(
            new_status="returned",
            new_payload={**payload},
            next_approvers=[],
            invalidate_others=False,
            supplement_notify=[],
        )

    if action == "reject":
        # 立即 rejected — 下游 B/C 从未被骚扰，不发补通知
        return ChainAdvanceResult(
            new_status="rejected",
            new_payload={**payload},
            next_approvers=[],
            invalidate_others=False,
            supplement_notify=[],
        )

    if action == "approve":
        # 是否最后一人？
        if current_idx == len(approvers) - 1:
            return ChainAdvanceResult(
                new_status="done",
                new_payload={**payload},
                next_approvers=[],
                invalidate_others=False,
                supplement_notify=[],
            )
        # 推进到下一个 approver — immutable 更新 current_idx
        next_idx = current_idx + 1
        new_chain = {**chain, "current_idx": next_idx}
        new_payload = {**payload, "approval_chain": new_chain}
        return ChainAdvanceResult(
            new_status="in_review",
            new_payload=new_payload,
            next_approvers=[approvers[next_idx]],
            invalidate_others=False,
            supplement_notify=[],
        )

    raise ValueError(f"sequential 模式不支持 action={action!r}")


def _advance_parallel_all(
    payload: dict[str, Any],
    actor_id: UUID,
    action: Action,
    approvers: list[UUID],
) -> ChainAdvanceResult:
    """parallel_all 模式：所有审批人都同意才推进。

    决策依据 04-CONTEXT.md §并行会签 全员同意：
    - approve → 检查 decisions 全 approve → done；否则 in_review 等其他人
    - reject / return → 立即终止 + invalidate_chain + 发补通知给其他未决策 approver

    Args:
        payload: 当前 payload
        actor_id: 提交决策的人
        action: 决策动作
        approvers: 审批人 UUID list

    Returns:
        ChainAdvanceResult
    """
    chain = payload["approval_chain"]
    decisions: dict[str, Any] = dict(chain.get("decisions", {}))  # immutable copy
    actor_str = str(actor_id)

    # 记录决策
    new_decisions = {
        **decisions,
        actor_str: {
            "action": action,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    }

    if action in ("return", "reject"):
        # 任一拒绝/退回 → 立即终止 + 失效其他 token
        # supplement_notify: 除当前 actor 外其他「未决策」的人
        # （已决策的人 token 已自然消费，不需要补通知；当前 actor token 是 except_jti，也不通知）
        supplement = [
            a for a in approvers
            if a != actor_id and decisions.get(str(a)) is None
        ]
        new_chain = {**chain, "decisions": new_decisions}
        new_payload = {**payload, "approval_chain": new_chain}
        new_status: NodeStatus = "rejected" if action == "reject" else "returned"
        return ChainAdvanceResult(
            new_status=new_status,
            new_payload=new_payload,
            next_approvers=[],
            invalidate_others=True,
            supplement_notify=supplement,
        )

    if action == "approve":
        # 检查是否全员 approve
        all_approved = all(
            new_decisions.get(str(a)) is not None
            and new_decisions[str(a)].get("action") == "approve"
            for a in approvers
        )
        new_chain = {**chain, "decisions": new_decisions}
        new_payload = {**payload, "approval_chain": new_chain}
        if all_approved:
            return ChainAdvanceResult(
                new_status="done",
                new_payload=new_payload,
                next_approvers=[],
                invalidate_others=False,
                supplement_notify=[],
            )
        # 还有人未决策 → in_review
        return ChainAdvanceResult(
            new_status="in_review",
            new_payload=new_payload,
            next_approvers=[],
            invalidate_others=False,
            supplement_notify=[],
        )

    raise ValueError(f"parallel_all 模式不支持 action={action!r}")


def _advance_parallel_any(
    payload: dict[str, Any],
    actor_id: UUID,
    action: Action,
    approvers: list[UUID],
) -> ChainAdvanceResult:
    """parallel_any 模式：任一同意即推进；任一拒绝/退回即终止。

    决策依据 04-CONTEXT.md §或签 任一同意：
    - approve → 立即 done + invalidate_chain + 发补通知"已被 X 处理"
    - reject / return → 立即终止 + invalidate_chain + 补通知（与 parallel_all 一致）

    Args:
        payload: 当前 payload
        actor_id: 提交决策的人
        action: 决策动作
        approvers: 审批人 UUID list

    Returns:
        ChainAdvanceResult
    """
    chain = payload["approval_chain"]
    decisions: dict[str, Any] = dict(chain.get("decisions", {}))  # immutable copy
    actor_str = str(actor_id)

    # 记录决策
    new_decisions = {
        **decisions,
        actor_str: {
            "action": action,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    }
    new_chain = {**chain, "decisions": new_decisions}
    new_payload = {**payload, "approval_chain": new_chain}

    # 任一终态：approve → done；reject → rejected；return → returned
    if action == "approve":
        new_status: NodeStatus = "done"
    elif action == "reject":
        new_status = "rejected"
    elif action == "return":
        new_status = "returned"
    else:
        raise ValueError(f"parallel_any 模式不支持 action={action!r}")

    # supplement_notify: 除当前 actor 外其他「未决策」的 approver
    supplement = [
        a for a in approvers
        if a != actor_id and decisions.get(str(a)) is None
    ]

    return ChainAdvanceResult(
        new_status=new_status,
        new_payload=new_payload,
        next_approvers=[],
        invalidate_others=True,
        supplement_notify=supplement,
    )
