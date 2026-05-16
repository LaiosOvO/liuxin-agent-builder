"""Start 节点 executor。

Start 节点是工作流的起点，将初始输入透传到自身 namespace。
下游节点通过 `{{ start.<field> }}` 引用 start 节点的输出。

设计：
- execute() 把整个 state 返回，使得 state[node_id] 包含所有初始字段
- 下游 Jinja2 引用 `{{ start.name }}` 时，state["start"]["name"] 即可取到
- v1 约定：初始 input dict 已在 state 中（由 LangGraph ainvoke 传入），
  Start 节点只是把它整体作为自己的输出
"""
from __future__ import annotations

from typing import Any

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor


class StartNodeExecutor(BaseNodeExecutor):
    """Start 节点执行器。

    行为：把当前整个 state 透传到自身 namespace，
    使下游节点可以通过 `{{ start.<field> }}` 引用初始输入。
    """

    async def execute(self, config: dict, state: dict) -> dict[str, Any]:
        """透传 state 作为 start 节点输出。

        Args:
            config: 渲染后的节点配置（start 节点通常无特殊配置）
            state: 当前 state dict（含初始输入）

        Returns:
            state 的浅拷贝，作为 start 节点的输出
        """
        return dict(state)
