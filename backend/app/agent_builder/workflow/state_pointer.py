"""State Pointer Pattern — 大字段透明 Redis 代理模块。

防护 Pitfall 1（checkpoint 写入放大）：节点输出中 JSON 编码后超过 4KB 的字段，
自动写入 Redis 并替换为 pointer 字符串；读 state 时自动反向解引用。

Pointer 格式: ``__ptr__:redis:state:<32位 hex uuid>``
Redis key: ``agent_builder:state_ptr:<workspace_id>:<instance_id>:<uuid>``
TTL: 30 天

参考来源:
- PITFALLS.md Pitfall 1: Pointer State Pattern 防 checkpoint 膨胀
- docs/reading-dify-02-06-redis-pointer-2026-05-16.md: Dify 旁路存储模式
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# 单字段 JSON 编码后 UTF-8 字节数阈值，超过则写 Redis pointer
LARGE_THRESHOLD_BYTES = 4096

# pointer 字符串前缀，用于扫描识别
POINTER_PREFIX = "__ptr__:redis:state:"

# Redis key 前缀（租户隔离 + 实例隔离）
REDIS_KEY_PREFIX = "agent_builder:state_ptr"

# 30 天 TTL（秒）
TTL_SECONDS = 30 * 86400


def is_pointer(value: Any) -> bool:
    """判断 value 是否为 state pointer 字符串。

    Args:
        value: 任意值

    Returns:
        True 当且仅当 value 是以 POINTER_PREFIX 开头的字符串
    """
    return isinstance(value, str) and value.startswith(POINTER_PREFIX)


def parse_pointer(pointer: str) -> str:
    """从 pointer 字符串提取 uuid 部分（32位 hex）。

    Args:
        pointer: 合法的 pointer 字符串

    Returns:
        32位 hex uuid 字符串

    Raises:
        ValueError: pointer 格式非法
    """
    if not is_pointer(pointer):
        raise ValueError(f"非法 pointer 格式（期望 '{POINTER_PREFIX}...'）：{pointer!r}")
    return pointer[len(POINTER_PREFIX):]


def _redis_key(workspace_id: UUID, instance_id: UUID, ptr_uuid: str) -> str:
    """构造 Redis key（含租户和实例命名空间）。

    格式: ``agent_builder:state_ptr:<workspace_id>:<instance_id>:<uuid>``

    Args:
        workspace_id: 工作区 UUID（防租户碰撞）
        instance_id: 流程实例 UUID（便于批量清理）
        ptr_uuid: pointer uuid（32位 hex）

    Returns:
        完整 Redis key 字符串
    """
    return f"{REDIS_KEY_PREFIX}:{workspace_id}:{instance_id}:{ptr_uuid}"


async def write_state_with_pointers(
    state_delta: Any,
    *,
    workspace_id: UUID,
    instance_id: UUID,
    redis: Redis,
) -> Any:
    """扫描 state_delta dict，大字段写 Redis 并替换为 pointer。

    算法（遵循不可变性原则）：
    1. 仅处理顶层 dict；非 dict 原样返回
    2. 每个 value JSON 编码后计算 UTF-8 字节数
    3. 超过 LARGE_THRESHOLD_BYTES：生成 uuid → 写 Redis（SETEX TTL） → 替换为 pointer 字符串
    4. 未超过：保留原值
    5. Redis 不可用时：记录 warning，返回原 state_delta（降级模式）

    Args:
        state_delta: 节点 execute() 返回的输出字典
        workspace_id: 用于 Redis key 命名空间隔离
        instance_id: 用于 Redis key 命名空间隔离及批量清理
        redis: Redis async 客户端实例

    Returns:
        新 dict，大字段已被 pointer 替换；或原值（非 dict 输入 / Redis 失败时）
    """
    if not isinstance(state_delta, dict):
        # 非 dict 输出（如 if_else 节点返回 bool），不处理
        return state_delta

    out: dict[str, Any] = {}
    for key, value in state_delta.items():
        # 计算 JSON 编码字节数
        try:
            encoded = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # 不可序列化（如包含 lambda），保留原值让 LangGraph 自行处理
            out[key] = value
            continue

        size = len(encoded.encode("utf-8"))
        if size > LARGE_THRESHOLD_BYTES:
            ptr_uuid = uuid.uuid4().hex
            redis_key = _redis_key(workspace_id, instance_id, ptr_uuid)
            try:
                await redis.set(redis_key, encoded, ex=TTL_SECONDS)
                out[key] = f"{POINTER_PREFIX}{ptr_uuid}"
                logger.debug(
                    "state_pointer: 字段 %r 大小 %d bytes → Redis pointer %s",
                    key, size, ptr_uuid,
                )
            except Exception as exc:
                # Redis 不可用降级：保留原值，不阻断节点执行
                logger.warning(
                    "state_pointer: Redis 写入失败，降级保留原值（key=%r, size=%d）: %s",
                    key, size, exc,
                )
                out[key] = value
        else:
            out[key] = value

    return out


async def read_state_with_pointers(
    state: Any,
    *,
    workspace_id: UUID,
    instance_id: UUID,
    redis: Redis,
) -> Any:
    """递归扫描 state，遇到 pointer 字符串透明从 Redis 拉回真实值。

    遍历规则：
    - str + is_pointer → 从 Redis 取回原始 JSON，反序列化后返回
    - dict → 递归处理每个 value
    - list → 递归处理每个元素
    - 其他 → 原样返回

    Pointer 缺失处理：Redis key 不存在（过期或未写入）时，
    返回 ``{"__ptr_missing__": pointer}`` 标记，**不抛错**。

    Args:
        state: 任意 state 值（str / dict / list / 其他）
        workspace_id: 用于构建 Redis key
        instance_id: 用于构建 Redis key
        redis: Redis async 客户端实例

    Returns:
        解引用后的值
    """
    if is_pointer(state):
        ptr_uuid = parse_pointer(state)
        redis_key = _redis_key(workspace_id, instance_id, ptr_uuid)
        try:
            encoded = await redis.get(redis_key)
        except Exception as exc:
            logger.warning("state_pointer: Redis 读取失败（ptr=%s）: %s", ptr_uuid, exc)
            return {"__ptr_missing__": state}

        if encoded is None:
            logger.warning("state_pointer: pointer 已过期或不存在（ptr=%s）", ptr_uuid)
            return {"__ptr_missing__": state}

        # decode_responses=True 时 encoded 是 str；否则是 bytes
        raw = encoded if isinstance(encoded, str) else encoded.decode("utf-8")
        return json.loads(raw)

    if isinstance(state, dict):
        return {
            k: await read_state_with_pointers(
                v, workspace_id=workspace_id, instance_id=instance_id, redis=redis,
            )
            for k, v in state.items()
        }

    if isinstance(state, list):
        return [
            await read_state_with_pointers(
                v, workspace_id=workspace_id, instance_id=instance_id, redis=redis,
            )
            for v in state
        ]

    return state


async def cleanup_instance_pointers(
    workspace_id: UUID,
    instance_id: UUID,
    *,
    redis: Redis,
) -> int:
    """批量删除某实例的所有 state pointers（Phase 7 自动清理使用）。

    使用 SCAN 迭代避免 KEYS 大集合阻塞。

    Args:
        workspace_id: 工作区 UUID
        instance_id: 流程实例 UUID
        redis: Redis async 客户端实例

    Returns:
        删除的 key 数量
    """
    pattern = f"{REDIS_KEY_PREFIX}:{workspace_id}:{instance_id}:*"
    deleted = 0
    async for key in redis.scan_iter(match=pattern, count=100):
        await redis.delete(key)
        deleted += 1
    logger.info(
        "state_pointer: 清理实例 %s/%s 的 %d 个 pointers",
        workspace_id, instance_id, deleted,
    )
    return deleted
