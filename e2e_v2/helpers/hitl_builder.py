"""HITL DSL builder (single mode) — Python port 自 e2e/helpers/hitl-builder.ts。

仅保留 single mode 接口；chain mode 见 chain_builder.py（更明确分离）。
"""
from __future__ import annotations

from typing import Any

from e2e_v2.helpers.chain_builder import build_chain_dsl


def build_hitl_dsl(
    *,
    approver_emails: list[str],
    name: str = "HITL E2E single 模式工作流",
    timeout_seconds: int = 86_400,
    escalate_to: str | None = None,
    description: str = "请审批此申请",
) -> dict[str, Any]:
    """构建含 single mode HITL 节点的 DSL（Phase 3 已实现的最小测试单元）。

    转发到 chain_builder.build_chain_dsl(chain_mode='single')。
    """
    return build_chain_dsl(
        chain_mode="single",
        approvers=approver_emails,
        name=name,
        timeout_seconds=timeout_seconds,
        escalate_to=escalate_to,
        description=description,
    )
