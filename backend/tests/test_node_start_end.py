"""Start/End 节点 executor 单元测试 + tool_registry 测试。

测试范围：
- StartNodeExecutor：透传 state、空 state 场景
- EndNodeExecutor：返回完成标记
- register_tool 装饰器：注册/查找/重复注册/非法名称
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.nodes.end import EndNodeExecutor
from app.agent_builder.workflow.nodes.start import StartNodeExecutor


# ── 辅助构造 node_def ──────────────────────────────────────────────────────────

def make_start_node(node_id: str = "start") -> dict:
    return {"id": node_id, "type": "start", "config": {}}


def make_end_node(node_id: str = "end") -> dict:
    return {"id": node_id, "type": "end", "config": {}}


# ── StartNodeExecutor 测试 ─────────────────────────────────────────────────────


async def test_start_executor_passes_state_through():
    """Start 节点应将整个 state 透传到 node output。"""
    executor = StartNodeExecutor(make_start_node())
    state = {"name": "Alice", "age": 30, "tags": ["a", "b"]}
    result = await executor(state)
    # __call__ 返回 {node_id: execute_result}
    assert "start" in result
    output = result["start"]
    assert output["name"] == "Alice"
    assert output["age"] == 30
    assert output["tags"] == ["a", "b"]


async def test_start_executor_with_empty_state():
    """Start 节点对空 state 应返回空 dict。"""
    executor = StartNodeExecutor(make_start_node())
    state: dict = {}
    result = await executor(state)
    assert "start" in result
    assert result["start"] == {}


async def test_start_executor_does_not_mutate_state():
    """Start 节点应返回 state 副本，不修改原始 state。"""
    executor = StartNodeExecutor(make_start_node())
    state = {"key": "value"}
    result = await executor(state)
    output = result["start"]
    # 修改输出不影响原 state
    output["new_key"] = "new_value"
    assert "new_key" not in state


async def test_start_executor_custom_node_id():
    """Start 节点应使用自定义 node_id 作为输出 key。"""
    executor = StartNodeExecutor(make_start_node(node_id="start_node_1"))
    state = {"x": 42}
    result = await executor(state)
    assert "start_node_1" in result
    assert result["start_node_1"]["x"] == 42


# ── EndNodeExecutor 测试 ───────────────────────────────────────────────────────


async def test_end_executor_returns_completion_marker():
    """End 节点应返回 _completed=True 标记。"""
    executor = EndNodeExecutor(make_end_node())
    state = {"start": {"name": "Bob"}}
    result = await executor(state)
    assert "end" in result
    assert result["end"]["_completed"] is True


async def test_end_executor_does_not_modify_other_state():
    """End 节点不应修改 state 中其他字段。"""
    executor = EndNodeExecutor(make_end_node())
    state = {"start": {"value": 100}, "existing_key": "should_stay"}
    result = await executor(state)
    # 只有 end 节点的 output
    assert set(result.keys()) == {"end"}
    assert result["end"]["_completed"] is True


# ── tool_registry 测试 ────────────────────────────────────────────────────────


def test_register_tool_decorator():
    """@register_tool 应能成功注册并从 TOOL_REGISTRY 查找。"""
    from app.agent_builder.workflow import tool_registry as tr

    # 使用唯一名称避免与其他测试冲突
    tool_name = "test_tool_lookup_unique_xyz123"
    # 清理（如果存在）
    tr.TOOL_REGISTRY.pop(tool_name, None)

    @tr.register_tool(tool_name)
    async def my_tool(*, x: int) -> dict:
        return {"result": x * 2}

    found = tr.get_registered_tool(tool_name)
    assert found is my_tool

    # 清理测试注册
    del tr.TOOL_REGISTRY[tool_name]


def test_register_tool_duplicate_raises():
    """重复注册同名 tool 应抛出 ValueError。"""
    from app.agent_builder.workflow import tool_registry as tr

    tool_name = "test_duplicate_tool_unique_abc456"
    tr.TOOL_REGISTRY.pop(tool_name, None)

    @tr.register_tool(tool_name)
    async def first(_: int = 0) -> dict:
        return {}

    with pytest.raises(ValueError, match="已注册"):
        @tr.register_tool(tool_name)
        async def second(_: int = 0) -> dict:
            return {}

    # 清理
    del tr.TOOL_REGISTRY[tool_name]


def test_register_tool_invalid_name():
    """包含非法字符的 tool 名应抛出 ValueError。"""
    from app.agent_builder.workflow import tool_registry as tr

    with pytest.raises(ValueError, match="非法 tool 名"):
        @tr.register_tool("invalid-name!")
        async def fn() -> dict:
            return {}


def test_get_registered_tool_returns_none_for_unknown():
    """查找未注册的 tool 应返回 None。"""
    from app.agent_builder.workflow.tool_registry import get_registered_tool
    result = get_registered_tool("nonexistent_tool_xyz_99999")
    assert result is None


async def test_builtin_echo_tool_works():
    """内置 echo tool 应正确执行。"""
    from app.agent_builder.workflow.tool_registry import get_registered_tool
    echo = get_registered_tool("echo")
    assert echo is not None
    result = await echo(text="hello")
    assert result["echoed"] == "hello"
    assert result["length"] == 5


async def test_builtin_uppercase_tool_works():
    """内置 uppercase tool 应正确执行。"""
    from app.agent_builder.workflow.tool_registry import get_registered_tool
    uppercase = get_registered_tool("uppercase")
    assert uppercase is not None
    result = await uppercase(text="hello world")
    assert result["result"] == "HELLO WORLD"
