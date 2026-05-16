"""DSL JSON Schema 定义模块。

提供：
- DSL_VERSION：当前 DSL 版本号常量
- DSL_SCHEMA：JSON Schema Draft 7 字典，用于验证 DSL 结构
- RESERVED_NODE_IDS：保留节点 ID 集合（禁止用户使用）

设计原则：
- 一处定义，多处引用（validator / compiler / test 均从此引入）
- 与 Pydantic 模型（dsl_models.py）保持镜像一致
"""
from __future__ import annotations

# 当前 DSL 版本
DSL_VERSION: str = "1.0"

# 保留节点 ID（禁止用户使用，防止与系统内部命名冲突）
RESERVED_NODE_IDS: frozenset[str] = frozenset({
    "state",
    "event",
    "ptr",
    "__ptr__",
    "start_event",
    "end_event",
    "input",
    "output",
    "__start__",
    "__end__",
})

# DSL JSON Schema（Draft 7）
# 用于 jsonschema.validate() 顶层校验
DSL_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "WorkflowDSL",
    "description": "工作流 DSL 定义（v1.0）",
    "type": "object",
    "required": ["version", "state_schema", "nodes", "edges"],
    "additionalProperties": False,
    "properties": {
        "version": {
            "const": DSL_VERSION,
            "description": "DSL 版本号，固定为 1.0",
        },
        "name": {
            "type": "string",
            "description": "工作流名称（可选）",
        },
        "state_schema": {
            "type": "object",
            "description": "工作流状态字段定义，字段名 → Python 类型字符串",
            "additionalProperties": {
                "enum": ["str", "int", "float", "bool", "list", "dict", "any"],
            },
        },
        "nodes": {
            "type": "array",
            "description": "节点列表，至少包含 start + end 共 2 个节点",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["id", "type", "config"],
                "additionalProperties": False,
                "properties": {
                    "id": {
                        "type": "string",
                        "pattern": "^[a-z][a-z0-9_]*$",
                        "description": "节点 ID，小写字母开头，仅含小写字母/数字/下划线",
                    },
                    "type": {
                        "enum": ["start", "end", "llm", "tool", "if_else"],
                        "description": "节点类型",
                    },
                    "position": {
                        "type": "object",
                        "description": "画布位置（回显用，不影响执行）",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                        },
                        "additionalProperties": False,
                    },
                    "config": {
                        "type": "object",
                        "description": "节点配置（由各节点 schema 进一步约束）",
                    },
                },
            },
        },
        "edges": {
            "type": "array",
            "description": "边列表（if_else 节点的下游通过 config 声明，不在 edges 中）",
            "items": {
                "type": "object",
                "required": ["id", "source", "target"],
                "additionalProperties": False,
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "边 ID，唯一标识",
                    },
                    "source": {
                        "type": "string",
                        "description": "边起点节点 ID",
                    },
                    "target": {
                        "type": "string",
                        "description": "边终点节点 ID",
                    },
                },
            },
        },
    },
}
