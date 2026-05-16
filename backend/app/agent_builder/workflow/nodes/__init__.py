"""节点执行器注册表。

提供：
- NODE_EXECUTORS：dict[str, type[BaseNodeExecutor]]
  - 以 DSL 节点 type 字符串为 key
  - 以对应 executor 类为 value
  - DSLCompiler 通过 NODE_EXECUTORS[node_type](node_def) 实例化

当前注册的节点类型：
- "start"   → StartNodeExecutor
- "end"     → EndNodeExecutor
- "if_else" → IfElseNodeExecutor
- "tool"    → ToolNodeExecutor
- "llm"     → LLMNodeExecutor（Plan 02-05）
- "hitl"    → HITLNodeExecutor（Plan 03-02：interrupt + Command(resume)）

Plan 接入说明：
- Plan 02-04：start / end / if_else / tool
- Plan 02-05：llm 节点（init_chat_model 多 provider）
- Plan 03-02：hitl 节点（LangGraph 1.2 interrupt + Command(resume)）

设计参考（Dify 阅读笔记 docs/reading-dify-02-04-base-nodes-2026-05-16.md）：
- Dify 用 pkgutil.walk_packages 自动发现，我们手动 import（项目规模小，可读性优先）
- Dify NodeComponentMap 前端也用相同 dict 模式注册 React 组件
"""
from __future__ import annotations

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor
from app.agent_builder.workflow.nodes.end import EndNodeExecutor
from app.agent_builder.workflow.nodes.hitl import HITLNodeExecutor
from app.agent_builder.workflow.nodes.if_else import IfElseNodeExecutor
from app.agent_builder.workflow.nodes.llm import LLMNodeExecutor
from app.agent_builder.workflow.nodes.start import StartNodeExecutor
from app.agent_builder.workflow.nodes.tool import ToolNodeExecutor

# 节点类型 → executor 类的注册表
# DSLCompiler 通过 NODE_EXECUTORS[node["type"]](node, jinja_env=...) 实例化
NODE_EXECUTORS: dict[str, type[BaseNodeExecutor]] = {
    "start": StartNodeExecutor,
    "end": EndNodeExecutor,
    "if_else": IfElseNodeExecutor,
    "tool": ToolNodeExecutor,
    "llm": LLMNodeExecutor,
    "hitl": HITLNodeExecutor,
}

__all__ = [
    "NODE_EXECUTORS",
    "BaseNodeExecutor",
    "StartNodeExecutor",
    "EndNodeExecutor",
    "IfElseNodeExecutor",
    "ToolNodeExecutor",
    "LLMNodeExecutor",
    "HITLNodeExecutor",
]
