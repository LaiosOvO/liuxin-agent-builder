"""Tool 节点 Python function 模式单元测试。

测试范围：
- 调用已注册的 echo/uppercase 工具
- args 参数正确传递
- function 未注册时抛出 NodeExecutionError
- Jinja2 args 渲染（args.text = "{{ start.name }}"）
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.nodes.base import NodeExecutionError
from app.agent_builder.workflow.nodes.tool import ToolNodeExecutor


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def make_python_tool_node(
    function: str = "echo",
    args: dict | None = None,
    retry_count: int = 0,
) -> dict:
    """构造 Python function tool 节点定义。"""
    return {
        "id": "tool_py_1",
        "type": "tool",
        "config": {
            "kind": "python",
            "function": function,
            "args": args or {},
            "retry_count": retry_count,
            "timeout_sec": 10,
        },
    }


# ── 基础调用测试 ───────────────────────────────────────────────────────────────


async def test_python_tool_lookup():
    """调用内置 echo 工具，应正确返回 echoed 字段。"""
    node = make_python_tool_node(function="echo", args={"text": "hello"})
    executor = ToolNodeExecutor(node)
    state: dict = {}
    result = await executor(state)
    assert "tool_py_1" in result
    inner = result["tool_py_1"]
    assert "result" in inner
    assert inner["result"]["echoed"] == "hello"
    assert inner["result"]["length"] == 5


async def test_python_tool_args_passed_correctly():
    """调用 uppercase 工具，args 应完整传递。"""
    node = make_python_tool_node(function="uppercase", args={"text": "hello world"})
    executor = ToolNodeExecutor(node)
    state: dict = {}
    result = await executor(state)
    inner = result["tool_py_1"]
    assert inner["result"]["result"] == "HELLO WORLD"


async def test_python_tool_not_found_raises():
    """function="nonexistent" 时应抛出 NodeExecutionError（tool 未注册）。"""
    node = make_python_tool_node(function="nonexistent_tool_xyz_99999")
    executor = ToolNodeExecutor(node)
    state: dict = {}
    with pytest.raises(NodeExecutionError) as exc_info:
        await executor(state)
    assert exc_info.value.node_id == "tool_py_1"
    assert "未注册" in exc_info.value.message


async def test_python_tool_jinja_args():
    """args.text = '{{ start.name }}' 应被 Jinja2 渲染后传给 tool。"""
    node = make_python_tool_node(
        function="echo",
        args={"text": "{{ start.name }}"},
    )
    executor = ToolNodeExecutor(node)
    state = {"start": {"name": "Charlie"}}
    result = await executor(state)
    inner = result["tool_py_1"]
    assert inner["result"]["echoed"] == "Charlie"
    assert inner["result"]["length"] == 7


async def test_python_tool_custom_registered():
    """自定义注册 tool 应能被正确调用。"""
    from app.agent_builder.workflow import tool_registry as tr

    tool_name = "test_custom_tool_unique_task2_abc"
    tr.TOOL_REGISTRY.pop(tool_name, None)

    @tr.register_tool(tool_name)
    async def multiply(*, a: int, b: int) -> dict:
        return {"product": a * b}

    try:
        node = make_python_tool_node(function=tool_name, args={"a": 3, "b": 7})
        executor = ToolNodeExecutor(node)
        state: dict = {}
        result = await executor(state)
        assert result["tool_py_1"]["result"]["product"] == 21
    finally:
        # 清理测试注册
        tr.TOOL_REGISTRY.pop(tool_name, None)
