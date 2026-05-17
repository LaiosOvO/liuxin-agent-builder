"""Mock Huly chunter API server — Phase 5.A acid test 用 aiohttp stub。

监听本地端口（test fixture 通过 free_port 分配）模拟 Huly chunter API：
- ``POST /api/v1/chunter/messages``
  - 接受 body: ``{channel, message, idempotency_key}``
  - 返回: ``{message_id, channel, echoed_message_preview}``
  - status: 200 (success) / 400 (missing required fields)

为什么真起 aiohttp server 而非 mock daemon 的 HTTP client：
- daemon 是独立子进程，无法在主进程 mock 它的出站 HTTP
- 必须用真实 HTTP server 监听本地端口
- daemon 通过 HULY_ENDPOINT env var 知道 mock server URL

设计要点：
- 不依赖外部 Huly self-host（CONTEXT.md decision §HulyPlugin Acid Test）
- 每个 message 生成唯一 message_id（``huly-msg-{uuid4().hex[:8]}``）
- 不实现真实 Huly 鉴权 / DB / chunter 业务逻辑（Phase 5.C 真接入时再考虑）

License: 独立创作，仅借鉴 aiohttp.web 标准用法（Python 生态公开模式）。
"""

from __future__ import annotations

import uuid
from typing import Any

from aiohttp import web

# ── handler ──────────────────────────────────────────────────────────────────


async def chunter_messages_handler(request: web.Request) -> web.Response:
    """POST /api/v1/chunter/messages — 接受 daemon 的卡片发送请求。

    模拟 Huly chunter API 的最简核心契约：
    1. 必须含 ``channel`` 和 ``message`` 字段
    2. 返回 ``message_id`` 让调用方持久化 / 回查
    3. ``echoed_message_preview`` 截断 message 前 50 字符方便测试断言

    Args:
        request: aiohttp Request，body 是 JSON
                 (``{channel: str, message: str, idempotency_key: str}``)

    Returns:
        200 + ``{message_id, channel, echoed_message_preview}`` (success)
        400 + ``{error}`` (missing required field)
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:  # noqa: BLE001
        return web.json_response({"error": f"invalid JSON: {e}"}, status=400)

    if "channel" not in body or "message" not in body:
        return web.json_response(
            {"error": "missing required field: channel or message"},
            status=400,
        )

    message_id = f"huly-msg-{uuid.uuid4().hex[:8]}"
    return web.json_response(
        {
            "message_id": message_id,
            "channel": body["channel"],
            "echoed_message_preview": body["message"][:50],
        }
    )


# ── app builder ──────────────────────────────────────────────────────────────


def build_mock_app() -> web.Application:
    """构造 aiohttp Application 含 chunter messages route。

    用法（conftest fixture）::

        from aiohttp import web

        app = build_mock_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            await runner.cleanup()

    Returns:
        aiohttp.web.Application 含 ``POST /api/v1/chunter/messages`` 路由
    """
    app = web.Application()
    app.router.add_post("/api/v1/chunter/messages", chunter_messages_handler)
    return app
