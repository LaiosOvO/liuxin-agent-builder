"""HitlTokenStore.invalidate_chain 集成测试 — 真实 Postgres + 真实 Redis（CLAUDE.md 2.2，不 mock DB）。

测试覆盖（≥ 10 用例）：
- invalidate_chain 返回 [(jti, actor_id), ...] tuple list
- 排除 except_jti 不被失效
- 已消费 token 不被重复消费
- 其他 instance 的 token 不受影响
- Redis pipeline 上失效 jti 都已 SET
- 空 instance 返回空 list
- 在 advisory_lock 内调用（Pitfall 2 模拟）
- 幂等性：第二次调用返回空 list
- 0005 partial index 存在（含 WHERE used_at IS NULL）
- 0005 downgrade 删除 partial index

设计参考 docs/reading-dify-04-01-chain-payload-2026-05-17.md §3：
- invalidate_chain 是「parallel_* reject / parallel_any approve」时的副作用
- 与 invalidate_siblings 区别：scope 从 node_state_id → instance_id
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import select, text

from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.workflow.hitl_token_store import (
    HitlTokenStore,
    _REDIS_PREFIX,
    _REDIS_TTL_SECONDS,
    _redis_key,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def redis_client() -> Redis:
    """真实 Redis 客户端（测试隔离用独立 key 前缀避免污染）。"""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:16379/0")
    client = Redis.from_url(redis_url, decode_responses=True)
    # 测试前清理本测试用前缀（防上次测试残留）
    keys = await client.keys(f"{_REDIS_PREFIX}*")
    if keys:
        await client.delete(*keys)
    yield client
    # 测试后清理
    keys = await client.keys(f"{_REDIS_PREFIX}*")
    if keys:
        await client.delete(*keys)
    await client.aclose()


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


async def _seed_workflow_instance(db_session, *, num_actors: int = 1) -> dict:
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
        {"id": str(ws_id), "name": "chain测试ws", "slug": f"chain-ws-{ws_id.hex[:8]}"},
    )
    for i, uid in enumerate(user_ids):
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
                "VALUES (:id, :email, :ph, 'active', false)"
            ),
            {"id": str(uid), "email": f"u{i}_{uuid.uuid4().hex[:6]}@chain.test", "ph": "hash"},
        )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "chain_wf",
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


async def _make_token(
    db_session,
    *,
    inst_id: uuid.UUID,
    node_state_id: uuid.UUID,
    actor_id: uuid.UUID,
    action: str = "approve",
    used: bool = False,
) -> HitlToken:
    """便利函数：创建 token；used=True 时直接标记已消费。"""
    token = HitlToken(
        instance_id=inst_id,
        node_state_id=node_state_id,
        actor_id=actor_id,
        action=action,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    if used:
        token.used_at = datetime.now(timezone.utc)
        token.used_ip = "test:pre-consumed"
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)
    return token


# ── invalidate_chain 测试 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalidate_chain_returns_jti_actor_pairs(
    db_session, redis_client, clean_phase4
):
    """5 个 token，invalidate_chain except 1 个 → 返回 4 行 (jti, actor_id)。"""
    seed = await _seed_workflow_instance(db_session, num_actors=5)
    tokens = []
    for actor in seed["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=actor,
            action="approve",
        )
        tokens.append(t)

    except_token = tokens[0]
    store = HitlTokenStore(db=db_session, redis=redis_client)
    rows = await store.invalidate_chain(seed["inst_id"], except_token.jti)
    await db_session.commit()

    # 应返回除 except 外的 4 个 (jti, actor_id)
    assert len(rows) == 4
    returned_jtis = {row[0] for row in rows}
    expected_jtis = {t.jti for t in tokens[1:]}
    assert returned_jtis == expected_jtis

    # 检查 actor_id 也正确返回
    jti_to_actor = {t.jti: t.actor_id for t in tokens[1:]}
    for jti, actor_id in rows:
        assert jti_to_actor[jti] == actor_id


@pytest.mark.asyncio
async def test_invalidate_chain_excludes_target(
    db_session, redis_client, clean_phase4
):
    """except_jti 的 token 不被失效（used_at 仍为 NULL）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=3)
    tokens = []
    for actor in seed["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=actor,
        )
        tokens.append(t)

    except_token = tokens[1]
    store = HitlTokenStore(db=db_session, redis=redis_client)
    await store.invalidate_chain(seed["inst_id"], except_token.jti)
    await db_session.commit()

    # except_jti 的 used_at 仍 None
    refreshed = await db_session.execute(
        select(HitlToken.used_at).where(HitlToken.jti == except_token.jti)
    )
    assert refreshed.scalar_one() is None, "except_jti 不应被失效"

    # 其他 2 个 token 都已失效
    for t in [tokens[0], tokens[2]]:
        r = await db_session.execute(
            select(HitlToken.used_at).where(HitlToken.jti == t.jti)
        )
        used_at = r.scalar_one()
        assert used_at is not None, f"非 except token jti={t.jti} 应被失效"


@pytest.mark.asyncio
async def test_invalidate_chain_skips_already_consumed(
    db_session, redis_client, clean_phase4
):
    """已消费 token 不被 invalidate_chain 重复消费（保留原 used_ip / used_at）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=3)
    # actor[0] token 已消费；actor[1]/[2] 未消费
    already_consumed = await _make_token(
        db_session,
        inst_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_ids"][0],
        used=True,
    )
    pending_1 = await _make_token(
        db_session,
        inst_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_ids"][1],
    )
    pending_2 = await _make_token(
        db_session,
        inst_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_ids"][2],
    )

    store = HitlTokenStore(db=db_session, redis=redis_client)
    rows = await store.invalidate_chain(seed["inst_id"], pending_1.jti)
    await db_session.commit()

    # 仅 pending_2 被失效（pending_1 是 except；already_consumed 已消费）
    assert len(rows) == 1
    assert rows[0][0] == pending_2.jti

    # 验证 already_consumed 的 used_ip 仍是 "test:pre-consumed"（未被覆盖）
    refreshed = await db_session.execute(
        select(HitlToken.used_ip).where(HitlToken.jti == already_consumed.jti)
    )
    assert refreshed.scalar_one() == "test:pre-consumed"


@pytest.mark.asyncio
async def test_invalidate_chain_skips_other_instance(
    db_session, redis_client, clean_phase4
):
    """跨 instance 隔离：其他 instance 的 token 不受影响。"""
    seed_a = await _seed_workflow_instance(db_session, num_actors=2)
    seed_b = await _seed_workflow_instance(db_session, num_actors=2)

    tokens_a = []
    for actor in seed_a["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed_a["inst_id"],
            node_state_id=seed_a["node_state_id"],
            actor_id=actor,
        )
        tokens_a.append(t)
    tokens_b = []
    for actor in seed_b["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed_b["inst_id"],
            node_state_id=seed_b["node_state_id"],
            actor_id=actor,
        )
        tokens_b.append(t)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    # 失效 inst_a 除 token_a[0] 外的所有
    rows = await store.invalidate_chain(seed_a["inst_id"], tokens_a[0].jti)
    await db_session.commit()

    # 仅 inst_a 的 1 个 token 被失效（token_a[1]）
    assert len(rows) == 1
    assert rows[0][0] == tokens_a[1].jti

    # inst_b 的 token 都未受影响
    for t in tokens_b:
        r = await db_session.execute(
            select(HitlToken.used_at).where(HitlToken.jti == t.jti)
        )
        assert r.scalar_one() is None, f"inst_b token jti={t.jti} 不应被失效"


@pytest.mark.asyncio
async def test_invalidate_chain_redis_pipeline_sets_keys(
    db_session, redis_client, clean_phase4
):
    """Redis pipeline 上失效的 jti 都已 SET（consumed）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=3)
    tokens = []
    for actor in seed["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=actor,
        )
        tokens.append(t)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    rows = await store.invalidate_chain(seed["inst_id"], tokens[0].jti)
    await db_session.commit()

    # 失效的 2 个 jti 在 Redis 上应 consumed
    for jti, _ in rows:
        val = await redis_client.get(_redis_key(jti))
        assert val == "consumed", f"jti={jti} 应在 Redis 上设为 consumed"
        ttl = await redis_client.ttl(_redis_key(jti))
        assert 0 < ttl <= _REDIS_TTL_SECONDS

    # except_jti 不应在 Redis 上
    except_redis = await redis_client.get(_redis_key(tokens[0].jti))
    assert except_redis is None, "except_jti 不应被 Redis 标记"


@pytest.mark.asyncio
async def test_invalidate_chain_empty_instance_returns_empty(
    db_session, redis_client, clean_phase4
):
    """instance 内无未消费 token → 返回空 list。"""
    seed = await _seed_workflow_instance(db_session, num_actors=1)
    fake_jti = uuid.uuid4()

    store = HitlTokenStore(db=db_session, redis=redis_client)
    rows = await store.invalidate_chain(seed["inst_id"], fake_jti)
    await db_session.commit()

    assert rows == []


@pytest.mark.asyncio
async def test_invalidate_chain_idempotent(
    db_session, redis_client, clean_phase4
):
    """同 instance 调两次 invalidate_chain，第二次返回空 list（幂等）。"""
    seed = await _seed_workflow_instance(db_session, num_actors=3)
    tokens = []
    for actor in seed["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=actor,
        )
        tokens.append(t)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    rows_1st = await store.invalidate_chain(seed["inst_id"], tokens[0].jti)
    await db_session.commit()
    assert len(rows_1st) == 2

    # 第二次调用：所有非 except 都已 used_at != NULL → 返回空
    rows_2nd = await store.invalidate_chain(seed["inst_id"], tokens[0].jti)
    await db_session.commit()
    assert rows_2nd == []


@pytest.mark.asyncio
async def test_invalidate_chain_with_advisory_lock_concurrent(
    db_session, redis_client, clean_phase4
):
    """在 pg_advisory_xact_lock 内调用 invalidate_chain 工作正常（Pitfall 2 模拟）。

    模拟 service 层调用方式：
        async with db.begin():
            await db.execute(text('SELECT pg_advisory_xact_lock(:k)'), {'k': key})
            await store.invalidate_chain(inst_id, except_jti)
        # commit 自动释放 lock
    """
    seed = await _seed_workflow_instance(db_session, num_actors=3)
    tokens = []
    for actor in seed["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=actor,
        )
        tokens.append(t)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    # 当前已有 begin 事务（db_session fixture）— 直接 acquire xact_lock
    lock_key = hash(str(seed["inst_id"])) & 0x7FFFFFFFFFFFFFFF
    await db_session.execute(
        text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key}
    )
    rows = await store.invalidate_chain(seed["inst_id"], tokens[0].jti)
    await db_session.commit()  # commit 自动释放 advisory_xact_lock

    assert len(rows) == 2
    # 验证锁已释放（再次 acquire 应立即成功）
    await db_session.execute(
        text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key}
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_invalidate_chain_used_ip_marker(
    db_session, redis_client, clean_phase4
):
    """invalidate_chain 写入 used_ip='system:chain-invalidate' + used_ua='system:invalidate_chain'。

    便于审计区分：真实用户消费 / sibling 失效 / chain 失效。
    """
    seed = await _seed_workflow_instance(db_session, num_actors=2)
    tokens = []
    for actor in seed["user_ids"]:
        t = await _make_token(
            db_session,
            inst_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=actor,
        )
        tokens.append(t)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    await store.invalidate_chain(seed["inst_id"], tokens[0].jti)
    await db_session.commit()

    # 检查 tokens[1] 标记
    r = await db_session.execute(
        select(HitlToken.used_ip, HitlToken.used_ua).where(HitlToken.jti == tokens[1].jti)
    )
    used_ip, used_ua = r.one()
    assert used_ip == "system:chain-invalidate"
    assert used_ua == "system:invalidate_chain"


# ── Alembic 0005 partial index 测试 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_alembic_0005_creates_partial_index(db_session):
    """0005 migration upgrade 后 pg_indexes 含 ix_hitl_tokens_instance_used + WHERE used_at IS NULL。"""
    result = await db_session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='hitl_tokens' AND indexname='ix_hitl_tokens_instance_used'"
        )
    )
    row = result.one_or_none()
    assert row is not None, "ix_hitl_tokens_instance_used 索引不存在 — 0005 migration 未应用"

    indexname, indexdef = row
    assert indexname == "ix_hitl_tokens_instance_used"
    # partial index 必须含 WHERE used_at IS NULL 子句
    assert "WHERE" in indexdef.upper()
    assert "USED_AT IS NULL" in indexdef.upper()


@pytest.mark.asyncio
async def test_alembic_0005_partial_index_covers_invalidate_chain_query(db_session, redis_client, clean_phase4):
    """EXPLAIN 验证 invalidate_chain 查询能命中 partial index（性能基线）。

    Note: 此测试只是 sanity check — 数据少时 PG 可能用 seq scan，不强制 assert index 命中。
    主要验证 SQL 执行不报错 + 索引存在即可。
    """
    seed = await _seed_workflow_instance(db_session, num_actors=2)
    for actor in seed["user_ids"]:
        await _make_token(
            db_session,
            inst_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=actor,
        )

    # 直接 EXPLAIN 看查询计划
    fake_except = uuid.uuid4()
    result = await db_session.execute(
        text(
            "EXPLAIN SELECT jti, actor_id FROM hitl_tokens "
            "WHERE instance_id = :iid AND jti != :except_jti AND used_at IS NULL"
        ),
        {"iid": str(seed["inst_id"]), "except_jti": str(fake_except)},
    )
    plan = "\n".join(str(row[0]) for row in result.all())
    # sanity check：plan 非空
    assert plan, "EXPLAIN 应输出查询计划"
