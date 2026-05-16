"""HITL payload 纯函数单元测试。

测试范围（10 个用例）：
- build_initial_payload：executor / reviewer 角色 + deadline 计算
- append_record：immutable + 顺序保留
- compute_next_status：submit→in_review / approve→done / return→returned / reject→rejected
- compute_next_status：非法组合 ValueError
- validate_form_data：合法 / 非法 schema 校验

测试约定（CLAUDE.md 2.2 单元测试）：
- 不依赖 DB / Redis / LangGraph
- 仅测纯函数行为 + 边界
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from jsonschema import ValidationError as JsonSchemaValidationError

from app.agent_builder.workflow.hitl_payload import (
    append_record,
    build_initial_payload,
    compute_next_status,
    validate_form_data,
)


# ── 测试辅助 ──────────────────────────────────────────────────────────────────


def _utc_now_iso() -> datetime:
    return datetime.now(timezone.utc)


def _sample_form_schema() -> dict:
    """简单 form_schema：name (str) + age (int >= 0)，name 必填。"""
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "age": {"type": "integer", "minimum": 0},
        },
        "required": ["name"],
    }


# ── build_initial_payload ─────────────────────────────────────────────────────


def test_build_initial_payload_executor_phase_submit():
    """role=executor → phase="submit"。"""
    actor_id = uuid4()
    payload = build_initial_payload(
        current_actor_id=actor_id,
        current_actor_email="alice@example.com",
        role="executor",
        timeout_seconds=3600,
        form_schema={},
    )
    assert payload["phase"] == "submit"
    assert payload["current_actor"]["id"] == str(actor_id)
    assert payload["current_actor"]["email"] == "alice@example.com"
    assert payload["current_actor"]["role"] == "executor"


def test_build_initial_payload_reviewer_phase_review():
    """role=reviewer → phase="review"。"""
    actor_id = uuid4()
    payload = build_initial_payload(
        current_actor_id=actor_id,
        current_actor_email="bob@example.com",
        role="reviewer",
        timeout_seconds=86400,
        form_schema=_sample_form_schema(),
    )
    assert payload["phase"] == "review"
    assert payload["current_actor"]["role"] == "reviewer"
    # form_schema 透传
    assert payload["form_schema"] == _sample_form_schema()


def test_build_initial_payload_deadline_at_correct():
    """deadline_at = started_at + timeout_seconds，容差 1s。"""
    actor_id = uuid4()
    before = _utc_now_iso()
    payload = build_initial_payload(
        current_actor_id=actor_id,
        current_actor_email="x@y.com",
        role="executor",
        timeout_seconds=300,  # 5 分钟
        form_schema={},
    )
    after = _utc_now_iso()

    started_at = datetime.fromisoformat(payload["started_at"])
    deadline_at = datetime.fromisoformat(payload["deadline_at"])
    delta_seconds = (deadline_at - started_at).total_seconds()

    # started_at 在 before / after 之间
    assert before <= started_at <= after
    # deadline 精确为 300 秒（纯函数无 IO，0 抖动）
    assert delta_seconds == pytest.approx(300, abs=1)


def test_build_initial_payload_default_approvers_to_self():
    """approvers 未提供 → 默认 [current_actor_id]。"""
    actor_id = uuid4()
    payload = build_initial_payload(
        current_actor_id=actor_id,
        current_actor_email="x@y.com",
        role="executor",
        timeout_seconds=60,
        form_schema={},
    )
    assert payload["approval_chain"]["approvers"] == [str(actor_id)]
    assert payload["approval_chain"]["mode"] == "single"
    assert payload["approval_chain"]["current_idx"] == 0
    assert payload["records"] == []
    assert payload["pending_approvers"] == []


# ── append_record ────────────────────────────────────────────────────────────


def test_append_record_immutable_does_not_mutate_original():
    """append_record 不修改原 payload（immutability）。"""
    original = build_initial_payload(
        current_actor_id=uuid4(),
        current_actor_email="orig@example.com",
        role="executor",
        timeout_seconds=60,
        form_schema={},
    )
    original_records_id = id(original["records"])

    new_payload = append_record(
        original,
        actor_id=uuid4(),
        actor_email="alice@example.com",
        action="submit",
        reason="LGTM",
        form_data={"name": "Alice"},
    )

    # 原 payload 的 records 仍为空，且是不同对象
    assert original["records"] == []
    assert id(original["records"]) == original_records_id
    assert len(new_payload["records"]) == 1
    assert new_payload["records"][0]["action"] == "submit"
    assert new_payload["records"][0]["actor_email"] == "alice@example.com"
    assert new_payload["records"][0]["reason"] == "LGTM"
    assert new_payload["records"][0]["form_data"] == {"name": "Alice"}


def test_append_record_preserves_order_across_multiple_calls():
    """多次 append 顺序正确（FIFO）。"""
    payload = build_initial_payload(
        current_actor_id=uuid4(),
        current_actor_email="o@x.com",
        role="executor",
        timeout_seconds=60,
        form_schema={},
    )

    actor1, actor2, actor3 = uuid4(), uuid4(), uuid4()
    p1 = append_record(payload, actor_id=actor1, actor_email="a1@x.com", action="submit")
    p2 = append_record(p1, actor_id=actor2, actor_email="a2@x.com", action="approve")
    p3 = append_record(p2, actor_id=actor3, actor_email="a3@x.com", action="return", reason="补充材料")

    assert len(p3["records"]) == 3
    assert p3["records"][0]["actor_email"] == "a1@x.com"
    assert p3["records"][1]["actor_email"] == "a2@x.com"
    assert p3["records"][2]["actor_email"] == "a3@x.com"
    assert p3["records"][2]["reason"] == "补充材料"
    # 同时验证每条 record 含审计字段
    for rec in p3["records"]:
        assert "ts" in rec
        # ts 是 ISO8601
        datetime.fromisoformat(rec["ts"])


# ── compute_next_status ──────────────────────────────────────────────────────


def test_compute_next_status_submit_to_in_review():
    """submit phase + action=submit → in_review。"""
    assert compute_next_status("submit", "submit") == "in_review"


def test_compute_next_status_approve_to_done():
    """review phase + action=approve → done（终态）。"""
    assert compute_next_status("approve", "review") == "done"


def test_compute_next_status_return_in_any_phase():
    """action=return → returned（任何 phase 触发）。"""
    assert compute_next_status("return", "submit") == "returned"
    assert compute_next_status("return", "review") == "returned"


def test_compute_next_status_reject_in_any_phase():
    """action=reject → rejected（任何 phase 触发）。"""
    assert compute_next_status("reject", "submit") == "rejected"
    assert compute_next_status("reject", "review") == "rejected"


def test_compute_next_status_invalid_combo_raises():
    """非法组合（如 approve in submit phase）抛 ValueError。"""
    with pytest.raises(ValueError, match="非法 action"):
        compute_next_status("approve", "submit")
    with pytest.raises(ValueError, match="非法 action"):
        compute_next_status("submit", "review")


# ── validate_form_data ───────────────────────────────────────────────────────


def test_validate_form_data_valid_passes():
    """合法 data 通过校验（无异常）。"""
    schema = _sample_form_schema()
    # 不抛异常 = 通过
    validate_form_data(schema, {"name": "Alice", "age": 30})
    validate_form_data(schema, {"name": "Bob"})  # age 可选


def test_validate_form_data_invalid_raises_jsonschema_error():
    """非法 data（缺必填 / type 不匹配）抛 jsonschema.ValidationError。"""
    schema = _sample_form_schema()

    # 缺必填 name
    with pytest.raises(JsonSchemaValidationError):
        validate_form_data(schema, {"age": 30})

    # age type 不匹配（str vs int）
    with pytest.raises(JsonSchemaValidationError):
        validate_form_data(schema, {"name": "Alice", "age": "thirty"})

    # age < 0
    with pytest.raises(JsonSchemaValidationError):
        validate_form_data(schema, {"name": "Alice", "age": -1})


def test_validate_form_data_empty_schema_accepts_anything():
    """空 schema {} 视为不约束，任意 data 通过。"""
    validate_form_data({}, {})
    validate_form_data({}, {"any": "thing", "nested": {"x": 1}})
