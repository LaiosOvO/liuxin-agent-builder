"""HITLNodeExecutor chain 字段 interrupt payload 单元测试（Plan 04-11 Task 1）。

测试范围（≥ 4 用例，全部 mock LangGraph interrupt）：
- chain_mode 字段透传到 interrupt payload（sequential / parallel_all / parallel_any）
- 向后兼容：旧 DSL 无 chain_mode → 默认 single
- approvers UUID list 序列化为 str list 传入 payload
- notify_channels 数组完整透传
- current_idx 默认 0
- chain 字段保持 Phase 3 既有字段（node_state_id / phase / form_schema / deadline_at / current_actor）不变

测试约定（CLAUDE.md 2.2）：
- 单元测试：mock interrupt 直接 patch；不依赖真实 PG / LangGraph runtime
- Phase 3 既有 test_hitl_node_executor.py 测试仍跑通（向后兼容）
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from app.agent_builder.workflow.nodes.hitl import HITLNodeExecutor


# ── 辅助构造 node_def + state ──────────────────────────────────────────────────


def _make_chain_node(
    *,
    node_id: str = "hitl",
    chain_mode: str | None = None,
    approvers: list[UUID] | None = None,
    current_idx: int | None = None,
    notify_channels: list[str] | None = None,
    form_schema: dict | None = None,
) -> dict:
    """构造一个带 chain 配置的 HITL node_def。

    chain_mode / approvers / current_idx / notify_channels 为 None 时不写入 config
    （测试默认值 / 向后兼容场景）。
    """
    config: dict = {
        "assignees": ["alice@example.com"],
        "timeout_seconds": 3600,
        "phase": "review",
        "form_schema": form_schema or {},
        "deadline_at": "2026-05-18T12:00:00+00:00",
        "current_actor": {
            "id": "u_alice",
            "email": "alice@example.com",
            "role": "reviewer",
        },
    }
    if chain_mode is not None:
        config["chain_mode"] = chain_mode
    if approvers is not None:
        config["approvers"] = approvers
    if current_idx is not None:
        config["current_idx"] = current_idx
    if notify_channels is not None:
        config["notify_channels"] = notify_channels
    return {"id": node_id, "type": "hitl", "config": config}


def _make_state() -> dict:
    return {
        "_node_state_id": str(uuid4()),
        "start": {"name": "Alice"},
    }


def _fake_resume_value() -> dict:
    return {
        "action": "approve",
        "reason": "",
        "form_data": {},
        "actor_id": "u_alice",
        "jti": "jti-123",
        "ip": "1.2.3.4",
        "ua": "Mozilla/5.0",
    }


# ── 测试 1: chain_mode='sequential' 透传 ──────────────────────────────────────


async def test_interrupt_payload_contains_chain_mode_sequential():
    """chain_mode='sequential' → interrupt() 收到 chain_mode='sequential'。"""
    approver_a = uuid4()
    approver_b = uuid4()
    approver_c = uuid4()
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode="sequential",
            approvers=[approver_a, approver_b, approver_c],
            current_idx=0,
            notify_channels=["email", "feishu"],
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["chain_mode"] == "sequential"
    assert len(payload["approvers"]) == 3
    assert payload["current_idx"] == 0
    assert payload["notify_channels"] == ["email", "feishu"]


# ── 测试 2: 向后兼容 — 无 chain_mode 默认 single ───────────────────────────────


async def test_interrupt_payload_default_single_backward_compat():
    """旧 DSL 无 chain_mode 字段 → interrupt_payload 默认 single。"""
    executor = HITLNodeExecutor(_make_chain_node())  # 无 chain 配置
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["chain_mode"] == "single"
    assert payload["approvers"] == []  # 默认空
    assert payload["current_idx"] == 0
    assert payload["notify_channels"] == ["email"]  # 默认 email


# ── 测试 3: approvers UUID list 透传 + 序列化为 str ─────────────────────────────


async def test_interrupt_payload_approvers_passed_through():
    """5 个 UUID approvers → payload.approvers 是 5 个 str。"""
    approvers_uuid = [uuid4() for _ in range(5)]
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode="parallel_all",
            approvers=approvers_uuid,
            current_idx=0,
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert len(payload["approvers"]) == 5
    # 每个元素都是 str（UUID → str 序列化）
    for actor_str in payload["approvers"]:
        assert isinstance(actor_str, str)
        # 可解析回 UUID 验证完整性
        UUID(actor_str)
    # 顺序保持
    assert payload["approvers"] == [str(a) for a in approvers_uuid]


# ── 测试 4: notify_channels=['email','feishu'] 透传 ────────────────────────────


async def test_interrupt_payload_notify_channels_multi():
    """notify_channels=['email','feishu','wecom'] → payload.notify_channels 完整透传。"""
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode="single",
            approvers=[uuid4()],
            notify_channels=["email", "feishu", "wecom"],
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["notify_channels"] == ["email", "feishu", "wecom"]


# ── 测试 5: chain_mode='parallel_any' + current_idx 非 0 ──────────────────────


async def test_interrupt_payload_parallel_any_with_current_idx():
    """parallel_any + current_idx=2 → 完整透传。"""
    approvers = [uuid4() for _ in range(4)]
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode="parallel_any",
            approvers=approvers,
            current_idx=2,
            notify_channels=["email"],
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["chain_mode"] == "parallel_any"
    assert payload["current_idx"] == 2
    assert len(payload["approvers"]) == 4


# ── 测试 6: chain_mode='parallel_all' approvers=[] 边界 ───────────────────────


async def test_interrupt_payload_parallel_all_empty_approvers():
    """parallel_all + approvers=[] → 仍传递空 list，不抛错（_on_hitl_enter 才校验）。"""
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode="parallel_all",
            approvers=[],
            current_idx=0,
            notify_channels=["email"],
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["chain_mode"] == "parallel_all"
    assert payload["approvers"] == []


# ── 测试 7: chain 扩展不破坏 Phase 3 既有字段 ──────────────────────────────────


async def test_interrupt_payload_phase3_fields_preserved():
    """chain 字段扩展后，Phase 3 既有 6 字段仍存在且正确。"""
    form_schema = {
        "type": "object",
        "properties": {"comment": {"type": "string"}},
    }
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode="sequential",
            approvers=[uuid4()],
            form_schema=form_schema,
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    # Phase 3 6 字段保留
    assert payload["node_state_id"] == state["_node_state_id"]
    assert payload["phase"] == "review"
    assert payload["form_schema"] == form_schema
    assert payload["deadline_at"] == "2026-05-18T12:00:00+00:00"
    assert payload["current_actor"]["email"] == "alice@example.com"
    # Plan 04-11 4 新字段
    assert "chain_mode" in payload
    assert "approvers" in payload
    assert "current_idx" in payload
    assert "notify_channels" in payload


# ── 测试 8: notify_channels=None → 默认 ['email'] ──────────────────────────────


async def test_interrupt_payload_notify_channels_none_defaults_to_email():
    """node_def 显式 notify_channels=None → payload 默认 ['email']。

    （rendered_config.get('notify_channels') 返回 None 时走 or 默认 — 防 None 污染 payload）。
    """
    config = _make_chain_node(chain_mode="single", approvers=[uuid4()])
    config["config"]["notify_channels"] = None  # 显式 None
    executor = HITLNodeExecutor(config)
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["notify_channels"] == ["email"]


# ── 测试 9: 4 chain mode 矩阵化 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "chain_mode", ["single", "sequential", "parallel_all", "parallel_any"]
)
async def test_interrupt_payload_all_four_chain_modes(chain_mode: str):
    """4 chain mode 全部能透传到 payload（参数化矩阵测试）。"""
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode=chain_mode,
            approvers=[uuid4(), uuid4()],
            current_idx=0,
            notify_channels=["email"],
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["chain_mode"] == chain_mode


# ── 测试 10: approvers 已是 str list 也能透传（防 ExecutionEngine 注入 str） ───


async def test_interrupt_payload_approvers_already_string():
    """approvers 注入时已是 str list（ExecutionEngine 写入 config 时）→ 不重复序列化。"""
    approver_strs = [str(uuid4()) for _ in range(3)]
    executor = HITLNodeExecutor(
        _make_chain_node(
            chain_mode="sequential",
            approvers=approver_strs,  # str list 而非 UUID list
        ),
    )
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=_fake_resume_value(),
    ) as mock_interrupt:
        await executor(state)

    payload = mock_interrupt.call_args[0][0]
    assert payload["approvers"] == approver_strs
