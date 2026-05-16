"""EventBus — Redis pub/sub + Redis Stream 事件桥接模块。

架构职责：
- publish()：同时写 Redis Stream（补发历史用）+ Redis pub/sub（实时推送用）
- subscribe()：返回 async generator，持续接收 pub/sub 消息
- replay_from_seq()：从 Redis Stream 取 seq > last_seq 的历史事件（断连重连用）

设计决策（CONTEXT.md + CLAUDE.md 2.7 Dify 参考）：
- Redis Stream key：agent_builder:instance_event_log:<instance_id>（保留 1 小时）
- Redis pub/sub channel：agent_builder:instance_events:<instance_id>
- seq 用 Redis INCR 单调递增（每 instance 独立计数器）
- 事件 payload：{id, event, instance_id, timestamp, data}

参考来源：
- docs/reading-dify-02-07-execution-sse-2026-05-16.md：Dify QueueNodeStartedEvent 等事件命名规范
- Dify 无断连补发（内存队列），本项目用 Redis Stream 补发是超越 Dify 的改进
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Redis Stream 最大长度（保留约 1 小时的事件，每秒约 1 个节点事件）
EVENT_LOG_MAX = 3600

# Redis Stream key TTL（秒）
EVENT_LOG_TTL = 3600

# 事件类型常量
EVENT_NODE_START = "node.start"
EVENT_NODE_COMPLETE = "node.complete"
EVENT_NODE_ERROR = "node.error"
EVENT_STATE_UPDATE = "state.update"
EVENT_INSTANCE_COMPLETE = "instance.complete"
EVENT_INSTANCE_FAILED = "instance.failed"


def _pubsub_channel(instance_id: UUID) -> str:
    """Redis pub/sub channel 名称。

    格式：agent_builder:instance_events:<instance_id>
    """
    return f"agent_builder:instance_events:{instance_id}"


def _stream_key(instance_id: UUID) -> str:
    """Redis Stream key 名称。

    格式：agent_builder:instance_event_log:<instance_id>
    """
    return f"agent_builder:instance_event_log:{instance_id}"


def _seq_key(instance_id: UUID) -> str:
    """Redis 单调序号 key 名称。

    格式：agent_builder:instance_event_seq:<instance_id>
    每 instance 独立计数，INCR 后作为事件 id
    """
    return f"agent_builder:instance_event_seq:{instance_id}"


class EventBus:
    """Redis 事件总线。

    线程安全（asyncio）：publish / subscribe / replay_from_seq 均为协程。
    所有方法参数均不可变；publish 返回新 packet dict（不修改输入）。
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(
        self,
        instance_id: UUID,
        event: str,
        data: dict,
    ) -> dict:
        """发布事件：同时写 Redis Stream + Redis pub/sub。

        算法：
        1. INCR seq_key 获取单调序号
        2. 构造 packet dict（不可变，新建，不修改 data）
        3. XADD 到 Redis Stream（MAXLEN ~ EVENT_LOG_MAX，近似截断）
        4. EXPIRE Stream key（EVENT_LOG_TTL 秒）
        5. PUBLISH 到 pub/sub channel

        Args:
            instance_id: 流程实例 UUID
            event: 事件类型字符串（如 "node.start"）
            data: 事件附加数据（不可变，publish 内部不修改）

        Returns:
            新建的 packet dict（含 id / event / instance_id / timestamp / data）
        """
        seq = await self.redis.incr(_seq_key(instance_id))
        packet = {
            "id": seq,
            "event": event,
            "instance_id": str(instance_id),
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }
        encoded = json.dumps(packet, ensure_ascii=False)

        # 写 Redis Stream（保留历史，用于断连补发）
        await self.redis.xadd(
            _stream_key(instance_id),
            {"packet": encoded},
            maxlen=EVENT_LOG_MAX,
            approximate=True,
        )
        # 刷新 TTL（每次 publish 延长保留期）
        await self.redis.expire(_stream_key(instance_id), EVENT_LOG_TTL)

        # 实时广播（pub/sub fan-out，多个 SSE 订阅者均可收到）
        await self.redis.publish(_pubsub_channel(instance_id), encoded)

        logger.debug(
            "EventBus.publish: instance=%s event=%s seq=%d",
            instance_id, event, seq,
        )
        return packet

    async def subscribe(self, instance_id: UUID):
        """订阅 instance 的实时事件流（async generator）。

        使用 Redis pub/sub 订阅；yield 每条收到的事件 dict。
        退出时自动取消订阅并关闭 pubsub 连接。

        用法：
            async for packet in bus.subscribe(instance_id):
                print(packet)

        Args:
            instance_id: 流程实例 UUID

        Yields:
            事件 packet dict（来自 pub/sub 消息解析）
        """
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(_pubsub_channel(instance_id))
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    raw = msg["data"]
                    # decode_responses=True 时 raw 是 str；否则是 bytes
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    yield json.loads(raw)
        finally:
            try:
                await pubsub.unsubscribe(_pubsub_channel(instance_id))
                await pubsub.aclose()
            except Exception as exc:
                logger.warning("EventBus.subscribe cleanup 失败: %s", exc)

    async def replay_from_seq(self, instance_id: UUID, last_seq: int):
        """从 Redis Stream 补发 seq > last_seq 的历史事件（断连重连用）。

        全量扫描 Stream，过滤 id > last_seq 的事件按序 yield。
        Stream 为空时不 yield，直接返回。

        Args:
            instance_id: 流程实例 UUID
            last_seq: 上次收到的最大序号（0 表示从头补发）

        Yields:
            事件 packet dict，按 seq 升序
        """
        entries = await self.redis.xrange(_stream_key(instance_id), "-", "+")
        for _entry_id, fields in entries:
            raw = fields.get("packet", "")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if not raw:
                continue
            packet = json.loads(raw)
            if packet.get("id", 0) > last_seq:
                yield packet
