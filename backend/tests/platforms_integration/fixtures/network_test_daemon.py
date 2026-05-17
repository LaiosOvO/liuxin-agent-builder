"""集成测 daemon fixture — 验证 AllowlistTransport 在真子进程内的行为。

启动后:

1. 从 env ``PLUGIN_NETWORK_ALLOW`` 解 allow_list
2. 用 ``make_sandboxed_http_client`` 构造 client
3. 从 env ``TARGET_URL`` 取目标 URL（默认 ``https://blocked.example.com/``）
4. 尝试 GET, 把结果按 ``<event>:<detail>`` 行输出到 stdout, 用 returncode 区分:
   - returncode 0  + stdout 含 ``unexpected_ok:`` ← 不应发生（白名单意外放行了真请求）
   - returncode 10 + stdout 含 ``blocked:``       ← AllowlistTransport 拒绝（v1 预期路径）
   - returncode 20 + stdout 含 ``network_error:`` ← 网络真发但 DNS / connect 失败（白名单放行 + 真网络不通）

子进程入口约定：
    python -m tests.platforms_integration.fixtures.network_test_daemon

调用方应:
    env={"PLUGIN_NETWORK_ALLOW": "host:port,...", "TARGET_URL": "https://..."}
    cwd=backend/  # 让 from app.agent_builder... import 可解析
"""

from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    # lazy import — 与 huly_plugin 相同 pattern，避免 daemon 启动时 PYTHONPATH 未含 backend/
    # 立刻 ImportError 看不到 stderr
    try:
        from app.agent_builder.platforms.exceptions import NetworkBlockedError
        from app.agent_builder.platforms.sandbox.network import (
            make_sandboxed_http_client,
        )
    except ImportError as e:
        print(f"import_error:{e}", flush=True)
        return 30

    raw_allow = os.environ.get("PLUGIN_NETWORK_ALLOW", "")
    allow = [e.strip() for e in raw_allow.split(",") if e.strip()]
    target = os.environ.get("TARGET_URL", "https://blocked.example.com/")

    async with make_sandboxed_http_client(allow, timeout=2.0) as client:
        try:
            resp = await client.get(target)
            print(f"unexpected_ok:{resp.status_code}", flush=True)
            return 0
        except NetworkBlockedError as e:
            # v1 预期路径 — AllowlistTransport 拒绝
            print(f"blocked:{e}", flush=True)
            return 10
        except Exception as e:  # noqa: BLE001 — daemon 兜底打印类型 + 信息
            # 真发请求失败（DNS / connect timeout / TLS） — v1 接受为 "白名单放行 + 真网络不通" 信号
            print(f"network_error:{type(e).__name__}:{e}", flush=True)
            return 20


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
