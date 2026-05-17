"""HulyPlugin daemon entrypoint — JSONRPC over stdio。

子进程跑 ``python -u -m plugins.huly.huly_plugin``：

- 主循环：从 stdin 行级读取 JSONRPC envelope
- 路由 method 名（"<capability>.<method>"）到对应 handler
- 结果走 stdout（行分隔 JSON envelope）

Phase 5.A acid test 范围（CONTEXT.md decision §HulyPlugin Acid Test）：
- **真实实现 1 个 capability call**：im.send_card → aiohttp POST 到 mock huly server
- 其他 capability method 显式 raise NotImplementedError → JSONRPC -32603 error
- HULY_ENDPOINT 由主进程通过 env var 注入（test fixture 注入 mock server URL）

设计要点：
- METHODS dict 集中路由 — 易扩展（Phase 5.C 加 doc.create_document 等）
- JSONRPC 2.0 标准 envelope（jsonrpc / id / method / params / result / error）
- Error code 约定：
  - -32601: Method not found（METHODS dict 没有这个 method 名）
  - -32603: Internal error（含 NotImplementedError）
  - -32000~-32099: 业务错误（HTTP 失败 / Huly auth 失败等 — Phase 5.C 加）
- stderr 写 debug log；主进程 _stderr_drain 持续读防 pipe 满（Pitfall 8）

License: 100% 独立创作（不拷 Dify dify-plugin-daemon Go 源码 / 不拷 Huly chunter TS 源码）。
仅借鉴：
- JSONRPC 2.0 协议（公开标准 https://www.jsonrpc.org/specification）
- Dify PluginDaemonError code/message 双字段设计（reading doc 借鉴点 #2）
- echo_daemon.py 主循环结构（同仓 Plan 05 测试 fixture）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

import aiohttp


# ── 配置 ────────────────────────────────────────────────────────────────────────

# HULY_ENDPOINT 由主进程通过 env 注入（test fixture 注入 mock server URL）；
# 默认 localhost:18765 仅作 stand-alone 调试用，acid test 必须显式注入。
HULY_ENDPOINT = os.environ.get("HULY_ENDPOINT", "http://localhost:18765")

# 单次 HTTP 调用超时（秒）—— 不要超过 daemon_client invoke_timeout 否则主进程先 timeout。
_HTTP_TIMEOUT_SECONDS = 5.0


# ── Capability handlers ──────────────────────────────────────────────────────


def _parse_network_allow() -> list[str]:
    """从 env ``PLUGIN_NETWORK_ALLOW`` 解出 ``["host:port", ...]`` 白名单。

    主进程（Plan 05b-04 daemon_client）会从 manifest ``sandbox.network`` 转化
    为 ``,`` 分隔字符串注入子进程；本函数解析后供 ``make_sandboxed_http_client`` 用。

    - env 未设 / 空字符串 → 返回 ``[]`` → ``im_send_card`` 走 5.A aiohttp fallback 路径
      （保证 5.A acid test 0 regression — 5.A 测试 fixture 不设此 env）
    - env 非空 → 走 Plan 05b-03 新 httpx + AllowlistTransport 路径
    """
    raw = os.environ.get("PLUGIN_NETWORK_ALLOW", "")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


async def _im_send_card_sandboxed(
    params: dict[str, Any], allow_list: list[str]
) -> dict[str, Any]:
    """Plan 05b-03 新路径：用 AllowlistTransport 注入的 httpx.AsyncClient 发请求。

    **lazy import**（HIGH-2 fix）— ``from app.agent_builder...`` 仅在此函数被调时才执行。
    5.A acid test 不设 ``PLUGIN_NETWORK_ALLOW`` → ``_parse_network_allow()`` 返回 ``[]``
    → ``im_send_card`` 走 aiohttp 分支 → 本函数从不被调用 → import 不执行
    → 子进程 PYTHONPATH 未含 backend/ 也不会 ModuleNotFoundError。
    """
    # lazy import — 防 5.A acid test daemon spawn 时 PYTHONPATH 未含 backend/ 立即崩溃
    from app.agent_builder.platforms.sandbox.network import (
        make_sandboxed_http_client,
    )

    recipient = params["recipient"]
    card = params["card"]
    idempotency_key = params["idempotency_key"]

    body = {
        "channel": recipient["id"],
        "message": f"## {card['title']}\n\n{card['body_markdown']}",
        "idempotency_key": idempotency_key,
    }

    async with make_sandboxed_http_client(
        allow_list, timeout=_HTTP_TIMEOUT_SECONDS
    ) as client:
        resp = await client.post(
            f"{HULY_ENDPOINT}/api/v1/chunter/messages",
            json=body,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Huly chunter API returned HTTP {resp.status_code}: {resp.text}"
            )
        data = resp.json()

    return {
        "plugin_name": "huly",
        "native_id": data["message_id"],
        "extras": {
            "channel": recipient["id"],
            "preview": data.get("echoed_message_preview", ""),
        },
    }


async def im_send_card(params: dict[str, Any]) -> dict[str, Any]:
    """IMCapability.send_card 真实实现（acid test 核心路径）。

    params 来自主进程 IMFacade.send_card：
    - recipient: ``asdict(RecipientSpec(kind=..., id=..., extras={...}))``
    - card: ``asdict(NormalizedCard(title=..., body_markdown=..., actions=[...]))``
    - idempotency_key: str

    **env-gated 双路径**（Plan 05b-03 引入；5.A 0 regression 关键）:

    - ``PLUGIN_NETWORK_ALLOW`` 未设 / 空字符串 → 走 5.A 原 aiohttp 路径（fallback）
    - ``PLUGIN_NETWORK_ALLOW="host:port,..."`` → 走 Plan 05b-03 新 httpx +
      AllowlistTransport 路径（``_im_send_card_sandboxed``）

    实现（共通）：
    1. 把 NormalizedCard 转 markdown body（``## title\\n\\n body_markdown``）
    2. POST 到 ``{HULY_ENDPOINT}/api/v1/chunter/messages``
       body: ``{channel, message, idempotency_key}``
    3. mock huly server 返回 ``{message_id, channel, echoed_message_preview}``
    4. 转换为 MessageRef dict 返回主进程

    Returns:
        ``{"plugin_name": "huly", "native_id": <huly message_id>, "extras": {...}}``

    Raises:
        aiohttp.ClientError / RuntimeError: HTTP 失败 → daemon dispatcher 转 JSONRPC -32000 error
        NetworkBlockedError: 新路径下 HULY_ENDPOINT host 不在白名单时 raise（Plan 05b-03）
    """
    allow_list = _parse_network_allow()
    if allow_list:
        # Plan 05b-03 新路径 — 仅在主进程明示注入 env 时走（5.A acid test 不触发）
        return await _im_send_card_sandboxed(params, allow_list)

    # 5.A 原路径 — aiohttp fallback（acid test 走此路径，0 regression）
    recipient = params["recipient"]
    card = params["card"]
    idempotency_key = params["idempotency_key"]

    body = {
        "channel": recipient["id"],
        "message": f"## {card['title']}\n\n{card['body_markdown']}",
        "idempotency_key": idempotency_key,
    }

    timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{HULY_ENDPOINT}/api/v1/chunter/messages",
            json=body,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(
                    f"Huly chunter API returned HTTP {resp.status}: {text}"
                )
            data = await resp.json()

    return {
        "plugin_name": "huly",
        "native_id": data["message_id"],
        "extras": {
            "channel": recipient["id"],
            "preview": data.get("echoed_message_preview", ""),
        },
    }


async def _not_implemented(params: dict[str, Any]) -> dict[str, Any]:
    """占位 handler — Phase 5.C / 5.D 实接入。

    Phase 5.A 仅实现 im.send_card；其他 capability method 走此路径，
    daemon dispatcher 会 catch NotImplementedError 并返回 JSONRPC -32603。
    """
    raise NotImplementedError(
        "HulyPlugin Phase 5.A 仅实现 im.send_card；"
        "其他 method 留 Phase 5.C (Doc) / 5.D (HR / Identity)"
    )


# ── Method routing ───────────────────────────────────────────────────────────

# method 名 → handler 映射。
# 注意：未在此 dict 中的 method 走 -32601 Method not found（与 NotImplementedError 区分）：
# - -32601: method 名根本不存在（如 typo / 客户端错版本）
# - -32603 (NotImplementedError): method 名存在但 Phase 5.A 未实现
METHODS: dict[str, Any] = {
    # IM capability — 1 个真实实现 + 2 个占位
    "im.send_card": im_send_card,
    "im.update_card": _not_implemented,
    "im.send_text": _not_implemented,
    # Doc capability — 全部占位（Phase 5.C 实接入）
    "doc.create_document": _not_implemented,
    "doc.replace_document_content": _not_implemented,
    "doc.apply_document_delta": _not_implemented,
    "doc.add_comment": _not_implemented,
    "doc.get_document": _not_implemented,
    # HR capability — 全部占位（Phase 5.D 实接入）
    "hr.list_employees": _not_implemented,
    "hr.get_employee": _not_implemented,
    "hr.list_departments": _not_implemented,
    "hr.resolve_department_members": _not_implemented,
    "hr.list_leave_requests": _not_implemented,
    "hr.create_leave_request": _not_implemented,
    # Identity capability — 全部占位（Phase 5.D 实接入）
    "identity.list_users": _not_implemented,
    "identity.resolve_user": _not_implemented,
}


# ── JSONRPC envelope 构造 / dispatch ─────────────────────────────────────────


def _make_success(rid: Any, result: Any) -> dict[str, Any]:
    """JSONRPC 2.0 success envelope。"""
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _make_error(rid: Any, code: int, message: str) -> dict[str, Any]:
    """JSONRPC 2.0 error envelope。"""
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


async def _process_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """处理单个 JSONRPC envelope，返回 response envelope。

    路由：
    1. method 不在 METHODS → -32601 Method not found
    2. handler 抛 NotImplementedError → -32603 Internal error（含 "Phase 5.C/5.D"）
    3. handler 抛其他异常 → -32000 业务错误
    4. handler 正常返回 → success envelope
    """
    rid = envelope.get("id")
    method_name = envelope.get("method", "")
    params = envelope.get("params") or {}

    handler = METHODS.get(method_name)
    if handler is None:
        return _make_error(rid, -32601, f"Method not found: {method_name}")

    try:
        result = await handler(params)
        return _make_success(rid, result)
    except NotImplementedError as e:
        return _make_error(rid, -32603, str(e))
    except Exception as e:  # noqa: BLE001 — daemon 兜底所有异常
        # -32000 ~ -32099 为应用业务错误（如 Huly API 鉴权失败 / 频率限制）
        return _make_error(rid, -32000, f"HulyPlugin internal error: {e!r}")


# ── Daemon main loop ─────────────────────────────────────────────────────────


async def main() -> None:
    """Daemon 主循环：从 stdin 读 JSONRPC 行，处理后写 stdout。

    协议：
    - 行级编码（每行一个完整 JSON envelope，utf-8）
    - readline 返回空 bytes → stdin EOF（主进程关闭 stdin）→ 退出主循环
    - 非法 JSON 行 → stderr log + skip（不能给 error response 因为不知道 id）

    实现细节：
    - 用 asyncio.StreamReader 包装 sys.stdin 实现 async readline
    - sys.stdout.buffer.write + flush 确保 response 立即送出（虽然 ``python -u`` 已 unbuffered）
    """
    # stderr 写启动信息（主进程 _stderr_drain 会读，Pitfall 8 防护）
    print(
        f"[huly_plugin] started; HULY_ENDPOINT={HULY_ENDPOINT}",
        file=sys.stderr,
        flush=True,
    )

    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            # stdin EOF — 主进程已关闭 stdin（close() 或 进程退出）
            break

        try:
            envelope = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stderr.write(
                f"[huly_plugin] invalid JSON line: {line!r} error={e}\n"
            )
            sys.stderr.flush()
            continue

        response = await _process_envelope(envelope)

        # 序列化 + 行分隔 + flush 立即送出
        out_line = (json.dumps(response) + "\n").encode("utf-8")
        sys.stdout.buffer.write(out_line)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    # 注意：logging 在 daemon 中不配置（避免污染 stdout）；
    # 仅用 sys.stderr.write 写 daemon 自身 debug 信息。
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
