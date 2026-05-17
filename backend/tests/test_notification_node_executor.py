"""NotificationNodeExecutor 集成测试（Plan 03-05 Task 2 — 10 用例）。

CLAUDE.md 2.2 真实 DB 三层测试约定 — 不 mock PG。
测试矩阵：
  1. test_notification_executor_registered_in_node_executors
  2. test_notification_schema_registered_in_node_schemas
  3. test_notification_node_single_recipient
  4. test_notification_node_multiple_recipients_all_sent
  5. test_notification_node_jinja_subject_rendered
  6. test_notification_node_jinja_body_rendered
  7. test_notification_node_jinja_recipient_expression
  8. test_notification_node_invalid_email_filtered
  9. test_notification_node_unsupported_channel_skipped
  10. test_notification_node_one_recipient_fails_others_continue
  11. test_notification_node_writes_state_correctly
  12. test_notification_node_does_not_create_hitl_token
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def clean_notification_node_tables(db_session):
    """每次测试后清理 Phase 3 表 + node_states + flow_instances。"""
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
    """创建一条完整 ws/user/wf/ver/inst 链路（不预创建 node_states — 由节点自管理）。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "通知节点ws", "slug": f"noti-node-ws-{ws_id.hex[:8]}"},
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
            "name": "noti_node_wf",
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

    return {
        "ws_id": ws_id,
        "user_id": user_id,
        "inst_id": inst_id,
    }


def _make_notification_node(
    node_id: str = "notif_1",
    config_overrides: dict | None = None,
) -> dict:
    """构造 Notification node_def（DSL 编译期格式）。"""
    config: dict = {
        "channels": ["email"],
        "recipients": ["alice@example.com"],
        "subject": "测试通知主题",
        "body": "测试通知正文",
    }
    if config_overrides:
        config.update(config_overrides)
    return {"id": node_id, "type": "notification", "config": config}


def _build_executor(seed: dict, node_def: dict):
    """构造 NotificationNodeExecutor 并注入 workspace_id / instance_id。"""
    from app.agent_builder.workflow.nodes.notification import NotificationNodeExecutor

    return NotificationNodeExecutor(
        node_def,
        workspace_id=seed["ws_id"],
        instance_id=seed["inst_id"],
    )


# ── 测试用例 ──────────────────────────────────────────────────────────────────


def test_notification_executor_registered_in_node_executors():
    """NODE_EXECUTORS['notification'] 注册正确（独立 unit，不依赖 DB）。"""
    from app.agent_builder.workflow.nodes import NODE_EXECUTORS
    from app.agent_builder.workflow.nodes.notification import NotificationNodeExecutor

    assert "notification" in NODE_EXECUTORS
    assert NODE_EXECUTORS["notification"] is NotificationNodeExecutor


def test_notification_schema_registered_in_node_schemas():
    """NODE_SCHEMAS['notification'] 注册正确（独立 unit，不依赖 DB）。"""
    from app.agent_builder.workflow.node_schemas import NODE_SCHEMAS

    assert "notification" in NODE_SCHEMAS
    schema, output_fields = NODE_SCHEMAS["notification"]
    # 必填字段
    assert "recipients" in schema["required"]
    assert "subject" in schema["required"]
    assert "body" in schema["required"]
    # 输出字段
    assert "sent_count" in output_fields
    assert "failed_count" in output_fields
    assert "notification_ids" in output_fields


@pytest.mark.asyncio
async def test_notification_node_single_recipient(
    db_session, clean_notification_node_tables
):
    """单个 recipient 成功入队 → sent_count=1。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(seed, _make_notification_node())

    state = {"start": {"name": "Alice"}}
    result = await executor(state)

    # LangGraph 返回 {node_id: ...}
    assert "notif_1" in result
    inner = result["notif_1"]
    assert inner["sent_count"] == 1
    assert inner["failed_count"] == 0
    assert len(inner["notification_ids"]) == 1

    # DB 验证：notifications 表确实落地 1 行 status='pending'/'sending'/'sent'
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.id == inner["notification_ids"][0])
    )
    notif = res.scalar_one()
    assert notif.recipient == "alice@example.com"
    assert notif.channel == "email"
    assert notif.reminder_round == 0
    # status 可能是 pending / sending / sent 取决于异步 task 执行进度
    assert notif.status in {"pending", "sending", "sent", "failed"}
    # payload.generic 标识为通用通知（Plan 03-05 区分于 HITL 邮件）
    assert notif.payload.get("generic") is True

    # 让 asyncio.create_task fallback 完成（避免 "Task was destroyed but it is pending"）
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_multiple_recipients_all_sent(
    db_session, clean_notification_node_tables
):
    """3 个 recipient → 全部入队成功，sent_count=3。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "recipients": [
                    "alice@example.com",
                    "bob@example.com",
                    "charlie@example.com",
                ]
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_1"]
    assert inner["sent_count"] == 3
    assert inner["failed_count"] == 0
    assert len(inner["notification_ids"]) == 3

    # DB 验证：3 行不同 recipient
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification)
        .where(Notification.instance_id == seed["inst_id"])
        .order_by(Notification.recipient)
    )
    rows = list(res.scalars().all())
    assert len(rows) == 3
    assert sorted(r.recipient for r in rows) == [
        "alice@example.com",
        "bob@example.com",
        "charlie@example.com",
    ]

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_jinja_subject_rendered(
    db_session, clean_notification_node_tables
):
    """subject 含 Jinja 表达式 → 在执行时被渲染。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "subject": "Hi {{ start.name }}, 您的流程已完成",
            }
        ),
    )

    result = await executor({"start": {"name": "Alice"}})

    notification_id = result["notif_1"]["notification_ids"][0]
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notif = res.scalar_one()
    # subject 被渲染：'Hi Alice, 您的流程已完成'
    assert notif.payload["subject"] == "Hi Alice, 您的流程已完成"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_jinja_body_rendered(
    db_session, clean_notification_node_tables
):
    """body 含 Jinja 表达式 + 多变量 → 全部正确渲染。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "body": "申请人: {{ start.applicant }}\n金额: {{ start.amount }} 元",
            }
        ),
    )

    result = await executor(
        {"start": {"applicant": "张三", "amount": 1000}}
    )

    notification_id = result["notif_1"]["notification_ids"][0]
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notif = res.scalar_one()
    assert notif.payload["body"] == "申请人: 张三\n金额: 1000 元"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_jinja_recipient_expression(
    db_session, clean_notification_node_tables
):
    """recipients='{{ user.email }}' 字符串 → 渲染为单 recipient。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "recipients": "{{ user.email }}",  # 字符串 Jinja 表达式
            }
        ),
    )

    result = await executor(
        {"start": {}, "user": {"email": "dynamic@example.com"}}
    )

    inner = result["notif_1"]
    assert inner["sent_count"] == 1

    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.id == inner["notification_ids"][0])
    )
    notif = res.scalar_one()
    assert notif.recipient == "dynamic@example.com"

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_invalid_email_filtered(
    db_session, clean_notification_node_tables
):
    """recipients=['valid@x.com', 'invalid', ''] → 仅 valid 入队（sent_count=1）。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "recipients": [
                    "valid@example.com",
                    "invalid",  # 无 @ 符号
                    "",
                    "not-an-email-at-all",
                    "another.valid@test.com",
                ]
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_1"]
    # 5 个 recipient，3 个无效，2 个有效
    assert inner["sent_count"] == 2
    assert inner["failed_count"] == 0
    assert len(inner["notification_ids"]) == 2

    # DB 仅 2 行
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.instance_id == seed["inst_id"])
    )
    rows = list(res.scalars().all())
    assert len(rows) == 2
    assert sorted(r.recipient for r in rows) == [
        "another.valid@test.com",
        "valid@example.com",
    ]

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_unknown_channel_skipped(
    db_session, clean_notification_node_tables
):
    """channels=['sms'] (未知通道) → skipped=True 不抛错，不入队任何行。

    Plan 04-10 修订：原测试断言 'feishu' 被 skip，现在 feishu/wecom/dingtalk/slack/mattermost/webhook
    都已支持（走 enqueue_generic_im_card）。仅完全未知 channel（如 sms）才会被跳过。
    """
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "channels": ["sms"],  # Plan 04-10 完全不支持的通道
            }
        ),
    )

    result = await executor({"start": {}})

    inner = result["notif_1"]
    assert inner["skipped"] is True
    assert inner["sent_count"] == 0
    assert inner["failed_count"] == 0
    assert inner["notification_ids"] == []

    # DB 无任何 notifications 行
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(func.count(Notification.id)).where(
            Notification.instance_id == seed["inst_id"]
        )
    )
    count = res.scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_notification_node_one_recipient_fails_others_continue(
    db_session, clean_notification_node_tables
):
    """mock 第 2 个 recipient 入队抛错 → state.failed_count=1, sent_count=2, graph 继续。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "recipients": [
                    "ok1@example.com",
                    "fail@example.com",
                    "ok2@example.com",
                ]
            }
        ),
    )

    # patch enqueue_generic_email：fail@example.com 抛错，其它正常
    from app.services.notification_service import NotificationService

    real_enqueue = NotificationService.enqueue_generic_email

    call_count = {"n": 0}

    async def maybe_fail_enqueue(self, *, recipient_email, **kwargs):
        call_count["n"] += 1
        if recipient_email == "fail@example.com":
            raise RuntimeError("mock 入队失败 — 模拟 SMTP 不可达 / DB 临时错误")
        return await real_enqueue(self, recipient_email=recipient_email, **kwargs)

    with patch.object(
        NotificationService, "enqueue_generic_email", maybe_fail_enqueue
    ):
        result = await executor({"start": {}})

    inner = result["notif_1"]
    assert inner["sent_count"] == 2  # ok1 + ok2
    assert inner["failed_count"] == 1  # fail
    assert len(inner["notification_ids"]) == 2

    # DB 验证：仅 2 行（fail 那次抛错被 rollback）
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification)
        .where(Notification.instance_id == seed["inst_id"])
        .order_by(Notification.recipient)
    )
    rows = list(res.scalars().all())
    assert len(rows) == 2
    recipients = sorted(r.recipient for r in rows)
    assert recipients == ["ok1@example.com", "ok2@example.com"]

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_writes_state_correctly(
    db_session, clean_notification_node_tables
):
    """返回 dict[node_id] 含 sent_count / failed_count / notification_ids 三字段。"""
    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(seed, _make_notification_node())

    result = await executor({"start": {}})

    # LangGraph 自动 merge 时的契约：{node_id: inner_dict}
    assert "notif_1" in result
    inner = result["notif_1"]

    # 三必填字段
    assert isinstance(inner["sent_count"], int)
    assert isinstance(inner["failed_count"], int)
    assert isinstance(inner["notification_ids"], list)

    # 数据一致性
    assert inner["sent_count"] + inner["failed_count"] == 1  # 单 recipient
    assert len(inner["notification_ids"]) == inner["sent_count"]

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_does_not_create_hitl_token(
    db_session, clean_notification_node_tables
):
    """Notification 节点执行后 hitl_tokens 表行数无增加（与 HITL 节点核心区别）。"""
    # 先记录 hitl_tokens 表行数
    res = await db_session.execute(text("SELECT COUNT(*) FROM hitl_tokens"))
    before_count = res.scalar_one()

    seed = await _seed_workflow_instance(db_session)
    executor = _build_executor(
        seed,
        _make_notification_node(
            config_overrides={
                "recipients": ["test1@x.com", "test2@x.com"],
            }
        ),
    )

    result = await executor({"start": {}})
    assert result["notif_1"]["sent_count"] == 2

    # 验证 hitl_tokens 表行数未增加（核心契约：Notification 节点不创建 token）
    res = await db_session.execute(text("SELECT COUNT(*) FROM hitl_tokens"))
    after_count = res.scalar_one()
    assert after_count == before_count, (
        f"Notification 节点不应创建 hitl_token；before={before_count} after={after_count}"
    )

    # 同时验证 notifications.payload 不含 tokens 字段（仅含 generic/subject/body/recipient_email）
    from app.agent_builder.models.notification import Notification

    res = await db_session.execute(
        select(Notification).where(Notification.instance_id == seed["inst_id"])
    )
    rows = list(res.scalars().all())
    for notif in rows:
        assert "tokens" not in notif.payload
        assert notif.payload.get("generic") is True

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_notification_node_creates_node_state_inline(
    db_session, clean_notification_node_tables
):
    """节点执行时自动 SELECT or INSERT node_states 行（满足 FK 约束）。

    与 HITL 节点要求 ExecutionEngine 预创建不同 — Notification 节点宽松自管。
    """
    seed = await _seed_workflow_instance(db_session)

    # 确认 node_states 表初始为空（针对本 instance）
    from app.agent_builder.models.node_state import NodeState

    res = await db_session.execute(
        select(func.count(NodeState.id)).where(
            NodeState.instance_id == seed["inst_id"]
        )
    )
    assert res.scalar_one() == 0

    executor = _build_executor(seed, _make_notification_node())
    result = await executor({"start": {}})
    assert result["notif_1"]["sent_count"] == 1

    # node_states 表应增加 1 行（status='running'，由 _resolve_node_state_id 创建）
    res = await db_session.execute(
        select(NodeState).where(NodeState.instance_id == seed["inst_id"])
    )
    rows = list(res.scalars().all())
    assert len(rows) == 1
    assert rows[0].node_id == "notif_1"
    assert rows[0].node_type == "notification"

    await asyncio.sleep(0.05)
