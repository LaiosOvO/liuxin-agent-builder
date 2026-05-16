"""state_pointer 阈值边界测试。

测试 4096 bytes 边界及 UTF-8 多字节字符计数的正确性。

边界定义：
- 恰好 4096 bytes（JSON 编码后）→ 不替换
- 4097 bytes → 替换为 pointer
- 中文字符按 UTF-8 计算（每个汉字 3 bytes）
"""
from __future__ import annotations

import json
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.agent_builder.workflow.state_pointer import (
    LARGE_THRESHOLD_BYTES,
    POINTER_PREFIX,
    is_pointer,
    write_state_with_pointers,
)

WORKSPACE_ID = uuid.UUID("aaaaaaaa-2222-0000-0000-000000000001")
INSTANCE_ID = uuid.UUID("bbbbbbbb-2222-0000-0000-000000000001")


@pytest_asyncio.fixture
async def fake_redis():
    """提供 fakeredis 实例（异步，decode_responses=True）。"""
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


def _make_string_of_json_bytes(n: int) -> str:
    """构造一个 JSON 编码后 UTF-8 恰好为 n bytes 的字符串。

    json.dumps("x"*k) = '"' + 'x'*k + '"' = k+2 bytes（全 ASCII）
    所以字符串长度 = n - 2
    """
    assert n >= 2
    return "a" * (n - 2)


@pytest.mark.asyncio
async def test_exact_4096_bytes_not_replaced(fake_redis):
    """JSON 编码后恰好等于 4096 bytes 的字段不应被替换（边界：> 不含等于）。"""
    # 构造 JSON 恰好 4096 bytes 的字符串
    s = _make_string_of_json_bytes(LARGE_THRESHOLD_BYTES)
    encoded = json.dumps(s, ensure_ascii=False)
    assert len(encoded.encode("utf-8")) == LARGE_THRESHOLD_BYTES, (
        f"构造失败：期望 {LARGE_THRESHOLD_BYTES} bytes，实际 {len(encoded.encode('utf-8'))} bytes"
    )

    state = {"field": s}
    result = await write_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    # 恰好等于阈值，不应被替换
    assert result["field"] == s
    assert not is_pointer(result["field"])


@pytest.mark.asyncio
async def test_4097_bytes_replaced(fake_redis):
    """JSON 编码后超过 4096 bytes（如 4097 bytes）的字段应被替换为 pointer。"""
    # 构造 JSON 恰好 4097 bytes 的字符串
    s = _make_string_of_json_bytes(LARGE_THRESHOLD_BYTES + 1)
    encoded = json.dumps(s, ensure_ascii=False)
    assert len(encoded.encode("utf-8")) == LARGE_THRESHOLD_BYTES + 1, (
        f"构造失败：期望 {LARGE_THRESHOLD_BYTES + 1} bytes，实际 {len(encoded.encode('utf-8'))} bytes"
    )

    state = {"field": s}
    result = await write_state_with_pointers(
        state,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    # 超过阈值，应被替换
    assert is_pointer(result["field"]), f"期望 pointer，实际: {result['field']!r}"
    assert result["field"].startswith(POINTER_PREFIX)


@pytest.mark.asyncio
async def test_chinese_utf8_bytes_counted(fake_redis):
    """中文字符的字节数按 UTF-8 计算（每个汉字 3 bytes）。

    构造：json.dumps('中' * k, ensure_ascii=False) 的 UTF-8 大小
    = 2（引号）+ k * 3 = 3k + 2 bytes

    选 k = 1366 → 3*1366 + 2 = 4100 bytes > 4096 → 应被替换
    选 k = 1364 → 3*1364 + 2 = 4094 bytes < 4096 → 不被替换
    """
    # 1364 个汉字：4094 bytes < 4096，不替换
    small_chinese = "中" * 1364
    small_encoded = json.dumps(small_chinese, ensure_ascii=False).encode("utf-8")
    assert len(small_encoded) == 4094  # 确认构造正确

    state_small = {"text": small_chinese}
    result_small = await write_state_with_pointers(
        state_small,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )
    assert result_small["text"] == small_chinese
    assert not is_pointer(result_small["text"])

    # 1366 个汉字：4100 bytes > 4096，替换
    large_chinese = "中" * 1366
    large_encoded = json.dumps(large_chinese, ensure_ascii=False).encode("utf-8")
    assert len(large_encoded) == 4100  # 确认构造正确

    state_large = {"text": large_chinese}
    result_large = await write_state_with_pointers(
        state_large,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )
    assert is_pointer(result_large["text"]), (
        f"4100 bytes 中文字符串应被替换，实际: {result_large['text']!r}"
    )
