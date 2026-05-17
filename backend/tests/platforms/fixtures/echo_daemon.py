"""Echo daemon — Phase 5.A Plan 05 test fixture（PLUG-FW-05 测试用）。

最小 daemon entry：读 stdin JSONRPC envelope 行，按 method 返回固定 result；
不真调外部服务，仅用于 PlatformDaemonClient 主流程 / fault isolation 单测。

用法（pytest 通过 ``-m tests.platforms.fixtures.echo_daemon`` 起子进程）::

    client = PlatformDaemonClient("tests.platforms.fixtures.echo_daemon")
    result = await client.invoke("im", "send_card", recipient={...}, card={...}, idempotency_key="k1")
    # → {"plugin_name": "echo", "native_id": "echo-k1", "extras": {}}

支持的 method:
- ``im.send_card`` → 正常 result（含 plugin_name="echo" + native_id="echo-<idempotency_key>"）
- ``im.echo_error`` → 返回 JSONRPC error 业务错（code=-32000）
- ``im.crash`` → ``sys.exit(1)`` 模拟 daemon crash（**Pitfall 2 fault isolation 测试**）
- ``im.slow`` → sleep 5s 模拟长耗时（timeout 测试用）
- 其他 method → 返回 JSONRPC error -32601 (Method not found)

JSONRPC 2.0 协议严格遵守：
- response envelope: ``{"jsonrpc":"2.0","id":<rid>,"result":<any>}`` 成功
- response envelope: ``{"jsonrpc":"2.0","id":<rid>,"error":{"code":<int>,"message":<str>}}`` 错误

实现要点：
- ``sys.stdin.buffer`` 读 binary 行（避免 newline 编码问题）
- ``sys.stdout.buffer.write + flush`` 确保 response 立即送出（虽然主进程已 ``-u`` unbuffered）
- 异常一律 wrap 为 JSONRPC -32603 internal error 返回
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any


def _make_success(rid: Any, result: Any) -> dict:
    """构造成功 response envelope（JSONRPC 2.0）。"""
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _make_error(rid: Any, code: int, message: str) -> dict:
    """构造错误 response envelope（JSONRPC 2.0）。"""
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


async def _handle_method(method: str, params: dict, rid: Any) -> dict | None:
    """按 method 分流到具体处理；返回 response dict（或 None 表示 crash 即将发生）。"""
    if method == "im.send_card":
        idempotency_key = params.get("idempotency_key", "k")
        return _make_success(
            rid,
            {
                "plugin_name": "echo",
                "native_id": f"echo-{idempotency_key}",
                "extras": {},
            },
        )

    if method == "im.echo_error":
        return _make_error(rid, -32000, "intentional error from echo daemon")

    if method == "im.crash":
        # 不返回 response —— 直接 sys.exit(1)
        # 主进程 _read_loop 检测 stdout EOF → Pitfall 2 fault isolation 走完
        sys.exit(1)

    if method == "im.slow":
        # 模拟长耗时 — 用于 invoke_timeout 测试
        await asyncio.sleep(5.0)
        return _make_success(rid, {"slept": 5.0})

    if method == "im.update_card":
        return _make_success(rid, None)

    if method == "im.send_text":
        recipient = params.get("recipient", {})
        return _make_success(
            rid,
            {
                "plugin_name": "echo",
                "native_id": f"text-{recipient.get('id', 'x')}",
                "extras": {},
            },
        )

    # Method not found
    return _make_error(rid, -32601, f"Method not found: {method}")


async def main() -> None:
    """daemon 主循环：从 stdin 读 JSONRPC 行，处理后写 stdout。

    协议：
    - 行级编码（每行一个完整 JSON envelope）
    - utf-8 编码
    - readline 返回空 bytes → EOF（主进程关闭 stdin） → 退出
    """
    loop = asyncio.get_event_loop()

    # 用 StreamReader 包装 sys.stdin 实现 async read
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            # stdin EOF —— 主进程关闭 stdin / close()
            break

        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            # 非法 JSON → log + skip（不能给 error response 因为不知道 id）
            sys.stderr.write(f"[echo_daemon] invalid JSON: {line!r}\n")
            sys.stderr.flush()
            continue

        rid = envelope.get("id")
        method = envelope.get("method", "")
        params = envelope.get("params", {})

        try:
            response = await _handle_method(method, params, rid)
        except SystemExit:
            # im.crash 走到这里
            raise
        except Exception as e:  # noqa: BLE001 — daemon 兜底所有异常
            response = _make_error(rid, -32603, f"Internal error in echo_daemon: {e}")

        if response is None:
            continue

        out_line = (json.dumps(response) + "\n").encode("utf-8")
        sys.stdout.buffer.write(out_line)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    asyncio.run(main())
