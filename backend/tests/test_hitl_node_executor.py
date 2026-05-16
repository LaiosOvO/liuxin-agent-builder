"""HITLNodeExecutor 单元测试（mock interrupt）。

测试范围（6+ 用例）：
- __call__ 检查 _node_state_id 缺失抛错
- __call__ 把 interrupt payload 拼装正确
- resume 后 form_data 校验逻辑
- resume 后输出含 completed_at + actor_id
- HITLNodeExecutor 不可调 execute()（已 override __call__）
- NODE_EXECUTORS["hitl"] 注册

测试约定（CLAUDE.md 2.2）：
- 单元测试不依赖真实 LangGraph runtime（mock interrupt）
- 集成测试在 test_hitl_interrupt_resume.py 里跑真实 graph
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from jsonschema import ValidationError as JsonSchemaValidationError

from app.agent_builder.workflow.nodes.base import NodeExecutionError
from app.agent_builder.workflow.nodes.hitl import HITLNodeExecutor


# ── 辅助构造 node_def + state ──────────────────────────────────────────────────


def _make_hitl_node(
    node_id: str = "hitl",
    form_schema: dict | None = None,
    config_overrides: dict | None = None,
) -> dict:
    """构造一个 HITL node_def（DSL 编译期格式）。"""
    config: dict = {
        "assignees": ["alice@example.com"],
        "timeout_seconds": 3600,
        "phase": "submit",  # 由 ExecutionEngine 注入或 DSL 配置
        "form_schema": form_schema or {},
        "deadline_at": "2026-05-18T12:00:00+00:00",
        "current_actor": {
            "id": "u_alice",
            "email": "alice@example.com",
            "role": "executor",
        },
    }
    if config_overrides:
        config.update(config_overrides)
    return {"id": node_id, "type": "hitl", "config": config}


def _make_state(with_node_state_id: bool = True) -> dict:
    state: dict = {"start": {"name": "Alice"}}
    if with_node_state_id:
        state["_node_state_id"] = str(uuid4())
    return state


# ── NODE_EXECUTORS 注册 ────────────────────────────────────────────────────────


def test_hitl_executor_registered_in_node_executors():
    """NODE_EXECUTORS 必须包含 'hitl' 键，值为 HITLNodeExecutor 类。"""
    from app.agent_builder.workflow.nodes import NODE_EXECUTORS

    assert "hitl" in NODE_EXECUTORS
    assert NODE_EXECUTORS["hitl"] is HITLNodeExecutor


def test_hitl_schema_registered_in_node_schemas():
    """NODE_SCHEMAS 必须包含 'hitl' 键。"""
    from app.agent_builder.workflow.node_schemas import NODE_SCHEMAS

    assert "hitl" in NODE_SCHEMAS
    schema, output_fields = NODE_SCHEMAS["hitl"]
    assert "assignees" in schema["properties"]
    assert "action" in output_fields
    assert "form_data" in output_fields


# ── HITLNodeExecutor.__call__ ───────────────────────────────────────────────────


async def test_hitl_executor_raises_if_node_state_id_missing():
    """state 中无 _node_state_id 时抛 NodeExecutionError。"""
    executor = HITLNodeExecutor(_make_hitl_node())
    state = _make_state(with_node_state_id=False)

    with pytest.raises(NodeExecutionError, match="_node_state_id"):
        await executor(state)


async def test_hitl_executor_calls_interrupt_with_correct_payload():
    """__call__ 调用 interrupt 时 payload 含 node_state_id / phase / form_schema / deadline_at / current_actor。"""
    form_schema = {
        "type": "object",
        "properties": {"comment": {"type": "string"}},
        "required": ["comment"],
    }
    executor = HITLNodeExecutor(_make_hitl_node(form_schema=form_schema))
    state = _make_state()

    # patch interrupt 返回模拟 resume value
    fake_resume = {
        "action": "submit",
        "reason": "",
        "form_data": {"comment": "OK"},
        "actor_id": "u_alice",
        "jti": "jti-123",
        "ip": "1.2.3.4",
        "ua": "Mozilla/5.0",
    }

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=fake_resume,
    ) as mock_interrupt:
        result = await executor(state)

    # interrupt 被调用且参数正确
    mock_interrupt.assert_called_once()
    call_args = mock_interrupt.call_args[0][0]  # interrupt(payload) → payload
    assert call_args["node_state_id"] == state["_node_state_id"]
    assert call_args["phase"] == "submit"
    assert call_args["form_schema"] == form_schema
    assert call_args["deadline_at"] == "2026-05-18T12:00:00+00:00"
    assert call_args["current_actor"]["email"] == "alice@example.com"

    # 输出结构正确
    assert "hitl" in result
    assert result["hitl"]["action"] == "submit"
    assert result["hitl"]["form_data"] == {"comment": "OK"}
    assert result["hitl"]["actor_id"] == "u_alice"
    assert result["hitl"]["jti"] == "jti-123"
    assert result["hitl"]["ip"] == "1.2.3.4"
    assert result["hitl"]["ua"] == "Mozilla/5.0"
    assert "completed_at" in result["hitl"]


async def test_hitl_executor_validates_form_data_against_schema():
    """form_schema 存在且 form_data 不符合时抛 jsonschema.ValidationError。"""
    form_schema = {
        "type": "object",
        "properties": {"age": {"type": "integer", "minimum": 0}},
        "required": ["age"],
    }
    executor = HITLNodeExecutor(_make_hitl_node(form_schema=form_schema))
    state = _make_state()

    bad_resume = {
        "action": "submit",
        "form_data": {"age": "not_a_number"},  # type 不匹配
        "actor_id": "u_alice",
    }

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=bad_resume,
    ):
        with pytest.raises(JsonSchemaValidationError):
            await executor(state)


async def test_hitl_executor_skips_validation_when_no_form_schema():
    """form_schema 为空 dict 时跳过校验，任何 form_data 通过。"""
    executor = HITLNodeExecutor(_make_hitl_node(form_schema={}))
    state = _make_state()

    fake_resume = {
        "action": "approve",
        "form_data": {"any": "thing", "nested": {"x": 1}},
        "actor_id": "u_bob",
    }

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value=fake_resume,
    ):
        result = await executor(state)

    assert result["hitl"]["action"] == "approve"
    assert result["hitl"]["form_data"] == {"any": "thing", "nested": {"x": 1}}


async def test_hitl_executor_raises_if_resume_not_dict():
    """resume value 不是 dict 时抛 NodeExecutionError。"""
    executor = HITLNodeExecutor(_make_hitl_node())
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value="just-a-string",  # 错误类型
    ):
        with pytest.raises(NodeExecutionError, match="dict"):
            await executor(state)


async def test_hitl_executor_records_completion_timestamp_iso8601():
    """输出 completed_at 是 ISO8601 字符串。"""
    from datetime import datetime

    executor = HITLNodeExecutor(_make_hitl_node())
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value={"action": "submit", "actor_id": "u1", "form_data": {}},
    ):
        result = await executor(state)

    completed_at = result["hitl"]["completed_at"]
    # 可解析为 datetime
    parsed = datetime.fromisoformat(completed_at)
    assert parsed.tzinfo is not None  # UTC tz 必须存在


async def test_hitl_executor_execute_method_raises():
    """HITLNodeExecutor.execute() 被直接调用应抛错（已 override __call__）。"""
    executor = HITLNodeExecutor(_make_hitl_node())
    with pytest.raises(NodeExecutionError, match="execute"):
        await executor.execute({}, {})


async def test_hitl_executor_passes_through_reason():
    """resume.reason 字段透传到 output。"""
    executor = HITLNodeExecutor(_make_hitl_node())
    state = _make_state()

    with patch(
        "app.agent_builder.workflow.nodes.hitl.interrupt",
        return_value={
            "action": "reject",
            "reason": "申请材料不齐全",
            "form_data": {},
            "actor_id": "u_alice",
        },
    ):
        result = await executor(state)

    assert result["hitl"]["action"] == "reject"
    assert result["hitl"]["reason"] == "申请材料不齐全"
