"""DSL 验证器 — 节点配置类型检查（Category 3）单元测试。

验证：
- test_llm_node_missing_model：E_INVALID_CONFIG
- test_llm_node_invalid_temperature：temperature=3.5 → E_INVALID_CONFIG
- test_tool_http_missing_url：E_INVALID_CONFIG
- test_if_else_no_default：E_IF_ELSE_NO_DEFAULT
- test_reserved_node_id：id="state" → E_NODE_ID_RESERVED
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.validator import DSLValidator, ValidationError


def get_error_codes(errors: list[ValidationError]) -> list[str]:
    return [e.code for e in errors]


def has_error(errors: list[ValidationError], code: str) -> bool:
    return code in get_error_codes(errors)


def make_simple_dsl(nodes: list[dict], edges: list[dict], state_schema: dict | None = None) -> dict:
    """构造最小 DSL dict。"""
    return {
        "version": "1.0",
        "name": "测试",
        "state_schema": state_schema or {},
        "nodes": nodes,
        "edges": edges,
    }


def start_node(nid: str = "start") -> dict:
    return {"id": nid, "type": "start", "config": {}}


def end_node(nid: str = "end") -> dict:
    return {"id": nid, "type": "end", "config": {}}


def edge(eid: str, src: str, tgt: str) -> dict:
    return {"id": eid, "source": src, "target": tgt}


# ─── LLM 节点配置错误 ─────────────────────────────────────────────────────────


class TestLlmNodeConfigErrors:
    """LLM 节点配置类型错误"""

    def test_llm_node_missing_model(self):
        """LLM 节点缺少 model 字段，应报 E_INVALID_CONFIG"""
        nodes = [
            start_node(),
            {
                "id": "llm_1",
                "type": "llm",
                "config": {
                    "user_prompt": "hello",
                    # 缺少 model
                },
            },
            end_node(),
        ]
        edges_list = [edge("e1", "start", "llm_1"), edge("e2", "llm_1", "end")]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_INVALID_CONFIG"), (
            f"期望 E_INVALID_CONFIG，实际：{get_error_codes(errors)}"
        )

    def test_llm_node_invalid_temperature(self):
        """LLM 节点 temperature=3.5 超出最大值 2，应报 E_INVALID_CONFIG"""
        nodes = [
            start_node(),
            {
                "id": "llm_1",
                "type": "llm",
                "config": {
                    "model": "openai:gpt-4o",
                    "user_prompt": "分析",
                    "temperature": 3.5,  # 超出范围
                },
            },
            end_node(),
        ]
        edges_list = [edge("e1", "start", "llm_1"), edge("e2", "llm_1", "end")]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_INVALID_CONFIG"), (
            f"期望 E_INVALID_CONFIG，实际：{get_error_codes(errors)}"
        )

    def test_llm_node_missing_prompt(self):
        """LLM 节点有 model 但没有 user_prompt 也没有 raw_prompt，应报 E_INVALID_CONFIG"""
        nodes = [
            start_node(),
            {
                "id": "llm_1",
                "type": "llm",
                "config": {
                    "model": "openai:gpt-4o",
                    # 无 user_prompt 也无 raw_prompt
                },
            },
            end_node(),
        ]
        edges_list = [edge("e1", "start", "llm_1"), edge("e2", "llm_1", "end")]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_INVALID_CONFIG"), (
            f"期望 E_INVALID_CONFIG，实际：{get_error_codes(errors)}"
        )

    def test_llm_node_negative_retry_count(self):
        """retry_count=-1 小于最小值 0，应报 E_INVALID_CONFIG"""
        nodes = [
            start_node(),
            {
                "id": "llm_1",
                "type": "llm",
                "config": {
                    "model": "m",
                    "user_prompt": "p",
                    "retry_count": -1,
                },
            },
            end_node(),
        ]
        edges_list = [edge("e1", "start", "llm_1"), edge("e2", "llm_1", "end")]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_INVALID_CONFIG"), (
            f"期望 E_INVALID_CONFIG，实际：{get_error_codes(errors)}"
        )


# ─── Tool 节点配置错误 ─────────────────────────────────────────────────────────


class TestToolNodeConfigErrors:
    """Tool 节点配置类型错误"""

    def test_tool_http_missing_url(self):
        """HTTP Tool 节点缺少 url 字段，应报 E_INVALID_CONFIG"""
        nodes = [
            start_node(),
            {
                "id": "tool_1",
                "type": "tool",
                "config": {
                    "kind": "http",
                    "method": "POST",
                    # 缺少 url
                },
            },
            end_node(),
        ]
        edges_list = [edge("e1", "start", "tool_1"), edge("e2", "tool_1", "end")]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_INVALID_CONFIG"), (
            f"期望 E_INVALID_CONFIG，实际：{get_error_codes(errors)}"
        )


# ─── IfElse 节点特殊检查 ──────────────────────────────────────────────────────


class TestIfElseSpecialRules:
    """E_IF_ELSE_NO_DEFAULT 检测"""

    def test_if_else_no_default(self):
        """if_else 节点缺 default_target 字段，应报 E_IF_ELSE_NO_DEFAULT"""
        nodes = [
            start_node(),
            {
                "id": "branch",
                "type": "if_else",
                "config": {
                    "conditions": [{"expr": "{{ x > 0 }}", "target_node_id": "end_ok"}],
                    # 缺少 default_target
                },
            },
            end_node("end_ok"),
        ]
        edges_list = [edge("e1", "start", "branch")]
        dsl = make_simple_dsl(nodes, edges_list, state_schema={"x": "int"})
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_IF_ELSE_NO_DEFAULT") or has_error(errors, "E_INVALID_CONFIG"), (
            f"期望 E_IF_ELSE_NO_DEFAULT 或 E_INVALID_CONFIG，实际：{get_error_codes(errors)}"
        )


# ─── 保留节点 ID 检查 ─────────────────────────────────────────────────────────


class TestReservedNodeId:
    """E_NODE_ID_RESERVED 检测"""

    def test_reserved_node_id_state(self):
        """节点 id='state' 是保留字，应报 E_NODE_ID_RESERVED"""
        nodes = [
            {"id": "state", "type": "start", "config": {}},  # 'state' 是保留字
            end_node(),
        ]
        edges_list = [edge("e1", "state", "end")]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_NODE_ID_RESERVED"), (
            f"期望 E_NODE_ID_RESERVED，实际：{get_error_codes(errors)}"
        )

    def test_reserved_node_id_event(self):
        """节点 id='event' 是保留字，应报 E_NODE_ID_RESERVED"""
        nodes = [
            start_node(),
            {"id": "event", "type": "llm", "config": {"model": "m", "user_prompt": "p"}},
            end_node(),
        ]
        edges_list = [
            edge("e1", "start", "event"),
            edge("e2", "event", "end"),
        ]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_NODE_ID_RESERVED"), (
            f"期望 E_NODE_ID_RESERVED，实际：{get_error_codes(errors)}"
        )

    def test_valid_node_id_not_reserved(self):
        """合法节点 ID 不报保留字错误"""
        nodes = [start_node(), llm_node(), end_node()]
        edges_list = [edge("e1", "start", "llm_1"), edge("e2", "llm_1", "end")]
        dsl = make_simple_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert not has_error(errors, "E_NODE_ID_RESERVED"), (
            f"不应有 E_NODE_ID_RESERVED，实际：{get_error_codes(errors)}"
        )


def llm_node(nid: str = "llm_1") -> dict:
    return {
        "id": nid,
        "type": "llm",
        "config": {"model": "openai:gpt-4o", "user_prompt": "hello"},
    }
