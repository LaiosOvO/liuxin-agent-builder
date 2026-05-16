"""NotificationService 集成测试（Plan 03-04 Task 2）。

测试 5 用例（CLAUDE.md 2.2 — 真实 PG / 不 mock DB）：
1. test_enqueue_creates_notification_pending：写入 notifications 一行 status=pending
2. test_enqueue_payload_contains_tokens：payload.tokens 含 jti+action
3. test_enqueue_unique_constraint：相同 (instance, node_state, channel, recipient, round) → IntegrityError
4. test_enqueue_arq_pool_none_fallback_asyncio：arq_pool=None 走 asyncio.create_task 不抛错
5. test_enqueue_with_reminder_round_changes_record：round=1 与 round=0 双行不冲突

依赖：
- 真实 PG（db_session fixture from conftest）
- arq_pool 用 stub（捕获 enqueue_job 调用而不真发 Redis）
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.notification import Notification
from app.services.notification_service import NotificationService


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3_tables(db_session):
    """每次测试后清理 Phase 3 表（参考 test_notification_model.py 模式）。"""
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
    """创建一条完整 ws/user/wf/ver/inst/node_state 链路 + 3 个 hitl_tokens。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "通知服务ws", "slug": f"notisvc-ws-{ws_id.hex[:8]}"},
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
            "name": "notisvc_wf",
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
    await db_session.commit()

    # 创建 3 个 hitl_tokens（submit / return / reject）
    tokens = []
    for action in ["submit", "return", "reject"]:
        jti = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO hitl_tokens (jti, instance_id, node_state_id, actor_id, action, expires_at) "
                "VALUES (:jti, :inst_id, :ns_id, :actor_id, :action, NOW() + INTERVAL '24 hours')"
            ),
            {
                "jti": str(jti),
                "inst_id": str(inst_id),
                "ns_id": str(node_state_id),
                "actor_id": str(user_id),
                "action": action,
            },
        )
        tokens.append((jti, action))
    await db_session.commit()

    # 重新 SELECT 拿真实的 ORM 对象（带 created_at server defaults）
    result = await db_session.execute(
        select(HitlToken).where(HitlToken.node_state_id == node_state_id)
    )
    token_orms = list(result.scalars().all())

    return {
        "ws_id": ws_id,
        "user_id": user_id,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
        "tokens": token_orms,
    }


class _FakeArqPool:
    """arq pool stub — 捕获 enqueue_job 调用而不真发 Redis。"""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, function_name: str, *args, **kwargs) -> None:
        self.enqueued.append((function_name, args, kwargs))


def _make_payload_kwargs(seed: dict) -> dict[str, Any]:
    """构造 enqueue_hitl_email 入参的公共部分。"""
    return {
        "workspace_id": seed["ws_id"],
        "instance_id": seed["inst_id"],
        "node_state_id": seed["node_state_id"],
        "recipient_email": "test@example.com",
        "tokens": seed["tokens"],
        "form_schema": {"type": "object", "properties": {}},
        "deadline_at": datetime.now(timezone.utc) + timedelta(hours=24),
        "actor_name": "审批人",
        "flow_title": "测试流程",
        "node_title": "测试节点",
        "applicant_name": "申请人",
        "description": "测试描述",
    }


# ── 5 个测试用例 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_creates_notification_pending(db_session, clean_phase3_tables):
    """写入 notifications 一行 status=pending + arq enqueue_job 被调用。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    notif = await svc.enqueue_hitl_email(**_make_payload_kwargs(seed))

    # ORM 返回值检查
    assert notif.id is not None
    assert notif.status == "pending"
    assert notif.channel == "email"
    assert notif.recipient == "test@example.com"
    assert notif.reminder_round == 0
    assert notif.workspace_id == seed["ws_id"]

    # DB 验证：notifications 行确实落地
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif.id)
    )
    db_notif = result.scalar_one()
    assert db_notif.status == "pending"
    assert db_notif.payload  # 非空 JSONB

    # arq enqueue_job 被调用 1 次（function_name + 一个位置参数 notification_id）
    assert len(arq.enqueued) == 1
    fn_name, args, kwargs = arq.enqueued[0]
    assert fn_name == "send_hitl_email_job"
    assert args == (str(notif.id),)


@pytest.mark.asyncio
async def test_enqueue_payload_contains_tokens(db_session, clean_phase3_tables):
    """payload.tokens 数组含 3 个 (jti, action) 记录。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    notif = await svc.enqueue_hitl_email(**_make_payload_kwargs(seed))

    # payload 结构检查
    payload = notif.payload
    assert "tokens" in payload
    assert len(payload["tokens"]) == 3
    actions = {t["action"] for t in payload["tokens"]}
    assert actions == {"submit", "return", "reject"}

    # 每个 token 含 jti（UUID 字符串格式）+ action 字段
    for token in payload["tokens"]:
        assert "jti" in token
        assert "action" in token
        # jti 应为 36 字符 UUID 字符串
        assert len(token["jti"]) == 36
        assert token["action"] in {"submit", "return", "reject"}

    # 其他 context 字段
    assert payload["flow_title"] == "测试流程"
    assert payload["node_title"] == "测试节点"
    assert payload["applicant_name"] == "申请人"
    assert payload["actor_name"] == "审批人"
    assert payload["description"] == "测试描述"
    assert "deadline_at" in payload
    assert "form_schema" in payload


@pytest.mark.asyncio
async def test_enqueue_unique_constraint(db_session, clean_phase3_tables):
    """相同 (instance, node_state, channel, recipient, round) 二次 enqueue → IntegrityError。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    # 第一次 enqueue 成功
    await svc.enqueue_hitl_email(**_make_payload_kwargs(seed))

    # 第二次相同参数 → UNIQUE 冲突
    with pytest.raises(IntegrityError) as exc_info:
        await svc.enqueue_hitl_email(**_make_payload_kwargs(seed))

    # 错误信息含 uq_notifications_dedup（或 unique 关键字）
    err_str = str(exc_info.value).lower()
    assert "uq_notifications_dedup" in err_str or "unique" in err_str

    # rollback 让 session 可继续用
    await db_session.rollback()


@pytest.mark.asyncio
async def test_enqueue_arq_pool_none_fallback_asyncio(db_session, clean_phase3_tables):
    """arq_pool=None → 走 asyncio.create_task fallback，不抛错（不实际等待 task 完成）。"""
    seed = await _seed_workflow_instance(db_session)
    svc = NotificationService(db_session, arq_pool=None)

    # 此调用不应抛错（fallback 路径只 create_task，不 await）
    # asyncio.create_task 创建的 task 在后台执行；其内部访问 async_session_maker
    # 可能在测试事件循环结束前未跑完 — 这没关系，我们只测试主路径不抛
    notif = await svc.enqueue_hitl_email(**_make_payload_kwargs(seed))

    # notifications 行已落地
    assert notif.id is not None
    assert notif.status == "pending"

    # 给 asyncio.create_task 一点时间执行（避免 "Task was destroyed but it is pending" warning）
    # 不强校验 task 结果（不依赖 SMTP）
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_enqueue_with_reminder_round_changes_record(db_session, clean_phase3_tables):
    """同 (instance, node_state, channel, recipient) 不同 round → 两行独立记录。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    # round=0 首次发送
    notif0 = await svc.enqueue_hitl_email(
        **_make_payload_kwargs(seed),
        reminder_round=0,
    )

    # round=1 催办（UNIQUE 不冲突 — round 也在唯一键内）
    notif1 = await svc.enqueue_hitl_email(
        **_make_payload_kwargs(seed),
        reminder_round=1,
    )

    # 两行 ID 不同
    assert notif0.id != notif1.id
    assert notif0.reminder_round == 0
    assert notif1.reminder_round == 1

    # DB 验证：两行确实落地
    result = await db_session.execute(
        select(Notification)
        .where(Notification.instance_id == seed["inst_id"])
        .order_by(Notification.reminder_round)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 2
    assert rows[0].reminder_round == 0
    assert rows[1].reminder_round == 1
    # 都是 pending（未发送过）
    assert all(r.status == "pending" for r in rows)
