"""HITL IM card arq job 集成测试（Plan 04-05 Task 3）。

测试 7 用例（CLAUDE.md 2.2 — 真实 PG + MockIMProvider）：
1. test_send_hitl_card_job_success：MockIMProvider 调用 + notif.status='sent' + payload['im_message_id']
2. test_send_hitl_card_job_idempotent_skip_sent：已 sent → 不重发
3. test_send_hitl_card_job_retries_on_connection_error：mock 前 2 次抛错，第 3 次成功
4. test_send_hitl_card_job_fails_after_3_retries：mock 全失败 → status='failed' + audit_log
5. test_send_hitl_card_job_unknown_provider_fails：notif.channel='nonexistent' → fail
6. test_send_hitl_card_job_structured_log_emitted：caplog 含 'im.card.send'
7. test_send_hitl_card_job_provider_call_args：provider 收到正确 args（recipient / deeplinks / 字段）
8. test_send_hitl_card_job_writes_im_message_id_to_payload：成功后 payload['im_message_id'] 写入
9. test_send_hitl_card_job_missing_notification_no_op：不存在的 notification_id → log.error

Mock 策略：
- MockIMProvider 注入 Registry（fixture clear_providers + register_provider）
- 真实 PG（db_session fixture）写入 notifications 行 + 验证状态变化
- 不依赖真实 IM SDK（lark-oapi / wechatpy / 等都未导入）
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import tenacity
from sqlalchemy import select, text

from app.agent_builder.models.notification import Notification
from app.agent_builder.notification.providers.base import (
    PROVIDER_FEISHU,
    PROVIDER_SLACK,
    clear_providers,
    register_provider,
)
from app.agent_builder.notification.providers.mock import MockIMProvider
from app.jobs.im_jobs import send_hitl_card_job


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolate_providers():
    """每个测试前后清空 IMProvider Registry。"""
    clear_providers()
    yield
    clear_providers()


@pytest.fixture(autouse=False)
async def clean_phase3_tables(db_session):
    """每次测试后清理 Phase 3+4 表（按 FK 依赖顺序）。"""
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


async def _seed_im_notification(
    db_session,
    *,
    channel: str = PROVIDER_FEISHU,
    recipient: str = "ou_test_user_001",
    reminder_round: int = 0,
    status: str = "pending",
) -> Notification:
    """创建一条完整的 ws/user/wf/ver/inst/node_state + notifications 行（IM channel）。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()
    jti1 = uuid.uuid4()
    jti2 = uuid.uuid4()
    jti3 = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "im测试ws", "slug": f"im-ws-{ws_id.hex[:8]}"},
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
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "im_wf",
            "created_by": str(user_id),
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

    notif = Notification(
        workspace_id=ws_id,
        instance_id=inst_id,
        node_state_id=node_state_id,
        channel=channel,
        recipient=recipient,
        reminder_round=reminder_round,
        status=status,
        payload={
            "tokens": [
                {"jti": str(jti1), "action": "approve"},
                {"jti": str(jti2), "action": "return"},
                {"jti": str(jti3), "action": "reject"},
            ],
            "form_schema": {"type": "object"},
            "deadline_at": datetime.now(timezone.utc).isoformat(),
            "actor_name": "李审批",
            "flow_title": "员工入职流程",
            "node_title": "HR 审批",
            "applicant_name": "张申请",
            "description": "请尽快审批此员工入职申请",
        },
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)
    return notif


# ── 测试用例 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_card_job_success(db_session, clean_phase3_tables, monkeypatch):
    """成功路径：MockIMProvider 调用 1 次 + notif.status='sent' + payload['im_message_id'] 写入。"""
    notif = await _seed_im_notification(db_session, channel=PROVIDER_FEISHU)

    mock = MockIMProvider(name=PROVIDER_FEISHU)
    register_provider(mock)

    await send_hitl_card_job(None, str(notif.id))

    # provider 调用了 1 次
    assert len(mock.calls) == 1
    call = mock.calls[0]
    assert call.method == "send_hitl_card"
    assert call.recipient == "ou_test_user_001"
    assert call.payload["flow_title"] == "员工入职流程"
    assert call.payload["actor_name"] == "李审批"
    assert len(call.payload["deeplinks"]) == 3
    # deeplink URL 含 jti
    assert all("/hitl/page/" in d["url"] for d in call.payload["deeplinks"])

    # DB 状态正确
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "sent"
    assert db_notif.sent_at is not None
    assert db_notif.error_message is None
    # im_message_id 已写入 payload
    assert db_notif.payload.get("im_message_id") == "mock-msg-1"


@pytest.mark.asyncio
async def test_send_hitl_card_job_idempotent_skip_sent(
    db_session, clean_phase3_tables, monkeypatch
):
    """已 sent 的 notification 二次调用 job → 跳过（不重发 provider）。"""
    notif = await _seed_im_notification(db_session, status="sent")

    mock = MockIMProvider(name=PROVIDER_FEISHU)
    register_provider(mock)

    await send_hitl_card_job(None, str(notif.id))

    # provider 未被调用
    assert len(mock.calls) == 0

    # status 仍然 sent
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "sent"


@pytest.mark.asyncio
async def test_send_hitl_card_job_retries_on_connection_error(
    db_session, clean_phase3_tables, monkeypatch
):
    """前 2 次 ConnectionError 第 3 次成功 → status='sent'（tenacity 重试）。"""
    notif = await _seed_im_notification(db_session)

    # fail_count=2 → 第 1/2 次抛 ConnectionError，第 3 次成功
    mock = MockIMProvider(name=PROVIDER_FEISHU, fail_count=2)
    register_provider(mock)

    # 加速测试：不真 sleep
    monkeypatch.setattr("app.jobs.im_jobs._RETRY_WAIT", tenacity.wait_none())

    await send_hitl_card_job(None, str(notif.id))

    # mock._send_attempts 累计 3 次（前 2 fail + 第 3 success）
    assert mock._send_attempts == 3
    # 但 calls 只记录成功的 1 次
    assert len(mock.calls) == 1

    # 最终 status=sent
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "sent"
    assert db_notif.error_message is None


@pytest.mark.asyncio
async def test_send_hitl_card_job_fails_after_3_retries(
    db_session, clean_phase3_tables, monkeypatch
):
    """3 次都 ConnectionError → notif.status='failed' + error_message + audit_log。"""
    notif = await _seed_im_notification(db_session)

    # fail_count=10 大于重试上限 3，模拟全失败
    mock = MockIMProvider(name=PROVIDER_FEISHU, fail_count=10)
    register_provider(mock)

    # 加速测试
    monkeypatch.setattr("app.jobs.im_jobs._RETRY_WAIT", tenacity.wait_none())

    await send_hitl_card_job(None, str(notif.id))

    # 总共调用 3 次（首次 + 2 次重试）
    assert mock._send_attempts == 3
    assert len(mock.calls) == 0  # 全失败 → 无成功记录

    # 最终 status=failed + error_message
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "failed"
    assert db_notif.error_message is not None
    assert "simulated" in db_notif.error_message or "网络错误" in db_notif.error_message

    # 验证 audit_log 写了（NOTI-10 可观测要求）
    audit_result = await db_session.execute(
        text(
            "SELECT action, meta FROM audit_logs WHERE action='im.send_failed' "
            "AND workspace_id=:ws_id"
        ),
        {"ws_id": str(db_notif.workspace_id)},
    )
    audit_rows = audit_result.fetchall()
    assert len(audit_rows) >= 1
    assert audit_rows[0][0] == "im.send_failed"


@pytest.mark.asyncio
async def test_send_hitl_card_job_unknown_provider_fails(
    db_session, clean_phase3_tables, monkeypatch
):
    """notif.channel 不在 Registry → status='failed' + audit_log 不抛异常。"""
    notif = await _seed_im_notification(db_session, channel="nonexistent_provider")

    # 不注册任何 provider
    await send_hitl_card_job(None, str(notif.id))

    # status=failed
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "failed"
    assert "nonexistent_provider" in (db_notif.error_message or "")

    # audit_log 写了
    audit_result = await db_session.execute(
        text(
            "SELECT action, meta FROM audit_logs WHERE action='im.send_failed' "
            "AND workspace_id=:ws_id"
        ),
        {"ws_id": str(db_notif.workspace_id)},
    )
    audit_rows = audit_result.fetchall()
    assert len(audit_rows) >= 1


@pytest.mark.asyncio
async def test_send_hitl_card_job_structured_log_emitted(
    db_session, clean_phase3_tables, monkeypatch, caplog
):
    """成功路径 caplog 含 'im.card.send' message + extra.provider / status / latency_ms。"""
    notif = await _seed_im_notification(db_session, channel=PROVIDER_SLACK)
    register_provider(MockIMProvider(name=PROVIDER_SLACK))

    caplog.set_level(logging.INFO, logger="app.jobs.im_jobs")
    await send_hitl_card_job(None, str(notif.id))

    # 找到 im.card.send 日志条目
    matched = [r for r in caplog.records if r.message == "im.card.send"]
    assert len(matched) >= 1
    success_log = matched[-1]  # 最后一条（成功）
    assert getattr(success_log, "provider", None) == PROVIDER_SLACK
    assert getattr(success_log, "status", None) == "sent"
    latency_ms = getattr(success_log, "latency_ms", None)
    assert isinstance(latency_ms, int)
    assert latency_ms >= 0
    assert getattr(success_log, "notification_id", None) == notif.id


@pytest.mark.asyncio
async def test_send_hitl_card_job_provider_receives_correct_args(
    db_session, clean_phase3_tables, monkeypatch
):
    """Provider 收到所有 7 个参数 + deeplinks 列表完整。"""
    notif = await _seed_im_notification(
        db_session, channel=PROVIDER_FEISHU, recipient="ou_specific_user"
    )

    mock = MockIMProvider(name=PROVIDER_FEISHU)
    register_provider(mock)

    await send_hitl_card_job(None, str(notif.id))

    assert len(mock.calls) == 1
    call = mock.calls[0]
    assert call.recipient == "ou_specific_user"
    p = call.payload
    assert p["flow_title"] == "员工入职流程"
    assert p["node_title"] == "HR 审批"
    assert p["applicant_name"] == "张申请"
    assert p["actor_name"] == "李审批"
    assert p["description"] == "请尽快审批此员工入职申请"
    # deeplinks: 3 个（approve / return / reject）
    actions = [d["action"] for d in p["deeplinks"]]
    assert set(actions) == {"approve", "return", "reject"}
    # 所有 URL 都含 /hitl/page/
    for d in p["deeplinks"]:
        assert d["url"].startswith("http")
        assert "/hitl/page/" in d["url"]


@pytest.mark.asyncio
async def test_send_hitl_card_job_writes_im_message_id_to_payload(
    db_session, clean_phase3_tables, monkeypatch
):
    """成功后 notif.payload['im_message_id'] 写入（供后续 update_card 用）。"""
    notif = await _seed_im_notification(db_session, channel=PROVIDER_FEISHU)
    register_provider(MockIMProvider(name=PROVIDER_FEISHU))

    # 验证写入前 payload 无 im_message_id
    assert "im_message_id" not in notif.payload

    await send_hitl_card_job(None, str(notif.id))

    # 重新读取
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)

    assert db_notif.payload.get("im_message_id") == "mock-msg-1"


@pytest.mark.asyncio
async def test_send_hitl_card_job_missing_notification_no_op(
    db_session, clean_phase3_tables, monkeypatch, caplog
):
    """notification_id 不存在 → log.error，不抛异常，不破坏 worker。"""
    register_provider(MockIMProvider(name=PROVIDER_FEISHU))

    caplog.set_level(logging.ERROR, logger="app.jobs.im_jobs")
    # 使用一个不存在的 BIGSERIAL ID
    await send_hitl_card_job(None, "999999999")

    # 找到 error 日志
    matched = [
        r
        for r in caplog.records
        if "send_hitl_card_job" in r.message and "不存在" in r.message
    ]
    assert len(matched) >= 1


@pytest.mark.asyncio
async def test_send_hitl_card_job_failure_log_extra_fields(
    db_session, clean_phase3_tables, monkeypatch, caplog
):
    """失败路径 caplog 含 status='failed' + error 字段。"""
    notif = await _seed_im_notification(db_session, channel=PROVIDER_FEISHU)
    register_provider(MockIMProvider(name=PROVIDER_FEISHU, fail_count=10))
    monkeypatch.setattr("app.jobs.im_jobs._RETRY_WAIT", tenacity.wait_none())

    caplog.set_level(logging.ERROR, logger="app.jobs.im_jobs")
    await send_hitl_card_job(None, str(notif.id))

    failure_logs = [
        r for r in caplog.records
        if r.message == "im.card.send" and getattr(r, "status", None) == "failed"
    ]
    assert len(failure_logs) >= 1
    fl = failure_logs[-1]
    assert getattr(fl, "provider", None) == PROVIDER_FEISHU
    assert isinstance(getattr(fl, "error", None), str)
