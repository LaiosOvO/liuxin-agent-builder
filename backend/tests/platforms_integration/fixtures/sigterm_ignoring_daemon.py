"""fixture daemon — 故意忽略 SIGTERM 触发 watchdog grace period 测试.

用法（Linux only — macOS RLIMIT 弱 enforcement）::

    cmd = [sys.executable, "-u", "-m",
           "tests.platforms_integration.fixtures.sigterm_ignoring_daemon"]
    client = PlatformDaemonClient(
        "tests.platforms_integration.fixtures.sigterm_ignoring_daemon",
        sandbox_config=SandboxConfig(memory="50Mi", ...),
        invoke_timeout=10.0,
    )
    # invoke alloc_200mb 触发 RSS > 50MB
    # → watchdog SIGTERM 被 SIG_IGN
    # → 3s grace → SIGKILL
    # → invoke raise SandboxLimitExceeded（on_violation 通过 _fail_all_pending 立即触发）

设计要点：
- `signal.signal(SIGTERM, SIG_IGN)` 必须在 stdin loop **之前** 设（否则 SIGTERM 默认 handler
  会先被触发，watchdog 测不到 grace path）
- alloc_200mb method 持续 append 200MB byte buffer 到 list（防 GC 回收，让 RSS 真涨）
- 简化版 JSONRPC stdio loop（不依赖 5.A capability framework — fixture 独立运行）
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys


async def main() -> None:
    """简化 JSONRPC stdio daemon — 故意忽略 SIGTERM 让 watchdog 测 grace path."""
    # 关键：在任何 IO 之前设 SIGTERM = SIG_IGN
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    # 异步连接 stdin（asyncio 标准 idiom）
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    big_buffer: list[bytes] = []  # 持续分配 — 让 RSS 真涨触发 watchdog

    while True:
        line = await reader.readline()
        if not line:
            break

        try:
            req = json.loads(line.decode())
            method = req.get("method", "")
            req_id = req.get("id")

            if method.endswith("alloc_200mb") or method.endswith("alloc"):
                # 持续分配 200MB（触发 watchdog memory_limit_bytes 检测）
                big_buffer.append(b"a" * (200 * 1024 * 1024))
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"alloc": True, "buffer_count": len(big_buffer)},
                }
            elif method.endswith("ping"):
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"plugin_name": "sigterm_ignoring", "pong": True},
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found in sigterm_ignoring_daemon",
                    },
                }

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        except Exception as e:  # noqa: BLE001 — fixture 兜底
            try:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id") if "req" in dir() else None,
                    "error": {"code": -32603, "message": str(e)},
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception:
                # stdin 已死之类，直接退出
                break


if __name__ == "__main__":
    asyncio.run(main())
