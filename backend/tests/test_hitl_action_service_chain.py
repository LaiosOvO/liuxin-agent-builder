"""HitlActionService chain 4 模式集成测试（Phase 4 04-02 — 真实 PG + Redis，CLAUDE.md 2.2）。

测试覆盖（≥ 13 用例 + 边界 + 日志验证）：
1. test_submit_sequential_approve_advances_to_next — A approve → next_approvers=[B] + 3 token + 通知
2. test_submit_sequential_approve_last_completes — A→B→C 都 approve 最后一人 done
3. test_submit_sequential_reject_terminates — A reject → rejected，无新 token
4. test_submit_parallel_all_partial_approve_keeps_review — A approve → in_review，B 仍未决策
5. test_submit_parallel_all_full_approve_completes — A+B+C 都 approve → done
6. test_submit_parallel_all_first_reject_invalidates_others — A reject → 失效 B/C + 补通知
7. test_submit_parallel_any_first_approve_invalidates_others — A approve → done + 失效 B/C
8. test_submit_parallel_any_first_reject_invalidates_others — A reject → rejected + 失效 B/C
9. test_invalidate_chain_within_advisory_lock — invalidate_chain 在 lock 内调
10. test_audit_log_includes_chain_mode — meta.chain_mode 正确
11. test_audit_log_includes_invalidated_count — meta.invalidated_count > 0
12. test_actor_not_in_approvers_raises_403_compatible — 越权 → ChainActorNotAuthorized
13. test_chain_advance_failure_does_not_consume_jti — chain 失败事务回滚
14. test_structured_log_emitted — caplog 捕获 hitl.chain.advance

设计参考 docs/reading-dify-04-02-chain-executor-2026-05-17.md：
- 真实 PG + Redis（CLAUDE.md 2.2 不 mock DB）
- mock graph_resumer（跳过 LangGraph ainvoke）
- mock NotificationService（spy 入队调用，不依赖 arq）
- 验证 invalidate_chain 在 advisory_lock 内调（与 Pitfall 2 一致）
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import select, text

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.services.hitl_action_service import (
    ChainActorNotAuthorized,
    HitlActionService,
    JtiAlreadyConsumed,
)
from app.services.notification_service import NotificationService


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase4(db_session):
    """每次测试后清理 Phase 3/4 + Phase 1/2 表。"""
    yield
    await db_session.execute(text("DELETE FROM notifications"))
    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


@pytest_asyncio.fixture
async def redis_client():
    """连接 test Redis（端口 16379）。"""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:16379/0")
    client = Redis.from_url(redis_url, decode_responses=True)
    keys = await client.keys("agent_builder:jti:*")
    if keys:
        await client.delete(*keys)
    yield client
    keys = await client.keys("agent_builder:jti:*")
    if keys:
        await client.delete(*keys)
    await client.aclose()


# ── 种子数据 helper ─────────────────────────────────────────────────────────


async def _seed_chain_flow(
    db_session,
    *,
    chain_mode: str = "sequential",
    num_approvers: int = 3,
    current_idx: int = 0,
    decisions: dict | None = None,
) -> dict:
    """创建完整 chain 数据：ws → N user → wf → ver → instance → node_state(chain payload) → tokens。

    Returns:
        dict {ws_id, user_ids (list[N]), inst_id, node_state_id, jti_map (dict[(actor_id, action) → jti])}
    """
    import json as _json

    ws_id = uuid.uuid4()
    user_ids = [uuid.uuid4() for _ in range(num_approvers)]
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "chain测试", "slug": f"chain-{ws_id.hex[:8]}"},
    )
    for i, uid in enumerate(user_ids):
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
                "VALUES (:id, :email, :ph, 'active', false)"
            ),
            {"id": str(uid), "email": f"u{i}_{uuid.uuid4().hex[:6]}@chain.test", "ph": "hash"},
        )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "chain_wf",
            "created_by": str(user_ids[0]),
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :ws_id, :wf_id, 1, 'published', '{}', :created_by)"
        ),
        {
            "id": str(ver_id),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "created_by": str(user_ids[0]),
        },
    )
    thread_id = f"{ws_id}:{inst_id}"
    await db_session.execute(
        text(
            "INSERT INTO flow_instances "
            "(id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot, thread_id, status) "
            "VALUES (:id, :ws_id, :wf_id, :ver_id, '{}', :thread_id, 'running')"
        ),
        {
            "id": str(inst_id),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "ver_id": str(ver_id),
            "thread_id": thread_id,
        },
    )

    # 构造 approval_chain payload
    approval_chain = {
        "mode": chain_mode,
        "approvers": [str(u) for u in user_ids],
        "current_idx": current_idx,
    }
    if chain_mode in ("parallel_all", "parallel_any"):
        approval_chain["decisions"] = decisions or {str(u): None for u in user_ids}

    initial_payload = {
        "phase": "review",
        "current_actor": {
            "id": str(user_ids[current_idx] if chain_mode == "sequential" else user_ids[0]),
            "email": f"u{current_idx}@chain.test",
            "role": "reviewer",
        },
        "approval_chain": approval_chain,
        "records": [],
        "pending_approvers": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "form_schema": {},
        "flow_title": "测试流程",
        "node_title": "审批节点",
    }
    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status, payload) "
            "VALUES (:id, :ws_id, :inst_id, 'hitl_1', 'hitl', 'in_review', CAST(:payload AS jsonb))"
        ),
        {
            "id": str(node_state_id),
            "ws_id": str(ws_id),
            "inst_id": str(inst_id),
            "payload": _json.dumps(initial_payload),
        },
    )

    # 创建 tokens
    # sequential: 仅 approvers[current_idx] 有 token
    # parallel_*: 所有 approvers 都有 token
    jti_map: dict = {}
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    actions_per_actor = ["approve", "return", "reject"]

    if chain_mode == "sequential":
        actors_with_tokens = [user_ids[current_idx]]
    else:  # parallel_all / parallel_any
        actors_with_tokens = user_ids

    for actor in actors_with_tokens:
        for action in actions_per_actor:
            jti = uuid.uuid4()
            jti_map[(actor, action)] = jti
            await db_session.execute(
                text(
                    "INSERT INTO hitl_tokens "
                    "(jti, instance_id, node_state_id, actor_id, action, expires_at) "
                    "VALUES (:jti, :inst, :ns, :actor, :action, :exp)"
                ),
                {
                    "jti": str(jti),
                    "inst": str(inst_id),
                    "ns": str(node_state_id),
                    "actor": str(actor),
                    "action": action,
                    "exp": expires_at,
                },
            )

    await db_session.commit()

    return {
        "ws_id": ws_id,
        "user_ids": user_ids,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
        "jti_map": jti_map,
    }


def _build_jwt_payload(seed: dict, actor_id: uuid.UUID, action: str) -> dict:
    return {
        "jti": str(seed["jti_map"][(actor_id, action)]),
        "flow_id": str(seed["inst_id"]),
        "node_state_id": str(seed["node_state_id"]),
        "actor_id": str(actor_id),
        "actor_email": f"actor_{actor_id.hex[:6]}@chain.test",
        "role": "reviewer",
        "action": action,
    }


async def _mock_graph_resumer(
    flow_instance, db, redis, *, resume_args, thread_id
) -> bool:
    return False


class _SpyNotificationService(NotificationService):
    """Spy NotificationService — 记录入队调用，不实际触发 arq。"""

    def __init__(self, db):
        super().__init__(db, arq_pool=None)
        self.calls: list[dict] = []

    async def enqueue_generic_email(self, **kwargs):
        self.calls.append({"method": "enqueue_generic_email", **kwargs})
        # 创建 placeholder Notification 但不入队 arq（mock）
        from app.agent_builder.models.notification import Notification

        notif = Notification(
            workspace_id=kwargs["workspace_id"],
            instance_id=kwargs["instance_id"],
            node_state_id=kwargs["node_state_id"],
            channel="email",
            recipient=kwargs["recipient_email"],
            reminder_round=0,
            status="pending",
            payload={
                "generic": True,
                "subject": kwargs["subject"],
                "body": kwargs["body"],
                "recipient_email": kwargs["recipient_email"],
            },
        )
        self.db.add(notif)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(notif)
        return notif

    async def enqueue_hitl_email(self, **kwargs):
        self.calls.append({"method": "enqueue_hitl_email", **kwargs})
        return None


# ── 13 测试用例 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_sequential_approve_advances_to_next(
    db_session, redis_client, clean_phase4
):
    """sequential A approve → next_approvers=[B] + 3 个新 token + 1 封通知 + ns.status=in_review。"""
    seed = await _seed_chain_flow(db_session, chain_mode="sequential", num_approvers=3, current_idx=0)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "approve")

    result = await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="A 同意",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["chain_mode"] == "sequential"
    assert result["new_node_status"] == "in_review"
    assert len(result["next_approvers"]) == 1
    assert result["next_approvers"][0] == str(seed["user_ids"][1])  # B

    # B 应有 3 个新 token（approve / return / reject）
    db_session.expire_all()
    actor_b = seed["user_ids"][1]
    b_tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.actor_id == actor_b)
        )
    ).scalars().all()
    assert len(b_tokens) == 3

    # 一封通知给 B
    assert len([c for c in spy_notif.calls if c["method"] == "enqueue_generic_email"]) == 1


@pytest.mark.asyncio
async def test_submit_sequential_approve_last_completes(
    db_session, redis_client, clean_phase4
):
    """sequential 链最后一人 approve → done，无新 token。"""
    seed = await _seed_chain_flow(
        db_session, chain_mode="sequential", num_approvers=3, current_idx=2,
    )
    actor_c = seed["user_ids"][2]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_c, "approve")

    result = await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="C 同意",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["new_node_status"] == "done"
    assert len(result["next_approvers"]) == 0
    # 无新 token 创建
    db_session.expire_all()
    new_a_tokens = (
        await db_session.execute(
            select(HitlToken).where(
                HitlToken.node_state_id == seed["node_state_id"],
                HitlToken.actor_id == seed["user_ids"][0],
            )
        )
    ).scalars().all()
    assert len(new_a_tokens) == 0  # A 从未生成过 token（current_idx=2 起点）


@pytest.mark.asyncio
async def test_submit_sequential_reject_terminates(
    db_session, redis_client, clean_phase4
):
    """sequential A reject → rejected，无新 token，无补通知。"""
    seed = await _seed_chain_flow(db_session, chain_mode="sequential", num_approvers=3, current_idx=0)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "reject")

    result = await service.submit_action(
        payload=jwt_payload,
        action="reject",
        reason="A 拒绝",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["new_node_status"] == "rejected"
    assert len(result["next_approvers"]) == 0
    assert result["invalidated_chain"] == 0  # sequential reject 不调 invalidate_chain

    # B/C 没有 token（从未生成）
    db_session.expire_all()
    b_tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.actor_id == seed["user_ids"][1])
        )
    ).scalars().all()
    assert len(b_tokens) == 0

    # 无通知（sequential reject 不发补通知）
    assert len(spy_notif.calls) == 0


@pytest.mark.asyncio
async def test_submit_parallel_all_partial_approve_keeps_review(
    db_session, redis_client, clean_phase4
):
    """parallel_all A approve → in_review，B/C 仍未决策。"""
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_all", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "approve")

    result = await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="A 同意",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["chain_mode"] == "parallel_all"
    assert result["new_node_status"] == "in_review"
    assert result["invalidated_chain"] == 0  # 部分 approve 不调 invalidate_chain

    # B/C 的 token 仍未消费
    db_session.expire_all()
    active_tokens = (
        await db_session.execute(
            select(HitlToken).where(
                HitlToken.actor_id.in_([seed["user_ids"][1], seed["user_ids"][2]]),
                HitlToken.used_at.is_(None),
            )
        )
    ).scalars().all()
    # 每人 3 个 action token = 6 个未消费
    assert len(active_tokens) == 6


@pytest.mark.asyncio
async def test_submit_parallel_all_full_approve_completes(
    db_session, redis_client, clean_phase4
):
    """parallel_all 全员 approve → done。"""
    # 模拟 A、B 已 approve，C 是最后一个
    decisions = {
        # str 形式 actor_id：模拟 A/B 已 approve
        # 但 _seed 时 user_ids 还没生成，这里改为先 seed 默认，后手动 update payload
    }
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_all", num_approvers=3)
    user_a, user_b, user_c = seed["user_ids"]

    # 手动更新 payload：A/B 已 approve
    ns = await db_session.get(NodeState, seed["node_state_id"])
    payload = dict(ns.payload)
    chain = dict(payload["approval_chain"])
    chain["decisions"] = {
        str(user_a): {"action": "approve", "ts": datetime.now(timezone.utc).isoformat()},
        str(user_b): {"action": "approve", "ts": datetime.now(timezone.utc).isoformat()},
        str(user_c): None,
    }
    payload["approval_chain"] = chain
    ns.payload = payload
    await db_session.commit()

    # 同时手动消费 A、B token（模拟之前 decision 已落）
    await db_session.execute(
        text(
            "UPDATE hitl_tokens SET used_at = NOW(), used_ip='already-decided' "
            "WHERE actor_id IN (:a, :b) AND used_at IS NULL"
        ),
        {"a": str(user_a), "b": str(user_b)},
    )
    await db_session.commit()

    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, user_c, "approve")

    result = await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="C 同意完结",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["new_node_status"] == "done"
    assert result["invalidated_chain"] == 0  # 全员 approve 不调 invalidate_chain


@pytest.mark.asyncio
async def test_submit_parallel_all_first_reject_invalidates_others(
    db_session, redis_client, clean_phase4
):
    """parallel_all A reject → rejected + invalidate_chain + B/C token 失效 + 2 封补通知。"""
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_all", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "reject")

    result = await service.submit_action(
        payload=jwt_payload,
        action="reject",
        reason="A 拒绝",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["new_node_status"] == "rejected"
    # B/C 各 3 token × 2 actor = 6 token 失效
    assert result["invalidated_chain"] == 6

    # B/C 所有 token 已 used_at SET
    db_session.expire_all()
    active_other = (
        await db_session.execute(
            select(HitlToken).where(
                HitlToken.actor_id.in_([seed["user_ids"][1], seed["user_ids"][2]]),
                HitlToken.used_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(active_other) == 0

    # 检查失效 token 的 used_ip 标记
    chain_invalidated_count = (
        await db_session.execute(
            select(HitlToken).where(
                HitlToken.used_ip == "system:chain-invalidate",
            )
        )
    ).scalars().all()
    assert len(chain_invalidated_count) == 6

    # 2 封补通知（B 1 封 + C 1 封，按 actor 去重）
    generic_calls = [c for c in spy_notif.calls if c["method"] == "enqueue_generic_email"]
    assert len(generic_calls) == 2
    # subject 含 "已被" + "拒绝"
    for call in generic_calls:
        assert "已被" in call["subject"]
        assert "拒绝" in call["subject"]


@pytest.mark.asyncio
async def test_submit_parallel_any_first_approve_invalidates_others(
    db_session, redis_client, clean_phase4
):
    """parallel_any A approve → done + invalidate_chain + 2 封补通知。"""
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_any", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "approve")

    result = await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="A 同意（or 签）",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["chain_mode"] == "parallel_any"
    assert result["new_node_status"] == "done"
    assert result["invalidated_chain"] == 6

    # 2 封补通知（subject 含"已被 X 处理"）
    generic_calls = [c for c in spy_notif.calls if c["method"] == "enqueue_generic_email"]
    assert len(generic_calls) == 2
    for call in generic_calls:
        assert "已被" in call["subject"]
        assert "处理" in call["subject"]


@pytest.mark.asyncio
async def test_submit_parallel_any_first_reject_invalidates_others(
    db_session, redis_client, clean_phase4
):
    """parallel_any A reject → rejected + 失效 + 补通知。"""
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_any", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "reject")

    result = await service.submit_action(
        payload=jwt_payload,
        action="reject",
        reason="A 拒绝（or 签）",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert result["new_node_status"] == "rejected"
    assert result["invalidated_chain"] == 6


@pytest.mark.asyncio
async def test_invalidate_chain_within_advisory_lock(
    db_session, redis_client, clean_phase4, monkeypatch
):
    """invalidate_chain 在 advisory_lock 持有期间被调（Pitfall 2 防护）。

    模式：spy db.execute 调用序列 — advisory_xact_lock 必须在 invalidate_chain SQL 之前。
    """
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_all", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "reject")

    # spy db.execute 调用顺序
    original_execute = db_session.execute
    execute_log: list[str] = []

    async def spy_execute(stmt, *args, **kwargs):
        stmt_text = str(stmt)
        if "advisory_xact_lock" in stmt_text.lower():
            execute_log.append("advisory_lock_acquired")
        elif "update hitl_tokens" in stmt_text.lower() and "system:chain-invalidate" in stmt_text.lower():
            execute_log.append("invalidate_chain_sql")
        elif "update hitl_tokens" in stmt_text.lower():
            # 包括 consume + invalidate_siblings
            execute_log.append("hitl_token_update")
        return await original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", spy_execute)

    await service.submit_action(
        payload=jwt_payload,
        action="reject",
        reason="lock 顺序测试",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    # advisory_lock_acquired 必须 first
    assert execute_log[0] == "advisory_lock_acquired"
    # 所有 hitl_token 更新都在 lock 之后
    lock_idx = 0
    for op in execute_log[1:]:
        assert op in {"hitl_token_update", "invalidate_chain_sql"}


@pytest.mark.asyncio
async def test_audit_log_includes_chain_mode(
    db_session, redis_client, clean_phase4
):
    """audit_log.meta 含 chain_mode 字段（Phase 4 新增 — Phase 7 Run Viewer 用）。"""
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_all", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "approve")

    await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="meta.chain_mode 测试",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "hitl.decision")
        )
    ).scalar_one()

    assert audit.meta["chain_mode"] == "parallel_all"
    assert "invalidated_count" in audit.meta
    assert "next_approvers" in audit.meta


@pytest.mark.asyncio
async def test_audit_log_includes_invalidated_count(
    db_session, redis_client, clean_phase4
):
    """parallel_* 终止时 audit_log.meta.invalidated_count > 0。"""
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_any", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "approve")

    await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="meta.invalidated_count 测试",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "hitl.decision")
        )
    ).scalar_one()

    assert audit.meta["invalidated_count"] == 6  # 2 actor × 3 action = 6


@pytest.mark.asyncio
async def test_actor_not_in_approvers_raises_403_compatible(
    db_session, redis_client, clean_phase4
):
    """actor_id 不在 approvers 内 → 抛 ChainActorNotAuthorized。"""
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_all", num_approvers=3)
    stranger_id = uuid.uuid4()  # 不在 approvers 内
    # 但 stranger 需要存在于 users 表 + 有 token（否则会被早期路径拦下）
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, :ph, 'active', false)"
        ),
        {"id": str(stranger_id), "email": f"stranger_{stranger_id.hex[:6]}@test.com", "ph": "hash"},
    )
    stranger_jti = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db_session.execute(
        text(
            "INSERT INTO hitl_tokens (jti, instance_id, node_state_id, actor_id, action, expires_at) "
            "VALUES (:jti, :inst, :ns, :actor, :action, :exp)"
        ),
        {
            "jti": str(stranger_jti),
            "inst": str(seed["inst_id"]),
            "ns": str(seed["node_state_id"]),
            "actor": str(stranger_id),
            "action": "approve",
            "exp": expires_at,
        },
    )
    await db_session.commit()

    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = {
        "jti": str(stranger_jti),
        "flow_id": str(seed["inst_id"]),
        "node_state_id": str(seed["node_state_id"]),
        "actor_id": str(stranger_id),
        "actor_email": "stranger@test.com",
        "role": "reviewer",
        "action": "approve",
    }

    with pytest.raises(ChainActorNotAuthorized):
        await service.submit_action(
            payload=jwt_payload,
            action="approve",
            reason="越权测试",
            form_data={},
            ip="10.0.0.1",
            ua="UA",
        )


@pytest.mark.asyncio
async def test_chain_advance_failure_does_not_consume_jti(
    db_session, redis_client, clean_phase4, monkeypatch
):
    """compute_chain_advance 内部抛异常 → 不 commit → 业务契约：consume UPDATE 不持久化。

    验证方式：spy db.commit() — 异常路径下 commit 不被调用，事务由调用方（API 层）回滚。
    （PG 层事务隔离 + SQLAlchemy session rollback 由集成框架兜底；此测试聚焦业务契约）
    """
    seed = await _seed_chain_flow(db_session, chain_mode="parallel_all", num_approvers=3)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "approve")

    # mock compute_chain_advance 抛异常
    import app.agent_builder.services.hitl_action_service as svc_mod

    def boom(*args, **kwargs):
        raise RuntimeError("simulated chain advance failure")

    monkeypatch.setattr(svc_mod, "compute_chain_advance", boom)

    # spy db.commit() — 验证异常路径下 commit 不被调用
    commit_call_count = [0]
    original_commit = db_session.commit

    async def spy_commit():
        commit_call_count[0] += 1
        return await original_commit()

    monkeypatch.setattr(db_session, "commit", spy_commit)

    # 不计 spy_notif 内部的 commit（它在 except 之前已 commit；本测试关注 service 主流程 commit）
    # 但 BOOM 在 _supplement_notify 之前，所以 spy_notif 也不应被调用
    spy_notif_calls_before = len(spy_notif.calls)

    with pytest.raises(RuntimeError, match="simulated chain advance failure"):
        await service.submit_action(
            payload=jwt_payload,
            action="approve",
            reason="chain 异常测试",
            form_data={},
            ip="10.0.0.1",
            ua="UA",
        )

    # 业务契约 1：service.submit_action 异常路径下不调 self.db.commit()
    # 这确保事务保持未提交状态；API 层 except 路径会调 rollback
    assert commit_call_count[0] == 0, (
        f"异常路径下 commit 被调用 {commit_call_count[0]} 次（期望 0）"
    )

    # 业务契约 2：异常前没有调 notification 入队（BOOM 早于 _supplement_notify）
    assert len(spy_notif.calls) == spy_notif_calls_before


@pytest.mark.asyncio
async def test_structured_log_emitted(db_session, redis_client, clean_phase4, caplog):
    """caplog 捕获 hitl.chain.advance log record 含全字段（Phase 7 Run Viewer 钩子）。"""
    seed = await _seed_chain_flow(db_session, chain_mode="sequential", num_approvers=3, current_idx=0)
    actor_a = seed["user_ids"][0]
    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor_a, "approve")

    with caplog.at_level(logging.INFO, logger="app.agent_builder.services.hitl_action_service"):
        await service.submit_action(
            payload=jwt_payload,
            action="approve",
            reason="caplog 测试",
            form_data={},
            ip="10.0.0.1",
            ua="UA",
        )

    # 查找 hitl.chain.advance record
    chain_advance_records = [r for r in caplog.records if r.message == "hitl.chain.advance"]
    assert len(chain_advance_records) == 1
    rec = chain_advance_records[0]

    # extra 字段全部就位
    assert rec.chain_mode == "sequential"
    assert rec.actor_id == str(actor_a)
    assert rec.action == "approve"
    assert rec.new_status == "in_review"
    assert rec.next_approvers_count == 1
    assert rec.invalidated_count == 0
    assert rec.instance_id == str(seed["inst_id"])
    assert rec.node_state_id == str(seed["node_state_id"])


@pytest.mark.asyncio
async def test_single_mode_backward_compat(db_session, redis_client, clean_phase4):
    """single 模式（Phase 3）行为不变 — chain_advance 走包装路径。"""
    # 用 _seed_chain_flow 但 chain_mode='sequential'，再手动改为 single
    import json as _json
    seed = await _seed_chain_flow(db_session, chain_mode="sequential", num_approvers=1, current_idx=0)
    actor = seed["user_ids"][0]

    # 把 node_state 改为 single mode + phase=review (single 模式 approve 走 review)
    ns = await db_session.get(NodeState, seed["node_state_id"])
    payload = dict(ns.payload)
    payload["phase"] = "review"  # single approve 应在 review phase
    chain = dict(payload["approval_chain"])
    chain["mode"] = "single"
    payload["approval_chain"] = chain
    ns.payload = payload
    await db_session.commit()

    spy_notif = _SpyNotificationService(db_session)
    service = HitlActionService(
        db_session,
        redis_client,
        graph_resumer=_mock_graph_resumer,
        notification_service=spy_notif,
    )
    jwt_payload = _build_jwt_payload(seed, actor, "approve")

    result = await service.submit_action(
        payload=jwt_payload,
        action="approve",
        reason="single mode 兼容测试",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    # single 模式：approve in review → done（compute_next_status 既有行为）
    assert result["chain_mode"] == "single"
    assert result["new_node_status"] == "done"
    assert result["invalidated_chain"] == 0
    assert result["next_approvers"] == []
    # single 模式不发 chain 通知
    assert len([c for c in spy_notif.calls if c["method"] == "enqueue_generic_email"]) == 0
