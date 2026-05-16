"""Reminder round 多轮 + UNIQUE 去重 + 并发集成测试（Plan 03-09 Task 3）。

测试 4 个用例（CLAUDE.md 2.2 — 真实 PG + 多 worker 并发模拟）：
1. test_reminder_round_unique_constraint：UNIQUE 约束防多 worker 抢锁重发
2. test_reminder_round_sequence_24_48_72：同节点连续 24h/48h/72h 触发 3 行 notifications
3. test_concurrent_two_workers_only_one_sends：两个 task 同时 scan → 1 行 round=N
4. test_reminder_email_template_uses_hitl_reminder_html：reminder 模板含红色 banner + [催办] 前缀

测试策略：
- 真实 PG (UNIQUE 约束 / advisory_lock) 不 mock
- 用 asyncio.gather 模拟并发 worker
- 渲染验证用 Jinja2 直接 render（不真发邮件）
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text

from app.agent_builder.models.notification import Notification
from app.jobs.email_jobs import _render_email_content
from app.jobs.hitl_timeout_jobs import (
    _ESCALATE_THRESHOLD_SECONDS,
    _ROUND_1_THRESHOLD_SECONDS,
    _ROUND_2_THRESHOLD_SECONDS,
    scan_hitl_timeouts,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3_tables(db_session):
    """每次测试后清理 Phase 3 表（FK 顺序）+ dispose engine 防跨测试事件循环污染。"""
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
    """禁用 send_hitl_email_job fallback 异步任务（防 asyncio.create_task 干扰）。"""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.jobs.email_jobs.send_hitl_email_job", _noop)
    yield


async def _seed_overdue_node(
    db_session, *, overdue_hours: float, seed_admin: bool = False
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """种一个超时 N 小时的 node + ws + inst + DSL。

    Returns: (ws_id, instance_id, node_state_id)
    """
    import json

    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()
    actor_email = f"actor_{user_id.hex[:6]}@test.com"

    now = datetime.now(timezone.utc)
    started_at = now - timedelta(hours=overdue_hours)
    deadline_at = started_at + timedelta(hours=24)

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(ws_id),
            "name": "rounds ws",
            "slug": f"rd-ws-{ws_id.hex[:8]}",
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, 'hash', 'active', false)"
        ),
        {"id": str(user_id), "email": actor_email},
    )

    if seed_admin:
        admin_id = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
                "VALUES (:id, :email, 'hash', 'active', false)"
            ),
            {"id": str(admin_id), "email": f"admin_{ws_id.hex[:6]}@test.com"},
        )
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

    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "rd_wf",
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

    payload = {
        "phase": "submit",
        "current_actor": {
            "id": str(user_id),
            "email": actor_email,
            "role": "executor",
        },
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
    return ws_id, inst_id, node_state_id


# ── 4 个测试用例 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reminder_round_unique_constraint(db_session, clean_phase3_tables):
    """UNIQUE 约束：相同 (instance, node_state, channel, recipient, round=1) 重入队 → IntegrityError。

    场景：手动 INSERT round=1 行（先 commit）+ 再尝试 INSERT → 触发 UNIQUE 冲突。
    """
    ws_id, inst_id, ns_id = await _seed_overdue_node(db_session, overdue_hours=25)

    actor_email = "actor@test.com"

    # 第一次 INSERT round=1 成功（先 commit 持久化）
    notif1 = Notification(
        workspace_id=ws_id,
        instance_id=inst_id,
        node_state_id=ns_id,
        channel="email",
        recipient=actor_email,
        reminder_round=1,
        status="pending",
        payload={"tokens": []},
    )
    db_session.add(notif1)
    await db_session.commit()

    # 验证第一行落地
    pre_check = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 1,
        )
    )
    assert len(list(pre_check.scalars().all())) == 1

    # 第二次 INSERT 同样 (instance, node_state, channel, recipient, round=1) 应失败
    notif2 = Notification(
        workspace_id=ws_id,
        instance_id=inst_id,
        node_state_id=ns_id,
        channel="email",
        recipient=actor_email,
        reminder_round=1,  # 同样的 round
        status="pending",
        payload={"tokens": []},
    )
    db_session.add(notif2)

    with pytest.raises(sa.exc.IntegrityError):
        await db_session.flush()

    # 恢复 session 状态
    await db_session.rollback()

    # 验证表中仍只有 1 行 round=1（first insert 已 commit 持久化）
    result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 1,
        )
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1, f"应只有 1 行 round=1（first insert 持久），实际 {len(rows)}"


@pytest.mark.asyncio
async def test_reminder_round_sequence_24_48_72(db_session, clean_phase3_tables):
    """同节点连续触发 24h/48h/72h → notifications 表共 3 行（round 1/2/3）。

    通过手动调整 started_at 模拟时间推进，scan 3 次。
    """
    import json

    ws_id, inst_id, ns_id = await _seed_overdue_node(
        db_session, overdue_hours=25, seed_admin=True
    )

    # 第 1 次 scan（25h 超时）→ round=1
    processed = await scan_hitl_timeouts(None)
    assert processed == 1
    round_1_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 1,
        )
    )
    assert round_1_result.scalar_one_or_none() is not None

    # 第 2 次 scan：手动调整 started_at = now - 49h → 触发 round=2
    new_started_at = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    new_deadline = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    await db_session.execute(
        text(
            "UPDATE node_states SET payload = jsonb_set("
            "  jsonb_set(payload, '{started_at}', to_jsonb(CAST(:started AS text))),"
            "  '{deadline_at}', to_jsonb(CAST(:deadline AS text))"
            ") WHERE id = :id"
        ),
        {"id": str(ns_id), "started": new_started_at, "deadline": new_deadline},
    )
    await db_session.commit()

    processed = await scan_hitl_timeouts(None)
    assert processed == 1
    round_2_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 2,
        )
    )
    assert round_2_result.scalar_one_or_none() is not None

    # 第 3 次 scan：started_at = now - 73h → 触发 round=3 (escalation)
    new_started_at = (datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()
    new_deadline = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    await db_session.execute(
        text(
            "UPDATE node_states SET payload = jsonb_set("
            "  jsonb_set(payload, '{started_at}', to_jsonb(CAST(:started AS text))),"
            "  '{deadline_at}', to_jsonb(CAST(:deadline AS text))"
            ") WHERE id = :id"
        ),
        {"id": str(ns_id), "started": new_started_at, "deadline": new_deadline},
    )
    await db_session.commit()

    processed = await scan_hitl_timeouts(None)
    assert processed == 1
    round_3_result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 3,
        )
    )
    assert round_3_result.scalar_one_or_none() is not None

    # 总计 3 行 notifications（round 1/2/3）
    all_result = await db_session.execute(
        select(Notification).where(Notification.node_state_id == ns_id)
    )
    all_notifs = list(all_result.scalars().all())
    assert len(all_notifs) == 3
    rounds = sorted([n.reminder_round for n in all_notifs])
    assert rounds == [1, 2, 3]


@pytest.mark.asyncio
async def test_concurrent_two_workers_only_one_sends(
    db_session, clean_phase3_tables
):
    """两个 worker 同时 scan 同一节点 → notifications 表只有 1 行 round=1。

    advisory_xact_lock(hash(node_state_id)) + UNIQUE 约束双保险。
    """
    ws_id, inst_id, ns_id = await _seed_overdue_node(db_session, overdue_hours=25)

    # asyncio.gather 模拟两个并发 worker
    # 注：因为 scan_hitl_timeouts 内部用 async_session_maker 创建独立 session，
    # 所以可以真实并发（不共享当前 db_session）
    results = await asyncio.gather(
        scan_hitl_timeouts(None),
        scan_hitl_timeouts(None),
        return_exceptions=True,
    )

    # 两个 worker 都应该跑完（不抛错）
    for r in results:
        assert not isinstance(r, Exception), f"worker 异常：{r}"

    # 关键断言：notifications 表只有 1 行 round=1
    result = await db_session.execute(
        select(Notification).where(
            Notification.node_state_id == ns_id,
            Notification.reminder_round == 1,
        )
    )
    notifs = list(result.scalars().all())
    assert len(notifs) == 1, (
        f"并发 race 防护失败：notifications 表有 {len(notifs)} 行 round=1（应为 1）"
    )


@pytest.mark.asyncio
async def test_reminder_email_template_uses_hitl_reminder_html(
    db_session, clean_phase3_tables
):
    """reminder 模板渲染：含红色 banner + [催办] 标识 + 截止时间高亮。

    通过 _render_email_content 直接渲染 + 断言 HTML 内容（不真发邮件）。
    """
    payload = {
        "tokens": [
            {"jti": "tok1", "action": "submit"},
            {"jti": "tok2", "action": "return"},
            {"jti": "tok3", "action": "reject"},
        ],
        "flow_title": "员工入职流程",
        "node_title": "HR 审批",
        "applicant_name": "张三",
        "actor_name": "李四",
        "deadline_at": "2026-05-18 14:00",
        "description": "请尽快审批此员工入职申请",
    }

    html = _render_email_content(payload, "hitl_reminder.html")

    # 红色 banner（#dc2626 是催办红色）
    assert "#dc2626" in html, "催办模板红色 banner 缺失"
    # [催办] 标识
    assert "[催办]" in html, "[催办] 标识缺失"
    # 截止时间显示（红色 #dc2626 同色）
    assert "2026-05-18 14:00" in html
    # 3 个按钮
    assert "/hitl/page/tok1" in html
    assert "/hitl/page/tok2" in html
    assert "/hitl/page/tok3" in html
    # 申请人 / 流程标题
    assert "张三" in html
    assert "员工入职流程" in html


# ── 升级模板渲染 bonus 单测 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalation_email_template_renders_correctly():
    """升级模板渲染：含 [升级] banner + overdue_hours + original_actor_email。"""
    payload = {
        "escalation": True,
        "flow_title": "员工入职流程",
        "node_title": "HR 审批",
        "applicant_name": "张三",
        "original_actor_email": "manager@test.com",
        "overdue_hours": 73.5,
        "deadline_at": "2026-05-14 14:00",
        "description": "需要您接手处理",
        "instance_id": "abc-def-123",
    }

    html = _render_email_content(payload, "hitl_escalation.html")

    # 升级 banner（更深红 #b91c1c）
    assert "#b91c1c" in html, "升级模板红色 banner 缺失"
    # [升级] 标识
    assert "[升级]" in html
    # overdue_hours 显示
    assert "73.5" in html
    # 原审批人
    assert "manager@test.com" in html
    # 申请人 / 流程
    assert "张三" in html
    assert "员工入职流程" in html
    # 实例 ID
    assert "abc-def-123" in html
    # 升级邮件无决策按钮 — 不应含 hitl/page 链接
    assert "/hitl/page/" not in html, "升级邮件不应含决策深链按钮"
