"""DSL Pydantic v2 模型模块。

提供：
- DSLNode：节点 Pydantic 模型
- DSLEdge：边 Pydantic 模型
- DSL：完整 DSL Pydantic 模型

设计说明：
- Pydantic 模型用于 Python 层 type-safe 操作（序列化/反序列化/IDE 补全）
- 验证逻辑以 JSON Schema（schema.py）为权威，Pydantic 模型为镜像
- 两者保持结构一致，如有修改需同步
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DSLNode(BaseModel):
    """工作流节点模型。

    id：节点 ID，小写字母开头，仅含小写字母/数字/下划线
    type：节点类型，5 种之一
    position：画布位置（回显用，不影响执行）
    config：节点配置（由各节点 schema 进一步约束）
    """

    id: str
    type: Literal["start", "end", "llm", "tool", "if_else", "hitl"]
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class DSLEdge(BaseModel):
    """工作流边模型。

    id：边 ID，唯一标识
    source：边起点节点 ID
    target：边终点节点 ID
    """

    id: str
    source: str
    target: str

    model_config = {"extra": "forbid"}


class DSL(BaseModel):
    """完整工作流 DSL 模型。

    version：DSL 版本号，固定为 "1.0"
    name：工作流名称（可选）
    state_schema：工作流状态字段定义，字段名 → Python 类型字符串
    nodes：节点列表
    edges：边列表
    """

    version: Literal["1.0"]
    name: str = ""
    state_schema: dict[str, str] = Field(default_factory=dict)
    nodes: list[DSLNode]
    edges: list[DSLEdge]

    model_config = {"extra": "forbid"}

    def get_node_by_id(self, node_id: str) -> DSLNode | None:
        """按 ID 查找节点，不存在返回 None。"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_start_node(self) -> DSLNode | None:
        """获取 start 节点，不存在返回 None。"""
        for node in self.nodes:
            if node.type == "start":
                return node
        return None

    def get_end_nodes(self) -> list[DSLNode]:
        """获取所有 end 节点列表。"""
        return [node for node in self.nodes if node.type == "end"]

    def to_dict(self) -> dict[str, Any]:
        """转为原始 dict（用于传给 JSON Schema 验证器）。"""
        return self.model_dump()
