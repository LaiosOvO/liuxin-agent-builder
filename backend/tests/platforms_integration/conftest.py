"""Phase 5.A platforms 集成测试共享 fixture。

集成测真起 daemon 子进程 + mock huly server（aiohttp.web），
本 conftest 提供 subprocess / 端口管理的工程基础设施：

- ``free_port`` fixture（mock huly server 监听用，端口 0 让 OS 分配） — Plan 01 已建
- ``mock_huly_server`` fixture（aiohttp stub 启动 + URL yield + cleanup） — Plan 07 追加
- ``project_root`` fixture（让 daemon spawn 用项目根目录作 cwd） — Plan 07 追加

Plan 07 HulyPlugin acid test 全链路：
- mock_huly_server fixture → 起 aiohttp stub 监听本地 free_port
- PlatformDaemonClient(env={HULY_ENDPOINT: url}, cwd=project_root) 真起 daemon 子进程
- daemon 收到 JSONRPC → 调 aiohttp POST → mock server 返回 message_id
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio


@pytest.fixture
def free_port() -> int:
    """获取本机可用端口号（用 socket bind 0 让 OS 分配）。

    用法：
        def test_mock_server(free_port):
            server = MockHulyServer(port=free_port)
            ...

    注意：
    - 返回的端口在 fixture 返回时已 close，理论上可能被其他进程抢用；
      实际测试中接 mock server bind 之前的窗口极短，可接受
    - 每次 fixture 调用独立端口，避免并行测试间冲突
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def project_root() -> str:
    """项目根目录绝对路径（daemon spawn cwd 用）。

    huly_plugin daemon 通过 ``python -u -m plugins.huly.huly_plugin`` 启动；
    pytest 跑在 ``backend/`` 下，但 ``plugins/`` 在项目根。
    Daemon 必须以项目根为 cwd 才能找到 ``plugins.huly`` 包。

    本 fixture 返回 ``backend/`` 的父目录（即项目根）。
    """
    return str(Path(__file__).resolve().parents[3])


@pytest_asyncio.fixture
async def mock_huly_server(free_port: int) -> AsyncIterator[str]:
    """启动 aiohttp mock huly server，yield URL，结束时 cleanup。

    用法（Plan 07 acid test）::

        @pytest.mark.asyncio
        async def test_huly(mock_huly_server, project_root):
            daemon = PlatformDaemonClient(
                module_entry="plugins.huly.huly_plugin",
                env={"HULY_ENDPOINT": mock_huly_server},
                cwd=project_root,
            )
            await daemon.invoke("im", "send_card", recipient={...}, card={...}, idempotency_key="k")

    Yields:
        ``"http://127.0.0.1:<port>"`` URL string

    Cleanup:
        web.AppRunner.cleanup() 确保端口释放 + connections 关闭
    """
    # 延迟 import 避免 aiohttp 在不需要 mock server 的测试中被加载
    from aiohttp import web

    from tests.platforms_integration.mock_huly_server import build_mock_app

    app = build_mock_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", free_port)
    await site.start()
    url = f"http://127.0.0.1:{free_port}"
    try:
        yield url
    finally:
        await runner.cleanup()
