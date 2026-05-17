"""NotificationNodeExecutor 多通道集成测试（Plan 04-10 Task 3）。

CLAUDE.md 2.2 三层测试 — 真实 PG（不 mock DB）+ MockIMProvider（不依赖外部 IM）。

测试矩阵（≥ 4 用例 + 边界用例）：
1. test_execute_email_only_backward_compat — 无 channels 字段 → 默认 ['email']
2. test_execute_email_and_feishu_dispatches_both — channels=['email','feishu'] → email + IM 入队
3. test_execute_skips_invalid_email_for_email_channel — email 格式错过滤
4. test_execute_partial_failure_continues — 一个 channel 失败不阻塞其他
5. test_execute_im_channel_accepts_any_recipient_string — IM 不校验邮箱格式
6. test_execute_multiple_im_channels_all_dispatched — channels=['feishu','wecom'] 都入队
7. test_execute_unknown_channel_skipped_within_mixed — channels=['email','sms','feishu']
8. test_execute_payload_distinct_per_channel — 每行独立 payload
9. test_execute_failed_count_isolated_per_channel — per-channel try/except
10. test_execute_state_contains_notification_ids_for_all_channels — state 完整
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def clean_phase4_notif_tables(db_session):
    """每次测试后清理 Phase 3+4 表。"""
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
    """创建一条完整 ws/user/wf/ver/inst 链路。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(ws_id),
            "name": "mc-node-ws",
            "slug": f"mc-node-ws-{ws_id.hex[:8]}",
        },
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
            "name": "mc_node_wf",
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
    await db_session.commit()

    return {"ws_id": ws_id, "user_id": user_id, "inst_id": inst_id}


def _make_notification_node(
    node_id: str = "notif_mc",
    config_overrides: dict | None = None,
) -> dict:
    """构造 Notification node_def。"""
    config: dict = {
        "channels": ["email"],
        "recipients": ["alice@example.com"],
        "subject": "测试主题",
        "body": "测试正文",
    }
    if config_overrides:
        config.update(config_overrides)
    return {"id": node_id, "type": "notification", "config": config}


def _build_executor(seed: dict, node_def: dict):
    """构造 NotificationNodeExecutor。"""
    from app.agent_builder.workflow.nodes.notification import NotificationNodeExecutor

    return NotificationNodeExecutor(
        node_def,
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
    )


# ── 测试用例 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_email_only_backward_compat(
    db_session, clean_phase4_notif_tables
):
    """无 channels 字段（Phase 3 旧 DSL）→ 默认 ['email']，单 channel 入队。"""
    seed = await _seed_workflow_instance(db_session)
    # 注意不在 config_overrides 内指定 channels
    node_def = {
        "id": "notif_legacy",
        "type": "notification",
        "config": {
            # 无 channels 字段
            "recipients": ["legacy@example.com"],
            "subject": "向后兼容测试",
            "body": "Phase 3 旧 DSL",
        },
    }
    executor = _build_executor(seed, node_def)

    result = await executor({"start": {}})

    inner = result["notif_legacy"]
    assert inner["sent_count"] == 1
    assert inner["failed_count"] == 0
    assert len(inner["notification_ids"]) == 1

    # DB 验证：1 行 channel='email'
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.id == inner["notification_ids"][0])
    )
    notif = res.scalar_one()
    assert notif.channel == "email"
    assert notif.recipient == "legacy@example.com"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_email_and_feishu_dispatches_both(
    db_session, clean_phase4_notif_tables
):
    """channels=['email','feishu'] + 同 recipients → email + IM 各 1 行。

    注意：recipients 字符串 'alice@example.com' 对 email 是合法邮箱，
    对 feishu 是合法 IM user_id 字符串（IM 不强校验邮箱格式）。
    """
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["email", "feishu"],
                "recipients": ["alice@example.com"],
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_mc"]
    # email channel 1 + feishu channel 1 = 2
    assert inner["sent_count"] == 2
    assert inner["failed_count"] == 0
    assert len(inner["notification_ids"]) == 2

    # DB 验证：2 行不同 channel
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification)
        .where(Notification.instance_id == seed["inst_id"])
        .order_by(Notification.channel)
    )
    rows = list(res.scalars().all())
    assert len(rows) == 2
    channels_in_db = {r.channel for r in rows}
    assert channels_in_db == {"email", "feishu"}

    # email 行 payload.generic=True 且 channel=email
    email_row = next(r for r in rows if r.channel == "email")
    assert email_row.payload.get("generic") is True

    # feishu 行 payload.generic=True 且 channel=feishu (走 enqueue_generic_im_card)
    feishu_row = next(r for r in rows if r.channel == "feishu")
    assert feishu_row.payload.get("generic") is True
    assert feishu_row.payload.get("recipient_im") == "alice@example.com"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_skips_invalid_email_for_email_channel(
    db_session, clean_phase4_notif_tables
):
    """email channel：'invalid-not-email' 被过滤，仅合法邮箱入队。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["email"],
                "recipients": [
                    "valid@example.com",
                    "invalid-not-email",  # 被过滤
                    "another@example.com",
                ],
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_mc"]
    # 2 合法邮箱 + 1 invalid 被过滤
    assert inner["sent_count"] == 2
    assert inner["failed_count"] == 0

    # DB 验证：仅 2 行
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(func.count(Notification.id)).where(
            Notification.instance_id == seed["inst_id"]
        )
    )
    assert res.scalar_one() == 2

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_partial_failure_continues(
    db_session, clean_phase4_notif_tables
):
    """email enqueue 成功 + feishu enqueue 抛错 → email_sent=1, feishu_failed=1。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["email", "feishu"],
                "recipients": ["user@example.com"],
            }
        ),
    )

    # patch enqueue_generic_im_card 抛错（模拟 IM API 不可达 / DB 错）
    from app.services.notification_service import NotificationService

    async def fail_im_enqueue(self, **kwargs):
        raise RuntimeError("mock IM 入队失败")

    with patch.object(
        NotificationService, "enqueue_generic_im_card", fail_im_enqueue
    ):
        result = await executor({"start": {}})

    inner = result["notif_mc"]
    # email 成功 + feishu 失败
    assert inner["sent_count"] == 1
    assert inner["failed_count"] == 1
    assert len(inner["notification_ids"]) == 1

    # DB 验证：仅 email 1 行（feishu 已 rollback）
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.instance_id == seed["inst_id"])
    )
    rows = list(res.scalars().all())
    assert len(rows) == 1
    assert rows[0].channel == "email"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_im_channel_accepts_any_recipient_string(
    db_session, clean_phase4_notif_tables
):
    """IM channel 接受任意字符串（不像 email 校验邮箱格式）。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["feishu"],
                "recipients": ["ou_abc_xyz_no_email"],  # 非邮箱格式但合法 IM user_id
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_mc"]
    # IM channel 应接受任意非空字符串
    assert inner["sent_count"] == 1
    assert inner["failed_count"] == 0

    # DB 验证
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(
            Notification.instance_id == seed["inst_id"]
        )
    )
    notif = res.scalar_one()
    assert notif.channel == "feishu"
    assert notif.recipient == "ou_abc_xyz_no_email"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_multiple_im_channels_all_dispatched(
    db_session, clean_phase4_notif_tables
):
    """channels=['feishu','wecom','dingtalk'] + 1 recipient → 3 行不同 IM channel。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["feishu", "wecom", "dingtalk"],
                "recipients": ["ou_universal_user"],
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_mc"]
    assert inner["sent_count"] == 3
    assert inner["failed_count"] == 0

    # DB 验证：3 行不同 channel
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification)
        .where(Notification.instance_id == seed["inst_id"])
        .order_by(Notification.channel)
    )
    rows = list(res.scalars().all())
    assert len(rows) == 3
    channels_in_db = sorted(r.channel for r in rows)
    assert channels_in_db == ["dingtalk", "feishu", "wecom"]

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_unknown_channel_skipped_within_mixed(
    db_session, clean_phase4_notif_tables, caplog
):
    """channels=['email','sms','feishu']：sms 跳过 + 警告，email + feishu 正常。"""
    import logging

    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["email", "sms", "feishu"],  # sms 未知
                "recipients": ["alice@example.com"],
            }
        ),
    )

    with caplog.at_level(logging.WARNING):
        result = await executor({"start": {}})

    inner = result["notif_mc"]
    # email + feishu 2 个 channel 成功
    assert inner["sent_count"] == 2

    # caplog 含未知 channel warning
    warning_msgs = [
        r.message for r in caplog.records if r.levelname == "WARNING"
    ]
    has_sms_warning = any("sms" in m for m in warning_msgs)
    assert has_sms_warning, (
        f"应有 sms 跳过 warning。Messages: {warning_msgs}"
    )

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_payload_distinct_per_channel(
    db_session, clean_phase4_notif_tables
):
    """每行 notification 独立 payload dict（同 (channel, recipient) 隔离）。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["email", "feishu"],
                "recipients": ["user@example.com"],
                "subject": "唯一主题",
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_mc"]
    assert inner["sent_count"] == 2

    # 两行 payload 各自独立（dict identity 不同）
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.instance_id == seed["inst_id"])
    )
    rows = list(res.scalars().all())
    assert len(rows) == 2

    # 修改其中一行 payload 应不影响另一行（通过 dict.update 模拟）
    rows[0].payload["custom"] = "marker"
    assert "custom" not in rows[1].payload

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_failed_count_isolated_per_channel(
    db_session, clean_phase4_notif_tables
):
    """email enqueue 失败 + feishu enqueue 成功 → email failed=1, feishu sent=1。

    与 test_execute_partial_failure_continues 相反方向。
    """
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["email", "feishu"],
                "recipients": ["user@example.com"],
            }
        ),
    )

    from app.services.notification_service import NotificationService

    async def fail_email_enqueue(self, **kwargs):
        raise RuntimeError("mock SMTP 不可达")

    with patch.object(
        NotificationService, "enqueue_generic_email", fail_email_enqueue
    ):
        result = await executor({"start": {}})

    inner = result["notif_mc"]
    # email 失败 + feishu 成功
    assert inner["sent_count"] == 1  # feishu
    assert inner["failed_count"] == 1  # email

    # DB 验证：仅 feishu 1 行
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.instance_id == seed["inst_id"])
    )
    rows = list(res.scalars().all())
    assert len(rows) == 1
    assert rows[0].channel == "feishu"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_execute_state_contains_notification_ids_for_all_channels(
    db_session, clean_phase4_notif_tables
):
    """返回 state.notification_ids 含所有 channel 的 id（按入队顺序）。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["email", "feishu", "slack"],
                "recipients": ["multi@example.com"],
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_mc"]
    assert inner["sent_count"] == 3
    notification_ids = inner["notification_ids"]
    assert len(notification_ids) == 3
    # 所有 id 都是 int 且唯一
    assert all(isinstance(nid, int) for nid in notification_ids)
    assert len(set(notification_ids)) == 3

    # DB 验证：3 行的 id 与 state 一致
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification.id).where(Notification.instance_id == seed["inst_id"])
    )
    db_ids = sorted(r for r in res.scalars().all())
    assert sorted(notification_ids) == db_ids

    await asyncio.sleep(0.05)
