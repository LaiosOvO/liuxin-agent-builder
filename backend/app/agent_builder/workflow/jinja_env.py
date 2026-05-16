"""Jinja2 沙箱环境模块。

提供：
- build_jinja_env()：构造白名单 filter 的 SandboxedEnvironment
- collect_referenced_variables()：提取模板中顶层变量引用（用于变量悬空检查）
- render_with_state()：使用状态 dict 渲染 Jinja2 模板字符串

安全策略（CONTEXT.md 锁定）：
- 使用 jinja2.sandbox.SandboxedEnvironment（沙箱，不允许访问私有属性和危险方法）
- StrictUndefined：引用未定义变量直接抛异常（而非静默渲染为空字符串）
- 白名单 filter（仅允许 6 个）：tojson / default / lower / upper / length / truncate
- 禁用所有其他内置 filter（清空 env.filters，防止 attr/map 等访问任意属性）
- 禁用所有全局函数（env.globals = {}）
- 注意：循环/块语句（{% for %} / {% if %} 等）在 SandboxedEnvironment 中语法仍可解析，
  但验证器只允许纯插值表达式，执行器应在节点层做额外检查

使用示例：
    env = build_jinja_env()
    result = render_with_state("{{ start.employee_id | upper }}", state, env)
    variables = collect_referenced_variables("{{ a.b }} {{ c }}", env)
    # → {"a", "c"}
"""
from __future__ import annotations

import json
from typing import Any

import jinja2
import jinja2.meta
from jinja2 import sandbox


def _safe_tojson(value: Any) -> str:
    """安全 JSON 序列化，不暴露原始 json.dumps 的完整接口。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def _safe_default(value: Any, default_val: Any = "") -> Any:
    """如果值为 None/Undefined，返回 default_val，否则返回原值。"""
    if value is None:
        return default_val
    return value


def _safe_truncate(value: str, length: int = 80, killwords: bool = False, end: str = "...") -> str:
    """安全截断字符串，超过 length 时加 end 后缀。"""
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= length:
        return value
    if killwords:
        return value[:length] + end
    # 按词截断
    truncated = value[:length]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + end


def build_jinja_env() -> sandbox.SandboxedEnvironment:
    """构造白名单 filter 的 SandboxedEnvironment。

    安全配置：
    - SandboxedEnvironment：沙箱模式，无法访问私有属性（以 _ 开头的方法）
    - StrictUndefined：引用未定义变量直接抛 UndefinedError（不静默）
    - autoescape=False：不自动 HTML 转义（DSL 不是 HTML 模板）
    - env.filters：清空内置 filter，只保留白名单 6 个
    - env.globals：清空所有内置全局函数（range/dict/namespace 等）

    Returns:
        配置好的 SandboxedEnvironment 实例
    """
    env = sandbox.SandboxedEnvironment(
        loader=None,
        autoescape=False,
        undefined=jinja2.StrictUndefined,
    )

    # 清空内置 filter，仅保留白名单
    # 这是关键安全措施：防止 attr/map/select/groupby 等 filter 访问任意对象属性
    safe_filters: dict[str, Any] = {
        "tojson": _safe_tojson,
        "default": _safe_default,
        "lower": str.lower,
        "upper": str.upper,
        "length": len,
        "truncate": _safe_truncate,
    }
    env.filters = safe_filters

    # 清空内置全局函数（range / namespace / dict 等不暴露给模板）
    env.globals = {}

    return env


def collect_referenced_variables(
    template_str: str,
    env: sandbox.SandboxedEnvironment | None = None,
) -> set[str]:
    """提取 Jinja2 模板中的顶层变量引用集合。

    使用 jinja2.meta.find_undeclared_variables 提取模板 AST 中所有未声明变量。
    对于 {{ x.y.z }}，返回顶层变量名 "x"（不含 ".y.z" 路径）。

    Args:
        template_str: Jinja2 模板字符串（如 "{{ start.employee_id }}"）
        env: SandboxedEnvironment 实例，None 时自动创建

    Returns:
        顶层变量名集合（如 {"start", "state_var"}）

    Example:
        >>> collect_referenced_variables("{{ a.b }} {{ c | upper }}")
        {"a", "c"}
    """
    if env is None:
        env = build_jinja_env()
    ast = env.parse(template_str)
    return jinja2.meta.find_undeclared_variables(ast)


def render_with_state(
    template_str: str,
    state: dict[str, Any],
    env: sandbox.SandboxedEnvironment | None = None,
) -> str:
    """使用状态 dict 渲染 Jinja2 模板字符串。

    Args:
        template_str: Jinja2 模板字符串（如 "{{ start.employee_id | upper }}"）
        state: 状态 dict，键为节点 ID 或 state_schema 字段名
        env: SandboxedEnvironment 实例，None 时自动创建

    Returns:
        渲染后的字符串

    Raises:
        jinja2.UndefinedError: 引用未定义变量（StrictUndefined）
        jinja2.TemplateSyntaxError: 模板语法错误
        jinja2.TemplateAssertionError: 使用未知 filter

    Example:
        >>> state = {"start": {"employee_id": "EMP001"}}
        >>> render_with_state("{{ start.employee_id }}", state)
        "EMP001"
    """
    if env is None:
        env = build_jinja_env()
    template = env.from_string(template_str)
    return template.render(**state)
