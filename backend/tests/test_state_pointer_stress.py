"""state_pointer 压力测试。

验证 Pitfall 1 防护效果：50 个节点 × 大输出时，
state 中的 pointer 字符串体积远小于原始数据，
checkpoint 不会膨胀。

CLAUDE.md 2.2 — 集成测试，使用 fakeredis（无需真实 Redis）。
"""
from __future__ import annotations

import asyncio
import json
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor
from app.agent_builder.workflow.state_pointer import (
    POINTER_PREFIX,
    is_pointer,
)

WORKSPACE_ID = uuid.UUID("aaaaaaaa-4444-0000-0000-000000000001")
INSTANCE_ID = uuid.UUID("bbbbbbbb-4444-0000-0000-000000000001")

# 模拟 LLM 输出大小（100KB 每节点输出）
LLM_OUTPUT_SIZE = 100_000

# 测试节点数量（压力测试：50 节点）
NODE_COUNT = 50


@pytest_asyncio.fixture
async def fake_redis():
    """提供 fakeredis 实例（异步，decode_responses=True）。"""
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


class MockLLMNodeExecutor(BaseNodeExecutor):
    """模拟 LLM 节点：返回固定大小的消息（用于压力测试）。"""

    def __init__(self, node_def: dict, message_size: int = LLM_OUTPUT_SIZE, **kwargs):
        super().__init__(node_def, **kwargs)
        self._message_size = message_size

    async def execute(self, config: dict, state: dict) -> dict:
        return {
            "message": "L" * self._message_size,
            "role": "assistant",
            "usage": {"tokens": self._message_size // 4},
        }


@pytest.mark.asyncio
async def test_50_nodes_with_large_output_checkpoint_size(fake_redis):
    """50 个节点 × 100KB LLM 输出：state 中 pointer 总体积 << 原始数据总量。

    防护 Pitfall 1（checkpoint 写入放大）：
    原始数据总量 = 50 × 100KB = 5MB
    state 中 pointer 字符串（已写 Redis）应 << 1MB

    测试策略：
    - 执行 50 个 MockLLMNodeExecutor 节点
    - 收集返回的 state delta（含 pointer 字符串）
    - 计算所有 state delta 的 JSON 序列化大小
    - 断言总大小 < 500KB（实际应约 50 × 200 bytes = ~10KB）
    """
    total_state: dict = {}
    all_deltas: list[dict] = []

    for i in range(NODE_COUNT):
        node_id = f"llm_{i}"
        node_def = {"id": node_id, "type": "llm", "config": {}}
        executor = MockLLMNodeExecutor(
            node_def,
            message_size=LLM_OUTPUT_SIZE,
            workspace_id=WORKSPACE_ID,
            instance_id=INSTANCE_ID,
            redis=fake_redis,
        )
        delta = await executor(total_state)
        total_state = {**total_state, **delta}
        all_deltas.append(delta)

    # 计算所有 state delta 的 JSON 序列化大小
    all_deltas_json = json.dumps(all_deltas, ensure_ascii=False, default=str)
    total_state_size_bytes = len(all_deltas_json.encode("utf-8"))

    # 计算原始数据总量（不使用 pointer 时的大小）
    raw_data_size = NODE_COUNT * LLM_OUTPUT_SIZE  # 50 × 100KB = 5MB

    # 断言：使用 pointer 后，state 大小 < 500KB（远小于原始 5MB）
    max_allowed_bytes = 500_000  # 500KB
    assert total_state_size_bytes < max_allowed_bytes, (
        f"state 总大小 {total_state_size_bytes:,} bytes 超过限制 {max_allowed_bytes:,} bytes。"
        f"原始数据 {raw_data_size:,} bytes。Pitfall 1 防护失效！"
    )

    # 验证所有节点的 message 都是 pointer
    for i, delta in enumerate(all_deltas):
        node_id = f"llm_{i}"
        output = delta[node_id]
        assert is_pointer(output["message"]), (
            f"节点 {node_id} 的 message 未被替换为 pointer: {output['message']!r}"
        )

    # 验证压缩比：state 大小 vs 原始大小
    compression_ratio = 1 - (total_state_size_bytes / raw_data_size)
    assert compression_ratio > 0.95, (
        f"压缩比 {compression_ratio:.2%} 低于预期 95%。"
        f"State: {total_state_size_bytes:,} bytes，原始: {raw_data_size:,} bytes"
    )


@pytest.mark.asyncio
async def test_concurrent_nodes_no_race_condition(fake_redis):
    """并发写入多个节点的大字段时，不发生 Redis key 碰撞或数据混乱。"""
    node_count = 20
    message_size = 5000  # 超过 4096 bytes 阈值

    async def run_node(i: int) -> dict:
        node_id = f"concurrent_llm_{i}"
        node_def = {"id": node_id, "type": "llm", "config": {}}
        executor = MockLLMNodeExecutor(
            node_def,
            message_size=message_size,
            workspace_id=WORKSPACE_ID,
            instance_id=INSTANCE_ID,
            redis=fake_redis,
        )
        # 每个节点用不同大小的消息，便于验证
        executor._message_size = message_size + i  # type: ignore[attr-defined]
        return await executor({})

    # 并发执行 20 个节点
    results = await asyncio.gather(*[run_node(i) for i in range(node_count)])

    # 验证每个节点的 pointer 指向正确的数据
    from app.agent_builder.workflow.state_pointer import REDIS_KEY_PREFIX, read_state_with_pointers
    for i, result in enumerate(results):
        node_id = f"concurrent_llm_{i}"
        output = result[node_id]
        assert is_pointer(output["message"]), f"节点 {node_id} 未生成 pointer"

        # 解引用并验证数据完整性
        expected_msg = "L" * (message_size + i)
        resolved = await read_state_with_pointers(
            result,
            workspace_id=WORKSPACE_ID,
            instance_id=INSTANCE_ID,
            redis=fake_redis,
        )
        assert resolved[node_id]["message"] == expected_msg, (
            f"节点 {node_id} 解引用后数据不匹配（并发竞争问题）"
        )
