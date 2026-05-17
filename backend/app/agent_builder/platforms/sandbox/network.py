"""AllowlistTransport — application-level 网络白名单（PLUG-FW-11）。

设计要点（RESEARCH §Pattern 3 + Pitfall 3 + docs/reading-dify-05b-03-network-allowlist-2026-05-18.md）:

- ``httpx.AsyncBaseTransport`` 子类化 — 注入点最干净（vs socket monkey-patch）
- ``exact (host, port)`` 匹配；host 自动 lowercase；port 缺省按 scheme 补齐 80/443
- 非白名单 host raise ``NetworkBlockedError``（Plan 05b-02 已占位定义）
- delegate 默认 ``httpx.AsyncHTTPTransport``；测试可 inject ``httpx.MockTransport``
- v1 不支持通配符（``*.example.com``）— 仅 exact host:port（manifest validator 已校验格式）
- 结构化日志 ``network.blocked`` event（host + port + scheme + allowlist size）

旁路警告（Pitfall 3 v1 trade-off — 详见 reading doc §v1 trade-off）:

- plugin 内 ``import requests; requests.get(...)`` 完全绕开（不走 httpx）
- plugin 内裸 ``socket.socket().connect(...)`` 完全绕开
- v1 mitigation: plugin developer guide 强制要求用 ``make_sandboxed_http_client()``
- v2: Phase 6 marketplace 引入 nsjail / Linux network namespace 真隔离

License: 100% 独立创作；引用 httpx BSD-3 公开 API（``AsyncBaseTransport`` /
``AsyncHTTPTransport``）。**严禁**拷贝 Dify AGPL-3.0 源码 — 详见 reading doc License 段。
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from ..exceptions import NetworkBlockedError

_log = logging.getLogger(__name__)


def _parse_allow_entry(entry: str) -> tuple[str, int] | None:
    """解析单条 allow_list 条目 ``"host:port"`` 为 ``(host_lower, port_int)`` tuple。

    - host 自动 lowercase（DNS 不区分大小写，URL 匹配也应一致）
    - port 必须显式声明（manifest validator 在 Plan 05b-01 已强制 ``^[a-z0-9.-]+:\\d+$``）
    - 缺 port 的条目跳过并 log warning（防止 plugin 作者笔误导致静默放行）

    Returns:
        ``(host, port)`` tuple 或 ``None``（条目非法时）
    """
    host, _, port_str = entry.partition(":")
    if not port_str:
        _log.warning(
            "AllowlistTransport: skipping malformed entry %r (missing :port)", entry
        )
        return None
    try:
        port = int(port_str)
    except ValueError:
        _log.warning(
            "AllowlistTransport: skipping malformed entry %r (port not int)", entry
        )
        return None
    return host.lower(), port


class AllowlistTransport(httpx.AsyncBaseTransport):
    """httpx 出站白名单 transport — plugin daemon 内显式注入。

    用法（plugin daemon entrypoint 内）::

        from app.agent_builder.platforms.sandbox.network import (
            make_sandboxed_http_client,
        )

        allow = ["api.example.com:443", "feishu-internal.com:443"]
        async with make_sandboxed_http_client(allow) as client:
            r = await client.post("https://api.example.com/v1/foo", json={...})
            # → 放行（进 delegate AsyncHTTPTransport 真发 HTTPS）

            r = await client.get("https://untrusted.com/")
            # → raise NetworkBlockedError

    设计选择（v1 简化）:

    - 不支持通配符（``*.example.com``） — Plan 05b-01 manifest validator 已限定
      ``^[a-z0-9.-]+:\\d+$``，不允许 ``*``；v2 marketplace 上才考虑 glob/CIDR
    - 不解析 path / query —— 仅 host:port 级（URL path 不算"出口")
    - 不区分 method（GET/POST 等） —— 白名单是 host 级访问控制，不是 RBAC

    Args:
        allow_list: 形如 ``["host1:port1", "host2:port2"]`` 的白名单。
            空列表 = 拒所有出站（restrictive baseline，Pitfall 8 默认安全）。
        delegate: 透传给真发请求的 transport；默认 ``httpx.AsyncHTTPTransport``。
            测试时可 inject ``httpx.MockTransport(lambda req: httpx.Response(200, ...))``
            避免真发 TCP 请求。
    """

    def __init__(
        self,
        allow_list: list[str],
        *,
        delegate: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allow_set: set[tuple[str, int]] = set()
        for entry in allow_list:
            parsed = _parse_allow_entry(entry)
            if parsed is not None:
                self._allow_set.add(parsed)
        self._delegate: httpx.AsyncBaseTransport = (
            delegate if delegate is not None else httpx.AsyncHTTPTransport()
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """检查 ``request.url`` 的 host:port，命中白名单则 delegate，否则 raise。

        URL 解析规则:

        - host 取 ``urlparse(url).hostname`` 并 lowercase（DNS 不区分大小写）
        - port 取 ``urlparse(url).port``；URL 无显式 port 时按 scheme 补齐
          （``https`` → 443，``http`` → 80，其它 → 0 → 必拒）

        结构化日志 ``network.blocked``（监控可基于此 event 串告警）::

            level=WARNING
            message="network.blocked host=untrusted.com port=443 scheme=https
                    allowlist_size=2 — not in allow_list"

        Raises:
            NetworkBlockedError: ``host:port`` 不在白名单时；含 ``host`` / ``port`` /
                ``allowlist`` 属性可被上层 logger / 监控提取。
        """
        parsed = urlparse(str(request.url))
        host = (parsed.hostname or "").lower()

        port = parsed.port
        if port is None:
            scheme = (parsed.scheme or "").lower()
            if scheme == "https":
                port = 443
            elif scheme == "http":
                port = 80
            else:
                # 未知 scheme（如 ftp / ws）— port=0 必拒，安全 baseline
                port = 0

        if (host, port) not in self._allow_set:
            _log.warning(
                "network.blocked host=%s port=%s scheme=%s "
                "allowlist_size=%d — not in allow_list",
                host,
                port,
                parsed.scheme,
                len(self._allow_set),
            )
            # 重建一份排序后的列表喂给 NetworkBlockedError，方便调试时一眼看到白名单内容
            allowlist_dump = sorted(f"{h}:{p}" for h, p in self._allow_set)
            raise NetworkBlockedError(host=host, port=port, allowlist=allowlist_dump)

        return await self._delegate.handle_async_request(request)

    async def aclose(self) -> None:
        """关闭 delegate transport（httpx.AsyncClient lifecycle 会调）。

        ``httpx.AsyncBaseTransport.aclose`` 是 async（不是 close）— 与 delegate
        ``httpx.AsyncHTTPTransport.aclose`` 接口对齐。
        """
        await self._delegate.aclose()


def make_sandboxed_http_client(
    allow_list: list[str],
    *,
    timeout: float = 10.0,
) -> httpx.AsyncClient:
    """plugin daemon 显式调此 factory 拿沙箱化 ``httpx.AsyncClient``。

    用法::

        async with make_sandboxed_http_client(["api.example.com:443"]) as client:
            r = await client.post("https://api.example.com/foo", json={...})

    Args:
        allow_list: 形如 ``["host:port", ...]`` 的白名单；空列表 = 拒所有出站。
        timeout: 单次请求默认超时（秒），默认 10s；plugin daemon 内业务可在
            ``client.post(url, timeout=2.0)`` 单独覆盖。

    Returns:
        ``httpx.AsyncClient`` 实例，``transport=AllowlistTransport(allow_list)``。
        调用方负责调 ``await client.aclose()`` 或用 ``async with`` 上下文管理。
    """
    return httpx.AsyncClient(
        transport=AllowlistTransport(allow_list),
        timeout=httpx.Timeout(timeout),
    )


__all__ = ["AllowlistTransport", "make_sandboxed_http_client"]
