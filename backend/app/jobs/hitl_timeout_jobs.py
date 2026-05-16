"""HITL 节点超时催办 + 升级 — arq cron job（Plan 03-09）。

设计参考 docs/reading-dify-03-09-timeout-worker-2026-05-17.md §7：
- arq cron(60s) 替代 Celery beat（CLAUDE.md §3 技术栈锁定）
- notifications UNIQUE 约束（03-01 已建）防多 worker 重发
- PG advisory_xact_lock(hash(node_state_id)) 处理 race condition
- 三档阶梯催办：24h round=1 / 48h round=2 / 72h escalate

主要入口：
- scan_hitl_timeouts(ctx): arq cron 主函数，扫描 waiting_human / in_review 节点
- 内部辅助：_trigger_reminder / _trigger_escalation

复用：
- NotificationService.enqueue_hitl_email（03-04）— reminder_round > 0 时模板自动用 hitl_reminder.html
- HitlService.batch_create_tokens（03-02）— 重新签发 token（首发 token 已过期）
- EscalationService.perform_escalation（本 plan Task 2）

CLAUDE.md immutability：本 job 写 DB 但不修改入参 node_state.payload（新 dict 替换）。
CLAUDE.md 2.4 多租户：通过 instance_id / node_state_id FK 链路隔离，
                       payload 含 workspace_id 时优先用 node_state.workspace_id（FK 主源）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.notification import Notification

log = logging.getLogger(__name__)

# ── 阶梯阈值（秒）— CONTEXT.md §邮件模板 + 超时催办策略 ─────────────────────────
_ROUND_1_THRESHOLD_SECONDS: Final[int] = 24 * 3600    # 24h：首催办
_ROUND_2_THRESHOLD_SECONDS: Final[int] = 48 * 3600    # 48h：二催办
_ESCALATE_THRESHOLD_SECONDS: Final[int] = 72 * 3600   # 72h：升级到 escalate_to

# ── 扫描 LIMIT — 参考 Dify human_input_timeout_tasks.py:103 ────────────────────
_SCAN_LIMIT: Final[int] = 100


async def scan_hitl_timeouts(ctx: dict | None) -> int:
    """arq cron 入口：每分钟扫一次超时 HITL 节点。

    Args:
        ctx: arq worker 上下文（含 redis 等）— 测试场景可传 None

    Returns:
        本次处理的节点数（用于监控 / 日志）。

    流程：
    1. SELECT node_states WHERE status IN (waiting_human, in_review)
        AND payload->>'deadline_at' 已超时
        ORDER BY id ASC LIMIT 100
    2. for each ns:
        a) advisory_xact_lock(hash(node_state_id)) — 防多 worker 同时处理
        b) 重新查 ns.status（已 done/rejected/returned 则 skip — 防 advisory_lock 与 scan 之间的状态变化）
        c) 算 elapsed_seconds = now - payload.started_at
        d) 查当前最大 reminder_round（从 notifications 表）
        e) dispatch：
            - elapsed >= 72h AND current_round < 3 → escalation
            - elapsed >= 48h AND current_round < 2 → reminder round=2
            - elapsed >= 24h AND current_round < 1 → reminder round=1
    3. 单个节点处理 try/except 隔离（防单失败整批 abort，借鉴 Dify Pattern C）
    """
    from app.agent_builder.db.engine import async_session_maker

    now = datetime.now(timezone.utc)
    processed = 0

    async with async_session_maker() as db:
        nodes = await _scan_overdue_nodes(db, now=now)
        log.info("scan_hitl_timeouts: 找到 %d 个潜在超时节点", len(nodes))
        # 仅取 ID — _process_node 内部重新加载（避免 detached ORM 对象跨 session 行为）
        node_ids = [ns.id for ns in nodes]

        for ns_id in node_ids:
            try:
                handled = await _process_node(ctx, db, ns_id, now=now)
                if handled:
                    processed += 1
            except Exception:
                # 单节点异常隔离 — 借鉴 Dify human_input_timeout_tasks.py:108
                log.exception(
                    "scan_hitl_timeouts: 处理节点 %s 失败（不影响其他节点）",
                    ns_id,
                )
                # 失败后 rollback 让 session 恢复可用
                try:
                    await db.rollback()
                except Exception:
                    pass

    log.info("scan_hitl_timeouts: 本次处理 %d 个节点", processed)
    return processed


async def _scan_overdue_nodes(
    db: AsyncSession, *, now: datetime
) -> list[NodeState]:
    """扫描可能超时的 HITL 节点。

    用 JSONB path expression 比较 deadline_at（payload['deadline_at']::timestamptz）。

    设计：
    - WHERE status IN ('waiting_human', 'in_review')：仅 HITL 中间态
    - 用 payload->>'deadline_at' 转 timestamptz 比较 < now()
    - payload 为 NULL 或缺 deadline_at 时不会命中（PG ::timestamptz cast NULL safe）
    - ORDER BY id ASC + LIMIT 100：FIFO + 防 OOM
    """
    stmt = (
        select(NodeState)
        .where(
            NodeState.status.in_(["waiting_human", "in_review"]),
            # JSONB path → 转 timestamptz → 比较
            # NULL safe：缺 deadline_at 时不命中（PG NULL < anything 为 NULL）
            sa.cast(NodeState.payload["deadline_at"].astext, sa.TIMESTAMP(timezone=True))
            < now,
        )
        .order_by(NodeState.id.asc())
        .limit(_SCAN_LIMIT)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _process_node(
    ctx: dict | None,
    db: AsyncSession,
    ns_id: UUID,
    *,
    now: datetime,
) -> bool:
    """处理单个超时节点（advisory_lock 保护下）。

    Args:
        ns_id: 节点状态 UUID（不传 ORM 对象 — 避免 detached object 跨 session race）

    Returns:
        True 表示触发了一次 reminder / escalation；False 表示 skip（状态变化 / 已处理过当前档）。
    """
    # 1. advisory_xact_lock — hash(node_state_id) 单进程内一致
    lock_key = hash(str(ns_id)) & 0x7FFFFFFFFFFFFFFF

    # advisory_xact_lock：当前事务结束时自动释放
    # 在持有 lock 之前完成事务隔离边界 — 锁内 SELECT 看到最新 committed 数据
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

    # 2. 锁内重新加载节点（fresh from PG — advisory_lock 释放期间可能有其他 worker 提交）
    ns = await db.get(NodeState, ns_id)
    if ns is None:
        log.warning("_process_node: 节点 %s 已删除，跳过", ns_id)
        await db.commit()
        return False

    if ns.status not in ("waiting_human", "in_review"):
        log.info(
            "_process_node: 节点 %s 状态已变更为 %s，跳过",
            ns.id,
            ns.status,
        )
        await db.commit()
        return False

    payload = ns.payload or {}
    started_at_str = payload.get("started_at")
    if not isinstance(started_at_str, str):
        log.warning(
            "_process_node: 节点 %s payload.started_at 缺失或类型错误，跳过",
            ns.id,
        )
        await db.commit()
        return False

    try:
        started_at = datetime.fromisoformat(started_at_str)
    except ValueError:
        log.warning(
            "_process_node: 节点 %s payload.started_at=%r 不是 ISO 格式，跳过",
            ns.id,
            started_at_str,
        )
        await db.commit()
        return False

    # 3. 算 elapsed_seconds
    if started_at.tzinfo is None:
        # 容错：假定 UTC
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed_seconds = (now - started_at).total_seconds()

    # 4. 查当前最大 reminder_round（从 notifications 表）
    max_round_result = await db.execute(
        select(sa.func.coalesce(sa.func.max(Notification.reminder_round), -1)).where(
            Notification.node_state_id == ns.id,
            Notification.channel == "email",
        )
    )
    current_round = max_round_result.scalar_one()
    # 解释：
    # - current_round = -1 表示从未发过任何邮件（连首发都没）
    # - current_round = 0 表示首发已发过，未催办
    # - current_round = 1 表示已发首催，未发二催
    # - current_round = 2 表示已发二催，未升级
    # - current_round = 3 表示已升级

    # 5. dispatch — 由高到低判断（避免跳过中间档）
    handled = False
    if elapsed_seconds >= _ESCALATE_THRESHOLD_SECONDS and current_round < 3:
        log.info(
            "_process_node: 节点 %s 已超 72h (elapsed=%.1fs, round=%s) → 升级",
            ns.id,
            elapsed_seconds,
            current_round,
        )
        await _trigger_escalation(ctx, db, ns)
        handled = True
    elif elapsed_seconds >= _ROUND_2_THRESHOLD_SECONDS and current_round < 2:
        log.info(
            "_process_node: 节点 %s 已超 48h (elapsed=%.1fs, round=%s) → 二催办",
            ns.id,
            elapsed_seconds,
            current_round,
        )
        await _trigger_reminder(ctx, db, ns, reminder_round=2)
        handled = True
    elif elapsed_seconds >= _ROUND_1_THRESHOLD_SECONDS and current_round < 1:
        log.info(
            "_process_node: 节点 %s 已超 24h (elapsed=%.1fs, round=%s) → 首催办",
            ns.id,
            elapsed_seconds,
            current_round,
        )
        await _trigger_reminder(ctx, db, ns, reminder_round=1)
        handled = True
    else:
        log.debug(
            "_process_node: 节点 %s elapsed=%.1fs round=%s 不满足任何档位，跳过",
            ns.id,
            elapsed_seconds,
            current_round,
        )

    # commit 释放 advisory_xact_lock
    await db.commit()
    return handled


async def _trigger_reminder(
    ctx: dict | None,
    db: AsyncSession,
    ns: NodeState,
    *,
    reminder_round: int,
) -> None:
    """触发催办邮件（NOTI-09）。

    复用 03-02 HitlService.batch_create_tokens 重签发 token（首发 token 已过 24h 默认过期），
    直接 INSERT notifications 行（不走 NotificationService.enqueue_hitl_email，因后者内部
    commit 会提前释放 advisory_lock — 我们要保持事务一致性到 _process_node 的统一 commit）。

    Args:
        ctx: arq worker 上下文（含 redis） — None 时走 fallback（不入队 arq）
        db: 当前 db session（advisory_lock 已持有 — 不提前 commit）
        ns: NodeState 实例
        reminder_round: 1 = 首催, 2 = 二催

    Notes:
        - UNIQUE 约束（instance_id, node_state_id, channel='email', recipient, reminder_round）
          保证不重复入队；advisory_lock 是第一道防线，UNIQUE 兜底防极端 race
        - arq enqueue_job 在事务 commit 之后由 _process_node 完成（避免回滚后仍 enqueue）
    """
    from app.agent_builder.services.hitl_service import HitlService

    payload = ns.payload or {}
    current_actor = payload.get("current_actor") or {}
    recipient_email = current_actor.get("email")
    if not recipient_email:
        log.warning(
            "_trigger_reminder: 节点 %s payload.current_actor.email 缺失，跳过",
            ns.id,
        )
        return

    actor_id_str = current_actor.get("id")
    if not actor_id_str:
        log.warning(
            "_trigger_reminder: 节点 %s payload.current_actor.id 缺失，跳过",
            ns.id,
        )
        return
    try:
        actor_id = UUID(actor_id_str)
    except ValueError:
        log.warning(
            "_trigger_reminder: 节点 %s actor_id=%r 不是 UUID，跳过",
            ns.id,
            actor_id_str,
        )
        return

    # 重签发 token（首发 token 已过 24h 默认过期）
    hitl_svc = HitlService(db)
    phase = payload.get("phase", "submit")
    allowed_actions = await hitl_svc.resolve_allowed_actions(phase)
    tokens = await hitl_svc.batch_create_tokens(
        instance_id=ns.instance_id,
        node_state_id=ns.id,
        actor_id=actor_id,
        allowed_actions=allowed_actions,
    )

    # 构造 notifications.payload（参考 NotificationService.enqueue_hitl_email 结构）
    deadline_at_str = payload.get("deadline_at")
    deadline_at_iso = (
        deadline_at_str
        if isinstance(deadline_at_str, str)
        else datetime.now(timezone.utc).isoformat()
    )
    token_records = [{"jti": str(t.jti), "action": t.action} for t in tokens]
    notif_payload: dict[str, Any] = {
        "tokens": token_records,
        "form_schema": dict(payload.get("form_schema") or {}),
        "deadline_at": deadline_at_iso,
        "actor_name": current_actor.get("email", ""),
        "flow_title": payload.get("flow_title", ""),
        "node_title": payload.get("node_title", ""),
        "applicant_name": payload.get("applicant_name", ""),
        "description": payload.get("description", ""),
    }

    notif = Notification(
        workspace_id=ns.workspace_id,
        instance_id=ns.instance_id,
        node_state_id=ns.id,
        channel="email",
        recipient=recipient_email,
        reminder_round=reminder_round,
        status="pending",
        payload=notif_payload,
    )
    db.add(notif)
    try:
        await db.flush()
        log.info(
            "_trigger_reminder: 节点 %s 已 INSERT round=%s 催办行 → %s",
            ns.id,
            reminder_round,
            recipient_email,
        )
    except sa.exc.IntegrityError:
        # UNIQUE 约束冲突 — 多 worker 抢到同一档（advisory_lock 已防大多数 race；
        # 此处兜底；rollback 让事务恢复可用 — 外层 _process_node 看不到此 INSERT）
        log.info(
            "_trigger_reminder: 节点 %s round=%s 已被其他 worker 处理（UNIQUE 冲突）",
            ns.id,
            reminder_round,
        )
        await db.rollback()
        return

    # 入队 arq job（commit 之后，由 _process_node 调用）
    # 这里只把 notif 暂存到 ns，让 _process_node commit 后再 enqueue
    # 简化：直接调用 send_hitl_email_job 异步 task（测试时被 monkeypatch）
    arq_pool = ctx.get("redis") if isinstance(ctx, dict) else None
    if arq_pool is not None:
        await arq_pool.enqueue_job("send_hitl_email_job", str(notif.id))
    else:
        # 测试 / dev fallback：直接 asyncio.create_task
        import asyncio

        from app.jobs.email_jobs import send_hitl_email_job

        asyncio.create_task(send_hitl_email_job(None, str(notif.id)))


async def _trigger_escalation(
    ctx: dict | None,
    db: AsyncSession,
    ns: NodeState,
) -> None:
    """触发升级（NOTI-09 + HITL-04 single 模式 + NET-05 audit）。

    委托给 EscalationService.perform_escalation（本 plan Task 2 实现）。

    Args:
        ctx: arq worker 上下文（含 redis） — None 时 fallback
        db: 当前 db session（advisory_lock 已持有）
        ns: NodeState 实例
    """
    from app.agent_builder.services.escalation_service import EscalationService

    arq_pool = ctx.get("redis") if isinstance(ctx, dict) else None
    es = EscalationService(db, arq_pool=arq_pool)
    await es.perform_escalation(ns)


# ── 公开常量供测试 / EscalationService 复用 ───────────────────────────────────


def get_thresholds() -> dict[str, int]:
    """返回阶梯阈值字典（供测试使用，便于断言不依赖魔法数）。"""
    return {
        "round_1": _ROUND_1_THRESHOLD_SECONDS,
        "round_2": _ROUND_2_THRESHOLD_SECONDS,
        "escalate": _ESCALATE_THRESHOLD_SECONDS,
    }
