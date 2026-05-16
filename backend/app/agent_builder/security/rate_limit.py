"""slowapi 速率限制配置模块。

提供：
- limiter: Limiter 单例（slowapi 0.1.9），Redis 后端分布式计数器
- get_token_from_path: 从 /hitl/page/<token> 或 /hitl/action/<token> 路径提取 token，
  用于按 token 维度独立限频（防止一个 token 被暴力扫描）
- 在 main.py 挂载 SlowAPIMiddleware 后，各路由用 @limiter.limit() 装饰器应用限频

限频规则（NET-03）：
  - /hitl/page/<token> GET:  每 token/min ≤ 5（防 Safe Links 扫描器滥用）
  - /hitl/action/<token> POST: 每 IP/min ≤ 30（防恶意重放）
  - /api/im/webhook/*:  每秒 ≤ 10（防 IM 平台重试风暴）
  - /api/auth/login:   每 IP/min ≤ 10（防暴力破解）
  - /api/auth/register: 每 IP/min ≤ 3（防扫号）
  - 全局默认:   每 IP/min ≤ 100

Storage: REDIS_URL 环境变量（同 Redis 服务，分布式计数器跨 worker 共享）
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_token_from_path(request: Request) -> str:
    """从 HITL 路径提取 token 作为限频 key。

    支持路径：
      - /hitl/page/<token>
      - /hitl/action/<token>

    非 HITL 路径降级为 IP 地址。
    """
    path: str = request.url.path.strip("/")
    parts: list[str] = path.split("/")
    # 路径格式：hitl / page|action / <token>
    if len(parts) >= 3 and parts[0] == "hitl" and parts[1] in ("page", "action"):
        return parts[2]
    return get_remote_address(request)


# 支持测试环境使用 memory:// 存储（避免依赖 Redis）
# SLOWAPI_STORAGE_URI 优先（测试时设为 "memory://"），否则使用 REDIS_URL
_storage_uri: str = os.environ.get(
    "SLOWAPI_STORAGE_URI",
    os.environ.get("REDIS_URL", "redis://redis:6379/0"),
)

limiter: Limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    storage_uri=_storage_uri,
)
