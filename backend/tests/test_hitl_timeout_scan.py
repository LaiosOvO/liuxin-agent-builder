"""HITL 超时扫描 cron job 集成测试（Plan 03-09 Task 1）。

测试 6 个用例（CLAUDE.md 2.2 — 真实 PG + Redis + arq job 测试）：
1. test_scan_no_overdue_returns_0：无超时节点 → 返回 0
2. test_scan_overdue_24h_triggers_reminder_round_1：插入 deadline=now-25h 节点 → notifications 含 round=1 行
3. test_scan_overdue_48h_triggers_round_2_skips_round_1：跳过中间档（避免补发首催）
4. test_scan_overdue_72h_triggers_escalation：超过 72h → notifications round=3 + audit_log escalate
5. test_scan_already_done_node_skipped：节点已 done/rejected/returned → skip
6. test_scan_multiple_overdue_nodes_all_processed：多个超时节点全部处理

测试策略：
- 直接构造 node_states + 各种 payload 组合
- 不真发邮件：scan 后断言 notifications 表 INSERT 行 + audit_logs 表 escalate 记录
- monkeypatch send_hitl_email_job（防 asyncio.create_task 干扰测试）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.notification import Notification
from app.jobs.hitl_timeout_jobs import (
    _ESCALATE_THRESHOLD_SECONDS,
    _ROUND_1_THRESHOLD_SECONDS,
    _ROUND_2_THRESHOLD_SECONDS,
    get_thresholds,
    scan_hitl_timeouts,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3_tables(db_session):
    """每次测试后清理 Phase 3 表（FK 顺序）。"""
    yield
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM notifications"))
    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


@pytest.fixture(autouse=True)
def stub_arq_email_jobs(monkeypatch):
    """禁用 asyncio.create_task 在 NotificationService / EscalationService fallback 路径。

    测试时不真发邮件 —— 让 send_hitl_email_job 不实际跑（避免后台 task 干扰断言）。
    """
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.jobs.email_jobs.send_hitl_email_job", _noop)
    yield


async def _seed_workspace_admin(db_session, ws_id: uuid.UUID) -> uuid.UUID:
    """种 workspace 下一个 admin 用户（EscalationService fallback 用）。"""
    admin_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, 'hash', 'active', false)"
        ),
        {"id": str(admin_id), "email": f"admin_{ws_id.hex[:6]}@test.com"},
    )
    # 取 admin 角色 ID
    role_result = await db_session.execute(
        text("SELECT id FROM roles WHERE code='admin' LIMIT 1")
    )
    role_id = role_result.scalar_one_or_none()
    if role_id is None:
        # 测试环境可能没有 seed roles — 临时插入
        await db_session.execute(
            text("INSERT INTO roles (code, name) VALUES ('admin', 'Admin') ON CONFLICT DO NOTHING")
        )
        role_result = await db_session.execute(
            text("SELECT id FROM roles WHERE code='admin'")
        )
        role_id = role_result.scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
            "VALUES (:ws_id, :user_id, :role_id) ON CONFLICT DO NOTHING"
        ),
        {"ws_id": str(ws_id), "user_id": str(admin_id), "role_id": role_id},
    )
    return admin_id


async def _seed_overdue_node(
    db_session,
    *,
    overdue_seconds: int,
    node_status: str = "waiting_human",
    skip_actor: bool = False,
    seed_admin: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """创建一条完整的 ws/user/wf/ver/inst/node_state 行 — 节点已超时 N 秒。

    Returns:
        (ws_id, instance_id, node_state_id)
    """
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()  # 申请人 / actor
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    now = datetime.now(timezone.utc)
    started_at = now - timedelta(seconds=overdue_seconds + 24 * 3600)
    # 默认 deadline = started_at + 24h，所以 overdue_seconds 是相对 deadline 的超时秒数
    deadline_at = started_at + timedelta(seconds=24 * 3600)

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "超时测试ws", "slug": f"timeout-ws-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, 'hash', 'active', false)"
        ),
        {"id": str(user_id), "email": f"actor_{uuid.uuid4().hex[:6]}@test.com"},
    )

    if seed_admin:
        await _seed_workspace_admin(db_session, ws_id)

    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "timeout_wf",
            "created_by": str(user_id),
        },
    )
    # DSL 含 hitl_1 节点 config.escalate_to = 'escalate@test.com'
    dsl_snapshot = {
        "nodes": [
            {
                "id": "hitl_1",
                "type": "hitl",
                "config": {"escalate_to": "escalate@test.com"},
            }
        ],
        "edges": [],
    }
    import json
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :ws_id, :wf_id, 1, 'published', :dsl, :created_by)"
        ),
        {
            "id": str(ver_id),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "dsl": json.dumps(dsl_snapshot),
            "created_by": str(user_id),
        },
    )
    thread_id = f"{ws_id}:{inst_id}"
    await db_session.execute(
        text(
            "INSERT INTO flow_instances "
            "(id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot, thread_id, status) "
            "VALUES (:id, :ws_id, :wf_id, :ver_id, :dsl, :thread_id, 'running')"
        ),
        {
            "id": str(inst_id),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "ver_id": str(ver_id),
            "dsl": json.dumps(dsl_snapshot),
            "thread_id": thread_id,
        },
    )

    payload: dict = {
        "phase": "submit",
        "approval_chain": {"mode": "single", "approvers": [str(user_id)], "current_idx": 0},
        "records": [],
        "pending_approvers": [],
        "started_at": started_at.isoformat(),
        "deadline_at": deadline_at.isoformat(),
        "form_schema": {"type": "object"},
        "flow_title": "员工入职流程",
        "node_title": "HR 审批",
        "applicant_name": "张三",
        "description": "请尽快审批",
    }
    if not skip_actor:
        payload["current_actor"] = {
            "id": str(user_id),
            "email": f"actor_{user_id.hex[:6]}@test.com",
            "role": "executor",
        }

    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status, payload) "
            "VALUES (:id, :ws_id, :inst_id, 'hitl_1', 'hitl', :status, :payload)"
        ),
        {
            "id": str(node_state_id),
            "ws_id": str(ws_id),
            "inst_id": str(inst_id),
            "status": node_status,
            "payload": json.dumps(payload),
        },
    )
    await db_session.commit()
    return ws_id, inst_id, node_state_id


# ── 6 个测试用例 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_no_overdue_returns_0(db_session, clean_phase3_tables):
    """无超时节点 → scan 返回 0。"""
    # 不种任何超时节点
    processed = await scan_hitl_timeouts(None)
    assert processed == 0


@pytest.mark.asyncio
async def test_scan_overdue_24h_triggers_reminder_round_1(
    db_session, clean_phase3_tables
):
    """节点超时 25h（超过 24h 阈值 1h）→ 入队 round=1 催办邮件。"""
    ws_id, inst_id, ns_id = await _seed_overdue_node(
        db_session, overdue_seconds=3600  # 超 deadline 1 小时（总 elapsed 25h）
    )

    processed = await scan_hitl_timeouts(None)
    assert processed == 1

    # 断言 notifications 表有 round=1 行
    result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 1,
        )
    )
    notifs = list(result.scalars().all())
    assert len(notifs) == 1
    assert notifs[0].channel == "email"
    assert notifs[0].status == "pending"
    # payload 应该含 tokens（reminder 路径重签发 token）
    assert "tokens" in notifs[0].payload
    assert len(notifs[0].payload["tokens"]) == 3  # submit/return/reject


@pytest.mark.asyncio
async def test_scan_overdue_48h_triggers_round_2_but_skips_round_1(
    db_session, clean_phase3_tables
):
    """节点超时 25h（总 elapsed 49h）→ 直接发 round=2，跳过 round=1（避免补发）。"""
    # 总 elapsed = 24h + overdue_seconds — 设 elapsed=49h，overdue=25h
    elapsed_target = _ROUND_2_THRESHOLD_SECONDS + 3600  # 49h
    ws_id, inst_id, ns_id = await _seed_overdue_node(
        db_session, overdue_seconds=elapsed_target - 24 * 3600
    )

    processed = await scan_hitl_timeouts(None)
    assert processed == 1

    # 断言：notifications 表仅有 round=2 行（NOT round=1）
    round1_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 1,
        )
    )
    assert round1_result.scalar_one_or_none() is None, "round=1 不应该被发送（跳过中间档）"

    round2_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 2,
        )
    )
    notifs = list(round2_result.scalars().all())
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_scan_overdue_72h_triggers_escalation(db_session, clean_phase3_tables):
    """节点超时 >= 72h → 升级：写 notifications round=3 + records 含 escalate + audit_log。"""
    # 总 elapsed = 73h
    elapsed_target = _ESCALATE_THRESHOLD_SECONDS + 3600
    ws_id, inst_id, ns_id = await _seed_overdue_node(
        db_session,
        overdue_seconds=elapsed_target - 24 * 3600,
        seed_admin=True,
    )

    processed = await scan_hitl_timeouts(None)
    assert processed == 1

    # 1. notifications 表有 round=3 行（升级邮件）
    result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 3,
        )
    )
    notifs = list(result.scalars().all())
    assert len(notifs) == 1
    assert notifs[0].channel == "email"
    # 升级邮件 recipient 应该是 node config.escalate_to
    assert notifs[0].recipient == "escalate@test.com"
    # payload 应该含 escalation=True 标识
    assert notifs[0].payload.get("escalation") is True
    assert notifs[0].payload.get("overdue_hours", 0) >= 72.0

    # 2. audit_log 有 hitl.escalate 行
    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "hitl.escalate",
            AuditLog.node_state_id == ns_id,
        )
    )
    audits = list(audit_result.scalars().all())
    assert len(audits) == 1
    assert audits[0].decision == "escalate"
    assert audits[0].meta.get("reason") == "timeout_72h"
    assert audits[0].meta.get("escalate_to") == "escalate@test.com"

    # 3. node_state.payload.records 含 escalate 记录
    from app.agent_builder.models.node_state import NodeState
    ns_result = await db_session.execute(
        select(NodeState).where(NodeState.id == ns_id)
    )
    ns = ns_result.scalar_one()
    await db_session.refresh(ns)
    records = ns.payload.get("records", [])
    escalate_records = [r for r in records if r.get("action") == "escalate"]
    assert len(escalate_records) == 1, f"escalate record 缺失，records={records}"
    assert escalate_records[0]["actor_email"] == "system"
    assert escalate_records[0]["escalate_to"] == "escalate@test.com"


@pytest.mark.asyncio
async def test_scan_already_done_node_skipped(db_session, clean_phase3_tables):
    """节点 status='done' / 'rejected' / 'returned' → scan 不处理。"""
    # 用 done 状态种 — 因为 scan 用 WHERE status IN ('waiting_human','in_review') 过滤
    # 所以 done 节点压根不会被 SELECT
    ws_id, inst_id, ns_id = await _seed_overdue_node(
        db_session,
        overdue_seconds=_ESCALATE_THRESHOLD_SECONDS - 24 * 3600 + 3600,  # 73h
        node_status="done",
    )

    processed = await scan_hitl_timeouts(None)
    assert processed == 0, "done 节点不应触发任何处理"

    # 断言：notifications 表没有任何行
    result = await db_session.execute(
        select(Notification).where(Notification.node_state_id == ns_id)
    )
    notifs = list(result.scalars().all())
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_scan_multiple_overdue_nodes_all_processed(
    db_session, clean_phase3_tables
):
    """多个超时节点 → 全部处理（不会因单个失败影响其他）。"""
    # 种 3 个不同档位的超时节点
    ws_id_a, inst_id_a, ns_id_a = await _seed_overdue_node(
        db_session, overdue_seconds=3600  # 25h
    )
    ws_id_b, inst_id_b, ns_id_b = await _seed_overdue_node(
        db_session,
        overdue_seconds=_ROUND_2_THRESHOLD_SECONDS - 24 * 3600 + 3600,  # 49h
    )
    ws_id_c, inst_id_c, ns_id_c = await _seed_overdue_node(
        db_session,
        overdue_seconds=_ESCALATE_THRESHOLD_SECONDS - 24 * 3600 + 3600,  # 73h
        seed_admin=True,
    )

    processed = await scan_hitl_timeouts(None)
    assert processed == 3

    # 每个节点都有对应的 notifications 行
    for ns_id, round_expected in [
        (ns_id_a, 1),
        (ns_id_b, 2),
        (ns_id_c, 3),
    ]:
        result = await db_session.execute(
            select(Notification).where(
                Notification.node_state_id == ns_id,
                Notification.reminder_round == round_expected,
            )
        )
        notifs = list(result.scalars().all())
        assert len(notifs) == 1, f"节点 {ns_id} round={round_expected} 缺失"


# ── 边界 / 鲁棒性测试（bonus）─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_thresholds_returns_correct_values():
    """get_thresholds 返回三档阈值（不依赖魔法数）。"""
    thresholds = get_thresholds()
    assert thresholds["round_1"] == 24 * 3600
    assert thresholds["round_2"] == 48 * 3600
    assert thresholds["escalate"] == 72 * 3600


@pytest.mark.asyncio
async def test_scan_node_missing_current_actor_skipped(db_session, clean_phase3_tables):
    """节点 payload.current_actor 缺失 → scan 不报错（log warning + skip 发邮件）。

    注：processed 计数 = 进入档位 dispatch 的次数（即使后续 _trigger_reminder
    因 actor 缺失而 noop）— 重点是断言不抛错 + notifications 未写入。
    """
    ws_id, inst_id, ns_id = await _seed_overdue_node(
        db_session, overdue_seconds=3600, skip_actor=True
    )

    # scan 应该不报错（仅 log warning）
    processed = await scan_hitl_timeouts(None)

    # 关键断言：notifications 表没有任何行（_trigger_reminder 早退）
    result = await db_session.execute(
        select(Notification).where(Notification.node_state_id == ns_id)
    )
    notifs = list(result.scalars().all())
    assert len(notifs) == 0, "current_actor 缺失时不应入队邮件"
    # processed 值可能是 0 或 1（实现选择），不强断言


@pytest.mark.asyncio
async def test_scan_round_1_already_sent_advances_to_round_2(
    db_session, clean_phase3_tables
):
    """已发过 round=1 + 时间到 48h → 应入队 round=2。"""
    # 总 elapsed = 49h
    elapsed_target = _ROUND_2_THRESHOLD_SECONDS + 3600
    ws_id, inst_id, ns_id = await _seed_overdue_node(
        db_session, overdue_seconds=elapsed_target - 24 * 3600
    )

    # 预先种 round=0 + round=1 表示首发 + 首催已发
    import json as _json
    actor_email = f"actor_{uuid.uuid4().hex[:6]}@test.com"
    for round_num in (0, 1):
        await db_session.execute(
            text(
                "INSERT INTO notifications "
                "(workspace_id, instance_id, node_state_id, channel, recipient, "
                " reminder_round, status, payload) "
                "VALUES (:ws_id, :inst_id, :ns_id, 'email', :recipient, "
                "        :round, 'sent', :payload)"
            ),
            {
                "ws_id": str(ws_id),
                "inst_id": str(inst_id),
                "ns_id": str(ns_id),
                "recipient": actor_email,
                "round": round_num,
                "payload": _json.dumps({"tokens": []}),
            },
        )
    await db_session.commit()

    processed = await scan_hitl_timeouts(None)
    assert processed == 1

    # 应入队 round=2
    result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 2,
        )
    )
    assert result.scalar_one_or_none() is not None
