"""DSL 编译器模块。

提供：
- CompiledGraph：编译结果数据类（StateGraph + state_type）
- DSLCompiler：将 DSL dict 编译为 LangGraph StateGraph

设计说明：
- 本 Plan（02-02）只搭骨架：占位 executor，真实节点逻辑由 02-04/05 接入
- compile() 必须先过 DSLValidator，有 error 级别错误时抛 DSLCompilationError
- StateGraph 使用 TypedDict 动态工厂（来自 types.py，02-01 交付）
- if_else 节点使用 add_conditional_edges（占位 router 直接返回 default_target）
- start/end 节点通过 LangGraph 的 START/END 特殊标记连接
- checkpointer 通过 compile() 参数传入，使 graph.compile(checkpointer=...) 生效

占位 executor 行为（Plan 02-04/05 接入真实 executor）：
    async def placeholder(state) -> dict:
        return {node_id: {"_placeholder": True, "type": node_type}}

Plan 02-04 接入方式：
    from app.agent_builder.workflow.nodes import get_node_executor
    executor = get_node_executor(node_type)
    graph.add_node(node_id, executor.execute)

使用示例：
    compiler = DSLCompiler()
    async with get_checkpointer() as checkpointer:
        compiled = compiler.compile(dsl, checkpointer=checkpointer)
        # compiled.graph 是已编译的 LangGraph CompiledGraph
        # compiled.state_type 是 TypedDict 类
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agent_builder.workflow.jinja_env import build_jinja_env
from app.agent_builder.workflow.types import build_state_typeddict
from app.agent_builder.workflow.validator import DSLCompilationError, DSLValidator, ValidationError


@dataclass
class CompiledGraph:
    """DSL 编译结果。

    Attributes:
        graph: 已编译的 LangGraph CompiledGraph（调用 StateGraph.compile() 后返回）
        state_type: DSL state_schema 对应的 TypedDict 类
        dsl: 原始 DSL dict（用于调试和日志）
    """

    graph: Any  # langgraph CompiledGraph（类型为 CompiledStateGraph，不导入避免循环）
    state_type: type
    dsl: dict


class DSLCompiler:
    """DSL → LangGraph StateGraph 编译器。

    编译流程：
    1. DSLValidator 全量验证（有 error 抛 DSLCompilationError）
    2. 从 DSL state_schema 构造 TypedDict
    3. 构造 StateGraph(TypedDict)
    4. 添加所有节点（占位 executor）
    5. 添加常规 edges（非 if_else 的 source 节点）
    6. 添加 if_else 的 conditional_edges
    7. 连接 START → start_node 和 end_node → END
    8. graph.compile(checkpointer=...) 返回 CompiledGraph
    """

    def __init__(self) -> None:
        self._jinja_env = build_jinja_env()

    def compile(
        self,
        dsl: dict,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> CompiledGraph:
        """将 DSL dict 编译为 LangGraph StateGraph。

        Args:
            dsl: DSL 原始字典（来自 JSON 解析）
            checkpointer: LangGraph checkpoint 保存器（可选，生产环境传入 AsyncPostgresSaver）

        Returns:
            CompiledGraph 实例，包含编译好的 graph 和 state_type

        Raises:
            DSLCompilationError: DSL 验证失败（包含所有 error 级别的验证错误）
            ValueError: DSL 结构异常（无 start 或 end 节点，正常情况不会发生）
        """
        # Step 1：验证（有 error 立即抛出）
        validator = DSLValidator()
        errors = validator.validate(dsl)
        fatal_errors = [e for e in errors if e.severity == "error"]
        if fatal_errors:
            raise DSLCompilationError(fatal_errors)

        # Step 2：构造 TypedDict
        state_schema: dict[str, str] = dsl.get("state_schema", {})
        state_type = build_state_typeddict(state_schema)

        # Step 3：构造 StateGraph
        graph = StateGraph(state_type)

        nodes: list[dict] = dsl.get("nodes", [])
        edges: list[dict] = dsl.get("edges", [])
        node_type_map: dict[str, str] = {n["id"]: n["type"] for n in nodes}

        # Step 4：添加所有节点（占位 executor）
        for node in nodes:
            executor = self._build_node_executor(node)
            graph.add_node(node["id"], executor)

        # Step 5：添加常规 edges（跳过 if_else 节点的 source，它用 conditional_edges）
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            src_type = node_type_map.get(src, "")
            if src_type == "if_else":
                continue  # if_else 的下游通过 add_conditional_edges 处理
            graph.add_edge(src, tgt)

        # Step 6：添加 if_else 的 conditional_edges
        for node in nodes:
            if node.get("type") == "if_else":
                router = self._make_if_else_router(node)
                # 收集所有可能的目标节点（用于 LangGraph conditional_edges 路径声明）
                cfg = node.get("config", {})
                conditions = cfg.get("conditions", [])
                default_target = cfg.get("default_target", "")
                possible_targets = {c.get("target_node_id", "") for c in conditions}
                possible_targets.add(default_target)
                possible_targets.discard("")
                graph.add_conditional_edges(
                    node["id"],
                    router,
                    path_map={t: t for t in possible_targets},
                )

        # Step 7：连接 LangGraph START → start_node 和 end_node → END
        start_nodes = [n for n in nodes if n.get("type") == "start"]
        end_nodes = [n for n in nodes if n.get("type") == "end"]

        if not start_nodes:
            raise ValueError("DSL 中没有 start 节点（应已被 validator 拦截）")
        if not end_nodes:
            raise ValueError("DSL 中没有 end 节点（应已被 validator 拦截）")

        start_id = start_nodes[0]["id"]
        graph.add_edge(START, start_id)

        for end_node in end_nodes:
            graph.add_edge(end_node["id"], END)

        # Step 8：编译（附加 checkpointer）
        compiled_graph = graph.compile(checkpointer=checkpointer)

        return CompiledGraph(
            graph=compiled_graph,
            state_type=state_type,
            dsl=dsl,
        )

    def _build_node_executor(self, node: dict) -> Callable:
        """构造节点 executor（Plan 02-04 接入真实 executor）。

        按节点 type 从 NODE_EXECUTORS 注册表查找 executor 类并实例化。
        未注册的节点类型（如 llm，Plan 02-05 接入）回退到占位 executor。

        Args:
            node: DSL 节点定义 dict

        Returns:
            已实例化的 BaseNodeExecutor 或 placeholder async 函数
        """
        from app.agent_builder.workflow.nodes import NODE_EXECUTORS

        node_type = node.get("type", "unknown")
        executor_cls = NODE_EXECUTORS.get(node_type)

        if executor_cls is not None:
            # 真实 executor：传入节点定义 + 共享 jinja_env
            return executor_cls(node, jinja_env=self._jinja_env)

        # 未注册节点类型（如 llm，Plan 02-05 接入）使用占位 executor
        return self._build_placeholder_executor(node)

    def _build_placeholder_executor(self, node: dict) -> Callable:
        """构造占位 executor（Plan 02-05 接入 llm 节点前的过渡）。

        Args:
            node: DSL 节点定义 dict

        Returns:
            异步函数 placeholder(state) -> dict
        """
        node_id = node["id"]
        node_type = node.get("type", "unknown")

        async def placeholder(state: dict) -> dict:
            """占位 executor：返回占位标识（Plan 02-05 接入真实逻辑）。"""
            return {node_id: {"_placeholder": True, "type": node_type}}

        # 为占位函数设置有意义的名称（便于 LangGraph 日志和调试）
        placeholder.__name__ = f"placeholder_{node_id}"
        placeholder.__qualname__ = f"DSLCompiler._build_placeholder_executor.<locals>.placeholder_{node_id}"

        return placeholder

    def _make_if_else_router(self, node: dict) -> Callable:
        """构造 if_else 节点的路由函数（Plan 02-04 接入真实 IfElseNodeExecutor）。

        使用 IfElseNodeExecutor.resolve_route 进行真实 Jinja2 条件求值：
        1. 按 conditions 顺序评估 Jinja2 expr
        2. 第一个为真的条件 → 返回其 target_node_id
        3. 无条件满足 → 返回 default_target

        Args:
            node: DSL if_else 节点定义 dict

        Returns:
            同步函数 router(state) -> str（返回目标节点 ID）
        """
        from app.agent_builder.workflow.nodes.if_else import IfElseNodeExecutor

        executor = IfElseNodeExecutor(node, jinja_env=self._jinja_env)

        def router(state: dict) -> str:
            """真实路由器：用 IfElseNodeExecutor.resolve_route 评估 Jinja2 条件。"""
            return executor.resolve_route(executor.config, state)

        router.__name__ = f"router_{node.get('id', 'if_else')}"
        return router
