"""Phase 5.A platforms 集成测试共享 fixture。

集成测真起 daemon 子进程 + mock huly server（aiohttp.web），
本 conftest 提供 subprocess / 端口管理的工程基础设施：
- free_port fixture（mock huly server 监听用，端口 0 让 OS 分配）
- mock_huly_server fixture（aiohttp stub — Plan 07 acid test 实现后启用）
- spawn_huly_daemon fixture（subprocess 包装 — Plan 07 acid test 实现后启用）

Plan 07 HulyPlugin acid test 前，本 conftest 仅 free_port 可用 + 留 fixture 骨架。
"""
from __future__ import annotations

import socket

import pytest


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
