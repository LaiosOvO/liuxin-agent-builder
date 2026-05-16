"""HitlToken ORM 模型单元 / 集成测试（CLAUDE.md 2.2 — 真实 DB，不 mock）。

测试目标：
- jti UUID 自动生成 + 默认值
- 重复 jti 抛 IntegrityError（PK 唯一性）
- 删除 flow_instance 级联删除 token（ON DELETE CASCADE）
- 索引 ix_hitl_tokens_node_state_used 存在（多租户性能保证）
- action VARCHAR 不做 DB 层枚举约束（service 层校验）

环境要求：
- POSTGRES_DSN 指向可用 Postgres
- alembic upgrade head 已执行（0001 + 0002 + 0003）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.agent_builder.models.hitl_token import HitlToken


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_hitl_tables(db_session):
    """每次测试后清理 Phase 3 表（保持 Phase 1/2 数据干净）。"""
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
    """创建一条完整的 ws + user + workflow + version + instance + node_state，返回各 ID。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "测试ws", "slug": f"test-ws-{ws_id.hex[:8]}"},
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
        {"id": str(wf_id), "ws_id": str(ws_id), "name": "wf", "created_by": str(user_id)},
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
        "wf_id": wf_id,
        "ver_id": ver_id,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
    }


# ── 测试 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_hitl_token_with_default_jti(db_session, clean_hitl_tables):
    """创建 HitlToken：jti 由 default=uuid4 自动生成，used_at 默认 NULL。"""
    seed = await _seed_workflow_instance(db_session)

    token = HitlToken(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="submit",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)

    assert token.jti is not None, "jti 应由 default 自动生成"
    assert isinstance(token.jti, uuid.UUID), "jti 类型应为 UUID"
    assert token.used_at is None, "新 token 默认 used_at = NULL"
    assert token.used_ip is None
    assert token.used_ua is None
    assert token.action == "submit"
    assert token.created_at is not None


@pytest.mark.asyncio
async def test_hitl_token_unique_jti_constraint(db_session, clean_hitl_tables):
    """同 jti 插入两次应抛 IntegrityError（PK 唯一）。"""
    seed = await _seed_workflow_instance(db_session)
    shared_jti = uuid.uuid4()

    token1 = HitlToken(
        jti=shared_jti,
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="submit",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(token1)
    await db_session.commit()

    token2 = HitlToken(
        jti=shared_jti,  # 同 jti
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="approve",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(token2)

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_hitl_token_cascade_delete_instance(db_session, clean_hitl_tables):
    """删除 flow_instance 应级联删除其 hitl_tokens。"""
    seed = await _seed_workflow_instance(db_session)

    # 插入 3 个 token（典型场景：执行人阶段 submit/return/reject 三按钮）
    for action in ("submit", "return", "reject"):
        token = HitlToken(
            instance_id=seed["inst_id"],
            node_state_id=seed["node_state_id"],
            actor_id=seed["user_id"],
            action=action,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db_session.add(token)
    await db_session.commit()

    # 验证 3 个 token 已插入
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM hitl_tokens WHERE instance_id = :id"),
        {"id": str(seed["inst_id"])},
    )
    assert result.scalar() == 3

    # 删除 flow_instance（ON DELETE CASCADE → node_states + hitl_tokens 一并清理）
    await db_session.execute(
        text("DELETE FROM flow_instances WHERE id = :id"),
        {"id": str(seed["inst_id"])},
    )
    await db_session.commit()

    # 验证 hitl_tokens 已被级联删除
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM hitl_tokens WHERE instance_id = :id"),
        {"id": str(seed["inst_id"])},
    )
    count = result.scalar()
    assert count == 0, f"hitl_tokens 应级联删除，但仍有 {count} 条"


@pytest.mark.asyncio
async def test_hitl_token_index_node_state_used_exists(db_session):
    """索引 ix_hitl_tokens_node_state_used 存在（POST 决策时同节点其他 token 失效）。"""
    result = await db_session.execute(
        text(
            """
            SELECT a.attname AS column_name, key_info.key_ord
            FROM pg_index pgi
            JOIN pg_class t ON t.oid = pgi.indrelid
            JOIN pg_class i ON i.oid = pgi.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid
            JOIN LATERAL unnest(pgi.indkey) WITH ORDINALITY AS key_info(attnum, key_ord)
                ON a.attnum = key_info.attnum
            WHERE t.relname = 'hitl_tokens'
              AND i.relname = 'ix_hitl_tokens_node_state_used'
            ORDER BY key_info.key_ord
            """
        )
    )
    columns = [(row[0], row[1]) for row in result.fetchall()]

    assert columns, "索引 ix_hitl_tokens_node_state_used 不存在"
    # 第一列必须是 node_state_id
    assert columns[0][0] == "node_state_id", (
        f"索引第一列期望 node_state_id，实际: {columns[0][0]}"
    )
    # 第二列必须是 used_at
    assert columns[1][0] == "used_at", (
        f"索引第二列期望 used_at，实际: {columns[1][0]}"
    )


@pytest.mark.asyncio
async def test_hitl_token_action_string_not_enum(db_session, clean_hitl_tables):
    """action 字段是 VARCHAR(16)，不做 DB 层枚举约束（service 层校验）。

    背景：CONTEXT.md 决策 — 用 VARCHAR 而非 ENUM，避免新增 action 需要 migration。
    """
    seed = await _seed_workflow_instance(db_session)

    # 写入合法 action
    token1 = HitlToken(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="submit",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(token1)
    await db_session.commit()

    # 写入"非法" action（DB 层应放行，service 层才校验）
    token2 = HitlToken(
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="bogus_action",  # 非业务标准动作，但 DB 层应允许
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add(token2)
    # 应成功 commit（不抛错）
    await db_session.commit()

    # 验证写入了
    result = await db_session.execute(
        select(HitlToken).where(HitlToken.action == "bogus_action")
    )
    assert result.scalar_one_or_none() is not None
