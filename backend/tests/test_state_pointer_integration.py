"""state_pointer 与 BaseNodeExecutor 集成测试。

测试 State Pointer Pattern 在 BaseNodeExecutor.__call__ 中的透明集成：
- 小输出不触发 pointer
- 大输出自动写 Redis 并替换为 pointer
- 下游节点透明解引用（read_state_with_pointers 在入口自动触发）
- 嵌套字段选择性替换（只替换超阈值字段）
- cleanup_instance_pointers 批量清理
- 无 pointer 上下文时节点正常工作（向后兼容）

使用 fakeredis 作为 Redis 后端（无需真实 Redis 实例）。
"""
from __future__ import annotations

import json
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.agent_builder.workflow.nodes.base import BaseNodeExecutor, NodeExecutionError
from app.agent_builder.workflow.state_pointer import (
    LARGE_THRESHOLD_BYTES,
    POINTER_PREFIX,
    cleanup_instance_pointers,
    is_pointer,
)

WORKSPACE_ID = uuid.UUID("aaaaaaaa-3333-0000-0000-000000000001")
INSTANCE_ID = uuid.UUID("bbbbbbbb-3333-0000-0000-000000000001")


@pytest_asyncio.fixture
async def fake_redis():
    """提供 fakeredis 实例（异步，decode_responses=True）。"""
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


def make_node_def(node_id: str, output: dict | str) -> dict:
    """辅助函数：构造节点定义字典。"""
    return {"id": node_id, "type": "echo", "config": {"output": output}}


class EchoNodeExecutor(BaseNodeExecutor):
    """简单的 echo 节点：直接返回 config["output"]（用于测试）。"""

    async def execute(self, config: dict, state: dict) -> dict:
        return config["output"]


class LargeOutputNodeExecutor(BaseNodeExecutor):
    """模拟 LLM 节点：返回大文本 + 小字段（用于测试选择性 pointer 替换）。

    固定返回：{message: "x"*N, usage: {tokens: 100}}
    其中 message 超过阈值，usage 不超过。
    """

    def __init__(self, node_def: dict, message_size: int = 10000, **kwargs):
        super().__init__(node_def, **kwargs)
        self._message_size = message_size

    async def execute(self, config: dict, state: dict) -> dict:
        return {
            "message": "x" * self._message_size,
            "role": "assistant",
            "usage": {"input_tokens": 50, "output_tokens": self._message_size // 4},
        }


class DownstreamNodeExecutor(BaseNodeExecutor):
    """下游节点：读取上游节点的 message 字段（用于验证透明解引用）。

    返回 message 的前 10 个字符（截断），避免 result 本身超阈值被再次 pointer 化。
    """

    async def execute(self, config: dict, state: dict) -> dict:
        # 从 state 中读取上游节点 llm_1 的 message
        llm_output = state.get("llm_1", {})
        upstream_message = llm_output.get("message", "") if isinstance(llm_output, dict) else ""
        # 截取前 10 个字符确认是真实值（"xxxx..."），避免 result 本身超阈值
        message_prefix = upstream_message[:10] if upstream_message else ""
        message_len = len(upstream_message)
        return {"message_prefix": message_prefix, "message_len": message_len, "ok": True}


@pytest.mark.asyncio
async def test_node_with_small_output(fake_redis):
    """小输出的节点不触发 pointer，state 直接存原值。"""
    node_def = {"id": "echo_1", "type": "echo", "config": {"output": {"text": "short"}}}
    executor = EchoNodeExecutor(
        node_def,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    state = {}
    result = await executor(state)

    assert result == {"echo_1": {"text": "short"}}
    # 不应有任何 pointer key 写入 Redis
    keys = [k async for k in fake_redis.scan_iter(match="agent_builder:state_ptr:*")]
    assert len(keys) == 0


@pytest.mark.asyncio
async def test_node_with_large_output(fake_redis):
    """大输出（>4KB message）的节点自动写 Redis 并替换为 pointer。"""
    node_def = {"id": "llm_1", "type": "llm", "config": {}}
    executor = LargeOutputNodeExecutor(
        node_def,
        message_size=10000,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    state = {}
    result = await executor(state)

    llm_output = result["llm_1"]
    # message 超过阈值，应被替换为 pointer
    assert is_pointer(llm_output["message"]), f"期望 pointer，实际: {llm_output['message']!r}"
    # role 不超过阈值，保留原值
    assert llm_output["role"] == "assistant"
    # usage 不超过阈值，保留原值
    assert llm_output["usage"]["input_tokens"] == 50

    # Redis 中应有真实 message
    ptr = llm_output["message"]
    ptr_uuid = ptr[len(POINTER_PREFIX):]
    from app.agent_builder.workflow.state_pointer import REDIS_KEY_PREFIX
    redis_key = f"{REDIS_KEY_PREFIX}:{WORKSPACE_ID}:{INSTANCE_ID}:{ptr_uuid}"
    stored = await fake_redis.get(redis_key)
    assert stored is not None
    assert json.loads(stored) == "x" * 10000


@pytest.mark.asyncio
async def test_downstream_node_reads_pointer(fake_redis):
    """节点 A 输出大文本（被替换为 pointer），节点 B 透明解引用并读到真实值。"""
    # 节点 A（LLM 大输出）
    llm_node_def = {"id": "llm_1", "type": "llm", "config": {}}
    llm_executor = LargeOutputNodeExecutor(
        llm_node_def,
        message_size=10000,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    # 节点 A 执行，state 中 llm_1.message 被替换为 pointer
    state: dict = {}
    result_a = await llm_executor(state)
    # 合并进 state（模拟 LangGraph merge）
    state = {**state, **result_a}

    # 验证 state 中 message 是 pointer
    assert is_pointer(state["llm_1"]["message"])

    # 节点 B（下游，读上游 message）
    downstream_node_def = {"id": "downstream_1", "type": "echo", "config": {"output": {}}}
    downstream_executor = DownstreamNodeExecutor(
        downstream_node_def,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    # 节点 B 执行时，__call__ 入口自动 read_state_with_pointers，解引用 pointer
    result_b = await downstream_executor(state)

    # 下游节点应看到真实 message（截取前10字符验证），而非 pointer 字符串
    assert result_b["downstream_1"]["message_prefix"] == "x" * 10, (
        f"下游节点未透明解引用 pointer，前缀: {result_b['downstream_1']['message_prefix']!r}"
    )
    assert result_b["downstream_1"]["message_len"] == 10000
    assert result_b["downstream_1"]["ok"] is True


@pytest.mark.asyncio
async def test_pointer_with_nested_dict_selective_replacement(fake_redis):
    """节点输出 {message: 10KB, usage: {tokens: 100}} 时，
    仅 message 被替换，usage 保留原值（选择性替换）。"""
    node_def = {"id": "llm_2", "type": "llm", "config": {}}
    executor = LargeOutputNodeExecutor(
        node_def,
        message_size=10000,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )

    result = await executor({})
    output = result["llm_2"]

    # message 超阈值 → pointer
    assert is_pointer(output["message"])
    # role 未超阈值 → 原值
    assert output["role"] == "assistant"
    # usage 是小 dict → 原值（不替换整体 dict，只替换超阈值的顶层字段）
    assert isinstance(output["usage"], dict)
    assert output["usage"]["input_tokens"] == 50


@pytest.mark.asyncio
async def test_pointer_cleanup_on_instance_complete(fake_redis):
    """cleanup_instance_pointers 应删除该实例所有 pointer key。"""
    # 写入几个 pointer
    node_def = {"id": "llm_3", "type": "llm", "config": {}}
    executor = LargeOutputNodeExecutor(
        node_def,
        message_size=10000,
        workspace_id=WORKSPACE_ID,
        instance_id=INSTANCE_ID,
        redis=fake_redis,
    )
    for _ in range(3):
        await executor({})

    # 验证有 key 写入
    keys_before = [k async for k in fake_redis.scan_iter(
        match=f"agent_builder:state_ptr:{WORKSPACE_ID}:{INSTANCE_ID}:*"
    )]
    assert len(keys_before) >= 3

    # 清理
    deleted = await cleanup_instance_pointers(
        WORKSPACE_ID, INSTANCE_ID, redis=fake_redis,
    )
    assert deleted >= 3

    # 验证已清理
    keys_after = [k async for k in fake_redis.scan_iter(
        match=f"agent_builder:state_ptr:{WORKSPACE_ID}:{INSTANCE_ID}:*"
    )]
    assert len(keys_after) == 0


@pytest.mark.asyncio
async def test_pointer_context_optional(fake_redis):
    """BaseNodeExecutor 未注入 pointer 上下文时，节点正常执行（向后兼容）。"""
    # 不传 workspace_id / instance_id / redis
    node_def = {"id": "echo_2", "type": "echo", "config": {"output": {"text": "hello"}}}
    executor = EchoNodeExecutor(node_def)  # 无 pointer 上下文

    result = await executor({})
    assert result == {"echo_2": {"text": "hello"}}

    # 即使有大字段，也不触发 pointer（因为没有上下文）
    big_node_def = {"id": "big_echo", "type": "echo", "config": {"output": {"text": "x" * 10000}}}

    class BigEchoExecutor(BaseNodeExecutor):
        async def execute(self, config: dict, state: dict) -> dict:
            return {"text": "x" * 10000}

    big_executor = BigEchoExecutor(big_node_def)  # 无 pointer 上下文
    big_result = await big_executor({})
    # 无 pointer 上下文，大字段直接返回（不走 pointer）
    assert big_result["big_echo"]["text"] == "x" * 10000
