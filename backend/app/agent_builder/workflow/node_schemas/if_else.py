"""IfElse 节点 Schema 定义。

IfElse 节点：
- 条件分支节点，根据 Jinja2 表达式结果路由到不同下游节点
- 必须指定 default_target（当所有 conditions 均不满足时走此分支）
- conditions 列表至少一个，每项含：
  - expr：Jinja2 布尔表达式（如 {{ llm_1.message | length > 100 }}）
  - target_node_id：满足条件时跳转的节点 ID
  - label：可选标签（前端显示用）
- 下游节点通过 conditions[].target_node_id + default_target 指定
  （不在 edges[] 中声明，DSLCompiler 负责调用 add_conditional_edges）
- 无输出字段（仅路由，不写 state）
"""
from __future__ import annotations

# 单个条件定义 Schema
IF_ELSE_CONDITION_SCHEMA: dict = {
    "type": "object",
    "required": ["expr", "target_node_id"],
    "additionalProperties": False,
    "properties": {
        "expr": {
            "type": "string",
            "description": "Jinja2 布尔表达式，为真时跳转 target_node_id",
        },
        "target_node_id": {
            "type": "string",
            "description": "满足条件时的目标节点 ID",
        },
        "label": {
            "type": "string",
            "description": "分支标签（前端显示用，可选）",
        },
    },
}

# IfElse 节点 JSON Schema
IF_ELSE_NODE_SCHEMA: dict = {
    "type": "object",
    "required": ["conditions", "default_target"],
    "additionalProperties": False,
    "properties": {
        "conditions": {
            "type": "array",
            "minItems": 1,
            "items": IF_ELSE_CONDITION_SCHEMA,
            "description": "条件列表，按顺序评估，第一个满足的条件生效",
        },
        "default_target": {
            "type": "string",
            "description": "默认目标节点 ID（当所有 conditions 均不满足时走此分支）",
        },
    },
}

# IfElse 节点输出字段（无输出，仅路由）
IF_ELSE_OUTPUT_FIELDS: frozenset[str] = frozenset()
