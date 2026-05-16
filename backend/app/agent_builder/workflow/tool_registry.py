"""Tool 注册表模块。

提供：
- TOOL_REGISTRY：全局 async function 注册表
- register_tool(name)：装饰器，注册 async function 为可调用 tool
- get_registered_tool(name)：按名查找已注册 tool

内置 demo 工具（用于 E2E 和测试）：
- echo：原样返回文本 + 长度
- uppercase：将文本转大写

Tool 命名规则：仅允许字母、数字、下划线、点（`^[a-z0-9_.]+$` 语义）。

设计参考（Dify 阅读笔记 docs/reading-dify-02-04-base-nodes-2026-05-16.md）：
- Dify Tool 节点需要重量级 DifyToolNodeRuntime（OAuth、文件管理）
- 我们 v1 用轻量注册表：仅支持纯 Python async function，参数通过 kwargs 传入
- Phase 6 插件机制将沿用相同注册接口扩展为沙箱执行
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# 全局 tool 注册表：tool 名 → async callable
TOOL_REGISTRY: dict[str, Callable[..., Awaitable[Any]]] = {}


def register_tool(name: str) -> Callable:
    """装饰器：注册一个 async function 为可调用 tool。

    Args:
        name: tool 名称，仅允许字母/数字/下划线/点

    Returns:
        装饰器函数

    Raises:
        ValueError: tool 名不合法或已被注册

    Example:
        @register_tool("echo")
        async def echo(*, text: str) -> dict:
            return {"echoed": text}
    """
    # 验证命名规则：仅允许字母数字下划线点
    if not name.replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"非法 tool 名: '{name}'（仅允许字母/数字/下划线/点）")

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if name in TOOL_REGISTRY:
            raise ValueError(f"Tool '{name}' 已注册，请勿重复注册")
        TOOL_REGISTRY[name] = fn
        return fn

    return decorator


def get_registered_tool(name: str) -> Callable[..., Awaitable[Any]] | None:
    """按名查找已注册 tool。

    Args:
        name: tool 名称

    Returns:
        已注册的 async callable，未找到时返回 None
    """
    return TOOL_REGISTRY.get(name)


# ── 内置 demo 工具（用于 E2E 测试和快速体验）──────────────────────────────────────


@register_tool("echo")
async def echo(*, text: str) -> dict:
    """原样返回文本并附加长度信息。

    Args:
        text: 输入文本

    Returns:
        {"echoed": text, "length": len(text)}
    """
    return {"echoed": text, "length": len(text)}


@register_tool("uppercase")
async def uppercase(*, text: str) -> dict:
    """将文本转大写。

    Args:
        text: 输入文本

    Returns:
        {"result": text.upper()}
    """
    return {"result": text.upper()}
