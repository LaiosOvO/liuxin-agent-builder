"""compute_chain_advance + ChainAdvanceResult 单元测试（Phase 4-01）。

覆盖范围（≥ 15 用例）：
- 4 chain mode × 3 action = 12 状态机分支
- ChainAdvanceResult frozen dataclass + default_factory
- 严格 immutability：入参 payload deep equal 调用前后
- build_initial_payload 扩展（chain_mode + decisions 字典 / current_idx）
- 边界异常：非法 actor / 非法 chain_mode / sequential 越权

测试约定（CLAUDE.md 2.2 单元测试）：
- 不依赖 DB / Redis / LangGraph
- 仅测纯函数行为 + 边界

Dify 对比：Dify human_input.py 无 chain，不存在对应测试 — 本文件全独立设计。
"""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.agent_builder.workflow.hitl_payload import (
    ChainAdvanceResult,
    build_initial_payload,
    compute_chain_advance,
)


# ── 测试辅助 ──────────────────────────────────────────────────────────────────


def _make_chain_payload(
    *,
    mode: str,
    approvers: list[UUID],
    current_idx: int = 0,
    decisions: dict[str, dict] | None = None,
) -> dict:
    """构造 chain 测试 payload（不走 build_initial_payload 便于精准控制字段）。"""
    chain: dict = {
        "mode": mode,
        "approvers": [str(a) for a in approvers],
        "current_idx": current_idx,
    }
    if decisions is not None:
        chain["decisions"] = decisions

    return {
        "phase": "review",
        "current_actor": {"id": str(approvers[0]), "email": "a@test.com", "role": "reviewer"},
        "approval_chain": chain,
        "records": [],
        "pending_approvers": [],
        "started_at": "2026-05-17T10:00:00+00:00",
        "deadline_at": "2026-05-18T10:00:00+00:00",
        "form_schema": {},
    }


# ── ChainAdvanceResult 数据类测试 ─────────────────────────────────────────────


def test_chain_advance_result_frozen():
    """ChainAdvanceResult @dataclass(frozen=True) 设置字段抛 FrozenInstanceError。"""
    result = ChainAdvanceResult(
        new_status="done",
        new_payload={"foo": "bar"},
    )
    with pytest.raises(FrozenInstanceError):
        result.new_status = "rejected"  # type: ignore[misc]


def test_chain_advance_result_default_factory():
    """default_factory 防共享 mutable 默认值陷阱（两个实例的 list 独立）。"""
    r1 = ChainAdvanceResult(new_status="done", new_payload={})
    r2 = ChainAdvanceResult(new_status="done", new_payload={})
    # frozen dataclass 不能 append，先检查初始化都是空 list
    assert r1.next_approvers == []
    assert r2.next_approvers == []
    # 验证不是同一对象（即每次实例化都是新 list）
    assert r1.next_approvers is not r2.next_approvers
    assert r1.supplement_notify is not r2.supplement_notify


# ── build_initial_payload chain_mode 扩展测试 ─────────────────────────────────


def test_build_initial_payload_single_mode_backward_compat():
    """默认 chain_mode='single' 与 Phase 3 行为一致（向后兼容）。"""
    actor_id = uuid4()
    payload = build_initial_payload(
        current_actor_id=actor_id,
        current_actor_email="a@test.com",
        role="reviewer",
        timeout_seconds=3600,
        form_schema={},
    )
    assert payload["approval_chain"]["mode"] == "single"
    assert payload["approval_chain"]["approvers"] == [str(actor_id)]
    assert payload["approval_chain"]["current_idx"] == 0
    # single 模式不应初始化 decisions 字典
    assert "decisions" not in payload["approval_chain"]


def test_build_initial_payload_sequential_current_idx_zero():
    """sequential 模式 current_idx 必为 0 (指向链首)。"""
    actors = [uuid4(), uuid4(), uuid4()]
    payload = build_initial_payload(
        current_actor_id=actors[0],
        current_actor_email="a@test.com",
        role="reviewer",
        timeout_seconds=3600,
        form_schema={},
        approvers=actors,
        chain_mode="sequential",
    )
    assert payload["approval_chain"]["mode"] == "sequential"
    assert payload["approval_chain"]["approvers"] == [str(a) for a in actors]
    assert payload["approval_chain"]["current_idx"] == 0
    # sequential 模式也不初始化 decisions（用 current_idx 推进）
    assert "decisions" not in payload["approval_chain"]


def test_build_initial_payload_parallel_all_initializes_decisions():
    """parallel_all 模式 decisions 字典正确初始化（所有 approver 起始 None）。"""
    actors = [uuid4(), uuid4(), uuid4()]
    payload = build_initial_payload(
        current_actor_id=actors[0],
        current_actor_email="a@test.com",
        role="reviewer",
        timeout_seconds=3600,
        form_schema={},
        approvers=actors,
        chain_mode="parallel_all",
    )
    decisions = payload["approval_chain"]["decisions"]
    assert set(decisions.keys()) == {str(a) for a in actors}
    assert all(v is None for v in decisions.values())


def test_build_initial_payload_parallel_any_initializes_decisions():
    """parallel_any 模式同样初始化 decisions 字典（与 parallel_all 同结构）。"""
    actors = [uuid4(), uuid4()]
    payload = build_initial_payload(
        current_actor_id=actors[0],
        current_actor_email="a@test.com",
        role="reviewer",
        timeout_seconds=3600,
        form_schema={},
        approvers=actors,
        chain_mode="parallel_any",
    )
    decisions = payload["approval_chain"]["decisions"]
    assert set(decisions.keys()) == {str(a) for a in actors}
    assert all(v is None for v in decisions.values())


# ── compute_chain_advance: single 模式（向后兼容） ────────────────────────────


def test_compute_chain_advance_single_approve():
    """single 模式 approve → done（Phase 3 行为兼容）。"""
    a = uuid4()
    payload = _make_chain_payload(mode="single", approvers=[a])
    result = compute_chain_advance(payload, a, "approve")
    assert result.new_status == "done"
    assert result.next_approvers == []
    assert result.invalidate_others is False
    assert result.supplement_notify == []


def test_compute_chain_advance_single_reject():
    """single 模式 reject → rejected。"""
    a = uuid4()
    payload = _make_chain_payload(mode="single", approvers=[a])
    result = compute_chain_advance(payload, a, "reject")
    assert result.new_status == "rejected"
    assert result.invalidate_others is False


def test_compute_chain_advance_single_return():
    """single 模式 return → returned。"""
    a = uuid4()
    payload = _make_chain_payload(mode="single", approvers=[a])
    result = compute_chain_advance(payload, a, "return")
    assert result.new_status == "returned"


# ── compute_chain_advance: sequential 模式 ────────────────────────────────────


def test_compute_chain_advance_sequential_approve_advances_to_next():
    """sequential A approve → in_review + current_idx=1 + next_approvers=[B]。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(mode="sequential", approvers=[a, b, c], current_idx=0)
    result = compute_chain_advance(payload, a, "approve")

    assert result.new_status == "in_review"
    assert result.next_approvers == [b]
    assert result.invalidate_others is False
    assert result.supplement_notify == []
    # immutable check
    assert result.new_payload["approval_chain"]["current_idx"] == 1
    # 原 payload 不变
    assert payload["approval_chain"]["current_idx"] == 0


def test_compute_chain_advance_sequential_approve_last_done():
    """sequential 最后一人 approve → done（无 next_approvers）。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(mode="sequential", approvers=[a, b, c], current_idx=2)
    result = compute_chain_advance(payload, c, "approve")

    assert result.new_status == "done"
    assert result.next_approvers == []
    assert result.invalidate_others is False


def test_compute_chain_advance_sequential_reject_terminates_no_supplement():
    """sequential A reject → rejected 立即终止 + 不发补通知（B/C 从未被骚扰）。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(mode="sequential", approvers=[a, b, c], current_idx=0)
    result = compute_chain_advance(payload, a, "reject")

    assert result.new_status == "rejected"
    assert result.next_approvers == []
    assert result.invalidate_others is False
    assert result.supplement_notify == []


def test_compute_chain_advance_sequential_return_terminates():
    """sequential return → returned 终态。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(mode="sequential", approvers=[a, b, c], current_idx=1)
    result = compute_chain_advance(payload, b, "return")

    assert result.new_status == "returned"
    assert result.next_approvers == []
    assert result.invalidate_others is False


def test_compute_chain_advance_sequential_wrong_actor_raises():
    """sequential 越权：B 在 current_idx=0 时尝试决策（应是 A 决策）→ ValueError。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(mode="sequential", approvers=[a, b, c], current_idx=0)
    with pytest.raises(ValueError, match="不是当前轮的 approver"):
        compute_chain_advance(payload, b, "approve")


# ── compute_chain_advance: parallel_all 模式 ──────────────────────────────────


def test_compute_chain_advance_parallel_all_partial_approve_in_review():
    """parallel_all A approve 后 B 未决策 → in_review。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_all",
        approvers=[a, b, c],
        decisions={str(a): None, str(b): None, str(c): None},
    )
    result = compute_chain_advance(payload, a, "approve")

    assert result.new_status == "in_review"
    assert result.next_approvers == []
    assert result.invalidate_others is False
    assert result.supplement_notify == []
    # decisions[A] 已更新为 approve；B/C 仍 None
    new_decisions = result.new_payload["approval_chain"]["decisions"]
    assert new_decisions[str(a)]["action"] == "approve"
    assert new_decisions[str(b)] is None
    assert new_decisions[str(c)] is None


def test_compute_chain_advance_parallel_all_complete_done():
    """parallel_all A+B+C 都 approve 最后一人触发 → done。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_all",
        approvers=[a, b, c],
        decisions={
            str(a): {"action": "approve", "ts": "2026-05-17T10:00:00+00:00"},
            str(b): {"action": "approve", "ts": "2026-05-17T10:01:00+00:00"},
            str(c): None,  # C 即将 approve
        },
    )
    result = compute_chain_advance(payload, c, "approve")

    assert result.new_status == "done"
    assert result.next_approvers == []
    assert result.invalidate_others is False


def test_compute_chain_advance_parallel_all_reject_invalidates_others():
    """parallel_all A reject → rejected + invalidate_others + supplement_notify=[B,C]。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_all",
        approvers=[a, b, c],
        decisions={str(a): None, str(b): None, str(c): None},
    )
    result = compute_chain_advance(payload, a, "reject")

    assert result.new_status == "rejected"
    assert result.invalidate_others is True
    # supplement_notify 应包含其他未决策的 B/C（不含 A 自己）
    assert set(result.supplement_notify) == {b, c}


def test_compute_chain_advance_parallel_all_return_terminates_with_invalidate():
    """parallel_all return → returned + invalidate + supplement_notify。"""
    a, b = uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_all",
        approvers=[a, b],
        decisions={str(a): None, str(b): None},
    )
    result = compute_chain_advance(payload, a, "return")

    assert result.new_status == "returned"
    assert result.invalidate_others is True
    assert result.supplement_notify == [b]


def test_compute_chain_advance_parallel_all_reject_skips_already_decided():
    """parallel_all reject 时已决策的 B 不在 supplement_notify（避免重复通知）。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    # B 已 approve；A 现 reject
    payload = _make_chain_payload(
        mode="parallel_all",
        approvers=[a, b, c],
        decisions={
            str(a): None,
            str(b): {"action": "approve", "ts": "2026-05-17T10:00:00+00:00"},
            str(c): None,
        },
    )
    result = compute_chain_advance(payload, a, "reject")

    assert result.new_status == "rejected"
    # supplement_notify 仅包含「未决策」的 C；B 已决策不重复通知
    assert result.supplement_notify == [c]


# ── compute_chain_advance: parallel_any 模式 ──────────────────────────────────


def test_compute_chain_advance_parallel_any_first_approve_wins():
    """parallel_any A approve → done + invalidate + supplement_notify=[B,C]。"""
    a, b, c = uuid4(), uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_any",
        approvers=[a, b, c],
        decisions={str(a): None, str(b): None, str(c): None},
    )
    result = compute_chain_advance(payload, a, "approve")

    assert result.new_status == "done"
    assert result.invalidate_others is True
    assert set(result.supplement_notify) == {b, c}


def test_compute_chain_advance_parallel_any_first_reject_wins():
    """parallel_any A reject → rejected + invalidate（与 parallel_all 一致）。"""
    a, b = uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_any",
        approvers=[a, b],
        decisions={str(a): None, str(b): None},
    )
    result = compute_chain_advance(payload, a, "reject")

    assert result.new_status == "rejected"
    assert result.invalidate_others is True
    assert result.supplement_notify == [b]


def test_compute_chain_advance_parallel_any_first_return_wins():
    """parallel_any A return → returned + invalidate。"""
    a, b = uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_any",
        approvers=[a, b],
        decisions={str(a): None, str(b): None},
    )
    result = compute_chain_advance(payload, a, "return")
    assert result.new_status == "returned"
    assert result.invalidate_others is True


# ── 异常路径 ──────────────────────────────────────────────────────────────────


def test_compute_chain_advance_invalid_actor_raises():
    """actor_id 不在 approvers 内 → ValueError。"""
    a, b = uuid4(), uuid4()
    intruder = uuid4()
    payload = _make_chain_payload(mode="parallel_any", approvers=[a, b])
    with pytest.raises(ValueError, match="不在 approvers"):
        compute_chain_advance(payload, intruder, "approve")


def test_compute_chain_advance_invalid_chain_mode_raises():
    """非法 chain_mode → ValueError。"""
    a = uuid4()
    payload = _make_chain_payload(mode="single", approvers=[a])
    # 篡改 mode 字段
    payload["approval_chain"]["mode"] = "invalid_mode"
    with pytest.raises(ValueError, match="非法 chain_mode"):
        compute_chain_advance(payload, a, "approve")


def test_compute_chain_advance_single_submit_rejected():
    """single 模式不支持 action=submit（应走 compute_next_status）。"""
    a = uuid4()
    payload = _make_chain_payload(mode="single", approvers=[a])
    with pytest.raises(ValueError, match="chain_mode=single 不支持"):
        compute_chain_advance(payload, a, "submit")


# ── 严格 immutability 测试 ────────────────────────────────────────────────────


def test_compute_chain_advance_immutability_sequential():
    """sequential 模式：入参 payload 调用前后 deep equal。"""
    a, b = uuid4(), uuid4()
    payload = _make_chain_payload(mode="sequential", approvers=[a, b], current_idx=0)
    payload_snapshot = copy.deepcopy(payload)
    _ = compute_chain_advance(payload, a, "approve")
    assert payload == payload_snapshot, "入参 payload 被意外修改"


def test_compute_chain_advance_immutability_parallel_all():
    """parallel_all 模式：入参 payload 调用前后 deep equal（含 decisions 字典）。"""
    a, b = uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_all",
        approvers=[a, b],
        decisions={str(a): None, str(b): None},
    )
    payload_snapshot = copy.deepcopy(payload)
    _ = compute_chain_advance(payload, a, "approve")
    assert payload == payload_snapshot, "入参 payload 被意外修改（含 decisions 字典）"


def test_compute_chain_advance_immutability_parallel_any():
    """parallel_any 模式：入参 payload 调用前后 deep equal。"""
    a, b = uuid4(), uuid4()
    payload = _make_chain_payload(
        mode="parallel_any",
        approvers=[a, b],
        decisions={str(a): None, str(b): None},
    )
    payload_snapshot = copy.deepcopy(payload)
    _ = compute_chain_advance(payload, a, "reject")
    assert payload == payload_snapshot


def test_compute_chain_advance_new_payload_independent_list():
    """new_payload 中的 approval_chain 是新对象（不共享原 payload 引用）。"""
    a, b = uuid4(), uuid4()
    payload = _make_chain_payload(mode="sequential", approvers=[a, b], current_idx=0)
    result = compute_chain_advance(payload, a, "approve")
    # 修改 result.new_payload 不应影响原 payload
    assert result.new_payload["approval_chain"] is not payload["approval_chain"]
