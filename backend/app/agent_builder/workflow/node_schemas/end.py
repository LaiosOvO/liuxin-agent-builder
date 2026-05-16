"""End 节点 Schema 定义。

End 节点：
- 工作流出口，每个 DSL 至少有一个
- config 为空对象（无配置项）
- 无输出字段（不产生任何输出）
"""
from __future__ import annotations

# End 节点 JSON Schema
END_NODE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
    "description": "End 节点配置，无需任何配置项",
}

# End 节点输出字段（无输出）
END_OUTPUT_FIELDS: frozenset[str] = frozenset()
