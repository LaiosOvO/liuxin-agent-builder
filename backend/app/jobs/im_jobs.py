"""arq job: 发送 HITL IM 卡片（Plan 04-05 Task 3）。

设计参考 docs/reading-im-sdk-04-05-providers-2026-05-17.md + email_jobs.py 模板：
- 克隆 email_jobs.send_hitl_email_job 结构（idempotent + 'sending' marker + tenacity 重试 + audit_log）
- channel 通用化：从 IMProvider Registry 通过 notif.channel 取 provider 调用
- 结构化日志 'im.card.send' 含 provider / recipient / status / latency_ms / notification_id

引用关系：
- get_provider 来自 notification.providers.base（Plan 04-05 Task 1）
- _build_deeplink 复用 email_jobs（不重写 — DRY）
- notifications 表 ORM 来自 Phase 3 03-01

NOTI-02..06 多通道扩展：
- Phase 4 仅出站：send_hitl_card → status=sent
- 暂不实现 update_card（决策后回卡 — 留 Plan 04-10 multichannel）

CLAUDE.md immutability：
- 入参 notification_id 是 str（arq enqueue 序列化）
- payload 字段读取后构建 deeplinks 列表（新建）— 不修改 notif.payload dict
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.agent_builder.notification.providers.base import get_provider
from app.jobs.email_jobs import _build_deeplink

log = logging.getLogger(__name__)


# ── tenacity 重试配置（NOTI-10 显式 3 次指数退避） ──────────────────────────
# 1s / 2s / 4s 公比 2 — 与 email_jobs 一致便于运维一致性观察
_RETRY_STOP = stop_after_attempt(3)
_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=4)
# 重试触发：网络 / IO 错误（业务错误如未授权 / 卡片格式错不重试）
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _build_deeplinks_from_tokens(tokens: list[dict]) -> list[dict[str, str]]:
    """从 notif.payload.tokens 构造 deeplinks 列表（用于 send_hitl_card 入参）。

    Args:
        tokens: notif.payload['tokens'] 形如 [{"jti": "xxx", "action": "approve"}, ...]

    Returns:
        [{"action": "approve", "url": "https://host/hitl/page/jti-xxx"}, ...]
    """
    return [
        {"action": t["action"], "url": _build_deeplink(t["jti"])}
        for t in tokens
    ]


async def send_hitl_card_job(ctx: dict | None, notification_id: str) -> None:
    """arq job 入口：发送 HITL IM 卡片（NOTI-02..06）。

    流程（与 email_jobs.send_hitl_email_job 平行）：
    1. SELECT notifications WHERE id=:id
    2. 幂等：if status=='sent' 跳过
    3. status='sending' + commit
    4. provider = get_provider(notif.channel)  # 来自 IMProvider Registry
    5. 渲染 deeplinks（同 email_jobs）
    6. tenacity 3 次指数退避调 provider.send_hitl_card
    7. 成功 → status='sent' + sent_at=now() + payload['im_message_id'] (供 update_card)
    8. 失败 → status='failed' + error_message + audit_log
    9. 结构化日志 'im.card.send' (provider, recipient, status, latency_ms, notification_id)

    Args:
        ctx: arq worker 上下文（含 redis 等）— 测试可传 None
        notification_id: notifications.id 字符串
    """
    from app.agent_builder.db.engine import async_session_maker
    from app.agent_builder.models.notification import Notification

    notif_id_int = int(notification_id)
    started_at = time.perf_counter()

    async with async_session_maker() as db:
        notif = await db.get(Notification, notif_id_int)
        if notif is None:
            log.error(
                "send_hitl_card_job: notification %s 不存在", notification_id
            )
            return

        # 幂等：已发送过则跳过（防多 worker / 重启场景）
        if notif.status == "sent":
            log.info(
                "send_hitl_card_job: notification %s 已 sent，跳过重发",
                notification_id,
            )
            return

        # 标记 sending（让其他 worker 不重复抢）
        notif.status = "sending"
        await db.commit()

        # provider 查找（未注册 → fail）
        try:
            provider = get_provider(notif.channel)
        except KeyError as exc:
            notif.status = "failed"
            notif.error_message = f"未知 IM provider: {notif.channel} ({exc})"[:1000]
            log.error(
                "send_hitl_card_job: unknown provider channel=%s notification_id=%s",
                notif.channel,
                notification_id,
            )
            await _write_audit_log_failure(
                db, notif, f"unknown provider {notif.channel}"
            )
            await db.commit()  # 一次性 commit notif.status 改动 + audit_log
            return

        # 渲染 deeplinks
        tokens = notif.payload.get("tokens", [])
        deeplinks = _build_deeplinks_from_tokens(tokens)

        # 提取 send_hitl_card 入参
        flow_title = notif.payload.get("flow_title", "")
        node_title = notif.payload.get("node_title", "")
        applicant_name = notif.payload.get("applicant_name", "")
        actor_name = notif.payload.get("actor_name", "")
        deadline_at = notif.payload.get("deadline_at", "")
        description = notif.payload.get("description", "")

        # tenacity 3 次指数退避调 provider.send_hitl_card
        message_id: str | None = None
        try:
            async for attempt in AsyncRetrying(
                stop=_RETRY_STOP,
                wait=_RETRY_WAIT,
                retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
                reraise=True,
            ):
                with attempt:
                    result = await provider.send_hitl_card(
                        recipient=notif.recipient,
                        flow_title=flow_title,
                        node_title=node_title,
                        applicant_name=applicant_name,
                        actor_name=actor_name,
                        deadline_at=deadline_at,
                        description=description,
                        deeplinks=deeplinks,
                    )
                    message_id = result.get("message_id")
            # 成功路径
            notif.status = "sent"
            notif.sent_at = datetime.now(timezone.utc)
            notif.error_message = None
            # 写回 im_message_id 供后续 update_card 用（payload immutable 模式：新 dict）
            if message_id:
                new_payload = dict(notif.payload)
                new_payload["im_message_id"] = message_id
                notif.payload = new_payload

            latency_ms = int((time.perf_counter() - started_at) * 1000)
            log.info(
                "im.card.send",
                extra={
                    "provider": notif.channel,
                    "recipient": notif.recipient,
                    "status": "sent",
                    "latency_ms": latency_ms,
                    "notification_id": notif.id,
                    "message_id": message_id,
                },
            )
        except Exception as exc:
            notif.status = "failed"
            notif.error_message = str(exc)[:1000]
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            log.exception(
                "im.card.send",
                extra={
                    "provider": notif.channel,
                    "recipient": notif.recipient,
                    "status": "failed",
                    "latency_ms": latency_ms,
                    "notification_id": notif.id,
                    "error": str(exc)[:200],
                },
            )
            await _write_audit_log_failure(db, notif, str(exc))
        finally:
            await db.commit()


async def _write_audit_log_failure(db, notif, error: str) -> None:
    """通知发送失败时写 audit_log（NOTI-10 显式可观测，与 email_jobs 一致）。

    action='im.send_failed'
    meta 含 notification_id / channel / recipient / error 摘要
    """
    try:
        from app.services.audit import log as audit_log

        await audit_log(
            db,
            action="im.send_failed",
            workspace_id=notif.workspace_id,
            target_type="notification",
            target_id=None,  # notifications.id 是 BIGSERIAL，不是 UUID
            meta={
                "notification_id": notif.id,
                "channel": notif.channel,
                "recipient": notif.recipient,
                "reminder_round": notif.reminder_round,
                "error": error[:500],
            },
        )
    except Exception:
        # 审计写入失败不应影响主流程
        log.exception("写 audit_log 失败 notification_id=%s", notif.id)
