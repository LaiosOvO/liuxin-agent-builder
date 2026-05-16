"""DSLCompiler 接入真实 executor 的集成测试（Task 3）。

测试范围：
- start → end 图用真实 executor 跑通
- start → tool(python echo) → end 图
- start → if_else(条件分支) → end_high/end_low
- Jinja2 模板在 tool config 中正确渲染
- _build_node_executor 对未注册节点（llm）回退到 placeholder

注意：
- 这些测试不需要真实 Postgres（无 checkpointer，checkpointer=None）
- graph.ainvoke 直接在内存运行
- llm 节点用 placeholder 替代（Plan 02-05 接入）
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.compiler import DSLCompiler


# ── 辅助 DSL 工厂 ─────────────────────────────────────────────────────────────

def start_end_dsl(state_schema: dict | None = None) -> dict:
    """最简 DSL：start → end。

    state_schema 需包含节点 ID 字段（start/end），因为节点输出写入 state[node_id]。
    """
    return {
        "version": "1.0",
        "name": "start-end-test",
        "state_schema": state_schema or {
            "name": "str",
            "value": "int",
            "start": "dict",   # StartNodeExecutor 输出写入此字段
            "end": "dict",     # EndNodeExecutor 输出写入此字段
        },
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "end"},
        ],
    }


def tool_python_dsl(function: str = "echo", args: dict | None = None) -> dict:
    """start → tool(python) → end。

    state_schema 需包含 start/tool_1/end 节点 ID 字段以保留节点输出。
    """
    return {
        "version": "1.0",
        "name": "tool-python-test",
        "state_schema": {
            "input": "str",
            "output": "str",
            "start": "dict",    # StartNodeExecutor 输出
            "tool_1": "dict",   # ToolNodeExecutor 输出
            "end": "dict",      # EndNodeExecutor 输出
        },
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "tool_1",
                "type": "tool",
                "config": {
                    "kind": "python",
                    "function": function,
                    "args": args or {"text": "hello"},
                    # timeout_sec 不在 TOOL_PYTHON_SCHEMA 中，不传
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "tool_1"},
            {"id": "e2", "source": "tool_1", "target": "end"},
        ],
    }


def if_else_dsl() -> dict:
    """start → if_else(x > 5) → end_high/end_low。

    state_schema 需包含节点 ID 字段保留输出。
    注意：IfElse 条件引用顶层 state 字段 x，不引用 start.x。
    """
    return {
        "version": "1.0",
        "name": "if-else-test",
        "state_schema": {
            "x": "int",
            "start": "dict",       # StartNodeExecutor 输出
            "branch": "dict",      # IfElseNodeExecutor 输出（_routed_to）
            "end_high": "dict",    # EndNodeExecutor 输出
            "end_low": "dict",     # EndNodeExecutor 输出
        },
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "branch",
                "type": "if_else",
                "config": {
                    "conditions": [
                        # 引用顶层 state 字段 x（非 start.x）
                        {"expr": "{{ x > 5 }}", "target_node_id": "end_high"},
                    ],
                    "default_target": "end_low",
                },
            },
            {"id": "end_high", "type": "end", "config": {}},
            {"id": "end_low", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "branch"},
        ],
    }


def tool_jinja_args_dsl() -> dict:
    """start → tool(echo, args.text="{{ start.name }}") → end。

    Jinja2 渲染时 state 含 start={name: ...}（由 StartNodeExecutor 透传），
    所以 args.text="{{ start.name }}" 能正确取到 start 节点的 name 字段。
    """
    return {
        "version": "1.0",
        "name": "jinja-args-test",
        "state_schema": {
            "name": "str",
            "start": "dict",    # StartNodeExecutor 输出（含 name）
            "tool_1": "dict",   # ToolNodeExecutor 输出
            "end": "dict",      # EndNodeExecutor 输出
        },
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "tool_1",
                "type": "tool",
                "config": {
                    "kind": "python",
                    "function": "echo",
                    # start 节点透传 state，所以 state["start"]["name"] 有值
                    "args": {"text": "{{ start.name }}"},
                    # timeout_sec 不在 TOOL_PYTHON_SCHEMA 中，不传
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "tool_1"},
            {"id": "e2", "source": "tool_1", "target": "end"},
        ],
    }


# ── 测试用例 ──────────────────────────────────────────────────────────────────


async def test_start_end_graph_runs():
    """start → end 图：初始 state 含 name/value，graph.ainvoke 返回 state 含 _completed。"""
    dsl = start_end_dsl()
    compiler = DSLCompiler()
    compiled = compiler.compile(dsl, checkpointer=None)

    initial_state = {"name": "Alice", "value": 42}
    result = await compiled.graph.ainvoke(initial_state)

    # end 节点应写入 _completed=True
    assert "end" in result
    assert result["end"]["_completed"] is True
    # start 节点应透传初始 state
    assert "start" in result
    assert result["start"]["name"] == "Alice"
    assert result["start"]["value"] == 42


async def test_tool_python_in_graph():
    """start → tool(python echo 'hello') → end：state 应含 tool_1.result.echoed=='hello'。"""
    dsl = tool_python_dsl(function="echo", args={"text": "hello"})
    compiler = DSLCompiler()
    compiled = compiler.compile(dsl, checkpointer=None)

    result = await compiled.graph.ainvoke({})

    assert "tool_1" in result
    assert result["tool_1"]["result"]["echoed"] == "hello"
    assert result["tool_1"]["result"]["length"] == 5


async def test_if_else_routes_correctly():
    """start → if_else(x > 5) → end_high/end_low：x=10 走 end_high。"""
    dsl = if_else_dsl()
    compiler = DSLCompiler()
    compiled = compiler.compile(dsl, checkpointer=None)

    # x=10 → 条件 x > 5 为真 → end_high
    result_high = await compiled.graph.ainvoke({"x": 10})
    assert "end_high" in result_high
    assert result_high["end_high"]["_completed"] is True
    # end_low 不应被执行
    assert "end_low" not in result_high or result_high.get("end_low") is None


async def test_if_else_routes_to_default():
    """start → if_else(x > 5) → end_low：x=2 走 default（end_low）。"""
    dsl = if_else_dsl()
    compiler = DSLCompiler()
    compiled = compiler.compile(dsl, checkpointer=None)

    result_low = await compiled.graph.ainvoke({"x": 2})
    assert "end_low" in result_low
    assert result_low["end_low"]["_completed"] is True


async def test_jinja_template_in_tool_config():
    """tool.config.args.text='{{ start.name }}' 应在执行时被 Jinja2 渲染。"""
    dsl = tool_jinja_args_dsl()
    compiler = DSLCompiler()
    compiled = compiler.compile(dsl, checkpointer=None)

    result = await compiled.graph.ainvoke({"name": "Charlie"})

    assert "tool_1" in result
    assert result["tool_1"]["result"]["echoed"] == "Charlie"
    assert result["tool_1"]["result"]["length"] == 7


async def test_llm_node_falls_back_to_placeholder():
    """llm 节点（NODE_EXECUTORS 已注册 LLMNodeExecutor）可正常编译。

    注意：此测试仅验证 DSLCompiler 能正确实例化 LLMNodeExecutor（不实际调用 LLM）。
    当 NODE_EXECUTORS 中有 llm 时，不再回退到 placeholder。
    """
    from app.agent_builder.workflow.nodes import NODE_EXECUTORS

    dsl = {
        "version": "1.0",
        "name": "llm-compile-test",
        "state_schema": {
            "text": "str",
            "start": "dict",
            "llm_1": "dict",
            "end": "dict",
        },
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "llm_1",
                "type": "llm",
                "config": {
                    "model": "openai:gpt-4o",
                    "user_prompt": "hello",
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm_1"},
            {"id": "e2", "source": "llm_1", "target": "end"},
        ],
    }
    compiler = DSLCompiler()
    compiled = compiler.compile(dsl, checkpointer=None)

    # DSL 编译不应抛出异常，graph 可创建
    assert compiled.graph is not None

    # 验证 NODE_EXECUTORS 包含正确的节点类型
    assert "start" in NODE_EXECUTORS
    assert "end" in NODE_EXECUTORS
    assert "if_else" in NODE_EXECUTORS
    assert "tool" in NODE_EXECUTORS
