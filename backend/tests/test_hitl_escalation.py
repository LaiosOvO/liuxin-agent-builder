"""EscalationService 集成测试（Plan 03-09 Task 2）。

测试 5 个用例（CLAUDE.md 2.2 — 真实 PG）：
1. test_resolve_escalate_to_email_format：node_config.escalate_to='user@x.com' 直接返回
2. test_resolve_escalate_to_fallback_to_workspace_admin：无 escalate_to → 取 workspace admin
3. test_perform_escalation_writes_records：records 含 {action: 'escalate', actor_email: 'system'}
4. test_perform_escalation_sends_email_to_escalate_to_user：notifications 含 round=3 行
5. test_perform_escalation_writes_audit_log_NET_05：audit_log 完整字段

测试策略：
- 直接构造 NodeState + DSL config + EscalationService 调用
- 不真发邮件：断言 notifications 表 INSERT 行
- 不触发 advisory_lock（外层 service 单元化测试）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.notification import Notification
from app.agent_builder.services.escalation_service import EscalationService


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3_tables(db_session):
    """每次测试后清理 Phase 3 表（FK 顺序）+ dispose engine。"""
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
    # Phase 3 plan 03-09 测试用 async_session_maker 跨 fixture session — dispose 防污染
    from app.agent_builder.db.engine import engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def stub_arq_email_jobs(monkeypatch):
    """禁用 asyncio.create_task 在 NotificationService / EscalationService fallback 路径。"""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.jobs.email_jobs.send_hitl_email_job", _noop)
    yield


async def _seed_workspace_with_admin(
    db_session, *, ws_name: str = "测试 ws", admin_email: str | None = None
) -> tuple[uuid.UUID, str]:
    """种 workspace + admin 用户（用于 fallback 测试）。

    Returns:
        (workspace_id, admin_email)
    """
    ws_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    if admin_email is None:
        admin_email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": ws_name, "slug": f"esc-ws-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, 'hash', 'active', false)"
        ),
        {"id": str(admin_id), "email": admin_email},
    )
    # 关联 admin 角色
    role_result = await db_session.execute(
        text("SELECT id FROM roles WHERE code='admin' LIMIT 1")
    )
    role_id = role_result.scalar_one_or_none()
    if role_id is None:
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
    await db_session.commit()
    return ws_id, admin_email


async def _seed_overdue_node_for_escalation(
    db_session,
    ws_id: uuid.UUID,
    *,
    node_config_escalate_to: str | None = "escalate@test.com",
) -> tuple[uuid.UUID, NodeState]:
    """种一个超时 73h 的 node_state（含 instance + DSL 节点 config）。

    Returns:
        (instance_id, node_state) — node_state 在 db_session 内 fresh-loaded
    """
    import json
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

    # DSL 含 escalate_to 配置
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
            "name": "esc_wf",
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
        "current_actor": {"id": str(user_id), "email": user_email, "role": "executor"},
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


# ── 5 个测试用例 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_escalate_to_email_format(db_session, clean_phase3_tables):
    """node_config.escalate_to='user@x.com' → 返回 [email]（Phase 4 list 兼容）。"""
    ws_id, _ = await _seed_workspace_with_admin(db_session)
    es = EscalationService(db_session)

    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "manager@company.com"},
        workspace_id=ws_id,
    )
    # Phase 4: 返回类型从 str 改为 list[str]
    assert result == ["manager@company.com"]


@pytest.mark.asyncio
async def test_resolve_escalate_to_fallback_to_workspace_admin(
    db_session, clean_phase3_tables
):
    """无 escalate_to → 取 workspace 下 admin 角色用户的 email 列表。"""
    ws_id, admin_email = await _seed_workspace_with_admin(
        db_session, admin_email="ws_admin@test.com"
    )
    es = EscalationService(db_session)

    # node_config 不含 escalate_to
    result = await es.resolve_escalate_to(
        node_config={"other_field": "abc"},
        workspace_id=ws_id,
    )
    # Phase 4: list[str]
    assert result == ["ws_admin@test.com"]


@pytest.mark.asyncio
async def test_resolve_escalate_to_returns_none_when_no_admin(
    db_session, clean_phase3_tables
):
    """无 escalate_to + workspace 无 admin → 返回 None（不抛错）。"""
    ws_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(ws_id),
            "name": "无 admin ws",
            "slug": f"noadmin-{ws_id.hex[:8]}",
        },
    )
    await db_session.commit()

    es = EscalationService(db_session)
    result = await es.resolve_escalate_to(
        node_config=None,
        workspace_id=ws_id,
    )
    assert result is None


@pytest.mark.asyncio
async def test_perform_escalation_writes_records(db_session, clean_phase3_tables):
    """perform_escalation 后 node_state.payload.records 含 {action: 'escalate', ...}。"""
    ws_id, _ = await _seed_workspace_with_admin(db_session)
    inst_id, ns = await _seed_overdue_node_for_escalation(db_session, ws_id)

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    # refetch node_state
    result = await db_session.execute(
        select(NodeState).where(NodeState.id == ns.id)
    )
    fresh_ns = result.scalar_one()
    await db_session.refresh(fresh_ns)

    records = fresh_ns.payload.get("records", [])
    assert len(records) == 1
    record = records[0]
    assert record["action"] == "escalate"
    assert record["actor_email"] == "system"
    assert record["reason"] == "timeout_72h"
    # Phase 4: records.escalate_to 改为 list[str] + 新增 escalate_count
    assert record["escalate_to"] == ["escalate@test.com"]
    assert record["escalate_count"] == 1
    assert "ts" in record


@pytest.mark.asyncio
async def test_perform_escalation_sends_email_to_escalate_to_user(
    db_session, clean_phase3_tables
):
    """perform_escalation 后 notifications 表有 round=3 行 + payload.escalation=True。"""
    ws_id, _ = await _seed_workspace_with_admin(db_session)
    inst_id, ns = await _seed_overdue_node_for_escalation(
        db_session, ws_id, node_config_escalate_to="boss@company.com"
    )

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    # notifications 表有 round=3 行
    result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns.id,
            Notification.reminder_round == 3,
        )
    )
    notifs = list(result.scalars().all())
    assert len(notifs) == 1
    notif = notifs[0]
    assert notif.recipient == "boss@company.com"
    assert notif.channel == "email"
    assert notif.status == "pending"

    # payload 含 escalation 标识 + 上下文字段
    assert notif.payload["escalation"] is True
    assert notif.payload["flow_title"] == "员工入职流程"
    assert notif.payload["node_title"] == "HR 审批"
    assert notif.payload["applicant_name"] == "张三"
    assert "original_actor_email" in notif.payload
    assert notif.payload["overdue_hours"] >= 72.0


@pytest.mark.asyncio
async def test_perform_escalation_writes_audit_log_NET_05(
    db_session, clean_phase3_tables
):
    """perform_escalation 后 audit_log 含完整 NET-05 字段。"""
    ws_id, _ = await _seed_workspace_with_admin(db_session)
    inst_id, ns = await _seed_overdue_node_for_escalation(db_session, ws_id)

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "hitl.escalate",
            AuditLog.node_state_id == ns.id,
        )
    )
    audits = list(audit_result.scalars().all())
    assert len(audits) == 1
    audit = audits[0]

    # NET-05 字段断言
    assert audit.workspace_id == ws_id
    assert audit.target_type == "node_state"
    assert audit.target_id == ns.id
    assert audit.actor_user_id is None  # system 触发
    assert audit.actor_ip == "system"
    assert audit.actor_ua == "hitl_timeout_worker"
    assert audit.decision == "escalate"
    assert audit.node_state_id == ns.id

    # meta 字段
    assert audit.meta["reason"] == "timeout_72h"
    assert audit.meta["escalate_to"] == "escalate@test.com"
    assert audit.meta["instance_id"] == str(inst_id)
    assert "original_actor_email" in audit.meta


@pytest.mark.asyncio
async def test_perform_escalation_skips_when_no_escalate_to_and_no_admin(
    db_session, clean_phase3_tables
):
    """无 escalate_to + 无 admin → 跳过升级，不抛错，不写 notifications / audit。"""
    # 种 workspace 但不种 admin
    ws_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(ws_id),
            "name": "无 admin ws",
            "slug": f"noadm-{ws_id.hex[:8]}",
        },
    )
    await db_session.commit()

    # 种节点（node_config_escalate_to=None 表示 DSL 也无配置）
    inst_id, ns = await _seed_overdue_node_for_escalation(
        db_session, ws_id, node_config_escalate_to=None
    )

    es = EscalationService(db_session)
    await es.perform_escalation(ns)
    await db_session.commit()

    # notifications 表无 round=3 行
    notif_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns.id,
            Notification.reminder_round == 3,
        )
    )
    assert notif_result.scalar_one_or_none() is None

    # audit 表也无 hitl.escalate 行
    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "hitl.escalate",
            AuditLog.node_state_id == ns.id,
        )
    )
    assert audit_result.scalar_one_or_none() is None
