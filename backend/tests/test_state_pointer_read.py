"""state_pointer 读取路径单元测试。

测试 read_state_with_pointers 的递归解引用行为：
- pointer → 拉回原值
- 嵌套 dict 中的 pointer → 递归解引用
- 嵌套 list 中的 pointer → 递归解引用
- 不存在的 pointer → 返回 {__ptr_missing__: ...} 标记
- 非 pointer 字符串 → 原样返回

使用 fakeredis 作为 Redis 后端。
"""
from __future__ import annotations

import json
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.agent_builder.workflow.state_pointer import (
    POINTER_PREFIX,
    REDIS_KEY_PREFIX,
    TTL_SECONDS,
    read_state_with_pointers,
)

WORKSPACE_ID = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000001")
INSTANCE_ID = uuid.UUID("bbbbbbbb-1111-0000-0000-000000000001")


@pytest_asyncio.fixture
async def fake_redis():
    """提供 fakeredis 实例（异步，decode_responses=True）。"""
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


async def _store_pointer(
    fake_redis,
    value: object,
    workspace_id: uuid.UUID = WORKSPACE_ID,
    instance_id: uuid.UUID = INSTANCE_ID,
) -> str:
    """辅助函数：向 fakeredis 写入一个值，返回 pointer 字符串。"""
    ptr_uuid = uuid.uuid4().hex
    redis_key = f"{REDIS_KEY_PREFIX}:{workspace_id}:{instance_id}:{ptr_uuid}"
    encoded = json.dumps(value, ensure_ascii=False)
    await fake_redis.set(redis_key, encoded, ex=TTL_SECONDS)
    return f"{POINTER_PREFIX}{ptr_uuid}"


@pytest.mark.asyncio
async def test_read_pointer_resolved(fake_redis):
    """state 中包含 pointer 字符串时，read 应拉回原始值。"""
    original_value = {"text": "这是一段很长的文本内容", "tokens": 100}
    pointer = await _store_pointer(fake_redis, original_value)

    state = {"llm_output": pointer, "role": "assistant"}
    result = await read_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    assert result["llm_output"] == original_value
    assert result["role"] == "assistant"


@pytest.mark.asyncio
async def test_read_nested_dict(fake_redis):
    """嵌套 dict 中的 pointer 应被递归解引用。"""
    inner_value = "nested large value"
    pointer = await _store_pointer(fake_redis, inner_value)

    state = {
        "a": {
            "b": pointer,
            "c": "normal value",
        }
    }
    result = await read_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    assert result["a"]["b"] == inner_value
    assert result["a"]["c"] == "normal value"


@pytest.mark.asyncio
async def test_read_nested_list(fake_redis):
    """嵌套 list 中的多个 pointer 应各自被递归解引用。"""
    value1 = {"content": "first chunk"}
    value2 = {"content": "second chunk"}
    ptr1 = await _store_pointer(fake_redis, value1)
    ptr2 = await _store_pointer(fake_redis, value2)

    state = {"chunks": [ptr1, ptr2, "plain string"]}
    result = await read_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    assert result["chunks"][0] == value1
    assert result["chunks"][1] == value2
    assert result["chunks"][2] == "plain string"


@pytest.mark.asyncio
async def test_read_missing_pointer_returns_marker(fake_redis):
    """pointer 对应的 Redis key 不存在时，返回 {__ptr_missing__: pointer}，不抛错。"""
    # 构造一个不存在于 Redis 的 pointer
    fake_ptr_uuid = "0" * 32
    missing_pointer = f"{POINTER_PREFIX}{fake_ptr_uuid}"

    state = {"output": missing_pointer}
    result = await read_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    assert result["output"] == {"__ptr_missing__": missing_pointer}


@pytest.mark.asyncio
async def test_read_non_pointer_string_passthrough(fake_redis):
    """非 pointer 的普通字符串应原样返回，不尝试 Redis 查询。"""
    plain_string = "just a normal string"

    result = await read_state_with_pointers(
        plain_string,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    assert result == plain_string
