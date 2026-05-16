"""IfElse 节点 executor 单元测试。

测试范围：
- 路由逻辑：默认路由、条件匹配、Jinja2 表达式求值（truthy/falsy）
- 边界情况：expr 求值异常跳过、多条件顺序匹配
- execute() 返回 _routed_to 标记
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.nodes.if_else import IfElseNodeExecutor


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def make_if_else_node(conditions: list[dict], default_target: str = "end") -> dict:
    """构造 IfElse 节点定义。"""
    return {
        "id": "if_else_1",
        "type": "if_else",
        "config": {
            "conditions": conditions,
            "default_target": default_target,
        },
    }


# ── 路由逻辑测试 ───────────────────────────────────────────────────────────────


async def test_if_else_routes_to_default_when_no_match():
    """当所有条件不匹配时，应路由到 default_target。"""
    node = make_if_else_node(
        conditions=[
            {"expr": "{{ False }}", "target_node_id": "node_a"},
        ],
        default_target="default_end",
    )
    executor = IfElseNodeExecutor(node)
    state = {}
    # resolve_route 使用原始 config（self.config），不使用 _render_config 结果
    target = executor.resolve_route(executor.config, state)
    assert target == "default_end"


async def test_if_else_routes_to_first_matching_condition():
    """当第一个条件匹配时，应路由到该 target_node_id。"""
    node = make_if_else_node(
        conditions=[
            {"expr": "{{ True }}", "target_node_id": "node_match"},
            {"expr": "{{ True }}", "target_node_id": "node_second"},
        ],
        default_target="default",
    )
    executor = IfElseNodeExecutor(node)
    state = {}
    target = executor.resolve_route(executor.config, state)
    # 应该匹配第一个
    assert target == "node_match"


async def test_if_else_jinja_expr_truthy():
    """Jinja2 表达式 `{{ x > 5 }}` 当 x=10 时应为 truthy。"""
    node = make_if_else_node(
        conditions=[
            {"expr": "{{ x > 5 }}", "target_node_id": "high"},
        ],
        default_target="low",
    )
    executor = IfElseNodeExecutor(node)
    state = {"x": 10}
    target = executor.resolve_route(executor.config, state)
    assert target == "high"


async def test_if_else_jinja_expr_falsy():
    """Jinja2 表达式 `{{ x > 5 }}` 当 x=1 时应为 falsy，走 default。"""
    node = make_if_else_node(
        conditions=[
            {"expr": "{{ x > 5 }}", "target_node_id": "high"},
        ],
        default_target="low",
    )
    executor = IfElseNodeExecutor(node)
    state = {"x": 1}
    target = executor.resolve_route(executor.config, state)
    assert target == "low"


async def test_if_else_invalid_expr_skips_condition():
    """expr 求值失败（变量未定义）时，应跳过该 condition，继续检查下一条。"""
    node = make_if_else_node(
        conditions=[
            # 引用未定义变量，会抛 UndefinedError → 跳过
            {"expr": "{{ undefined_var > 5 }}", "target_node_id": "unreachable"},
            {"expr": "{{ True }}", "target_node_id": "reachable"},
        ],
        default_target="default",
    )
    executor = IfElseNodeExecutor(node)
    state = {}
    # resolve_route 使用原始 config，跳过求值失败的 expr
    target = executor.resolve_route(executor.config, state)
    # 第一个 condition 跳过（undefined 变量），第二个 True 匹配
    assert target == "reachable"


async def test_if_else_execute_returns_routed_to_marker():
    """execute() 应返回包含 _routed_to 字段的 dict。"""
    node = make_if_else_node(
        conditions=[
            {"expr": "{{ True }}", "target_node_id": "node_a"},
        ],
        default_target="end",
    )
    executor = IfElseNodeExecutor(node)
    state = {}
    # __call__ 返回 {node_id: result}
    result = await executor(state)
    assert "if_else_1" in result
    inner = result["if_else_1"]
    assert "_routed_to" in inner
    assert inner["_routed_to"] == "node_a"


async def test_if_else_multiple_conditions_sequential():
    """多个条件时，应按顺序求值，返回第一个 truthy 的目标。"""
    node = make_if_else_node(
        conditions=[
            {"expr": "{{ x < 0 }}", "target_node_id": "negative"},
            {"expr": "{{ x == 0 }}", "target_node_id": "zero"},
            {"expr": "{{ x > 0 }}", "target_node_id": "positive"},
        ],
        default_target="unknown",
    )
    executor = IfElseNodeExecutor(node)

    for x_val, expected in [(-5, "negative"), (0, "zero"), (7, "positive")]:
        state = {"x": x_val}
        assert executor.resolve_route(executor.config, state) == expected


async def test_if_else_string_equality_condition():
    """字符串相等条件 `{{ status == 'active' }}`。"""
    node = make_if_else_node(
        conditions=[
            {"expr": "{{ status == 'active' }}", "target_node_id": "active_branch"},
        ],
        default_target="inactive_branch",
    )
    executor = IfElseNodeExecutor(node)

    state_active = {"status": "active"}
    assert executor.resolve_route(executor.config, state_active) == "active_branch"

    state_inactive = {"status": "disabled"}
    assert executor.resolve_route(executor.config, state_inactive) == "inactive_branch"
