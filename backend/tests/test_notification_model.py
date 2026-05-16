"""Notification ORM 模型单元 / 集成测试（CLAUDE.md 2.2 — 真实 DB，不 mock）。

测试目标：
- 默认 status=pending + reminder_round=0 + payload={}
- UNIQUE 约束 (instance_id, node_state_id, channel, recipient, reminder_round) 去重
- payload JSONB roundtrip（dict → DB → 读回保持结构）
- workspace 删除 → 级联删除 notifications（ON DELETE CASCADE）
- 索引 ix_notifications_status_created 存在（重试 worker 性能保证）
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.agent_builder.models.notification import Notification


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3_tables(db_session):
    """每次测试后清理 Phase 3 表。"""
    yield
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM notifications"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


async def _seed_workflow_instance(db_session) -> dict[str, uuid.UUID]:
    """创建一条完整的 ws + user + workflow + version + instance + node_state。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "通知测试ws", "slug": f"noti-ws-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, :ph, 'active', false)"
        ),
        {"id": str(user_id), "email": f"u_{uuid.uuid4().hex[:6]}@test.com", "ph": "hash"},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {"id": str(wf_id), "ws_id": str(ws_id), "name": "noti_wf", "created_by": str(user_id)},
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
            "created_by": str(user_id),
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
    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status) "
            "VALUES (:id, :ws_id, :inst_id, 'hitl_1', 'hitl', 'waiting_human')"
        ),
        {
            "id": str(node_state_id),
            "ws_id": str(ws_id),
            "inst_id": str(inst_id),
        },
    )
    await db_session.commit()

    return {
        "ws_id": ws_id,
        "user_id": user_id,
        "wf_id": wf_id,
        "ver_id": ver_id,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
    }


# ── 测试 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_notification_default_values(db_session, clean_phase3_tables):
    """新 Notification 默认值：status=pending, reminder_round=0, payload={}。"""
    seed = await _seed_workflow_instance(db_session)

    noti = Notification(
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        channel="email",
        recipient="approver@test.com",
    )
    db_session.add(noti)
    await db_session.commit()
    await db_session.refresh(noti)

    assert noti.id is not None, "id 应由 BIGSERIAL 自动生成"
    assert noti.status == "pending", "默认 status 应为 pending"
    assert noti.reminder_round == 0, "默认 reminder_round 应为 0"
    assert noti.payload == {}, "默认 payload 应为空 dict（来自 server_default '{}'）"
    assert noti.sent_at is None
    assert noti.error_message is None
    assert noti.created_at is not None


@pytest.mark.asyncio
async def test_notification_unique_dedup_constraint(db_session, clean_phase3_tables):
    """UNIQUE 约束：同 (instance, node_state, channel, recipient, round) 不可重复插入。

    NOTI-09 催办去重场景：多 worker 并发抢锁时不重复发送同样的提醒。
    """
    seed = await _seed_workflow_instance(db_session)

    noti1 = Notification(
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        channel="email",
        recipient="approver@test.com",
        reminder_round=0,
    )
    db_session.add(noti1)
    await db_session.commit()

    noti2 = Notification(
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        channel="email",
        recipient="approver@test.com",
        reminder_round=0,  # 同 round → UNIQUE 违反
    )
    db_session.add(noti2)

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 但 reminder_round=1 应可插入（催办轮次不同）
    noti3 = Notification(
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        channel="email",
        recipient="approver@test.com",
        reminder_round=1,
    )
    db_session.add(noti3)
    await db_session.commit()  # 应成功


@pytest.mark.asyncio
async def test_notification_payload_jsonb_roundtrip(db_session, clean_phase3_tables):
    """payload JSONB 写入字典 → 读出保持原结构（NOTI-10 催办重发用）。"""
    seed = await _seed_workflow_instance(db_session)

    original_payload = {
        "subject": "审批通知 [流程#123]",
        "body_html": "<h1>请审批</h1>",
        "body_text": "请审批",
        "buttons": [
            {"label": "通过", "url": "https://example.com/hitl/page/abc", "color": "green"},
            {"label": "退回", "url": "https://example.com/hitl/page/xyz", "color": "yellow"},
        ],
        "meta": {"render_time": "2026-05-17T12:00:00Z"},
    }

    noti = Notification(
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        channel="email",
        recipient="approver@test.com",
        payload=original_payload,
    )
    db_session.add(noti)
    await db_session.commit()
    await db_session.refresh(noti)

    # 读回应保持结构
    result = await db_session.execute(
        select(Notification).where(Notification.id == noti.id)
    )
    retrieved = result.scalar_one()
    assert retrieved.payload == original_payload, "payload 应 roundtrip 保持结构"
    assert retrieved.payload["buttons"][0]["label"] == "通过"
    assert len(retrieved.payload["buttons"]) == 2


@pytest.mark.asyncio
async def test_notification_workspace_cascade_delete(db_session, clean_phase3_tables):
    """删除 workspace → 级联删除 notifications（ON DELETE CASCADE）。"""
    seed = await _seed_workflow_instance(db_session)

    noti = Notification(
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        channel="email",
        recipient="approver@test.com",
    )
    db_session.add(noti)
    await db_session.commit()

    # 删除 workspace（级联应清理 workflow → instance → node_state → notification）
    # 注意：notifications 直接对 workspace 有 FK CASCADE，但因 instance/node_state
    # 也对 workspace 间接级联，触发顺序由 PG 处理。
    await db_session.execute(
        text("DELETE FROM workspaces WHERE id = :id"),
        {"id": str(seed["ws_id"])},
    )
    await db_session.commit()

    # 验证 notifications 被级联删除
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM notifications WHERE workspace_id = :id"),
        {"id": str(seed["ws_id"])},
    )
    count = result.scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_notification_status_created_index_exists(db_session):
    """索引 ix_notifications_status_created 存在（NOTI-10 重试 worker 扫描）。"""
    result = await db_session.execute(
        text(
            """
            SELECT a.attname AS column_name, key_info.key_ord
            FROM pg_index pgi
            JOIN pg_class t ON t.oid = pgi.indrelid
            JOIN pg_class i ON i.oid = pgi.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid
            JOIN LATERAL unnest(pgi.indkey) WITH ORDINALITY AS key_info(attnum, key_ord)
                ON a.attnum = key_info.attnum
            WHERE t.relname = 'notifications'
              AND i.relname = 'ix_notifications_status_created'
            ORDER BY key_info.key_ord
            """
        )
    )
    columns = [(row[0], row[1]) for row in result.fetchall()]

    assert columns, "索引 ix_notifications_status_created 不存在"
    assert columns[0][0] == "status", f"索引第一列期望 status，实际: {columns[0][0]}"
    assert columns[1][0] == "created_at", f"索引第二列期望 created_at，实际: {columns[1][0]}"
