"""工作流 DSL 状态类型工厂模块。

提供：
- PY_TYPE_MAP：DSL 类型字符串 → Python 类型映射表
- SCHEMA_TYPES：支持的类型字符串列表
- build_state_typeddict()：从 DSL state_schema 动态构造 TypedDict 类

设计决策（CONTEXT.md 锁定）：
- 使用 TypedDict（不用 Pydantic v2，与 LangGraph 1.x 兼容性更好）
- 运行时从 DSL state_schema 字段（{"field_name": "str"} 格式）动态生成
- total=False 使所有字段变为 NotRequired（允许部分更新，LangGraph 最佳实践）

示例：
    schema = {"employee_id": "str", "score": "float", "approved": "bool"}
    StateType = build_state_typeddict(schema)
    # 等价于：
    # class StateType(TypedDict, total=False):
    #     employee_id: str
    #     score: float
    #     approved: bool
"""
from __future__ import annotations

from typing import TypedDict

# DSL 类型字符串 → Python 类型映射
# 对应 DSL state_schema 字段中允许的值
PY_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "any": object,  # 兜底类型，等价于 Any（TypedDict 用 object 近似）
}

# 支持的类型字符串列表（公共常量，用于 DSL 校验器）
SCHEMA_TYPES: list[str] = list(PY_TYPE_MAP.keys())


def build_state_typeddict(
    state_schema: dict[str, str],
    name: str = "WorkflowState",
) -> type:
    """从 DSL state_schema 动态构造 TypedDict 类。

    Args:
        state_schema: DSL 中的 state_schema 字段，格式为：
            {"field_name": "str" | "int" | "float" | "bool" | "list" | "dict" | "any"}
        name: 生成的 TypedDict 类名（默认 "WorkflowState"）

    Returns:
        一个 TypedDict 子类，total=False（所有字段 NotRequired）。
        可直接传给 LangGraph StateGraph 作为 StateType 参数。

    Raises:
        ValueError: state_schema 中包含 PY_TYPE_MAP 不支持的类型字符串

    Example:
        >>> StateType = build_state_typeddict({"x": "str", "count": "int"})
        >>> app = StateGraph(StateType)
    """
    # 校验：收集所有未知类型，一次性报错（不要报一个才发现下一个）
    unknown = [
        f"{field!r}: {type_str!r}"
        for field, type_str in state_schema.items()
        if type_str not in PY_TYPE_MAP
    ]
    if unknown:
        raise ValueError(
            f"state_schema 包含未知类型：{unknown}。"
            f"支持的类型：{SCHEMA_TYPES}"
        )

    # 构造字段 dict：{"field_name": Python_type}
    fields: dict[str, type] = {
        field: PY_TYPE_MAP[type_str]
        for field, type_str in state_schema.items()
    }

    # 动态创建 TypedDict 类（total=False 使所有字段为 NotRequired）
    # type: ignore[misc] — TypedDict() 动态调用 mypy 无法静态推断
    return TypedDict(name, fields, total=False)  # type: ignore[misc]
