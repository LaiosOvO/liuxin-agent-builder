"""HITL email arq job 重试集成测试（Plan 03-04 Task 3）。

测试 5 用例（CLAUDE.md 2.2 — 真实 PG + monkeypatch _send_email）：
1. test_send_hitl_email_success：1 次成功 → notif.status=sent + sent_at 已写
2. test_send_hitl_email_idempotent：已 sent 的 notification 二次 enqueue → skip 不重发
3. test_send_hitl_email_retries_on_smtp_error：第 1 次 SMTPException，第 2 次成功 → 重试 1 次
4. test_send_hitl_email_fails_after_3_retries：3 次都 SMTP fail → notif.status=failed + error_message
5. test_send_hitl_email_uses_reminder_template_when_round_gt_0：reminder_round=1 用 hitl_reminder.html

Mock 策略：
- monkeypatch app.jobs.email_jobs._send_email（直接 stub，不真发邮件）
- 真实 PG（db_session fixture）写入 notifications 行 + 验证状态变化
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosmtplib
import pytest
from sqlalchemy import select, text

from app.agent_builder.models.notification import Notification
from app.jobs.email_jobs import (
    _build_deeplink,
    _render_email_content,
    send_hitl_email_job,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3_tables(db_session):
    """每次测试后清理 Phase 3 表。"""
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


async def _seed_notification(
    db_session,
    *,
    reminder_round: int = 0,
    status: str = "pending",
) -> Notification:
    """创建一条完整的 ws/user/wf/ver/inst/node_state + notifications 行。"""
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
        {"id": str(ws_id), "name": "邮件job测试ws", "slug": f"emailjob-ws-{ws_id.hex[:8]}"},
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
            "name": "emailjob_wf",
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

    # 建 notifications 行（直接构造 ORM 实例 — 不走 NotificationService 避免 arq 干扰）
    notif = Notification(
        workspace_id=ws_id,
        instance_id=inst_id,
        node_state_id=node_state_id,
        channel="email",
        recipient="approver@example.com",
        reminder_round=reminder_round,
        status=status,
        payload={
            "tokens": [
                {"jti": str(jti1), "action": "submit"},
                {"jti": str(jti2), "action": "return"},
                {"jti": str(jti3), "action": "reject"},
            ],
            "form_schema": {"type": "object"},
            "deadline_at": (datetime.now(timezone.utc)).isoformat(),
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


# ── 辅助：monkeypatch _send_email 跟踪调用 ────────────────────────────────────


class _SendEmailRecorder:
    """记录每次 _send_email 调用 + 模拟成功 / 失败。"""

    def __init__(
        self,
        *,
        fail_count: int = 0,
        exception_factory=None,
    ) -> None:
        """fail_count: 前 N 次抛异常，第 N+1 次成功（fail_count=0 即始终成功）。"""
        self.calls: list[dict[str, Any]] = []
        self.fail_count = fail_count
        self.exception_factory = exception_factory or (
            lambda: aiosmtplib.errors.SMTPException("simulated SMTP failure")
        )

    async def __call__(self, *, to: str, subject: str, html_body: str) -> None:
        self.calls.append(
            {"to": to, "subject": subject, "html_body": html_body}
        )
        if len(self.calls) <= self.fail_count:
            raise self.exception_factory()


# ── 5 个测试用例 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_email_success(db_session, clean_phase3_tables, monkeypatch):
    """1 次成功路径 → notif.status=sent + sent_at 已写 + _send_email 调用 1 次。"""
    notif = await _seed_notification(db_session)

    recorder = _SendEmailRecorder(fail_count=0)
    monkeypatch.setattr("app.jobs.email_jobs._send_email", recorder)

    await send_hitl_email_job(None, str(notif.id))

    # 重新 SELECT 拿到最新状态（job 内部用自己的 session）
    await db_session.commit()  # 清空当前 session 缓存
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)

    assert db_notif.status == "sent"
    assert db_notif.sent_at is not None
    assert db_notif.error_message is None

    # _send_email 调用 1 次
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["to"] == "approver@example.com"
    assert "员工入职流程" in call["subject"]
    assert "HR 审批" in call["subject"]
    # html_body 含 deeplink + 申请人 + 按钮
    assert "/hitl/page/" in call["html_body"]
    assert "张申请" in call["html_body"]


@pytest.mark.asyncio
async def test_send_hitl_email_idempotent(db_session, clean_phase3_tables, monkeypatch):
    """已 sent 的 notification 二次调用 job → 跳过（不重发 _send_email）。"""
    # 直接创建 status='sent' 的 notification
    notif = await _seed_notification(db_session, status="sent")

    recorder = _SendEmailRecorder(fail_count=0)
    monkeypatch.setattr("app.jobs.email_jobs._send_email", recorder)

    await send_hitl_email_job(None, str(notif.id))

    # _send_email 未被调用
    assert len(recorder.calls) == 0

    # status 仍然 sent
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "sent"


@pytest.mark.asyncio
async def test_send_hitl_email_retries_on_smtp_error(
    db_session, clean_phase3_tables, monkeypatch
):
    """第 1 次 SMTPException，第 2 次成功 → 重试 1 次 + 最终 status=sent。"""
    notif = await _seed_notification(db_session)

    # fail_count=1 → 第 1 次抛异常，第 2 次成功
    recorder = _SendEmailRecorder(fail_count=1)
    monkeypatch.setattr("app.jobs.email_jobs._send_email", recorder)

    # 用 monkeypatch 替换 wait_exponential 让重试不真 sleep（加速测试）
    import tenacity
    monkeypatch.setattr(
        "app.jobs.email_jobs._RETRY_WAIT", tenacity.wait_none()
    )

    await send_hitl_email_job(None, str(notif.id))

    # 重试 1 次 → 共 2 次调用
    assert len(recorder.calls) == 2

    # 最终 status=sent
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "sent"
    assert db_notif.sent_at is not None
    assert db_notif.error_message is None  # 最终成功不留 error_message


@pytest.mark.asyncio
async def test_send_hitl_email_fails_after_3_retries(
    db_session, clean_phase3_tables, monkeypatch
):
    """3 次都 SMTPException → notif.status=failed + error_message 写入。"""
    notif = await _seed_notification(db_session)

    # fail_count=10 大于重试上限 3，模拟全失败
    recorder = _SendEmailRecorder(fail_count=10)
    monkeypatch.setattr("app.jobs.email_jobs._send_email", recorder)

    # 加速测试：不真 sleep
    import tenacity
    monkeypatch.setattr(
        "app.jobs.email_jobs._RETRY_WAIT", tenacity.wait_none()
    )

    await send_hitl_email_job(None, str(notif.id))

    # 总共调用 3 次（首次 + 2 次重试 = stop_after_attempt(3)）
    assert len(recorder.calls) == 3

    # 最终 status=failed + error_message 存
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "failed"
    assert db_notif.error_message is not None
    assert "simulated SMTP failure" in db_notif.error_message

    # 验证 audit_log 也写了（NOTI-10 可观测要求）
    from sqlalchemy import text as sa_text
    audit_result = await db_session.execute(
        sa_text(
            "SELECT action, meta FROM audit_logs WHERE action='email.send_failed' "
            "AND workspace_id=:ws_id"
        ),
        {"ws_id": str(db_notif.workspace_id)},
    )
    audit_rows = audit_result.fetchall()
    assert len(audit_rows) >= 1
    assert audit_rows[0][0] == "email.send_failed"


@pytest.mark.asyncio
async def test_send_hitl_email_uses_reminder_template_when_round_gt_0(
    db_session, clean_phase3_tables, monkeypatch
):
    """reminder_round=1 → 使用 hitl_reminder.html 模板（含 [催办] 标识）。"""
    notif = await _seed_notification(db_session, reminder_round=1)

    recorder = _SendEmailRecorder(fail_count=0)
    monkeypatch.setattr("app.jobs.email_jobs._send_email", recorder)

    await send_hitl_email_job(None, str(notif.id))

    # 调用了 1 次
    assert len(recorder.calls) == 1
    call = recorder.calls[0]

    # subject 含 [催办] 前缀
    assert call["subject"].startswith("[催办] ")

    # html_body 来自 hitl_reminder.html — 含红色 banner #dc2626 (催办色)
    assert "#dc2626" in call["html_body"], "催办模板红色 banner 缺失"
    assert "[催办]" in call["html_body"]

    # 状态 sent
    await db_session.commit()
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    await db_session.refresh(db_notif)
    assert db_notif.status == "sent"


# ── Bonus：辅助函数单元测试（提升覆盖率） ───────────────────────────────────


def test_build_deeplink_default_base_url(monkeypatch):
    """_build_deeplink 默认从 PUBLIC_BASE_URL env 读取。"""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com")
    url = _build_deeplink("abc-def")
    assert url == "https://example.com/hitl/page/abc-def"


def test_build_deeplink_strips_trailing_slash(monkeypatch):
    """_build_deeplink rstrip('/') 防双斜杠。"""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com/")
    url = _build_deeplink("xyz")
    assert url == "https://example.com/hitl/page/xyz"


def test_render_email_content_decision_template():
    """_render_email_content 渲染 hitl_decision.html 模板。"""
    payload = {
        "tokens": [{"jti": "tok1", "action": "submit"}],
        "flow_title": "Flow A",
        "node_title": "Node A",
        "applicant_name": "App A",
        "actor_name": "Actor A",
        "deadline_at": "2026-05-18 14:00",
        "description": "Desc A",
    }
    html = _render_email_content(payload, "hitl_decision.html")
    assert "Flow A" in html
    assert "Node A" in html
    assert "/hitl/page/tok1" in html
    assert "提交" in html
