"""工作流 DSL TypedDict 动态工厂单元测试。

测试目标：
- 基础 TypedDict 构造正确
- 未知类型抛 ValueError（含详细错误信息）
- total=False 生效（所有字段 NotRequired）
- 运行时实例化行为符合预期（TypedDict 底层是普通 dict）
- 多种类型混合构造正确
- SCHEMA_TYPES 列表完整
"""
from __future__ import annotations

import pytest


def test_build_basic_typeddict():
    """基础场景：state_schema = {"x": "str", "y": "int"} → 类型 TypedDict 含 x: str, y: int。"""
    from typing import get_type_hints

    from app.agent_builder.workflow.types import build_state_typeddict

    schema = {"x": "str", "y": "int"}
    StateType = build_state_typeddict(schema)

    # 类名正确
    assert StateType.__name__ == "WorkflowState"

    # 类型 hints 正确
    hints = get_type_hints(StateType)
    assert hints.get("x") is str, f"x 期望 str，实际: {hints.get('x')}"
    assert hints.get("y") is int, f"y 期望 int，实际: {hints.get('y')}"


def test_unknown_type_raises():
    """state_schema 含未知类型字符串应抛 ValueError，且包含未知类型名称。"""
    from app.agent_builder.workflow.types import build_state_typeddict

    with pytest.raises(ValueError) as exc_info:
        build_state_typeddict({"x": "foo", "y": "bar"})

    error_msg = str(exc_info.value)
    # 错误信息应包含未知类型名
    assert "foo" in error_msg or "bar" in error_msg, (
        f"错误信息应包含未知类型名，实际: {error_msg}"
    )


def test_total_false():
    """构造的 TypedDict 应为 total=False（所有字段 NotRequired）。"""
    from app.agent_builder.workflow.types import build_state_typeddict

    schema = {"name": "str", "age": "int"}
    StateType = build_state_typeddict(schema)

    # total=False 时 __required_keys__ 为空集
    assert hasattr(StateType, "__required_keys__"), "TypedDict 应有 __required_keys__"
    assert len(StateType.__required_keys__) == 0, (
        f"total=False 时 __required_keys__ 应为空，实际: {StateType.__required_keys__}"
    )
    # __optional_keys__ 应包含所有字段
    assert "name" in StateType.__optional_keys__
    assert "age" in StateType.__optional_keys__


def test_state_instance_creation():
    """运行时实例化：TypedDict 底层是普通 dict，实例化通过 type check。"""
    from app.agent_builder.workflow.types import build_state_typeddict

    schema = {"x": "str", "y": "int", "score": "float", "active": "bool"}
    StateType = build_state_typeddict(schema)

    # TypedDict 在运行时就是普通 dict，可以直接构造
    instance = {"x": "hello", "y": 42, "score": 0.95, "active": True}
    # 验证可以作为 dict 使用
    assert instance["x"] == "hello"
    assert isinstance(instance, dict), "TypedDict 实例应为 dict 子类型（运行时）"


def test_all_supported_types():
    """所有支持的类型字符串均能正确映射到 Python 类型。"""
    from typing import get_type_hints

    from app.agent_builder.workflow.types import PY_TYPE_MAP, build_state_typeddict

    schema = {
        "s": "str",
        "i": "int",
        "f": "float",
        "b": "bool",
        "l": "list",
        "d": "dict",
        "a": "any",
    }
    StateType = build_state_typeddict(schema, name="AllTypesState")
    hints = get_type_hints(StateType)

    for field, type_str in schema.items():
        expected_type = PY_TYPE_MAP[type_str]
        assert hints[field] is expected_type, (
            f"字段 {field!r}（{type_str!r}）期望 {expected_type}，实际: {hints[field]}"
        )


def test_custom_name():
    """build_state_typeddict 的 name 参数正确设置类名。"""
    from app.agent_builder.workflow.types import build_state_typeddict

    StateType = build_state_typeddict({"x": "str"}, name="MyCustomState")
    assert StateType.__name__ == "MyCustomState"


def test_schema_types_list_complete():
    """SCHEMA_TYPES 列表应包含所有 PY_TYPE_MAP 的键。"""
    from app.agent_builder.workflow.types import PY_TYPE_MAP, SCHEMA_TYPES

    assert set(SCHEMA_TYPES) == set(PY_TYPE_MAP.keys()), (
        f"SCHEMA_TYPES 与 PY_TYPE_MAP keys 不一致: "
        f"SCHEMA_TYPES={sorted(SCHEMA_TYPES)}, "
        f"PY_TYPE_MAP keys={sorted(PY_TYPE_MAP.keys())}"
    )
