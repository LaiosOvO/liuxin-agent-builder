"""EscalationService.perform_escalation 多 email fan-out 集成测试（Plan 04-04 Task 2）。

测试 6 个用例（CLAUDE.md 2.2 — 真实 PG）：
1. test_perform_with_3_role_admins_sends_3_emails
2. test_perform_writes_3_audit_logs
3. test_perform_dept_expression_skips_escalation
4. test_perform_no_escalator_skips
5. test_perform_records_escalate_count_field
6. test_perform_logs_structured_escalation_resolved（用 caplog 捕获）

测试策略：
- 直接构造 NodeState + DSL config + EscalationService 调用
- 不真发邮件：断言 notifications 表 INSERT 行
- 用 caplog 捕获 'hitl.escalation.resolved' 结构化日志
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.notification import Notification
from app.agent_builder.services.escalation_service import EscalationService


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase4_tables(db_session):
    """每次测试后清理 Phase 4 表（FK 顺序）+ dispose engine。"""
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
    from app.agent_builder.db.engine import engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def stub_arq_email_jobs(monkeypatch):
    """禁用 asyncio.create_task 在 fallback 路径。"""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("app.jobs.email_jobs.send_hitl_email_job", _noop)
    yield


async def _seed_workspace_with_admins(
    db_session,
    *,
    admin_emails: list[str],
    slug_prefix: str = "esc",
) -> uuid.UUID:
    """种 workspace + N 个 admin。"""
    ws_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(ws_id),
            "name": f"{slug_prefix} ws",
            "slug": f"{slug_prefix}-{ws_id.hex[:8]}",
        },
    )

    # 查 admin role id
    role_result = await db_session.execute(
        text("SELECT id FROM roles WHERE code='admin' LIMIT 1")
    )
    role_id = role_result.scalar_one()

    for email in admin_emails:
        admin_id = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
                "VALUES (:id, :email, 'hash', 'active', false)"
            ),
            {"id": str(admin_id), "email": email},
        )
        await db_session.execute(
            text(
                "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
                "VALUES (:ws_id, :user_id, :role_id) ON CONFLICT DO NOTHING"
            ),
            {"ws_id": str(ws_id), "user_id": str(admin_id), "role_id": role_id},
        )
    await db_session.commit()
    return ws_id


async def _seed_overdue_node(
    db_session,
    ws_id: uuid.UUID,
    *,
    node_config_escalate_to: str | None = None,
) -> tuple[uuid.UUID, NodeState]:
    """种一个超时 73h 的 node_state（含 instance + DSL 节点 config）。

    Returns:
        (instance_id, node_state)
    """
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()
    user_email = f"original_{uuid.uuid4().hex[:6]}@test.com"

    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, 'hash', 'active', false)"
        ),
        {"id": str(user_id), "email": user_email},
    )

    node_config: dict = {}
    if node_config_escalate_to is not None:
        node_config["escalate_to"] = node_config_escalate_to
    dsl_snapshot = {
        "nodes": [{"id": "hitl_1", "type": "hitl", "config": node_config}],
        "edges": [],
    }

    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "perform_wf",
            "created_by": str(user_id),
        },
    )
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

    now = datetime.now(timezone.utc)
    started_at = now - timedelta(hours=73)
    deadline_at = started_at + timedelta(hours=24)
    payload = {
        "phase": "submit",
        "current_actor": {
            "id": str(user_id),
            "email": user_email,
            "role": "executor",
        },
        "approval_chain": {
            "mode": "single",
            "approvers": [str(user_id)],
            "current_idx": 0,
        },
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

    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status, payload) "
            "VALUES (:id, :ws_id, :inst_id, 'hitl_1', 'hitl', 'waiting_human', :payload)"
        ),
        {
            "id": str(node_state_id),
            "ws_id": str(ws_id),
            "inst_id": str(inst_id),
            "payload": json.dumps(payload),
        },
    )
    await db_session.commit()

    result = await db_session.execute(
        select(NodeState).where(NodeState.id == node_state_id)
    )
    ns = result.scalar_one()
    return inst_id, ns


# ── 测试用例 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_perform_with_3_role_admins_sends_3_emails(
    db_session, clean_phase4_tables
):
    """role:admin 在 workspace 有 3 个 admin → notifications 3 行 reminder_round=3。"""
    ws_id = await _seed_workspace_with_admins(
        db_session,
        admin_emails=["a1@test.com", "a2@test.com", "a3@test.com"],
        slug_prefix="multi3",
    )
    inst_id, ns = await _seed_overdue_node(
        db_session, ws_id, node_config_escalate_to="role:admin"
    )

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    # 断言 notifications 表 3 行 reminder_round=3
    result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns.id,
            Notification.reminder_round == 3,
        )
    )
    notifs = list(result.scalars().all())
    assert len(notifs) == 3, f"期望 3 行 notifications，实际 {len(notifs)}"

    recipients = {n.recipient for n in notifs}
    assert recipients == {"a1@test.com", "a2@test.com", "a3@test.com"}

    # 每行都是 status=pending + channel=email + escalation=True
    for n in notifs:
        assert n.channel == "email"
        assert n.status == "pending"
        assert n.payload["escalation"] is True


@pytest.mark.asyncio
async def test_perform_writes_3_audit_logs(db_session, clean_phase4_tables):
    """role:admin 3 人 → audit_logs 3 行 action='hitl.escalate'（每人独立审计行）。"""
    ws_id = await _seed_workspace_with_admins(
        db_session,
        admin_emails=["b1@test.com", "b2@test.com", "b3@test.com"],
        slug_prefix="audit3",
    )
    inst_id, ns = await _seed_overdue_node(
        db_session, ws_id, node_config_escalate_to="role:admin"
    )

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    # 断言 audit_logs 表 3 行
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "hitl.escalate",
            AuditLog.node_state_id == ns.id,
        )
    )
    audits = list(result.scalars().all())
    assert len(audits) == 3

    # 每条 meta.escalate_to 是单 email（per-row）
    audit_targets = {a.meta["escalate_to"] for a in audits}
    assert audit_targets == {"b1@test.com", "b2@test.com", "b3@test.com"}

    # meta.escalate_count 标识总人数
    for a in audits:
        assert a.meta["escalate_count"] == 3
        assert a.meta["reason"] == "timeout_72h"
        assert a.meta["instance_id"] == str(inst_id)
        assert a.decision == "escalate"
        assert a.actor_user_id is None  # system 触发


@pytest.mark.asyncio
async def test_perform_dept_expression_skips_escalation(
    db_session, clean_phase4_tables
):
    """node_config.escalate_to='dept:HR' → catch NotImplementedError，不发邮件不写 audit。"""
    ws_id = await _seed_workspace_with_admins(
        db_session,
        admin_emails=["dept_admin@test.com"],
        slug_prefix="dept",
    )
    inst_id, ns = await _seed_overdue_node(
        db_session, ws_id, node_config_escalate_to="dept:HR"
    )

    es = EscalationService(db_session)
    # 不应抛错（catch NotImplementedError 跳过升级）
    await es.perform_escalation(ns)
    await db_session.commit()

    # notifications 无升级行
    notif_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns.id,
            Notification.reminder_round == 3,
        )
    )
    assert notif_result.scalar_one_or_none() is None

    # audit_log 无 hitl.escalate 行
    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "hitl.escalate",
            AuditLog.node_state_id == ns.id,
        )
    )
    assert audit_result.scalar_one_or_none() is None

    # records 也无 escalate 记录
    result = await db_session.execute(
        select(NodeState).where(NodeState.id == ns.id)
    )
    fresh_ns = result.scalar_one()
    await db_session.refresh(fresh_ns)
    records = (fresh_ns.payload or {}).get("records", [])
    assert len([r for r in records if r.get("action") == "escalate"]) == 0


@pytest.mark.asyncio
async def test_perform_no_escalator_skips(db_session, clean_phase4_tables):
    """resolve_escalate_to 返回 None（无 escalate_to + 无 admin）→ 0 emails。"""
    # workspace 无 admin
    ws_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(ws_id),
            "name": "no_admin ws",
            "slug": f"noadm-{ws_id.hex[:8]}",
        },
    )
    await db_session.commit()

    inst_id, ns = await _seed_overdue_node(
        db_session, ws_id, node_config_escalate_to=None
    )

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    # 0 notifications
    notif_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns.id,
            Notification.reminder_round == 3,
        )
    )
    assert notif_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_perform_records_escalate_count_field(
    db_session, clean_phase4_tables
):
    """records.escalate_to 改为 list[str] + 新增 escalate_count 字段。"""
    ws_id = await _seed_workspace_with_admins(
        db_session,
        admin_emails=["c1@test.com", "c2@test.com"],
        slug_prefix="count",
    )
    inst_id, ns = await _seed_overdue_node(
        db_session, ws_id, node_config_escalate_to="role:admin"
    )

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    result = await db_session.execute(
        select(NodeState).where(NodeState.id == ns.id)
    )
    fresh_ns = result.scalar_one()
    await db_session.refresh(fresh_ns)

    records = (fresh_ns.payload or {}).get("records", [])
    escalate_records = [r for r in records if r.get("action") == "escalate"]
    assert len(escalate_records) == 1
    er = escalate_records[0]
    # Phase 4 schema 变更
    assert isinstance(er["escalate_to"], list)
    assert set(er["escalate_to"]) == {"c1@test.com", "c2@test.com"}
    assert er["escalate_count"] == 2
    assert er["actor_email"] == "system"
    assert er["reason"] == "timeout_72h"

    # payload.escalate_to 顶层字段也是 list
    assert isinstance(fresh_ns.payload["escalate_to"], list)
    assert set(fresh_ns.payload["escalate_to"]) == {"c1@test.com", "c2@test.com"}


@pytest.mark.asyncio
async def test_perform_logs_structured_escalation_resolved(
    db_session, clean_phase4_tables, caplog
):
    """perform_escalation 写结构化日志 'hitl.escalation.resolved' 含 expression / matched_count。"""
    ws_id = await _seed_workspace_with_admins(
        db_session,
        admin_emails=["log1@test.com", "log2@test.com"],
        slug_prefix="log",
    )
    inst_id, ns = await _seed_overdue_node(
        db_session, ws_id, node_config_escalate_to="role:admin"
    )

    es = EscalationService(db_session)
    with caplog.at_level(
        logging.INFO,
        logger="app.agent_builder.services.escalation_service",
    ):
        await es.perform_escalation(ns)
        await db_session.commit()

    # 找到结构化日志
    structured = [r for r in caplog.records if r.message == "hitl.escalation.resolved"]
    assert len(structured) == 1, "未捕获 hitl.escalation.resolved 日志"

    log_record = structured[0]
    # extra 字段断言
    assert log_record.expression == "role:admin"
    assert log_record.matched_count == 2
    assert log_record.successful_count == 2
    assert log_record.workspace_id == str(ws_id)
    assert log_record.node_state_id == str(ns.id)
    assert log_record.instance_id == str(inst_id)


@pytest.mark.asyncio
async def test_perform_with_user_uuid_sends_single_email(
    db_session, clean_phase4_tables
):
    """user:<uuid> 命中 → 1 行 notifications + 1 行 audit_log（边界保证 user: 也走 fan-out 框架）。"""
    ws_id = await _seed_workspace_with_admins(
        db_session,
        admin_emails=["existing_admin@test.com"],
        slug_prefix="user",
    )

    # 种一个普通用户（非 admin），通过 user: 升级
    target_user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, 'hash', 'active', false)"
        ),
        {"id": str(target_user_id), "email": "target@test.com"},
    )
    role_result = await db_session.execute(
        text("SELECT id FROM roles WHERE code='editor' LIMIT 1")
    )
    role_id = role_result.scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
            "VALUES (:ws_id, :user_id, :role_id) ON CONFLICT DO NOTHING"
        ),
        {"ws_id": str(ws_id), "user_id": str(target_user_id), "role_id": role_id},
    )
    await db_session.commit()

    inst_id, ns = await _seed_overdue_node(
        db_session, ws_id, node_config_escalate_to=f"user:{target_user_id}"
    )

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    # 1 行 notifications，recipient=target user
    notif_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns.id,
            Notification.reminder_round == 3,
        )
    )
    notifs = list(notif_result.scalars().all())
    assert len(notifs) == 1
    assert notifs[0].recipient == "target@test.com"

    # 1 行 audit_log
    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "hitl.escalate",
            AuditLog.node_state_id == ns.id,
        )
    )
    audits = list(audit_result.scalars().all())
    assert len(audits) == 1
    assert audits[0].meta["escalate_to"] == "target@test.com"
    assert audits[0].meta["escalate_count"] == 1
