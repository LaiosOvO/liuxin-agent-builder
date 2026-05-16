"""Tool 节点 executor（HTTP + Python function 双模式）。

ToolNodeExecutor 支持两种 tool 执行模式：

1. **HTTP 模式** (`kind: "http"`)：
   - method/url/headers/body 全部支持 Jinja2 模板
   - 使用 httpx.AsyncClient 执行 HTTP 请求
   - 支持 tenacity 重试（httpx.RequestError / TimeoutException / HTTPStatusError）
   - 返回：{"output": body, "status_code": code, "headers": dict}

2. **Python function 模式** (`kind: "python"`)：
   - 从 TOOL_REGISTRY 查找已注册的 async function
   - 使用 Jinja2 渲染后的 args dict 作为 kwargs 调用
   - 返回：{"result": fn_return_value}

DSL config 格式（HTTP 模式）：
    {
        "kind": "http",
        "method": "GET",
        "url": "https://api.example.com/{{ start.user_id }}",
        "headers": {"Authorization": "Bearer {{ start.token }}"},
        "body": null,
        "retry_count": 2,
        "timeout_sec": 10
    }

DSL config 格式（Python 模式）：
    {
        "kind": "python",
        "function": "echo",
        "args": {"text": "{{ start.message }}"},
        "retry_count": 0,
        "timeout_sec": 30
    }

设计参考（Dify 阅读笔记 docs/reading-dify-02-04-base-nodes-2026-05-16.md）：
- Dify Tool 节点需要 DifyToolNodeRuntime（OAuth认证、文件管理）
- 我们 v1 轻量版：HTTP 用 httpx，Python 用 TOOL_REGISTRY 注册表
- Phase 6 插件机制将扩展为沙箱执行，接口与 TOOL_REGISTRY 兼容
"""
from __future__ import annotations

from typing import Any

import httpx

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor, NodeExecutionError
from app.agent_builder.workflow.tool_registry import get_registered_tool


class ToolNodeExecutor(BaseNodeExecutor):
    """Tool 节点执行器（HTTP + Python function 双模式）。

    默认重试 2 次、超时 10 秒，可通过节点 config 覆盖。
    HTTP 模式下 httpx.RequestError / TimeoutException / HTTPStatusError 触发重试。
    """

    def _default_retry_count(self) -> int:
        """Tool 节点默认重试 2 次。"""
        return 2

    def _default_timeout(self) -> int:
        """Tool 节点默认超时 10 秒。"""
        return 10

    def _retryable_exceptions(self) -> tuple[type[Exception], ...]:
        """HTTP 相关异常触发重试。"""
        return (
            httpx.RequestError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
        )

    async def execute(self, config: dict, state: dict) -> dict:
        """根据 config.kind 分发到对应执行模式。

        Args:
            config: 渲染后的节点配置
            state: 当前 state dict

        Returns:
            HTTP 模式：{"output": body, "status_code": code, "headers": dict}
            Python 模式：{"result": fn_return_value}

        Raises:
            NodeExecutionError: kind 不支持、HTTP 失败、tool 未注册等
        """
        kind: str = config.get("kind", "")
        if kind == "http":
            return await self._exec_http(config, state)
        if kind == "python":
            return await self._exec_python(config, state)
        raise NodeExecutionError(
            self.node_id,
            f"不支持的 tool kind: '{kind}'（仅支持 'http' 和 'python'）",
        )

    async def _exec_http(self, config: dict, state: dict) -> dict:
        """执行 HTTP 请求。

        Args:
            config: 渲染后的 HTTP 配置
            state: 当前 state dict

        Returns:
            {"output": response_body, "status_code": int, "headers": dict}

        Raises:
            httpx.HTTPStatusError: 4xx/5xx 响应（触发重试）
        """
        method: str = config["method"].upper()
        url: str = config["url"]
        headers: dict = config.get("headers", {}) or {}
        body: Any = config.get("body")
        timeout_sec: float = float(config.get("timeout_sec", self._default_timeout()))

        # 判断 body 类型：dict/list → json，str → data，None → 不传
        json_body: dict | list | None = None
        data_body: str | None = None
        if isinstance(body, (dict, list)):
            json_body = body
        elif isinstance(body, str):
            data_body = body

        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                data=data_body,
            )
            response.raise_for_status()

            # 尝试解析 JSON，失败则返回纯文本
            try:
                response_body: Any = response.json()
            except ValueError:
                response_body = response.text

            return {
                "output": response_body,
                "status_code": response.status_code,
                "headers": dict(response.headers),
            }

    async def _exec_python(self, config: dict, state: dict) -> dict:
        """执行已注册的 Python async function。

        Args:
            config: 渲染后的 Python 配置（含 function 名和 args）
            state: 当前 state dict

        Returns:
            {"result": fn_return_value}

        Raises:
            NodeExecutionError: tool 未注册
        """
        fn_name: str = config["function"]
        fn = get_registered_tool(fn_name)
        if fn is None:
            raise NodeExecutionError(
                self.node_id,
                f"Tool '{fn_name}' 未注册，请先用 @register_tool('{fn_name}') 注册",
            )
        args: dict = config.get("args", {}) or {}
        result = await fn(**args)
        return {"result": result}
