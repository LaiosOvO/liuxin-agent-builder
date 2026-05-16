"""Start 节点 Schema 定义。

Start 节点：
- 工作流入口，每个 DSL 只能有一个
- config 为空对象（无配置项）
- 输出字段：state_schema 中声明的所有字段（运行时从输入注入）
"""
from __future__ import annotations

# Start 节点 JSON Schema
START_NODE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
    "description": "Start 节点配置，无需任何配置项",
}

# Start 节点输出字段（运行时由 state_schema 动态决定，此处为特殊标记）
# 验证器中对 start 节点的引用 {{ start.<field> }} 检查逻辑：
# <field> 必须是 state_schema 中声明的字段名，或 "output"（兜底）
START_OUTPUT_FIELDS: frozenset[str] = frozenset({
    "output",  # 通用兜底字段
    # state_schema 字段在验证器中动态添加
})
