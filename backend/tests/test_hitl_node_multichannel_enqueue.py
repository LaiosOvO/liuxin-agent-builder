"""ExecutionEngine._on_hitl_enter 集成测试（Plan 04-11 Task 2）。

测试覆盖（≥ 6 用例 — 真实 PG，CLAUDE.md 2.2 不 mock DB）：
1. test_on_hitl_enter_single_creates_1_token — chain_mode=single + 1 approver → 3 token + 1 notification
2. test_on_hitl_enter_sequential_creates_first_only — 3 approvers + sequential → 仅 approvers[0] 3 tokens
3. test_on_hitl_enter_parallel_all_creates_all_tokens — 3 approvers → 3 × 3 = 9 tokens
4. test_on_hitl_enter_enqueues_multichannel — notify_channels=['email','feishu'] + bindings → 2 notif per actor
5. test_on_hitl_enter_resolve_assignees_email_to_uuid — 'alice@example.com' → 解析为 UUID 后创建 token
6. test_on_hitl_enter_structured_log_emitted — caplog 含 'hitl.node.entered' + chain_mode

设计参考 docs/reading-dify-04-11-hitl-node-chain-2026-05-17.md：
- enter 钩子集中处理副作用（NodeState INSERT + tokens INSERT + 通知 fan-out + 结构化日志）
- 单 actor 通知失败不阻塞其他 actor（per-actor try/except）
- 通过 NotificationService.enqueue_hitl_multichannel 复用 Plan 04-10 fan-out 逻辑
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.notification import Notification
from app.agent_builder.workflow.execution_engine import ExecutionEngine

pytestmark = pytest.mark.asyncio


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def fake_redis_instance():
    """独立 fakeredis 实例（_on_hitl_enter 当前未直接用 redis，但保留 ExecutionEngine 构造一致）。"""
    r = await fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def mock_arq_pool():
    """Mock arq pool：仅 assert enqueue_job 被调用。"""
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    return pool


@pytest.fixture(autouse=False)
async def clean_phase4_node_enter(db_session):
    """每次测试后清理 Phase 3/4 表 + Phase 1/2 链路。"""
    yield
    await db_session.execute(text("DELETE FROM notifications"))
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


async def _seed_workspace_with_users(
    db_session,
    *,
    num_actors: int = 1,
    with_im_bindings: bool = False,
) -> dict:
    """种子数据：完整 ws / N user / wf / ver / inst 链路。

    Args:
        num_actors: 创建多少个 active 用户作为候选 approvers
        with_im_bindings: 是否为每个 user 设置 im_bindings JSONB

    Returns:
        {
          'ws_id': UUID,
          'user_ids': [UUID, ...],
          'user_emails': [str, ...],
          'inst_id': UUID,
        }
    """
    ws_id = uuid.uuid4()
    user_ids = [uuid.uuid4() for _ in range(num_actors)]
    user_emails = [f"u{i}_{uuid.uuid4().hex[:6]}@04-11.test" for i in range(num_actors)]
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    # 1. workspace
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "04-11 测试", "slug": f"p411-{ws_id.hex[:8]}"},
    )

    # 2. users（含可选 im_bindings JSONB）
    for uid, email in zip(user_ids, user_emails):
        im_bindings_json = (
            '{"feishu": "ou_' + uid.hex[:16] + '", "wecom": "WeCom_' + uid.hex[:8] + '"}'
            if with_im_bindings
            else "{}"
        )
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, status, is_super_admin, im_bindings) "
                "VALUES (:id, :email, :ph, :name, 'active', false, CAST(:bindings AS jsonb))"
            ),
            {
                "id": str(uid),
                "email": email,
                "ph": "hash",
                "name": f"用户{uid.hex[:4]}",
                "bindings": im_bindings_json,
            },
        )

    # 3. user_workspace_roles（每 user 加 admin 角色，方便 role: 解析测试）
    # 先查 role.code='admin'（role_id 是 int）
    admin_role_id = (await db_session.execute(
        text("SELECT id FROM roles WHERE code = 'admin' LIMIT 1")
    )).scalar_one()
    for uid in user_ids:
        await db_session.execute(
            text(
                "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id, granted_by) "
                "VALUES (:ws, :uid, :role, NULL)"
            ),
            {"ws": str(ws_id), "uid": str(uid), "role": int(admin_role_id)},
        )

    # 4. workflow + version + instance
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws, :name, 'published', :u)"
        ),
        {
            "id": str(wf_id),
            "ws": str(ws_id),
            "name": "04-11 工作流",
            "u": str(user_ids[0]),
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :ws, :wf, 1, 'published', '{}', :u)"
        ),
        {
            "id": str(ver_id),
            "ws": str(ws_id),
            "wf": str(wf_id),
            "u": str(user_ids[0]),
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO flow_instances "
            "(id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot, thread_id, status, created_by) "
            "VALUES (:id, :ws, :wf, :ver, CAST(:dsl AS jsonb), :tid, 'running', :u)"
        ),
        {
            "id": str(inst_id),
            "ws": str(ws_id),
            "wf": str(wf_id),
            "ver": str(ver_id),
            "dsl": '{"name": "04-11 测试流程"}',
            "tid": f"{ws_id}:{inst_id}",
            "u": str(user_ids[0]),
        },
    )

    await db_session.commit()
    return {
        "ws_id": ws_id,
        "user_ids": user_ids,
        "user_emails": user_emails,
        "inst_id": inst_id,
    }


def _make_hitl_node_def(
    *,
    node_id: str = "hitl_1",
    chain_mode: str = "single",
    assignees: list[str] | None = None,
    notify_channels: list[str] | None = None,
    timeout_seconds: int = 3600,
    form_schema: dict | None = None,
) -> dict:
    return {
        "id": node_id,
        "type": "hitl",
        "name": "审批节点",
        "config": {
            "chain_mode": chain_mode,
            "assignees": assignees or [],
            "notify_channels": notify_channels or ["email"],
            "timeout_seconds": timeout_seconds,
            "form_schema": form_schema or {},
            "applicant_name": "申请人A",
            "description": "请审批员工入职",
        },
    }


# ── 测试 1: chain_mode=single + 1 approver → 3 token + 1 notification ────────


async def test_on_hitl_enter_single_creates_1_token(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """single 模式 + 1 approver → 1 actor × 3 actions = 3 token + 1 email notification。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=1)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="single",
        assignees=[seed["user_emails"][0]],
        notify_channels=["email"],
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    # 验证 NodeState 创建
    assert node_state_id is not None
    ns = await db_session.get(NodeState, node_state_id)
    assert ns is not None
    assert ns.status == "waiting_human"
    assert ns.payload is not None
    assert ns.payload["approval_chain"]["mode"] == "single"
    assert len(ns.payload["approval_chain"]["approvers"]) == 1

    # 验证 token 创建（3 个 action）
    tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(tokens) == 3
    assert {t.action for t in tokens} == {"approve", "return", "reject"}
    assert all(t.actor_id == seed["user_ids"][0] for t in tokens)

    # 验证 notification 创建（1 email）
    notifs = (
        await db_session.execute(
            select(Notification).where(Notification.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(notifs) == 1
    assert notifs[0].channel == "email"
    assert notifs[0].recipient == seed["user_emails"][0]


# ── 测试 2: sequential + 3 approvers → 仅 approvers[0] 3 tokens ──────────────


async def test_on_hitl_enter_sequential_creates_first_only(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """sequential 模式 + 3 approvers → 仅 approvers[0] 收到 3 token + 1 notification。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=3)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="sequential",
        assignees=seed["user_emails"],  # 3 个 email
        notify_channels=["email"],
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    # 仅 approvers[0] 3 token
    tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(tokens) == 3
    assert all(t.actor_id == seed["user_ids"][0] for t in tokens)

    # 仅 1 个 notification（approvers[0] 收）
    notifs = (
        await db_session.execute(
            select(Notification).where(Notification.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(notifs) == 1
    assert notifs[0].recipient == seed["user_emails"][0]

    # payload.approval_chain.approvers 含 3 人
    ns = await db_session.get(NodeState, node_state_id)
    assert len(ns.payload["approval_chain"]["approvers"]) == 3
    assert ns.payload["approval_chain"]["mode"] == "sequential"
    assert ns.payload["approval_chain"]["current_idx"] == 0


# ── 测试 3: parallel_all + 3 approvers → 9 tokens + 3 notifications ──────────


async def test_on_hitl_enter_parallel_all_creates_all_tokens(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """parallel_all 模式 + 3 approvers → 3 × 3 = 9 tokens + 3 email notifications。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=3)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="parallel_all",
        assignees=seed["user_emails"],
        notify_channels=["email"],
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    # 9 token（3 actor × 3 action）
    tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(tokens) == 9
    actor_set = {t.actor_id for t in tokens}
    assert actor_set == set(seed["user_ids"])
    # 每个 actor 都有 3 action
    for uid in seed["user_ids"]:
        actor_tokens = [t for t in tokens if t.actor_id == uid]
        assert len(actor_tokens) == 3
        assert {t.action for t in actor_tokens} == {"approve", "return", "reject"}

    # 3 个 notification（每 actor 一封 email）
    notifs = (
        await db_session.execute(
            select(Notification).where(Notification.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(notifs) == 3
    assert {n.recipient for n in notifs} == set(seed["user_emails"])

    # payload.approval_chain.decisions 初始化所有 approver 为 None
    ns = await db_session.get(NodeState, node_state_id)
    assert "decisions" in ns.payload["approval_chain"]
    assert len(ns.payload["approval_chain"]["decisions"]) == 3
    assert all(v is None for v in ns.payload["approval_chain"]["decisions"].values())


# ── 测试 4: notify_channels=['email','feishu'] + bindings → 2 notif per actor ─


async def test_on_hitl_enter_enqueues_multichannel(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """parallel_all + 3 approvers + channels=['email','feishu'] → 6 notif（3 email + 3 feishu）。"""
    seed = await _seed_workspace_with_users(
        db_session, num_actors=3, with_im_bindings=True
    )
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="parallel_all",
        assignees=seed["user_emails"],
        notify_channels=["email", "feishu"],
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    notifs = (
        await db_session.execute(
            select(Notification).where(Notification.node_state_id == node_state_id)
        )
    ).scalars().all()
    # 3 actor × 2 channel = 6 通知
    assert len(notifs) == 6

    channel_counts: dict[str, int] = {}
    for n in notifs:
        channel_counts[n.channel] = channel_counts.get(n.channel, 0) + 1
    assert channel_counts.get("email") == 3
    assert channel_counts.get("feishu") == 3

    # 验证 mock_arq_pool 被调用 6 次（每个 notif 一次 enqueue_job）
    assert mock_arq_pool.enqueue_job.call_count == 6


# ── 测试 5: assignees email → 解析为 UUID 后创建 token ──────────────────────


async def test_on_hitl_enter_resolve_assignees_email_to_uuid(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """assignees=['alice@x'] → resolve_assignees 拿到 UUID → token.actor_id == UUID。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=1)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="single",
        assignees=[seed["user_emails"][0]],  # 邮箱
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    # token.actor_id 是 user.id UUID（不是 email）
    tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert all(t.actor_id == seed["user_ids"][0] for t in tokens)


# ── 测试 6: structured log 'hitl.node.entered' + chain_mode ─────────────────


async def test_on_hitl_enter_structured_log_emitted(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter, caplog
):
    """caplog 含 'hitl.node.entered' 消息 + extra 字段 chain_mode / approvers_count / notify_channels。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=2)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="parallel_all",
        assignees=seed["user_emails"],
        notify_channels=["email"],
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.agent_builder.workflow.execution_engine",
    ):
        await engine._on_hitl_enter(
            node_def=node_def,
            instance_id=seed["inst_id"],
            workspace_id=seed["ws_id"],
            db=db_session,
        )

    # 找到 'hitl.node.entered' 日志记录
    entered_records = [
        rec for rec in caplog.records if rec.message == "hitl.node.entered"
    ]
    assert len(entered_records) == 1
    rec = entered_records[0]
    # extra dict 字段（caplog 直接挂在 record 上）
    assert rec.chain_mode == "parallel_all"
    assert rec.approvers_count == 2
    assert rec.target_actors_count == 2
    assert rec.notify_channels == ["email"]
    assert rec.instance_id == str(seed["inst_id"])


# ── 测试 7: assignees 为空 → NodeExecutionError ─────────────────────────────


async def test_on_hitl_enter_empty_assignees_raises(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """assignees=[] → resolve_assignees 返回 []，应抛 NodeExecutionError。"""
    from app.agent_builder.workflow.nodes.base import NodeExecutionError

    seed = await _seed_workspace_with_users(db_session, num_actors=1)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="single",
        assignees=[],  # 空
    )

    with pytest.raises(NodeExecutionError, match="assignees"):
        await engine._on_hitl_enter(
            node_def=node_def,
            instance_id=seed["inst_id"],
            workspace_id=seed["ws_id"],
            db=db_session,
        )


# ── 测试 8: assignees=role:admin → 解析多人 ─────────────────────────────────


async def test_on_hitl_enter_assignees_role_admin(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """assignees=['role:admin'] + 3 个 admin 用户 → parallel_all 模式创建 9 token。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=3)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="parallel_all",
        assignees=["role:admin"],  # 解析为 workspace 内 3 个 admin
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == node_state_id)
        )
    ).scalars().all()
    # role:admin 解析为 3 个 user，parallel_all 每人 3 token → 9
    assert len(tokens) == 9
    assert {t.actor_id for t in tokens} == set(seed["user_ids"])


# ── 测试 9: parallel_any + 2 approvers → 2 actor × 3 action = 6 token ──────


async def test_on_hitl_enter_parallel_any_creates_all_tokens(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """parallel_any 模式 + 2 approvers → 6 token + 2 notifications。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=2)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="parallel_any",
        assignees=seed["user_emails"],
        notify_channels=["email"],
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(tokens) == 6  # 2 × 3

    ns = await db_session.get(NodeState, node_state_id)
    assert ns.payload["approval_chain"]["mode"] == "parallel_any"
    # parallel_* 模式 decisions 字典初始化
    assert "decisions" in ns.payload["approval_chain"]
    assert len(ns.payload["approval_chain"]["decisions"]) == 2


# ── 测试 10: 向后兼容 — single + 1 approver + 无 notify_channels 字段 → email ──


async def test_on_hitl_enter_backward_compat_no_notify_channels(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """旧 DSL 无 notify_channels 字段 → 默认 ['email']，只创建 email notif。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=1)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    # 显式去掉 notify_channels 字段（模拟 Phase 3 旧 DSL）
    node_def = _make_hitl_node_def(
        chain_mode="single",
        assignees=[seed["user_emails"][0]],
    )
    del node_def["config"]["notify_channels"]

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    notifs = (
        await db_session.execute(
            select(Notification).where(Notification.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(notifs) == 1
    assert notifs[0].channel == "email"


# ── 测试 11: assignees user:<uuid> 表达式 ───────────────────────────────────


async def test_on_hitl_enter_assignees_user_uuid_expression(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """assignees=['user:<uuid>'] → 解析为单用户 token。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=1)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="single",
        assignees=[f"user:{seed['user_ids'][0]}"],
    )

    node_state_id = await engine._on_hitl_enter(
        node_def=node_def,
        instance_id=seed["inst_id"],
        workspace_id=seed["ws_id"],
        db=db_session,
    )

    tokens = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == node_state_id)
        )
    ).scalars().all()
    assert len(tokens) == 3
    assert all(t.actor_id == seed["user_ids"][0] for t in tokens)


# ── 测试 12: dept: 表达式抛 NotImplementedError ─────────────────────────────


async def test_on_hitl_enter_dept_expression_raises_not_implemented(
    db_session, fake_redis_instance, mock_arq_pool, clean_phase4_node_enter
):
    """assignees=['dept:研发部'] → NotImplementedError（Phase 5 实现）。"""
    seed = await _seed_workspace_with_users(db_session, num_actors=1)
    engine = ExecutionEngine(db_session, fake_redis_instance, arq_pool=mock_arq_pool)

    node_def = _make_hitl_node_def(
        chain_mode="single",
        assignees=["dept:研发部"],
    )

    with pytest.raises(NotImplementedError, match="Phase 5"):
        await engine._on_hitl_enter(
            node_def=node_def,
            instance_id=seed["inst_id"],
            workspace_id=seed["ws_id"],
            db=db_session,
        )
