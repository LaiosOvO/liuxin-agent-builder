"""NotificationService 多通道 fan-out 集成测试（Plan 04-10 Task 1）。

CLAUDE.md 2.2 三层测试 — 真实 PG（不 mock DB）+ MockIMProvider（不发真实 IM）。

测试矩阵（≥ 8 用例）：
1. test_multichannel_email_only — channels=['email'] → 1 行 + enqueue send_hitl_email_job
2. test_multichannel_email_and_feishu — channels=['email','feishu'] + bindings → 2 行
3. test_multichannel_skip_channel_without_binding — bindings 缺 feishu → 1 行 + caplog warning
4. test_multichannel_enqueue_after_commit — commit 后才 enqueue（防 Pitfall 2）
5. test_enqueue_generic_im_card_writes_row — channel=feishu + recipient → 1 行 + enqueue send_hitl_card_job
6. test_enqueue_generic_im_card_unique_constraint — 相同 (instance,ns,channel,recipient,round=0) 二次 → IntegrityError
7. test_multichannel_reminder_round_unique — round=1 与 round=0 不冲突
8. test_multichannel_no_im_bindings_dict_none — bindings=None → 仅 email 入队
9. test_multichannel_empty_channels_raises — channels=[] → ValueError
10. test_multichannel_unknown_channel_raises — channels=['sms'] → ValueError
11. test_enqueue_generic_im_card_rejects_email_channel — channel='email' → ValueError
12. test_multichannel_payload_immutable_across_channels — 每行独立 payload dict
13. test_multichannel_structured_log_emitted — caplog 'notification.multichannel.enqueued'
"""
from __future__ import annotations

import asyncio
import logging
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
async def clean_phase4_tables(db_session):
    """每次测试后清理 Phase 3+4 表（参考 test_notification_service.py 模式）。"""
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


async def _seed_workflow_instance(db_session) -> dict[str, Any]:
    """创建一条完整 ws/user/wf/ver/inst/node_state 链路 + 3 个 hitl_tokens。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "mc-ws", "slug": f"mc-ws-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, :ph, 'active', false)"
        ),
        {
            "id": str(user_id),
            "email": f"u_{uuid.uuid4().hex[:6]}@test.com",
            "ph": "hash",
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "mc_wf",
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
    await db_session.commit()

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

    async def enqueue_job(
        self, function_name: str, *args, **kwargs
    ) -> None:
        self.enqueued.append((function_name, args, kwargs))


def _make_multichannel_kwargs(seed: dict, channels: list[str]) -> dict[str, Any]:
    """构造 enqueue_hitl_multichannel 入参的公共部分。"""
    return {
        "workspace_id": seed["ws_id"],
        "instance_id": seed["inst_id"],
        "node_state_id": seed["node_state_id"],
        "recipient_email": "user@example.com",
        "recipient_im_bindings": None,  # 各测试 override
        "tokens": seed["tokens"],
        "form_schema": {"type": "object", "properties": {}},
        "deadline_at": datetime.now(timezone.utc) + timedelta(hours=24),
        "actor_name": "审批人",
        "flow_title": "测试流程",
        "node_title": "测试节点",
        "applicant_name": "申请人",
        "description": "测试描述",
        "channels": channels,
    }


# ── 测试用例（≥ 8 用例）─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multichannel_email_only(db_session, clean_phase4_tables):
    """channels=['email'] → 1 行 notifications + enqueue send_hitl_email_job。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email"])
    created = await svc.enqueue_hitl_multichannel(**kwargs)

    assert len(created) == 1
    assert created[0].channel == "email"
    assert created[0].recipient == "user@example.com"
    assert created[0].status == "pending"
    assert created[0].reminder_round == 0

    # DB 行数验证
    result = await db_session.execute(
        select(Notification).where(Notification.instance_id == seed["inst_id"])
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1

    # 入队验证
    assert len(arq.enqueued) == 1
    fn_name, args, _ = arq.enqueued[0]
    assert fn_name == "send_hitl_email_job"
    assert args == (str(created[0].id),)


@pytest.mark.asyncio
async def test_multichannel_email_and_feishu(db_session, clean_phase4_tables):
    """channels=['email','feishu'] + bindings.feishu='ou_x' → 2 行 + 2 不同 job。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email", "feishu"])
    kwargs["recipient_im_bindings"] = {"feishu": "ou_test_feishu_user"}

    created = await svc.enqueue_hitl_multichannel(**kwargs)

    assert len(created) == 2
    channels_created = {n.channel for n in created}
    assert channels_created == {"email", "feishu"}

    # 各 channel 的 recipient 正确
    by_channel = {n.channel: n for n in created}
    assert by_channel["email"].recipient == "user@example.com"
    assert by_channel["feishu"].recipient == "ou_test_feishu_user"

    # 各 channel 入队对应 job
    assert len(arq.enqueued) == 2
    jobs_by_args = {args[0]: fn for fn, args, _ in arq.enqueued}
    email_id = str(by_channel["email"].id)
    feishu_id = str(by_channel["feishu"].id)
    assert jobs_by_args[email_id] == "send_hitl_email_job"
    assert jobs_by_args[feishu_id] == "send_hitl_card_job"


@pytest.mark.asyncio
async def test_multichannel_skip_channel_without_binding(
    db_session, clean_phase4_tables, caplog
):
    """channels=['email','feishu']，bindings 无 feishu → 仅 email 1 行 + caplog warning。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email", "feishu"])
    kwargs["recipient_im_bindings"] = {"wecom": "WuPing"}  # 不含 feishu

    with caplog.at_level(logging.WARNING):
        created = await svc.enqueue_hitl_multichannel(**kwargs)

    # 仅 email 创建（feishu 缺 binding 跳过）
    assert len(created) == 1
    assert created[0].channel == "email"

    # 入队仅 1 个（email job）
    assert len(arq.enqueued) == 1
    fn_name, _, _ = arq.enqueued[0]
    assert fn_name == "send_hitl_email_job"

    # caplog 含 warning（"im_bindings 缺 feishu"）
    warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("缺 feishu" in m for m in warning_msgs), (
        f"未找到缺 feishu 的 warning。Messages: {warning_msgs}"
    )


@pytest.mark.asyncio
async def test_multichannel_enqueue_after_commit(db_session, clean_phase4_tables):
    """commit 后才 enqueue（防 Pitfall 2 worker 抢跑事务未提交行）。

    通过 mock arq.enqueue_job 内查询 DB 验证：被调用时 notif.id 必须已可 SELECT 到。
    """
    seed = await _seed_workflow_instance(db_session)

    # 自定义 arq pool：每次 enqueue_job 时 SELECT 数据库验证 notif 已可见
    enqueue_db_visibility: list[bool] = []

    class _VerifyArqPool:
        def __init__(self, db) -> None:
            self.db = db
            self.enqueued: list[tuple[str, tuple]] = []

        async def enqueue_job(
            self, function_name: str, *args, **kwargs
        ) -> None:
            self.enqueued.append((function_name, args))
            # 验证 notification_id 这时已在 DB 中
            notif_id = int(args[0])
            result = await self.db.execute(
                select(Notification).where(Notification.id == notif_id)
            )
            row = result.scalar_one_or_none()
            enqueue_db_visibility.append(row is not None)

    arq = _VerifyArqPool(db_session)
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email"])
    created = await svc.enqueue_hitl_multichannel(**kwargs)

    assert len(created) == 1
    # commit 之后才 enqueue → DB 行必须可见
    assert all(enqueue_db_visibility), (
        f"enqueue_job 调用时 notification 不可见 → 违反事务边界. "
        f"Visibility: {enqueue_db_visibility}"
    )


@pytest.mark.asyncio
async def test_enqueue_generic_im_card_writes_row(db_session, clean_phase4_tables):
    """channel=feishu + recipient=ou_x → 1 行 + enqueue send_hitl_card_job。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    notif = await svc.enqueue_generic_im_card(
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        recipient="ou_test_xyz",
        channel="feishu",
        subject="测试主题",
        body="测试正文",
    )

    assert notif.id is not None
    assert notif.channel == "feishu"
    assert notif.recipient == "ou_test_xyz"
    assert notif.status == "pending"
    assert notif.reminder_round == 0

    # payload 含 generic=True 标识
    assert notif.payload["generic"] is True
    assert notif.payload["subject"] == "测试主题"
    assert notif.payload["body"] == "测试正文"
    assert notif.payload["recipient_im"] == "ou_test_xyz"

    # 入队 send_hitl_card_job（不是 email job）
    assert len(arq.enqueued) == 1
    fn_name, args, _ = arq.enqueued[0]
    assert fn_name == "send_hitl_card_job"
    assert args == (str(notif.id),)


@pytest.mark.asyncio
async def test_enqueue_generic_im_card_unique_constraint(
    db_session, clean_phase4_tables
):
    """相同 (instance, node_state, channel, recipient, round=0) 重复 → IntegrityError。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    common_kwargs = {
        "workspace_id": seed["ws_id"],
        "instance_id": seed["inst_id"],
        "node_state_id": seed["node_state_id"],
        "recipient": "ou_duplicate",
        "channel": "feishu",
        "subject": "first",
        "body": "body1",
    }

    # 第一次成功
    await svc.enqueue_generic_im_card(**common_kwargs)

    # 第二次相同参数 → UNIQUE 冲突
    with pytest.raises(IntegrityError) as exc_info:
        await svc.enqueue_generic_im_card(**common_kwargs)

    err_str = str(exc_info.value).lower()
    assert "uq_notifications_dedup" in err_str or "unique" in err_str

    # rollback 让 session 可继续用
    await db_session.rollback()


@pytest.mark.asyncio
async def test_multichannel_reminder_round_unique(db_session, clean_phase4_tables):
    """reminder_round=1 + 0 不冲突（同 instance/ns/channel/recipient 不同 round）。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs0 = _make_multichannel_kwargs(seed, channels=["email"])
    created0 = await svc.enqueue_hitl_multichannel(**kwargs0)

    kwargs1 = _make_multichannel_kwargs(seed, channels=["email"])
    kwargs1["reminder_round"] = 1
    created1 = await svc.enqueue_hitl_multichannel(**kwargs1)

    assert created0[0].id != created1[0].id
    assert created0[0].reminder_round == 0
    assert created1[0].reminder_round == 1

    # DB 双行落地
    result = await db_session.execute(
        select(Notification)
        .where(Notification.instance_id == seed["inst_id"])
        .order_by(Notification.reminder_round)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_multichannel_no_im_bindings_dict_none(db_session, clean_phase4_tables):
    """bindings=None → 仅 email 入队（IM channel 全跳过 + warn）。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email", "feishu", "wecom"])
    kwargs["recipient_im_bindings"] = None  # None 而不是空 dict

    created = await svc.enqueue_hitl_multichannel(**kwargs)

    # 仅 email 创建
    assert len(created) == 1
    assert created[0].channel == "email"


@pytest.mark.asyncio
async def test_multichannel_empty_channels_raises(db_session, clean_phase4_tables):
    """channels=[] → ValueError（必须至少 1 通道）。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=[])

    with pytest.raises(ValueError) as exc_info:
        await svc.enqueue_hitl_multichannel(**kwargs)

    assert "至少包含一个通道" in str(exc_info.value)


@pytest.mark.asyncio
async def test_multichannel_unknown_channel_raises(db_session, clean_phase4_tables):
    """channels=['sms'] → ValueError（未知 channel）。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email", "sms"])

    with pytest.raises(ValueError) as exc_info:
        await svc.enqueue_hitl_multichannel(**kwargs)

    assert "未知 channels" in str(exc_info.value)
    assert "sms" in str(exc_info.value)


@pytest.mark.asyncio
async def test_enqueue_generic_im_card_rejects_email_channel(
    db_session, clean_phase4_tables
):
    """enqueue_generic_im_card(channel='email') → ValueError（email 应用 enqueue_generic_email）。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    with pytest.raises(ValueError) as exc_info:
        await svc.enqueue_generic_im_card(
            workspace_id=seed["ws_id"],
            instance_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            recipient="user@example.com",
            channel="email",
            subject="x",
            body="y",
        )

    assert "仅支持 IM channel" in str(exc_info.value)


@pytest.mark.asyncio
async def test_multichannel_payload_immutable_across_channels(
    db_session, clean_phase4_tables
):
    """每行独立 payload dict（防 worker 写回 im_message_id 污染其他 channel）。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email", "feishu"])
    kwargs["recipient_im_bindings"] = {"feishu": "ou_x"}

    created = await svc.enqueue_hitl_multichannel(**kwargs)
    assert len(created) == 2

    # 两行的 payload 必须是独立 dict（id 不同）
    assert created[0].payload is not created[1].payload

    # 模拟 worker 修改其中一行 payload — 不应污染另一行
    created[0].payload["im_message_id"] = "msg-1"
    assert "im_message_id" not in created[1].payload


@pytest.mark.asyncio
async def test_multichannel_structured_log_emitted(
    db_session, clean_phase4_tables, caplog
):
    """caplog 含 'notification.multichannel.enqueued' 结构化日志 + extra 字段。"""
    seed = await _seed_workflow_instance(db_session)
    arq = _FakeArqPool()
    svc = NotificationService(db_session, arq_pool=arq)

    kwargs = _make_multichannel_kwargs(seed, channels=["email", "feishu"])
    kwargs["recipient_im_bindings"] = {"feishu": "ou_log_test"}

    with caplog.at_level(logging.INFO):
        await svc.enqueue_hitl_multichannel(**kwargs)

    # 找结构化日志条
    multichannel_records = [
        r for r in caplog.records
        if r.message == "notification.multichannel.enqueued"
    ]
    assert len(multichannel_records) == 1, (
        f"未找到 multichannel.enqueued 日志。All records: "
        f"{[r.message for r in caplog.records]}"
    )

    rec = multichannel_records[0]
    # extra 字段（注意 logging 把 extra 平铺到 record 属性）
    assert hasattr(rec, "channels")
    assert sorted(rec.channels) == ["email", "feishu"]
    assert hasattr(rec, "skipped_count")
    assert rec.skipped_count == 0
