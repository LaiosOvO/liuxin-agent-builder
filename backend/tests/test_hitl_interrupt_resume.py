"""HITL node + LangGraph 1.2 interrupt + Command(resume) 集成测试。

测试范围（4+ 用例）：
- test_graph_pauses_at_hitl_node：ainvoke 后 graph 在 hitl 节点暂停（__interrupt__ 出现）
- test_resume_with_command_continues_graph：ainvoke(Command(resume={...})) 后节点完成
- test_resume_passes_form_data_to_node：Command(resume=form_data) → state.hitl.form_data 正确
- test_resume_with_invalid_form_data_raises：form_schema 不通过 → ValidationError

测试约定（CLAUDE.md 2.2）：
- 不 mock 任何 LangGraph 内部，用真实 InMemorySaver + StateGraph + interrupt
- thread_id 用 uuid，模拟生产环境

参考 docs/reading-dify-03-02-hitl-executor-2026-05-17.md §7.2 — venv 实测的 stream/ainvoke 模式
"""
from __future__ import annotations

import uuid
from typing import Any
from uuid import uuid4

import pytest
from jsonschema import ValidationError as JsonSchemaValidationError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

from app.agent_builder.workflow.nodes.hitl import HITLNodeExecutor


# ── State 定义 ──────────────────────────────────────────────────────────────────


class HitlGraphState(TypedDict, total=False):
    """测试用 graph state。

    必须显式声明字段（LangGraph TypedDict 只保留已声明字段）。
    """

    _node_state_id: str
    hitl: dict[str, Any]
    start: dict[str, Any]


# ── 辅助：构造 hitl node_def + LangGraph 图 ────────────────────────────────────


def _make_hitl_node_def(
    form_schema: dict | None = None,
    node_id: str = "hitl",
) -> dict:
    return {
        "id": node_id,
        "type": "hitl",
        "config": {
            "assignees": ["alice@example.com"],
            "timeout_seconds": 3600,
            "phase": "submit",
            "form_schema": form_schema or {},
            "deadline_at": "2026-05-18T12:00:00+00:00",
            "current_actor": {
                "id": "u_alice",
                "email": "alice@example.com",
                "role": "executor",
            },
        },
    }


def _build_graph(
    form_schema: dict | None = None,
    node_id: str = "hitl",
):
    """构造一个简单的 LangGraph 图：START → hitl → END。

    返回编译后的 graph + node_state_id（用于注入到初始 state）。
    """
    executor = HITLNodeExecutor(_make_hitl_node_def(form_schema=form_schema, node_id=node_id))

    builder = StateGraph(HitlGraphState)
    builder.add_node(node_id, executor)
    builder.add_edge(START, node_id)
    builder.add_edge(node_id, END)

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    return graph


# ── 集成测试 ───────────────────────────────────────────────────────────────────


async def test_graph_pauses_at_hitl_node():
    """ainvoke 后 graph 在 hitl 节点 interrupt，state 中含 __interrupt__。"""
    graph = _build_graph()
    thread_id = f"test:{uuid.uuid4()}"
    node_state_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # 首次 ainvoke → 触发 interrupt，graph 不再继续
    initial_state: HitlGraphState = {
        "_node_state_id": node_state_id,
        "start": {"name": "Alice"},
    }
    result = await graph.ainvoke(initial_state, config)

    # LangGraph 1.2 在 interrupt 时把 __interrupt__ 写入 result（state 不含 hitl 输出）
    assert "__interrupt__" in result, f"graph 应该在 hitl 暂停，实际 result keys: {list(result.keys())}"

    # state 中尚未含 hitl 节点完成的 output
    assert "hitl" not in result or result.get("hitl") is None

    # 检查 interrupt payload 正确（含 node_state_id / phase / deadline_at）
    interrupts = result["__interrupt__"]
    # interrupts 是元组 of Interrupt 对象
    interrupt_obj = interrupts[0]
    value = interrupt_obj.value
    assert value["node_state_id"] == node_state_id
    assert value["phase"] == "submit"
    assert value["deadline_at"] == "2026-05-18T12:00:00+00:00"
    assert value["current_actor"]["email"] == "alice@example.com"


async def test_resume_with_command_continues_graph():
    """ainvoke(Command(resume={...})) 后 graph 继续，hitl 节点完成。"""
    graph = _build_graph()
    thread_id = f"test:{uuid.uuid4()}"
    node_state_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # 1. 首次 invoke → 暂停
    await graph.ainvoke(
        {"_node_state_id": node_state_id, "start": {"name": "Alice"}},
        config,
    )

    # 2. resume with Command
    resume_value = {
        "action": "submit",
        "reason": "申请通过",
        "form_data": {},
        "actor_id": "u_alice",
        "jti": str(uuid4()),
        "ip": "1.2.3.4",
        "ua": "Mozilla/5.0",
    }
    final_state = await graph.ainvoke(Command(resume=resume_value), config)

    # 3. 检查 final state 中 hitl 节点已完成
    assert "hitl" in final_state
    hitl_output = final_state["hitl"]
    assert hitl_output["action"] == "submit"
    assert hitl_output["reason"] == "申请通过"
    assert hitl_output["actor_id"] == "u_alice"
    assert hitl_output["ip"] == "1.2.3.4"
    assert "completed_at" in hitl_output

    # _node_state_id 仍保留
    assert final_state["_node_state_id"] == node_state_id


async def test_resume_passes_form_data_to_node():
    """Command(resume={form_data: {...}}) → state.hitl.form_data 正确透传。"""
    form_schema = {
        "type": "object",
        "properties": {
            "salary": {"type": "number", "minimum": 0},
            "comment": {"type": "string"},
        },
        "required": ["salary"],
    }
    graph = _build_graph(form_schema=form_schema)
    thread_id = f"test:{uuid.uuid4()}"
    node_state_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    await graph.ainvoke(
        {"_node_state_id": node_state_id, "start": {}},
        config,
    )

    resume_value = {
        "action": "approve",
        "form_data": {"salary": 10000, "comment": "符合标准"},
        "actor_id": "u_bob",
    }
    final_state = await graph.ainvoke(Command(resume=resume_value), config)

    assert final_state["hitl"]["action"] == "approve"
    assert final_state["hitl"]["form_data"] == {"salary": 10000, "comment": "符合标准"}


async def test_resume_with_invalid_form_data_raises_validation_error():
    """form_schema 校验失败时（resume 注入坏 data）抛 jsonschema.ValidationError。"""
    form_schema = {
        "type": "object",
        "properties": {"age": {"type": "integer", "minimum": 0}},
        "required": ["age"],
    }
    graph = _build_graph(form_schema=form_schema)
    thread_id = f"test:{uuid.uuid4()}"
    node_state_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    await graph.ainvoke(
        {"_node_state_id": node_state_id, "start": {}},
        config,
    )

    bad_resume = {
        "action": "submit",
        "form_data": {"age": "not-a-number"},
        "actor_id": "u_alice",
    }

    # LangGraph 把节点内的 exception 包装后冒泡
    with pytest.raises(JsonSchemaValidationError):
        await graph.ainvoke(Command(resume=bad_resume), config)


async def test_state_retains_initial_fields_after_resume():
    """resume 后初始 state 中其他字段保留（state merge 语义）。"""
    graph = _build_graph()
    thread_id = f"test:{uuid.uuid4()}"
    node_state_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    await graph.ainvoke(
        {"_node_state_id": node_state_id, "start": {"applicant": "Alice", "score": 95}},
        config,
    )

    final = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "form_data": {},
                "actor_id": "u_reviewer",
            }
        ),
        config,
    )

    # start 字段保留
    assert final["start"] == {"applicant": "Alice", "score": 95}
    # _node_state_id 保留
    assert final["_node_state_id"] == node_state_id
    # hitl 输出新增
    assert final["hitl"]["action"] == "approve"
