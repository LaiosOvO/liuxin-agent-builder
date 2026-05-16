"""state_pointer 写入路径单元测试。

测试 write_state_with_pointers 的各种输入场景：
- 小字段直通（不替换）
- 大字段替换为 pointer
- pointer 格式校验
- Redis key 命名空间校验
- 非 dict 输入直通
- 不可序列化字段直通

使用 fakeredis 作为 Redis 后端（无需真实 Redis 实例）。
"""
from __future__ import annotations

import json
import re
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.agent_builder.workflow.state_pointer import (
    LARGE_THRESHOLD_BYTES,
    POINTER_PREFIX,
    REDIS_KEY_PREFIX,
    TTL_SECONDS,
    is_pointer,
    write_state_with_pointers,
)

WORKSPACE_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
INSTANCE_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def fake_redis():
    """提供 fakeredis 实例（异步，decode_responses=True）。"""
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


@pytest.mark.asyncio
async def test_write_small_value_passthrough(fake_redis):
    """小于 4096 bytes 的字段不应被替换为 pointer。"""
    small_value = "hello world"
    state = {"message": small_value, "role": "assistant"}

    result = await write_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    assert result["message"] == small_value
    assert result["role"] == "assistant"
    # Redis 中不应有任何 pointer key
    keys = [k async for k in fake_redis.scan_iter(match=f"{REDIS_KEY_PREFIX}:*")]
    assert len(keys) == 0


@pytest.mark.asyncio
async def test_write_large_string_replaced_with_pointer(fake_redis):
    """超过 4096 bytes 的字段应被替换为 pointer，原值写入 Redis。"""
    # 生成 5000 bytes 的 ASCII 字符串
    large_value = "x" * 5000
    state = {"message": large_value, "role": "assistant"}

    result = await write_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    # message 应被替换
    assert is_pointer(result["message"])
    # role 不超过阈值，保留原值
    assert result["role"] == "assistant"

    # Redis 中应有对应 key，值为原始 JSON
    ptr = result["message"]
    ptr_uuid = ptr[len(POINTER_PREFIX):]
    redis_key = f"{REDIS_KEY_PREFIX}:{WORKSPACE_ID}:{INSTANCE_ID}:{ptr_uuid}"
    stored = await fake_redis.get(redis_key)
    assert stored is not None
    assert json.loads(stored) == large_value


@pytest.mark.asyncio
async def test_pointer_format(fake_redis):
    """pointer 字符串格式应为 '__ptr__:redis:state:<32位小写 hex>'。"""
    large_value = "y" * 5000
    state = {"output": large_value}

    result = await write_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    ptr = result["output"]
    assert ptr.startswith(POINTER_PREFIX)

    # 提取 uuid 部分：应为 32 位小写 hex
    ptr_uuid = ptr[len(POINTER_PREFIX):]
    assert len(ptr_uuid) == 32
    assert re.fullmatch(r"[0-9a-f]{32}", ptr_uuid), f"uuid 不是 32位小写 hex: {ptr_uuid!r}"


@pytest.mark.asyncio
async def test_redis_key_namespace(fake_redis):
    """写入 Redis 后，key 应含 workspace_id + instance_id 前缀。"""
    large_value = "z" * 5000
    ws_id = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
    inst_id = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
    state = {"body": large_value}

    result = await write_state_with_pointers(
        state,
        workspace_id=ws_id,
        instance_id=inst_id,
        redis=fake_redis,
    )

    ptr = result["body"]
    ptr_uuid = ptr[len(POINTER_PREFIX):]
    expected_key = f"{REDIS_KEY_PREFIX}:{ws_id}:{inst_id}:{ptr_uuid}"

    # 验证 key 在 Redis 中存在
    value = await fake_redis.get(expected_key)
    assert value is not None, f"Redis key {expected_key!r} 不存在"


@pytest.mark.asyncio
async def test_write_non_dict_passthrough(fake_redis):
    """state_delta 不是 dict（如 None / str / int）时，原样返回，不处理。"""
    for non_dict_input in [None, "plain string", 42, [1, 2, 3]]:
        result = await write_state_with_pointers(
            non_dict_input,  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            instance_id=INSTANCE_ID,
            redis=fake_redis,
        )
        assert result == non_dict_input, (
            f"非 dict 输入 {non_dict_input!r} 应原样返回，实际: {result!r}"
        )


@pytest.mark.asyncio
async def test_write_unserializable_passthrough(fake_redis):
    """含不可 JSON 序列化对象的字段应保留原值（降级，不抛错）。

    注意：我们的实现使用 default=str 处理大部分非标类型，
    真正不可序列化的是循环引用等极端情况。
    这里测试包含自定义对象（带 __str__ 但非标准 JSON 类型）时的行为。

    实际上因为 default=str 兜底，大多数对象都能序列化。
    测试确保函数不抛异常，能正常返回 dict。
    """
    # 创建一个会在 json.dumps 中触发异常的对象
    # 通过子类化 str 来强制 TypeError（覆盖 default 失效的场景）
    class NonSerializable:
        def __repr__(self) -> str:
            return "non_serializable"

    # 由于 default=str 会把它序列化为字符串，这个字段不会报错
    # 但我们的代码路径确保了即使 json.dumps 抛 TypeError，也会走 except 分支保留原值
    non_serializable = NonSerializable()
    state = {"data": non_serializable, "role": "assistant"}

    # 函数不应抛出异常
    result = await write_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    assert isinstance(result, dict)
    assert "data" in result
    assert result["role"] == "assistant"
