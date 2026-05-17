"""HITL chain DSL builder — 顺序 / 并行全员 / 或签 4 模式 DSL 模板。

Phase 3 hitl_builder (TS) 只支持 single 模式；本 chain_builder 扩展到 4 模式 +
multichannel notify_channels（Plan 04-10 已落多通道）。

设计参考：
- backend/app/agent_builder/workflow/node_schemas/hitl_schema.py — chain_mode/approvers/notify_channels
- backend/app/agent_builder/services/chain_advance.py — 4 模式状态机
- backend/app/agent_builder/workflow/nodes/hitl.py — interrupt_payload 4 字段

输出 DSL JSON 结构与后端 schema 兼容：
{
  "version": "1.0",
  "name": "...",
  "state_schema": {...},
  "nodes": [
    {"id":"start","type":"start","label":"开始","position":{...},"config":{}},
    {"id":"hitl_1","type":"hitl","label":"审批","position":{...},"config":{
       "chain_mode":"sequential|parallel_all|parallel_any|single",
       "approvers":["email1","email2","email3"],
       "form_schema":{...},
       "timeout_seconds":86400,
       "notify_channels":["email"],
       "description":"请审批",
       "escalate_to":"email:admin@x.com"  # 可选
    }},
    {"id":"end","type":"end","label":"结束","position":{...},"config":{}}
  ],
  "edges": [...]
}
"""
from __future__ import annotations

from typing import Any, Literal

ChainMode = Literal["single", "sequential", "parallel_all", "parallel_any"]


_DEFAULT_FORM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason_detail": {
            "type": "string",
            "title": "详细原因",
            "maxLength": 500,
        }
    },
    "required": [],
    "additionalProperties": False,
}


def build_chain_dsl(
    *,
    chain_mode: ChainMode,
    approvers: list[str],
    name: str = "Phase 4 E2E 测试 — 审批链工作流",
    timeout_seconds: int = 86_400,
    notify_channels: list[str] | None = None,
    description: str = "请审批此申请",
    escalate_to: str | None = None,
    form_schema: dict[str, Any] | None = None,
    hitl_node_title: str = "审批节点",
) -> dict[str, Any]:
    """构建含单个 HITL chain 节点的 DSL（Start → HITL → End）。

    Args:
        chain_mode: 'single' / 'sequential' / 'parallel_all' / 'parallel_any'
        approvers: 审批人邮箱列表（single 模式仅取 [0]；其他模式按列表顺序）
        notify_channels: 通知通道（默认 ['email']；多通道 Plan 04-10 已支持）
        escalate_to: 升级表达式（如 'email:admin@x.com' / 'role:admin' / 'user:<uuid>'）
        form_schema: JSON Schema Draft-7（默认极简 reason_detail）

    Returns:
        DSL JSON dict（可直接 POST /api/v1/workflows）
    """
    if not approvers:
        raise ValueError("approvers 至少需要一个邮箱")

    if chain_mode not in ("single", "sequential", "parallel_all", "parallel_any"):
        raise ValueError(f"chain_mode '{chain_mode}' 非法，必须是 4 模式之一")

    channels = notify_channels or ["email"]

    hitl_config: dict[str, Any] = {
        "chain_mode": chain_mode,
        "approvers": list(approvers),  # 浅拷贝防外部修改
        "form_schema": form_schema or _DEFAULT_FORM_SCHEMA,
        "timeout_seconds": timeout_seconds,
        "notify_channels": list(channels),
        "description": description,
    }
    if escalate_to:
        hitl_config["escalate_to"] = escalate_to

    nodes = [
        {
            "id": "start",
            "type": "start",
            "label": "开始",
            "position": {"x": 80, "y": 200},
            "config": {},
        },
        {
            "id": "hitl_1",
            "type": "hitl",
            "label": hitl_node_title,
            "position": {"x": 320, "y": 200},
            "config": hitl_config,
        },
        {
            "id": "end",
            "type": "end",
            "label": "结束",
            "position": {"x": 560, "y": 200},
            "config": {},
        },
    ]

    edges = [
        {"id": "e1", "source": "start", "target": "hitl_1"},
        {"id": "e2", "source": "hitl_1", "target": "end"},
    ]

    return {
        "version": "1.0",
        "name": name,
        "state_schema": {
            "input": "str",
            "applicant_email": "str",
            "output": "str",
        },
        "nodes": nodes,
        "edges": edges,
    }


def build_sequential_chain_dsl(approvers: list[str], **kwargs: Any) -> dict[str, Any]:
    """顺序会签 sequential — A → B → C，每个 approve 才推下一个。"""
    return build_chain_dsl(
        chain_mode="sequential",
        approvers=approvers,
        name=kwargs.pop("name", "顺序会签 E2E 测试"),
        **kwargs,
    )


def build_parallel_all_dsl(approvers: list[str], **kwargs: Any) -> dict[str, Any]:
    """并行会签全员同意 parallel_all — A/B/C 同时收，任一 reject 即终止。"""
    return build_chain_dsl(
        chain_mode="parallel_all",
        approvers=approvers,
        name=kwargs.pop("name", "并行全员同意 E2E 测试"),
        **kwargs,
    )


def build_parallel_any_dsl(approvers: list[str], **kwargs: Any) -> dict[str, Any]:
    """或签任一同意 parallel_any — A/B/C 同时收，任一 approve 即推进。"""
    return build_chain_dsl(
        chain_mode="parallel_any",
        approvers=approvers,
        name=kwargs.pop("name", "或签任一同意 E2E 测试"),
        **kwargs,
    )


def build_escalation_dsl(
    *,
    approvers: list[str],
    escalate_to: str,
    timeout_seconds: int = 10,
    name: str = "超时升级 E2E 测试",
) -> dict[str, Any]:
    """超时升级测试用 DSL — 默认 10s 短超时便于 Standard mode 测试。"""
    return build_chain_dsl(
        chain_mode="single",
        approvers=approvers,
        name=name,
        timeout_seconds=timeout_seconds,
        escalate_to=escalate_to,
    )


def build_multichannel_dsl(
    *,
    approvers: list[str],
    channels: list[str],
    name: str = "5 家 IM 多通道投递 E2E 测试",
) -> dict[str, Any]:
    """多通道投递 DSL — channels 含 5 家 IM provider name。"""
    return build_chain_dsl(
        chain_mode="single",
        approvers=approvers,
        notify_channels=channels,
        name=name,
    )
