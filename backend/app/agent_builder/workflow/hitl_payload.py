"""HITL payload 纯函数（无副作用，便于单测）。

提供 HITL 节点状态机的核心 payload 构造 / 变迁 / 校验的纯函数 API：

- build_initial_payload(...)：构造 node_state.payload 初态（phase / current_actor / approval_chain / records / form_schema / 时间字段）
- append_record(...)：immutable 追加一条决策 record（不修改原 payload）
- compute_next_status(...)：根据 action + current_phase 计算节点 status（5 → 3 终态）
- validate_form_data(...)：jsonschema Draft-7 校验 form_data 是否符合 form_schema

设计参考 docs/reading-dify-03-02-hitl-executor-2026-05-17.md §7 LangGraph 1.2 interrupt 最佳实践：
- interrupt() 后节点函数从头重跑 → 纯函数必须 idempotent + immutable
- 副作用（DB INSERT / 邮件入队）由 ExecutionEngine 一次性触发，不在此模块

四态枚举（CLAUDE.md 2.5 + 03-CONTEXT.md §HITL 节点状态机）：
- submit：执行人提交（v1 single 模式直接进 review）
- approve：审核人通过
- return：退回（重新分配 / 回到上一节点）
- reject：拒绝（终止流程）

节点 status 5 → 3 终态：
- pending → waiting_human → in_review → done | rejected | returned
"""
from __future__ import annotations

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


# ── 纯函数：构造初态 ──────────────────────────────────────────────────────────


def build_initial_payload(
    *,
    current_actor_id: UUID,
    current_actor_email: str,
    role: Role,
    timeout_seconds: int,
    form_schema: dict[str, Any],
    approvers: list[UUID] | None = None,
) -> dict[str, Any]:
    """构造 HITL 节点初始 payload（写入 node_state.payload）。

    Args:
        current_actor_id: 当前决策人 user_id
        current_actor_email: 当前决策人邮箱（邮件发送 + 审计日志用）
        role: 当前阶段角色（executor / reviewer）
        timeout_seconds: 节点超时秒数（决定 deadline_at）
        form_schema: 决策表单 JSON Schema（前端 RJSF 渲染 + 服务端校验用）
        approvers: 审批人列表（v1 single 模式默认 [current_actor_id]）

    Returns:
        新的 payload dict（immutable，调用方不应原地修改）。

    Notes:
        - 不写 DB，纯函数；调用方负责把返回值写入 node_state.payload
        - 时间字段均为 UTC ISO8601 字符串（含 +00:00 后缀）
        - role=executor → phase=submit；role=reviewer → phase=review（v1 single
          模式：执行人 submit 直接走 review，再 approve = done）
    """
    now = datetime.now(timezone.utc)
    phase: Phase = "submit" if role == "executor" else "review"
    return {
        "phase": phase,
        "current_actor": {
            "id": str(current_actor_id),
            "email": current_actor_email,
            "role": role,
        },
        "approval_chain": {
            # Phase 3 仅 single；sequential / parallel_all / parallel_any → Phase 4
            "mode": "single",
            "approvers": [str(a) for a in (approvers or [current_actor_id])],
            "current_idx": 0,
        },
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
