"""节点 Schema 注册表。

提供：
- NODE_SCHEMAS：节点类型 → (JSON Schema dict, 输出字段集合) 映射
- get_node_schema(node_type)：按类型获取节点 JSON Schema
- get_node_output_fields(node_type)：按类型获取节点输出字段集合

使用示例：
    schema, output_fields = NODE_SCHEMAS["llm"]
    jsonschema.validate(node_config, schema)
    assert "message" in output_fields
"""
from __future__ import annotations

from app.agent_builder.workflow.node_schemas.end import END_NODE_SCHEMA, END_OUTPUT_FIELDS
from app.agent_builder.workflow.node_schemas.if_else import IF_ELSE_NODE_SCHEMA, IF_ELSE_OUTPUT_FIELDS
from app.agent_builder.workflow.node_schemas.llm import LLM_NODE_SCHEMA, LLM_OUTPUT_FIELDS
from app.agent_builder.workflow.node_schemas.start import START_NODE_SCHEMA, START_OUTPUT_FIELDS
from app.agent_builder.workflow.node_schemas.tool import TOOL_NODE_SCHEMA, TOOL_OUTPUT_FIELDS

# 节点类型 → (JSON Schema, 输出字段集合) 注册表
# 所有验证器 / 编译器通过此表查询各节点的 schema 和输出字段
NODE_SCHEMAS: dict[str, tuple[dict, frozenset[str]]] = {
    "start": (START_NODE_SCHEMA, START_OUTPUT_FIELDS),
    "end": (END_NODE_SCHEMA, END_OUTPUT_FIELDS),
    "llm": (LLM_NODE_SCHEMA, LLM_OUTPUT_FIELDS),
    "tool": (TOOL_NODE_SCHEMA, TOOL_OUTPUT_FIELDS),
    "if_else": (IF_ELSE_NODE_SCHEMA, IF_ELSE_OUTPUT_FIELDS),
}


def get_node_schema(node_type: str) -> dict:
    """按节点类型获取 JSON Schema。

    Args:
        node_type: 节点类型字符串（"start"/"end"/"llm"/"tool"/"if_else"）

    Returns:
        该节点类型的 JSON Schema dict

    Raises:
        KeyError: 未知节点类型
    """
    return NODE_SCHEMAS[node_type][0]


def get_node_output_fields(node_type: str) -> frozenset[str]:
    """按节点类型获取输出字段集合。

    Args:
        node_type: 节点类型字符串

    Returns:
        输出字段名称集合（frozenset）

    Raises:
        KeyError: 未知节点类型
    """
    return NODE_SCHEMAS[node_type][1]


__all__ = [
    "NODE_SCHEMAS",
    "get_node_schema",
    "get_node_output_fields",
    "START_NODE_SCHEMA",
    "START_OUTPUT_FIELDS",
    "END_NODE_SCHEMA",
    "END_OUTPUT_FIELDS",
    "LLM_NODE_SCHEMA",
    "LLM_OUTPUT_FIELDS",
    "TOOL_NODE_SCHEMA",
    "TOOL_OUTPUT_FIELDS",
    "IF_ELSE_NODE_SCHEMA",
    "IF_ELSE_OUTPUT_FIELDS",
]
