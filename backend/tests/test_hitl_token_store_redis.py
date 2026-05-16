"""HitlTokenStore 集成测试 — 真实 Postgres + 真实 Redis（CLAUDE.md 2.2，不 mock DB）。

测试覆盖：
- consume 首次返回 token + Redis 同步设置
- consume 重复返回 None（幂等 / AUTH-05 一次性消费）
- is_consumed Redis 命中（hot path）
- is_consumed Redis miss → PG 命中 → 回填 Redis
- is_consumed Redis miss + PG miss → 未消费返回 False
- is_consumed 未知 jti 返回 True（防伪造）
- invalidate_siblings 返回正确数量
- invalidate_siblings 排除目标 jti 不被标记
"""
from __future__ import annotations

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
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
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
    """种子数据：完整 ws/user/wf/ver/inst/node_state 链路。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "store测试ws", "slug": f"store-ws-{ws_id.hex[:8]}"},
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
        {"id": str(wf_id), "ws_id": str(ws_id), "name": "store_wf", "created_by": str(user_id)},
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


async def _make_token(
    db_session,
    seed: dict[str, uuid.UUID],
    action: str = "submit",
) -> HitlToken:
    """便利函数：创建一个未消费的 token。"""
    token = HitlToken(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action=action,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)
    return token


# ── 测试 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_first_time_returns_token_and_sets_redis(
    db_session, redis_client, clean_phase3
):
    """consume 首次：返回 HitlToken + Redis 已设置 jti key。"""
    seed = await _seed_workflow_instance(db_session)
    token = await _make_token(db_session, seed)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    consumed = await store.consume(token.jti, ip="1.2.3.4", ua="Mozilla/5.0")
    await db_session.commit()

    assert consumed is not None, "首次消费应返回 token"
    assert consumed.jti == token.jti
    assert consumed.used_at is not None
    assert consumed.used_ip == "1.2.3.4"
    assert consumed.used_ua == "Mozilla/5.0"

    # 验证 Redis 已被设置
    redis_val = await redis_client.get(_redis_key(token.jti))
    assert redis_val == "consumed"
    # 验证 TTL 约为 24h
    ttl = await redis_client.ttl(_redis_key(token.jti))
    assert 0 < ttl <= _REDIS_TTL_SECONDS, f"TTL 应在 (0, {_REDIS_TTL_SECONDS}] 范围内"


@pytest.mark.asyncio
async def test_consume_second_time_returns_none(db_session, redis_client, clean_phase3):
    """consume 重复调用：第二次返回 None（AUTH-05 一次性）。"""
    seed = await _seed_workflow_instance(db_session)
    token = await _make_token(db_session, seed)

    store = HitlTokenStore(db=db_session, redis=redis_client)

    first = await store.consume(token.jti, ip="1.2.3.4", ua="UA1")
    await db_session.commit()
    assert first is not None

    second = await store.consume(token.jti, ip="5.6.7.8", ua="UA2")
    await db_session.commit()
    assert second is None, "重复消费应返回 None"

    # 验证 PG 中 used_ip 仍然是首次消费的值（未被覆盖）
    result = await db_session.execute(
        select(HitlToken).where(HitlToken.jti == token.jti)
    )
    persisted = result.scalar_one()
    assert persisted.used_ip == "1.2.3.4", "二次消费不应覆盖首次的 used_ip"
    assert persisted.used_ua == "UA1"


@pytest.mark.asyncio
async def test_is_consumed_redis_hit_returns_true(db_session, redis_client, clean_phase3):
    """is_consumed Redis 命中：直接返回 True（hot path 不查 PG）。"""
    seed = await _seed_workflow_instance(db_session)
    token = await _make_token(db_session, seed)

    # 手动在 Redis 设置 key（模拟之前已消费过）
    await redis_client.set(_redis_key(token.jti), "consumed", ex=_REDIS_TTL_SECONDS)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    assert await store.is_consumed(token.jti) is True


@pytest.mark.asyncio
async def test_is_consumed_redis_miss_pg_hit_backfills_redis(
    db_session, redis_client, clean_phase3
):
    """is_consumed Redis miss + PG 命中（已消费）：返回 True，且 Redis 被回填。"""
    seed = await _seed_workflow_instance(db_session)
    token = await _make_token(db_session, seed)

    # 直接在 PG 标记为已消费（不走 store.consume，模拟旧数据 + Redis 失效场景）
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "UPDATE hitl_tokens SET used_at = :used_at, used_ip = '1.1.1.1' "
            "WHERE jti = :jti"
        ),
        {"used_at": now, "jti": str(token.jti)},
    )
    await db_session.commit()

    # 确认 Redis 中没有此 key
    redis_val_before = await redis_client.get(_redis_key(token.jti))
    assert redis_val_before is None

    store = HitlTokenStore(db=db_session, redis=redis_client)
    assert await store.is_consumed(token.jti) is True

    # 验证 Redis 已被回填
    redis_val_after = await redis_client.get(_redis_key(token.jti))
    assert redis_val_after == "consumed"


@pytest.mark.asyncio
async def test_is_consumed_neither_returns_false(db_session, redis_client, clean_phase3):
    """is_consumed Redis miss + PG miss（未消费）：返回 False。"""
    seed = await _seed_workflow_instance(db_session)
    token = await _make_token(db_session, seed)

    # Redis 中无 key，PG 中 used_at 为 NULL
    store = HitlTokenStore(db=db_session, redis=redis_client)
    assert await store.is_consumed(token.jti) is False

    # 确认 Redis 没被乱写
    redis_val = await redis_client.get(_redis_key(token.jti))
    assert redis_val is None, "未消费场景不应回填 Redis"


@pytest.mark.asyncio
async def test_is_consumed_unknown_jti_returns_true(
    db_session, redis_client, clean_phase3
):
    """is_consumed 未知 jti（PG 不存在）：返回 True 防伪造。"""
    fake_jti = uuid.uuid4()
    store = HitlTokenStore(db=db_session, redis=redis_client)
    assert await store.is_consumed(fake_jti) is True, "伪造 jti 应视为已消费"


@pytest.mark.asyncio
async def test_invalidate_siblings_returns_correct_count(
    db_session, redis_client, clean_phase3
):
    """invalidate_siblings：同 node_state_id 下其他 4 个 token 应被失效。"""
    seed = await _seed_workflow_instance(db_session)

    # 创建 5 个同 node_state 的 token
    tokens = []
    for action in ("submit", "approve", "return", "reject", "delegate"):
        t = await _make_token(db_session, seed, action=action)
        tokens.append(t)

    # 选其中一个作为"刚被合法消费"的
    consumed_jti = tokens[0].jti

    store = HitlTokenStore(db=db_session, redis=redis_client)
    invalidated_count = await store.invalidate_siblings(
        seed["node_state_id"],
        except_jti=consumed_jti,
    )
    await db_session.commit()

    assert invalidated_count == 4, f"应失效 4 个，实际 {invalidated_count}"

    # 验证 Redis 中其他 4 个 jti 都被设置
    for t in tokens[1:]:
        redis_val = await redis_client.get(_redis_key(t.jti))
        assert redis_val == "consumed", f"jti={t.jti} 应被回填 Redis"


@pytest.mark.asyncio
async def test_invalidate_siblings_excludes_target_jti(
    db_session, redis_client, clean_phase3
):
    """invalidate_siblings：except_jti 自身不被标记。"""
    seed = await _seed_workflow_instance(db_session)

    tokens = []
    for action in ("submit", "approve", "return"):
        t = await _make_token(db_session, seed, action=action)
        tokens.append(t)

    consumed_jti = tokens[0].jti

    store = HitlTokenStore(db=db_session, redis=redis_client)
    await store.invalidate_siblings(seed["node_state_id"], except_jti=consumed_jti)
    await db_session.commit()

    # consumed_jti 自身仍然是未消费状态（used_at IS NULL）
    result = await db_session.execute(
        select(HitlToken).where(HitlToken.jti == consumed_jti)
    )
    target_token = result.scalar_one()
    assert target_token.used_at is None, "except_jti 不应被标记为已消费"

    # 另两个应被标记
    for t in tokens[1:]:
        result = await db_session.execute(
            select(HitlToken).where(HitlToken.jti == t.jti)
        )
        sibling = result.scalar_one()
        assert sibling.used_at is not None, f"sibling jti={t.jti} 应被失效"
        assert sibling.used_ip == "system:sibling-invalidate"


@pytest.mark.asyncio
async def test_invalidate_siblings_zero_when_no_siblings(
    db_session, redis_client, clean_phase3
):
    """invalidate_siblings：node 下只有目标 token 时返回 0。"""
    seed = await _seed_workflow_instance(db_session)
    token = await _make_token(db_session, seed)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    count = await store.invalidate_siblings(
        seed["node_state_id"],
        except_jti=token.jti,
    )
    assert count == 0


@pytest.mark.asyncio
async def test_consume_followed_by_is_consumed_via_redis_only(
    db_session, redis_client, clean_phase3
):
    """组合测试：consume 后立即 is_consumed 应走 Redis 命中（无需查 PG）。"""
    seed = await _seed_workflow_instance(db_session)
    token = await _make_token(db_session, seed)

    store = HitlTokenStore(db=db_session, redis=redis_client)
    await store.consume(token.jti, ip="1.2.3.4", ua="UA")
    await db_session.commit()

    # 删除 PG 行（模拟极端场景：consume 后 PG 数据被 admin 误删除）
    # is_consumed 应仍然返回 True，因为 Redis 已经有 key
    await db_session.execute(
        text("DELETE FROM hitl_tokens WHERE jti = :jti"),
        {"jti": str(token.jti)},
    )
    await db_session.commit()

    assert await store.is_consumed(token.jti) is True, (
        "PG 行被删后，Redis 仍然能挡住二次消费"
    )
