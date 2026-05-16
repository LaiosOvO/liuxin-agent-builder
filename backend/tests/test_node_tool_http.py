"""Tool 节点 HTTP 模式单元测试（使用 pytest-httpx 模拟 httpx 请求）。

测试范围：
- GET/POST 请求正常响应
- Jinja2 URL 模板渲染
- 4xx/5xx 重试耗尽后抛出 NodeExecutionError
- 5xx 第 1 次失败第 2 次成功（重试成功）
- 超时场景（模拟 httpx.TimeoutException）

注意：pytest-httpx 0.35+ 的 API：
- `respx_mock` fixture → 使用 `httpx_mock` fixture（pytest-httpx 提供）
- httpx_mock.add_response(method=..., url=..., status_code=..., json=...)
"""
from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from app.agent_builder.workflow.nodes.base import NodeExecutionError
from app.agent_builder.workflow.nodes.tool import ToolNodeExecutor


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def make_http_tool_node(
    url: str = "https://api.example.com/data",
    method: str = "GET",
    headers: dict | None = None,
    body: dict | str | None = None,
    retry_count: int = 0,
    timeout_sec: int = 5,
) -> dict:
    """构造 HTTP tool 节点定义。"""
    return {
        "id": "tool_1",
        "type": "tool",
        "config": {
            "kind": "http",
            "method": method,
            "url": url,
            "headers": headers or {},
            "body": body,
            "retry_count": retry_count,
            "timeout_sec": timeout_sec,
        },
    }


# ── HTTP GET 成功 ──────────────────────────────────────────────────────────────


async def test_http_get_success(httpx_mock: HTTPXMock):
    """HTTP GET 请求成功时应返回 output/status_code/headers。"""
    httpx_mock.add_response(
        method="GET",
        url="https://api.example.com/data",
        status_code=200,
        json={"result": "ok", "count": 3},
    )
    executor = ToolNodeExecutor(make_http_tool_node())
    state: dict = {}
    result = await executor(state)
    assert "tool_1" in result
    output = result["tool_1"]
    assert output["status_code"] == 200
    assert output["output"]["result"] == "ok"
    assert output["output"]["count"] == 3
    assert "headers" in output


# ── HTTP POST JSON body ────────────────────────────────────────────────────────


async def test_http_post_json_body(httpx_mock: HTTPXMock):
    """HTTP POST 请求带 JSON body 应正确发送并返回响应。"""
    httpx_mock.add_response(
        method="POST",
        url="https://api.example.com/submit",
        status_code=201,
        json={"id": 42, "created": True},
    )
    node = make_http_tool_node(
        url="https://api.example.com/submit",
        method="POST",
        body={"name": "Alice", "email": "alice@example.com"},
    )
    executor = ToolNodeExecutor(node)
    state: dict = {}
    result = await executor(state)
    assert result["tool_1"]["status_code"] == 201
    assert result["tool_1"]["output"]["id"] == 42


# ── Jinja2 URL 渲染 ────────────────────────────────────────────────────────────


async def test_http_jinja_url_substitution(httpx_mock: HTTPXMock):
    """URL 中 `{{ start.id }}` 应被 Jinja2 渲染为实际值后发送请求。"""
    httpx_mock.add_response(
        method="GET",
        url="https://api.example.com/users/123",
        status_code=200,
        json={"user_id": 123, "name": "Bob"},
    )
    node = make_http_tool_node(url="https://api.example.com/users/{{ start.id }}")
    executor = ToolNodeExecutor(node)
    state = {"start": {"id": "123"}}
    result = await executor(state)
    assert result["tool_1"]["status_code"] == 200
    assert result["tool_1"]["output"]["user_id"] == 123


# ── 4xx/5xx 重试耗尽 ────────────────────────────────────────────────────────────


async def test_http_5xx_raises_after_retries(httpx_mock: HTTPXMock):
    """服务端 500 错误，重试耗尽后应抛出 NodeExecutionError。"""
    # 重试 2 次，共 3 次请求，全部返回 500
    for _ in range(3):
        httpx_mock.add_response(
            method="GET",
            url="https://api.example.com/data",
            status_code=500,
            json={"error": "internal"},
        )
    node = make_http_tool_node(retry_count=2)
    executor = ToolNodeExecutor(node)
    state: dict = {}
    with pytest.raises(NodeExecutionError) as exc_info:
        await executor(state)
    assert exc_info.value.node_id == "tool_1"


# ── 5xx 第 1 次失败第 2 次成功（重试成功）──────────────────────────────────────


async def test_http_5xx_retried_success(httpx_mock: HTTPXMock):
    """第 1 次返回 500，第 2 次返回 200，重试后应成功。"""
    httpx_mock.add_response(
        method="GET",
        url="https://api.example.com/data",
        status_code=500,
        json={"error": "temporary"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.example.com/data",
        status_code=200,
        json={"ok": True},
    )
    node = make_http_tool_node(retry_count=2)
    executor = ToolNodeExecutor(node)
    state: dict = {}
    result = await executor(state)
    assert result["tool_1"]["status_code"] == 200
    assert result["tool_1"]["output"]["ok"] is True


# ── 超时场景 ────────────────────────────────────────────────────────────────────


async def test_http_timeout_raises(httpx_mock: HTTPXMock):
    """HTTP 超时（ConnectTimeout）应抛出 NodeExecutionError。"""
    import httpx as _httpx
    httpx_mock.add_exception(
        _httpx.ConnectTimeout("Connection timed out"),
        method="GET",
        url="https://api.example.com/data",
    )
    # retry_count=0 直接失败不重试
    node = make_http_tool_node(retry_count=0)
    executor = ToolNodeExecutor(node)
    state: dict = {}
    with pytest.raises(NodeExecutionError) as exc_info:
        await executor(state)
    assert exc_info.value.node_id == "tool_1"
