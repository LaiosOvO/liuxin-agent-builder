"""SSE 端点 — 实例事件实时推送。

端点：
    GET /api/agent_builder/v1/instances/{instance_id}/events

功能：
1. 鉴权：复用 Phase 1 session cookie（Depends(get_current_user)）
2. 权限：校验 instance 属于当前 workspace，否则 404
3. 补发：Last-Event-ID 头 → replay_from_seq 补发历史事件
4. 实时：订阅 Redis pub/sub，持续 yield ServerSentEvent
5. 结束：instance.complete / instance.failed 时自然关闭 SSE 连接

参考来源：
- docs/reading-dify-02-07-execution-sse-2026-05-16.md：Dify 无断连补发（改进点）
- PLAN 02-07 sse_endpoint 段
- CONTEXT.md：SSE channel 路由 + Redis pub/sub fan-out + Last-Event-ID 补发决策

Nginx 配置要求（docs/plans/2026-05-16-agent-builder-design.md）：
    proxy_buffering off
    proxy_read_timeout 3600s
    X-Accel-Buffering: no
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_current_user
from app.agent_builder.db.session import get_db
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.user import User
from app.agent_builder.workflow.event_bus import EVENT_INSTANCE_COMPLETE, EVENT_INSTANCE_FAILED, EventBus
from app.agent_builder.workflow.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sse"])


# ── SSE 事件流端点 ─────────────────────────────────────────────────────────────────

@router.get(
    "/instances/{instance_id}/events",
    summary="订阅实例事件流（SSE）",
    description=(
        "实时订阅工作流实例的节点事件流（SSE）。\n\n"
        "支持断连重连：客户端重连时带 Last-Event-ID 头，服务端自动从 Redis Stream 补发历史事件。\n\n"
        "事件类型：node.start / node.complete / node.error / state.update / instance.complete / instance.failed\n\n"
        "instance.complete / instance.failed 事件后，服务端自动关闭 SSE 连接。"
    ),
    response_class=EventSourceResponse,
)
async def stream_instance_events(
    instance_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    """SSE 实例事件流。

    Args:
        instance_id: 要订阅的流程实例 UUID
        request: FastAPI Request（用于断连检测 request.is_disconnected()）
        current_user: 当前登录用户（session cookie 鉴权）
        db: AsyncSession
        last_event_id: HTTP Last-Event-ID 头（断连重连补发用）

    Returns:
        EventSourceResponse（持续 text/event-stream 响应）

    Raises:
        HTTPException(401): 未登录
        HTTPException(404): instance 不存在或不属于当前 workspace
    """
    ws_id: UUID = request.state.current_workspace_id

    # 1. 加载 instance + workspace 权限校验（WorkspaceScopedQuery 等价）
    result = await db.execute(
        select(FlowInstance).where(FlowInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()

    if instance is None or instance.workspace_id != ws_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"实例 {instance_id} 不存在或无权限访问",
        )

    redis = get_redis()
    bus = EventBus(redis)

    # 解析 Last-Event-ID（用于断连补发）
    last_seq = 0
    if last_event_id:
        try:
            last_seq = int(last_event_id)
        except ValueError:
            last_seq = 0

    logger.info(
        "SSE: 用户 %s 订阅实例 %s 事件 (last_seq=%d)",
        current_user.id, instance_id, last_seq,
    )

    async def event_generator() -> AsyncIterator[ServerSentEvent]:
        """SSE 事件生成器（按 PLAN 02-07 sse_endpoint 实现）。

        流程：
        1. 断连检测：request.is_disconnected() 为 True 时退出
        2. 补发历史：replay_from_seq(last_seq) 发历史事件
        3. 实时订阅：subscribe() 发实时事件
        4. 自动结束：instance.complete / instance.failed 事件后 return
        """
        # ── 阶段 1：补发历史事件（Last-Event-ID 之后）────────────────────────────
        async for packet in bus.replay_from_seq(instance_id, last_seq):
            if await request.is_disconnected():
                logger.debug("SSE: 客户端断连（补发阶段），退出 %s", instance_id)
                return
            yield ServerSentEvent(
                id=str(packet["id"]),
                event=packet["event"],
                data=json.dumps(packet, ensure_ascii=False),
            )
            # 补发阶段也要检查是否已完成（避免再进入 subscribe 阶段）
            if packet["event"] in (EVENT_INSTANCE_COMPLETE, EVENT_INSTANCE_FAILED):
                return

        # ── 阶段 2：实时订阅 pub/sub ──────────────────────────────────────────────
        async for packet in bus.subscribe(instance_id):
            if await request.is_disconnected():
                logger.debug("SSE: 客户端断连（订阅阶段），退出 %s", instance_id)
                return
            yield ServerSentEvent(
                id=str(packet["id"]),
                event=packet["event"],
                data=json.dumps(packet, ensure_ascii=False),
            )
            # instance 完成/失败时自然结束 SSE 连接
            if packet["event"] in (EVENT_INSTANCE_COMPLETE, EVENT_INSTANCE_FAILED):
                logger.info("SSE: 实例 %s 终止事件，关闭 SSE 连接", instance_id)
                return

    return EventSourceResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            # 防止 nginx/CDN 缓冲（CONTEXT.md nginx 配置要求）
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
