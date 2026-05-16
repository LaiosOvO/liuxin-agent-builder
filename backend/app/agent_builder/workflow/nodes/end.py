"""End 节点 executor。

End 节点是工作流的终点，不修改 state，仅作为终态标记。
LangGraph 连接 end_node → END 实现图终止。

设计：
- execute() 返回 {"_completed": True} 作为完成标记
- 不修改其他 state 字段
- 多个 end 节点时（if_else 分支），每个均可作为终点
"""
from __future__ import annotations

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor


class EndNodeExecutor(BaseNodeExecutor):
    """End 节点执行器。

    行为：不修改 state，仅返回完成标记 {"_completed": True}。
    LangGraph 通过 add_edge(end_node_id, END) 实现图终止。
    """

    async def execute(self, config: dict, state: dict) -> dict:
        """End 节点终态标记。

        Args:
            config: 渲染后的节点配置（end 节点通常无特殊配置）
            state: 当前 state dict（不修改）

        Returns:
            {"_completed": True}，作为完成标记写入 state[node_id]
        """
        return {"_completed": True}
