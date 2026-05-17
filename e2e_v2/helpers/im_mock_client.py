"""IM Mock Provider 客户端 — 通过 GET /api/test/im_mock_calls 拉取 mock 调用记录。

设计：
- spec 不直接 import backend 模块（避免 ASGI 循环依赖）
- 通过 HTTP endpoint 跟运行中的 backend 通信（与真实生产部署一致）
- 必须 backend 启动时 ENABLE_TEST_API=1 才有此 endpoint

用法：
    from e2e_v2.helpers.im_mock_client import IMMockClient

    async def test_im_invoke(httpx_client):
        mock = IMMockClient(httpx_client)
        await mock.clear("all")
        # ... 触发业务 ...
        calls = await mock.calls("feishu")
        assert len(calls) == 1
        assert calls[0]["method"] == "send_hitl_card"
"""
from __future__ import annotations

from typing import Any

import httpx


class IMMockClient:
    """封装 /api/test/im_mock_* endpoints 的轻量 HTTP 客户端。

    所有方法都是异步 + 返回新对象（不修改外部状态）— CLAUDE.md immutability。
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        """
        Args:
            http_client: 已配置 base_url 的 httpx.AsyncClient（来自 conftest fixture）
        """
        self._client = http_client

    async def calls(self, provider: str) -> list[dict[str, Any]]:
        """获取指定 Provider 的 mock 调用记录。

        Args:
            provider: 'feishu' / 'wecom' / 'dingtalk' / 'slack' / 'mattermost' / 'webhook'

        Returns:
            list of {method, recipient, payload} dict

        Raises:
            httpx.HTTPStatusError: 404 (provider 未注册) / 409 (非 mock provider)
        """
        resp = await self._client.get(
            "/api/test/im_mock_calls", params={"provider": provider}
        )
        resp.raise_for_status()
        return resp.json()

    async def clear(self, provider: str = "all") -> dict[str, Any]:
        """清空指定 Provider 的 mock 调用记录。

        Args:
            provider: provider 名 或 'all' 清空所有 mock provider

        Returns:
            {"cleared": [...], "count": N}
        """
        resp = await self._client.post(
            "/api/test/im_mock_clear", params={"provider": provider}
        )
        resp.raise_for_status()
        return resp.json()

    async def token_status(self, jti: str) -> dict[str, Any]:
        """查询 hitl_token 的 used_at 状态（Safe Links 回归基础）。

        Args:
            jti: JWT jti claim（UUID 字符串）

        Returns:
            {"jti", "used_at", "consumed", "exists", "used_ip", "used_ua"}
        """
        resp = await self._client.get("/api/test/hitl_tokens", params={"jti": jti})
        resp.raise_for_status()
        return resp.json()

    async def audit_logs(
        self,
        action: str | None = None,
        instance_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询最近的审计日志（委托 / 升级回归）。

        Args:
            action: 按 action 过滤（如 hitl.delegate / hitl.escalate）
            instance_id: 按 instance_id 过滤（通过 meta.instance_id JSONB）
            limit: 最多返回多少行

        Returns:
            list of audit_log dict
        """
        params: dict[str, str | int] = {"limit": limit}
        if action:
            params["action"] = action
        if instance_id:
            params["instance_id"] = instance_id

        resp = await self._client.get("/api/test/audit_logs", params=params)
        resp.raise_for_status()
        return resp.json()
