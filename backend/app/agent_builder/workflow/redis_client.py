"""异步 Redis 客户端单例模块。

提供全局连接池和 Redis 实例获取工具函数。
使用 redis.asyncio 驱动（redis 7.x），支持 decode_responses=True。

配置：
  REDIS_URL 环境变量（默认 redis://localhost:6379/0）
  REDIS_MAX_CONNECTIONS 环境变量（默认 20）
"""
from __future__ import annotations

import os

from redis.asyncio import ConnectionPool, Redis

_pool: ConnectionPool | None = None


def get_redis_pool() -> ConnectionPool:
    """获取（或创建）全局 Redis 连接池单例。

    第一次调用时从 REDIS_URL 环境变量读取配置并初始化连接池；
    后续调用返回同一实例（单例模式）。

    Returns:
        ConnectionPool 实例
    """
    global _pool
    if _pool is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        max_connections = int(os.environ.get("REDIS_MAX_CONNECTIONS", "20"))
        _pool = ConnectionPool.from_url(
            url,
            decode_responses=True,
            max_connections=max_connections,
        )
    return _pool


def get_redis() -> Redis:
    """获取 Redis 异步客户端实例（使用全局连接池）。

    Returns:
        Redis async 客户端（已配置 decode_responses=True）
    """
    return Redis(connection_pool=get_redis_pool())


def reset_redis_pool() -> None:
    """重置全局连接池（仅用于测试环境）。

    在测试中切换 REDIS_URL 时调用，确保下次 get_redis_pool() 重新初始化。
    """
    global _pool
    _pool = None
