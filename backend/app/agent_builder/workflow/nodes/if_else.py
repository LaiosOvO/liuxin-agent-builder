"""IfElse 节点 executor。

IfElse 节点实现条件分支路由：
- 对 conditions[].expr 依次 Jinja2 求值（布尔）
- 第一个 truthy 条件 → 路由到该 target_node_id
- 全部不匹配 → 路由到 default_target

DSL config 格式：
    {
        "conditions": [
            {"expr": "{{ x > 5 }}", "target_node_id": "node_high"},
            {"expr": "{{ x == 0 }}", "target_node_id": "node_zero"},
        ],
        "default_target": "node_low"
    }

设计参考（Dify 阅读笔记 docs/reading-dify-02-04-base-nodes-2026-05-16.md）：
- Dify 前端用结构化 ComparisonOperator + cases GUI 构建器
- 我们用 Jinja2 字符串表达式（更灵活，学习成本低，与 DSL 其他字段一致）
- 渲染结果映射："true"/"1"/"yes" → truthy，其他 → falsy

与 DSLCompiler 集成：
- if_else 节点不走普通 add_edge，而是走 add_conditional_edges
- DSLCompiler._make_if_else_router 调用 resolve_route 构造路由函数
"""
from __future__ import annotations

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor


class IfElseNodeExecutor(BaseNodeExecutor):
    """IfElse 节点执行器。

    行为：对 conditions[].expr 依次 Jinja2 求值，匹配则路由到对应 target_node_id，
    否则路由到 default_target。
    """

    async def execute(self, config: dict, state: dict) -> dict:
        """IfElse 节点执行：仅做路由，不修改 state 业务字段。

        注意：直接使用 self.config（原始未渲染配置）而非 config（已渲染），
        因为 conditions[].expr 是 Jinja2 表达式，需要延迟到 resolve_route 中求值，
        不能在 _render_config 阶段提前渲染（提前渲染会导致 UndefinedError）。

        Args:
            config: 渲染后的节点配置（仅用于读取非 expr 字段，如 default_target）
            state: 当前 state dict

        Returns:
            {"_routed_to": target_node_id}，记录路由结果（供事件/调试使用）
        """
        target = self.resolve_route(self.config, state)
        return {"_routed_to": target}

    def resolve_route(self, config: dict, state: dict) -> str:
        """对 conditions[].expr 依次 Jinja2 求值，返回目标节点 ID。

        注意：config 应为原始未渲染的节点配置（self.config），不是 _render_config 的结果。
        原因：conditions[].expr 是 Jinja2 模板字符串，需要在此处对 state 求值；
              如果在 _render_config 中提前渲染，则 undefined 变量会导致 UndefinedError 而非跳过。

        求值逻辑：
        1. 依次对每个 condition 的 expr 用 Jinja2 渲染（以 state 为上下文）
        2. 渲染结果（strip + lower）映射：
           - "true" / "1" / "yes" → truthy → 返回该 condition 的 target_node_id
           - 其他 → falsy → 继续下一条件
        3. 所有条件不匹配 → 返回 default_target
        4. expr 求值异常 → 跳过该 condition（容错处理）

        Args:
            config: 原始节点配置（含 conditions 列表 + default_target），不经过 _render_config
            state: 当前 state dict（作为 Jinja2 渲染上下文）

        Returns:
            目标节点 ID（str）
        """
        default_target: str = config.get("default_target", "")
        conditions: list[dict] = config.get("conditions", [])

        for cond in conditions:
            expr_str: str = cond.get("expr", "")
            target_node_id: str = cond.get("target_node_id", "")
            if not expr_str or not target_node_id:
                continue
            try:
                template = self.jinja_env.from_string(expr_str)
                rendered = template.render(**state).strip().lower()
                if rendered in ("true", "1", "yes"):
                    return target_node_id
            except Exception:
                # expr 求值失败（变量未定义、语法错误等），跳过该 condition
                continue

        return default_target
