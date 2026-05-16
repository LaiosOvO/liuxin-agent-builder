"""HitlService.batch_create_tokens_for_actors 集成测试（Phase 4 04-02）。

测试覆盖（≥ 5 用例 — 真实 PG，CLAUDE.md 2.2 不 mock DB）：
1. test_batch_create_tokens_for_3_actors_3_actions — 返回 9 行 token
2. test_batch_create_for_empty_actor_list — 返回空 list
3. test_batch_create_each_token_has_unique_jti — 所有 jti 唯一
4. test_batch_create_all_share_same_expires_at — 同批 expires_at 一致
5. test_batch_create_actor_action_combinations_correct — 笛卡尔积展开正确

设计参考 docs/reading-dify-04-02-chain-executor-2026-05-17.md：
- batch_create_tokens_for_actors 是 chain executor 调用入口（sequential approve / parallel_* init）
- 与 batch_create_tokens（单 actor）区别：本方法支持多 actor 笛卡尔积
- 真实 PG 验证 INSERT + UNIQUE 约束（jti PK）+ FK 链路
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.services.hitl_service import (
    DEFAULT_TOKEN_EXPIRES_IN,
    HitlService,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase4(db_session):
    """每次测试后清理 Phase 3/4 + Phase 1/2 表。"""
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


async def _seed_workflow_instance(db_session, *, num_actors: int = 3) -> dict:
    """种子数据：完整 ws / N user / wf / ver / inst / node_state 链路。

    Returns:
        {ws_id, user_ids (list[N]), inst_id, node_state_id}
    """
    ws_id = uuid.uuid4()
    user_ids = [uuid.uuid4() for _ in range(num_actors)]
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "batchchain测试", "slug": f"batch-{ws_id.hex[:8]}"},
    )
    for i, uid in enumerate(user_ids):
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
                "VALUES (:id, :email, :ph, 'active', false)"
            ),
            {"id": str(uid), "email": f"u{i}_{uuid.uuid4().hex[:6]}@batch.test", "ph": "hash"},
        )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "batch_wf",
            "created_by": str(user_ids[0]),
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
            "created_by": str(user_ids[0]),
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
        "user_ids": user_ids,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
    }


# ── 5 个测试用例 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_create_tokens_for_3_actors_3_actions(db_session, clean_phase4):
    """3 actor × 3 action → 9 行 token（笛卡尔积）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=3)
    service = HitlService(db_session)

    tokens = await service.batch_create_tokens_for_actors(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_ids=seed["user_ids"],
        allowed_actions=["approve", "return", "reject"],
    )
    await db_session.commit()

    # 返回值长度 = 3 × 3 = 9
    assert len(tokens) == 9
    # 每个 token 是 HitlToken 实例
    for t in tokens:
        assert isinstance(t, HitlToken)
        assert t.instance_id == seed["inst_id"]
        assert t.node_state_id == seed["node_state_id"]

    # DB 中也有 9 行
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == seed["node_state_id"])
        )
    ).scalars().all()
    assert len(rows) == 9


@pytest.mark.asyncio
async def test_batch_create_for_empty_actor_list(db_session, clean_phase4):
    """actor_ids=[] → 返回空 list，不写 DB（边界用例）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=1)
    service = HitlService(db_session)

    tokens = await service.batch_create_tokens_for_actors(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_ids=[],
        allowed_actions=["approve", "return", "reject"],
    )

    assert tokens == []

    # DB 中没有任何 token 行
    rows = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == seed["node_state_id"])
        )
    ).scalars().all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_batch_create_each_token_has_unique_jti(db_session, clean_phase4):
    """所有 token 的 jti 必须唯一（PK 约束 + uuid4 保证）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=3)
    service = HitlService(db_session)

    tokens = await service.batch_create_tokens_for_actors(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_ids=seed["user_ids"],
        allowed_actions=["approve", "return", "reject"],
    )
    await db_session.commit()

    # 9 个 jti 完全不同
    jtis = [t.jti for t in tokens]
    assert len(jtis) == 9
    assert len(set(jtis)) == 9


@pytest.mark.asyncio
async def test_batch_create_all_share_same_expires_at(db_session, clean_phase4):
    """同批 token 共享 expires_at（同时创建 — 单调时间差 < 1s）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=2)
    service = HitlService(db_session)

    before = datetime.now(timezone.utc)
    tokens = await service.batch_create_tokens_for_actors(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_ids=seed["user_ids"],
        allowed_actions=["approve", "reject"],
        expires_in_seconds=3600,
    )
    after = datetime.now(timezone.utc)
    await db_session.commit()

    # 2 × 2 = 4 个 token，但 expires_at 完全一致（一次性计算）
    expires_set = {t.expires_at for t in tokens}
    assert len(expires_set) == 1

    expires_at = tokens[0].expires_at
    expected_min = before + timedelta(seconds=3600)
    expected_max = after + timedelta(seconds=3600)
    # expires_at 在 [before+3600, after+3600] 范围内
    assert expected_min <= expires_at <= expected_max


@pytest.mark.asyncio
async def test_batch_create_actor_action_combinations_correct(db_session, clean_phase4):
    """笛卡尔积展开正确：每 (actor, action) 一行 token。"""
    seed = await _seed_workflow_instance(db_session, num_actors=2)
    actor_a, actor_b = seed["user_ids"]
    service = HitlService(db_session)

    tokens = await service.batch_create_tokens_for_actors(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_ids=[actor_a, actor_b],
        allowed_actions=["approve", "return", "reject"],
    )
    await db_session.commit()

    # 验证笛卡尔积：每 (actor, action) 组合都有一行
    by_actor_action = {}
    for t in tokens:
        key = (t.actor_id, t.action)
        assert key not in by_actor_action, f"重复 (actor, action): {key}"
        by_actor_action[key] = t

    expected_combinations = {
        (actor_a, "approve"),
        (actor_a, "return"),
        (actor_a, "reject"),
        (actor_b, "approve"),
        (actor_b, "return"),
        (actor_b, "reject"),
    }
    assert set(by_actor_action.keys()) == expected_combinations


@pytest.mark.asyncio
async def test_batch_create_default_expires_in_seconds(db_session, clean_phase4):
    """默认 expires_in_seconds = DEFAULT_TOKEN_EXPIRES_IN（24h）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=1)
    service = HitlService(db_session)

    before = datetime.now(timezone.utc)
    tokens = await service.batch_create_tokens_for_actors(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_ids=seed["user_ids"],
        allowed_actions=["approve"],
    )
    after = datetime.now(timezone.utc)
    await db_session.commit()

    assert len(tokens) == 1
    expires_at = tokens[0].expires_at
    # 默认 24h
    assert (before + timedelta(seconds=DEFAULT_TOKEN_EXPIRES_IN)) <= expires_at <= (
        after + timedelta(seconds=DEFAULT_TOKEN_EXPIRES_IN)
    )
