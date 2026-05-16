"""EventBus 单元测试。

使用 fakeredis 模拟 Redis（不需要真实 Redis），覆盖：
- publish：seq 递增 / Redis Stream 写入 / pub/sub 发布
- replay_from_seq：按 seq 过滤 / 空 Stream
- subscribe：收到事件
- Stream maxlen：超过上限后自动截断
- pub/sub channel 隔离：不同 instance 不串扰

约定：
- 每个测试使用独立的 fakeredis 实例（不共享状态）
- 不使用真实 Redis，不依赖 conftest.py
"""
from __future__ import annotations

import asyncio
import json
import uuid

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.agent_builder.workflow.event_bus import (
    EventBus,
    EVENT_NODE_START,
    EVENT_NODE_COMPLETE,
    EVENT_INSTANCE_COMPLETE,
    EVENT_INSTANCE_FAILED,
    _pubsub_channel,
    _seq_key,
    _stream_key,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def fake_redis():
    """每个测试使用独立的 fakeredis.aioredis.FakeRedis 实例。"""
    r = await fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def bus(fake_redis):
    """EventBus 实例（绑定 fake_redis）。"""
    return EventBus(fake_redis)


# ── 测试 1：publish 每次调用 seq 单调递增 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_increments_seq(bus):
    """连发 3 个事件，seq 应分别为 1 / 2 / 3。"""
    inst_id = uuid.uuid4()
    p1 = await bus.publish(inst_id, EVENT_NODE_START, {"node_id": "a"})
    p2 = await bus.publish(inst_id, EVENT_NODE_COMPLETE, {"node_id": "a"})
    p3 = await bus.publish(inst_id, EVENT_INSTANCE_COMPLETE, {"final_status": "completed"})

    assert p1["id"] == 1
    assert p2["id"] == 2
    assert p3["id"] == 3


# ── 测试 2：publish 写入 Redis Stream ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_writes_to_xstream(bus, fake_redis):
    """publish 后，Redis Stream 应有 1 条记录，内容与 packet 一致。"""
    inst_id = uuid.uuid4()
    packet = await bus.publish(inst_id, EVENT_NODE_START, {"node_id": "start"})

    entries = await fake_redis.xrange(_stream_key(inst_id), "-", "+")
    assert len(entries) == 1

    _entry_id, fields = entries[0]
    stored = json.loads(fields["packet"])
    assert stored["id"] == packet["id"]
    assert stored["event"] == EVENT_NODE_START
    assert stored["instance_id"] == str(inst_id)
    assert stored["data"]["node_id"] == "start"


# ── 测试 3：publish 同时发布到 pub/sub ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_publishes_to_pubsub(fake_redis):
    """publish 后，pub/sub 频道应能收到同一 packet。"""
    inst_id = uuid.uuid4()
    bus = EventBus(fake_redis)

    received = []

    async def subscriber():
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(_pubsub_channel(inst_id))
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received.append(json.loads(msg["data"]))
                break
        await pubsub.aclose()

    # 先启动订阅，再 publish
    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0.05)  # 等订阅建立

    packet = await bus.publish(inst_id, EVENT_NODE_COMPLETE, {"node_id": "n1"})
    await asyncio.wait_for(sub_task, timeout=3.0)

    assert len(received) == 1
    assert received[0]["id"] == packet["id"]
    assert received[0]["event"] == EVENT_NODE_COMPLETE


# ── 测试 4：replay_from_seq 按 seq 过滤 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_from_seq_filters_correctly(bus):
    """publish 5 个事件，replay_from_seq(last_seq=2) 应只返回 seq 3/4/5。"""
    inst_id = uuid.uuid4()
    for i in range(5):
        await bus.publish(inst_id, EVENT_NODE_START, {"node_id": f"n{i}"})

    replayed = []
    async for packet in bus.replay_from_seq(inst_id, last_seq=2):
        replayed.append(packet)

    assert len(replayed) == 3
    assert [p["id"] for p in replayed] == [3, 4, 5]


# ── 测试 5：replay_from_seq 空 Stream 不 yield ─────────────────────────────────

@pytest.mark.asyncio
async def test_replay_empty_stream(bus):
    """空 Stream 时 replay_from_seq 应不产生任何 yield。"""
    inst_id = uuid.uuid4()
    replayed = []
    async for packet in bus.replay_from_seq(inst_id, last_seq=0):
        replayed.append(packet)
    assert replayed == []


# ── 测试 6：subscribe 收到 1 个事件 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_yields_events(fake_redis):
    """publish 1 个事件，subscribe 应能收到这 1 个事件。"""
    inst_id = uuid.uuid4()
    bus = EventBus(fake_redis)

    received = []

    async def sub_one():
        async for packet in bus.subscribe(inst_id):
            received.append(packet)
            break  # 收到 1 个就退出

    task = asyncio.create_task(sub_one())
    await asyncio.sleep(0.05)

    await bus.publish(inst_id, EVENT_INSTANCE_COMPLETE, {"final_status": "completed"})
    await asyncio.wait_for(task, timeout=3.0)

    assert len(received) == 1
    assert received[0]["event"] == EVENT_INSTANCE_COMPLETE


# ── 测试 7：Stream maxlen 截断 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_maxlen(fake_redis):
    """发 100 个事件，maxlen=10 → Stream 长度应 ≤ 15（近似截断允许少量超出）。"""
    inst_id = uuid.uuid4()
    # 使用自定义 EventBus 子类，覆盖 maxlen 参数
    from app.agent_builder.workflow import event_bus as eb_module

    # 临时 patch EVENT_LOG_MAX 为 10，测试截断逻辑
    original_max = eb_module.EVENT_LOG_MAX
    eb_module.EVENT_LOG_MAX = 10
    try:
        bus = EventBus(fake_redis)
        for i in range(100):
            await bus.publish(inst_id, EVENT_NODE_START, {"node_id": f"n{i}"})
    finally:
        eb_module.EVENT_LOG_MAX = original_max

    entries = await fake_redis.xrange(_stream_key(inst_id), "-", "+")
    # XADD MAXLEN ~ 10 允许近似截断（实际长度可能到 15 左右）
    assert len(entries) <= 15, f"Stream 长度 {len(entries)} 超出预期上限 15"


# ── 测试 8：pub/sub channel 隔离 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pubsub_channel_isolation(fake_redis):
    """发到 inst_A 的事件，subscribe inst_B 收不到。"""
    inst_a = uuid.uuid4()
    inst_b = uuid.uuid4()
    bus = EventBus(fake_redis)

    received_b = []

    async def sub_b_with_timeout():
        try:
            pubsub = fake_redis.pubsub()
            await pubsub.subscribe(_pubsub_channel(inst_b))
            # 等待 0.3s，期间发布 inst_A 的事件，inst_B 不应收到
            try:
                async with asyncio.timeout(0.3):
                    async for msg in pubsub.listen():
                        if msg.get("type") == "message":
                            received_b.append(json.loads(msg["data"]))
            except TimeoutError:
                pass
            await pubsub.aclose()
        except Exception:
            pass

    task = asyncio.create_task(sub_b_with_timeout())
    await asyncio.sleep(0.05)

    # 发到 inst_A（不是 inst_B）
    await bus.publish(inst_a, EVENT_NODE_START, {"node_id": "x"})
    await bus.publish(inst_a, EVENT_INSTANCE_COMPLETE, {"final_status": "completed"})

    await asyncio.wait_for(task, timeout=1.0)

    assert received_b == [], f"inst_B 不应收到 inst_A 的事件，但收到了：{received_b}"
