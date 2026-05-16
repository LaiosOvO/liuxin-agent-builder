"""HitlService 集成测试（CLAUDE.md 2.2，不 mock DB）。

测试覆盖（6+ 用例）：
- batch_create_tokens 写 3 行 INSERT（submit phase 3 actions）
- batch_create_tokens 不同 actions 产生不同 jti
- batch_create_tokens expires_at 与默认值 24h 精度一致
- batch_create_tokens 自定义 expires_in_seconds
- resolve_allowed_actions submit / review 正确
- resolve_allowed_actions 非法 phase 抛 ValueError

测试约定：
- 真实 PG（CLAUDE.md 2.2，不 mock DB）
- 使用与 test_hitl_token_store_redis.py 相同的 seed 模式
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.services.hitl_service import (
    DEFAULT_TOKEN_EXPIRES_IN,
    HitlService,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3(db_session):
    """每次测试后清理 Phase 3 + Phase 1/2 表。"""
    yield
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


async def _seed_workflow_instance(db_session) -> dict[str, uuid.UUID]:
    """种子数据：完整 ws/user/wf/ver/inst/node_state 链路（FK 必备）。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "service测试ws", "slug": f"service-ws-{ws_id.hex[:8]}"},
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
            "name": "service_wf",
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

    return {
        "ws_id": ws_id,
        "user_id": user_id,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
    }


# ── batch_create_tokens ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_create_tokens_writes_3_rows_for_submit_phase(
    db_session, clean_phase3
):
    """submit phase 的 3 个 actions 各写一行 hitl_tokens。"""
    seed = await _seed_workflow_instance(db_session)
    service = HitlService(db_session)

    tokens = await service.batch_create_tokens(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        allowed_actions=["submit", "return", "reject"],
    )
    await db_session.commit()

    assert len(tokens) == 3
    assert {t.action for t in tokens} == {"submit", "return", "reject"}

    # DB 验证：3 行 hitl_tokens 确实落地
    result = await db_session.execute(
        select(HitlToken).where(HitlToken.node_state_id == seed["node_state_id"])
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    for row in rows:
        assert row.actor_id == seed["user_id"]
        assert row.instance_id == seed["inst_id"]
        assert row.used_at is None  # 新创建 token 未消费


@pytest.mark.asyncio
async def test_batch_create_tokens_each_jti_unique(db_session, clean_phase3):
    """3 个 token 的 jti 互不相同（uuid4 默认）。"""
    seed = await _seed_workflow_instance(db_session)
    service = HitlService(db_session)

    tokens = await service.batch_create_tokens(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        allowed_actions=["submit", "return", "reject"],
    )
    await db_session.commit()

    jtis = {t.jti for t in tokens}
    assert len(jtis) == 3  # 3 个唯一 jti


@pytest.mark.asyncio
async def test_batch_create_tokens_default_expires_at_24h(db_session, clean_phase3):
    """expires_at 默认为 now + 24h，容差 ±5s。"""
    seed = await _seed_workflow_instance(db_session)
    service = HitlService(db_session)

    before = datetime.now(timezone.utc)
    tokens = await service.batch_create_tokens(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        allowed_actions=["submit"],
    )
    await db_session.commit()
    after = datetime.now(timezone.utc)

    expected_min = before + timedelta(seconds=DEFAULT_TOKEN_EXPIRES_IN - 5)
    expected_max = after + timedelta(seconds=DEFAULT_TOKEN_EXPIRES_IN + 5)

    assert expected_min <= tokens[0].expires_at <= expected_max


@pytest.mark.asyncio
async def test_batch_create_tokens_custom_expires_in(db_session, clean_phase3):
    """expires_in_seconds=300 → 5 分钟后过期。"""
    seed = await _seed_workflow_instance(db_session)
    service = HitlService(db_session)

    before = datetime.now(timezone.utc)
    tokens = await service.batch_create_tokens(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        allowed_actions=["approve"],
        expires_in_seconds=300,
    )
    await db_session.commit()
    after = datetime.now(timezone.utc)

    expected_min = before + timedelta(seconds=295)
    expected_max = after + timedelta(seconds=305)

    assert expected_min <= tokens[0].expires_at <= expected_max


@pytest.mark.asyncio
async def test_batch_create_tokens_review_phase_3_actions(db_session, clean_phase3):
    """review phase: [approve, return, reject] 3 行。"""
    seed = await _seed_workflow_instance(db_session)
    service = HitlService(db_session)

    tokens = await service.batch_create_tokens(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        allowed_actions=["approve", "return", "reject"],
    )
    await db_session.commit()

    assert len(tokens) == 3
    assert {t.action for t in tokens} == {"approve", "return", "reject"}


# ── resolve_allowed_actions ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_allowed_actions_submit_phase(db_session):
    """phase=submit → [submit, return, reject]。"""
    service = HitlService(db_session)
    actions = await service.resolve_allowed_actions("submit")
    assert actions == ["submit", "return", "reject"]


@pytest.mark.asyncio
async def test_resolve_allowed_actions_review_phase(db_session):
    """phase=review → [approve, return, reject]。"""
    service = HitlService(db_session)
    actions = await service.resolve_allowed_actions("review")
    assert actions == ["approve", "return", "reject"]


@pytest.mark.asyncio
async def test_resolve_allowed_actions_returns_copy_not_reference(db_session):
    """返回 list 是副本（修改不影响后续调用）。"""
    service = HitlService(db_session)
    actions1 = await service.resolve_allowed_actions("submit")
    actions1.append("hack")  # 修改不应污染全局
    actions2 = await service.resolve_allowed_actions("submit")
    assert actions2 == ["submit", "return", "reject"]
    assert "hack" not in actions2


@pytest.mark.asyncio
async def test_resolve_allowed_actions_invalid_phase_raises(db_session):
    """非法 phase 抛 ValueError。"""
    service = HitlService(db_session)
    with pytest.raises(ValueError, match="非法 phase"):
        await service.resolve_allowed_actions("unknown_phase")
    with pytest.raises(ValueError, match="非法 phase"):
        await service.resolve_allowed_actions("")
