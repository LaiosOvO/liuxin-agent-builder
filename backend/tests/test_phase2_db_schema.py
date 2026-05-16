"""Phase 2 数据库表结构集成测试。

测试目标：
- workflows 表存在 + 列结构正确
- workflow_versions 唯一约束（同 workflow_id/version_no/kind）
- flow_instances thread_id 唯一约束
- node_states 级联删除（删除 flow_instance 后 node_states 被清理）
- workflows 索引第一列为 workspace_id（多租户性能保证）

环境要求：
- POSTGRES_DSN 指向可用 Postgres（SSH 隧道 localhost:15432）
- alembic upgrade head 已执行（0001 + 0002）
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


# ── fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase2_tables(db_session):
    """每次测试后清理 Phase 2 表（保持 Phase 1 数据完整）。"""
    yield
    # 按 FK 依赖顺序删除
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.commit()


# ── 测试 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workflows_table_exists(db_session):
    """workflows 表存在，包含必要列。"""
    result = await db_session.execute(
        text(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'workflows'
            ORDER BY ordinal_position
            """
        )
    )
    columns = {row[0]: row[1] for row in result.fetchall()}

    assert columns, "workflows 表不存在（列查询结果为空）"

    # 必须存在的列
    required_columns = {
        "id",
        "workspace_id",
        "name",
        "description",
        "status",
        "current_draft_version_id",
        "current_published_version_id",
        "created_by",
        "created_at",
        "updated_at",
    }
    missing = required_columns - set(columns.keys())
    assert not missing, f"workflows 表缺少列：{missing}"

    # 关键列类型校验
    assert "uuid" in columns["id"].lower(), f"id 列类型期望 uuid，实际: {columns['id']}"
    assert "character" in columns["name"].lower() or "varchar" in columns["name"].lower(), (
        f"name 列类型期望 varchar，实际: {columns['name']}"
    )


@pytest.mark.asyncio
async def test_workflow_versions_unique_constraint(db_session, clean_phase2_tables):
    """workflow_versions 唯一约束：同 workflow_id + version_no + kind 插入两次应失败。"""
    import uuid as _uuid
    from sqlalchemy.exc import IntegrityError

    # 先插入一个 workspace + user（Phase 1 表）供 FK 引用
    ws_id = _uuid.uuid4()
    user_id = _uuid.uuid4()

    await db_session.execute(
        text(
            "INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"
        ),
        {"id": str(ws_id), "name": "测试ws", "slug": f"test-ws-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, status, is_super_admin)
            VALUES (:id, :email, :ph, 'active', false)
            """
        ),
        {"id": str(user_id), "email": f"u{_uuid.uuid4().hex[:6]}@test.example.com", "ph": "hash"},
    )

    wf_id = _uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO workflows (id, workspace_id, name, status, created_by)
            VALUES (:id, :ws_id, :name, 'draft', :created_by)
            """
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "测试工作流",
            "created_by": str(user_id),
        },
    )
    await db_session.commit()

    # 第一次插入（version_no=1, kind='published'）应成功
    ver_id_1 = _uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by)
            VALUES (:id, :ws_id, :wf_id, 1, 'published', '{}', :created_by)
            """
        ),
        {
            "id": str(ver_id_1),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "created_by": str(user_id),
        },
    )
    await db_session.commit()

    # 第二次插入相同 (workflow_id, version_no, kind) 应违反 UNIQUE
    ver_id_2 = _uuid.uuid4()
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by)
                VALUES (:id, :ws_id, :wf_id, 1, 'published', '{}', :created_by)
                """
            ),
            {
                "id": str(ver_id_2),
                "ws_id": str(ws_id),
                "wf_id": str(wf_id),
                "created_by": str(user_id),
            },
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_flow_instances_thread_id_unique(db_session, clean_phase2_tables):
    """flow_instances thread_id 唯一约束：同 thread_id 插入两次应失败。"""
    import uuid as _uuid
    from sqlalchemy.exc import IntegrityError

    # 准备 workspace + user + workflow + workflow_version
    ws_id = _uuid.uuid4()
    user_id = _uuid.uuid4()
    wf_id = _uuid.uuid4()
    ver_id = _uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "测试ws2", "slug": f"test-ws2-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, status, is_super_admin)
            VALUES (:id, :email, :ph, 'active', false)
            """
        ),
        {"id": str(user_id), "email": f"u2{_uuid.uuid4().hex[:6]}@test.example.com", "ph": "hash"},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {"id": str(wf_id), "ws_id": str(ws_id), "name": "wf2", "created_by": str(user_id)},
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
    await db_session.commit()

    thread_id = f"{ws_id}:{_uuid.uuid4()}"

    # 第一次插入（应成功）
    inst_id_1 = _uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO flow_instances
                (id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot, thread_id, status)
            VALUES (:id, :ws_id, :wf_id, :ver_id, '{}', :thread_id, 'pending')
            """
        ),
        {
            "id": str(inst_id_1),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "ver_id": str(ver_id),
            "thread_id": thread_id,
        },
    )
    await db_session.commit()

    # 第二次插入相同 thread_id（应违反 UNIQUE）
    inst_id_2 = _uuid.uuid4()
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO flow_instances
                    (id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot, thread_id, status)
                VALUES (:id, :ws_id, :wf_id, :ver_id, '{}', :thread_id, 'pending')
                """
            ),
            {
                "id": str(inst_id_2),
                "ws_id": str(ws_id),
                "wf_id": str(wf_id),
                "ver_id": str(ver_id),
                "thread_id": thread_id,
            },
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_node_states_cascade_delete(db_session, clean_phase2_tables):
    """删除 flow_instance 后关联 node_states 应被级联删除。"""
    import uuid as _uuid

    ws_id = _uuid.uuid4()
    user_id = _uuid.uuid4()
    wf_id = _uuid.uuid4()
    ver_id = _uuid.uuid4()
    inst_id = _uuid.uuid4()
    node_id = _uuid.uuid4()

    # 准备数据
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "测试ws3", "slug": f"test-ws3-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, :ph, 'active', false)"
        ),
        {"id": str(user_id), "email": f"u3{_uuid.uuid4().hex[:6]}@test.example.com", "ph": "hash"},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {"id": str(wf_id), "ws_id": str(ws_id), "name": "wf3", "created_by": str(user_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :ws_id, :wf_id, 1, 'published', '{}', :created_by)"
        ),
        {"id": str(ver_id), "ws_id": str(ws_id), "wf_id": str(wf_id), "created_by": str(user_id)},
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
            "VALUES (:id, :ws_id, :inst_id, :node_id, 'llm', 'completed')"
        ),
        {
            "id": str(node_id),
            "ws_id": str(ws_id),
            "inst_id": str(inst_id),
            "node_id": "llm_1",
        },
    )
    await db_session.commit()

    # 验证 node_state 已插入
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM node_states WHERE instance_id = :inst_id"),
        {"inst_id": str(inst_id)},
    )
    assert result.scalar() == 1

    # 删除 flow_instance（应级联删除 node_states）
    await db_session.execute(
        text("DELETE FROM flow_instances WHERE id = :id"),
        {"id": str(inst_id)},
    )
    await db_session.commit()

    # 验证 node_state 已被级联删除
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM node_states WHERE instance_id = :inst_id"),
        {"inst_id": str(inst_id)},
    )
    count = result.scalar()
    assert count == 0, f"node_states 应级联删除，但仍有 {count} 条记录"


@pytest.mark.asyncio
async def test_index_workspace_first_column(db_session):
    """workflows 表的 ix_workflows_ws_status_created 索引第一列为 workspace_id。"""
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
            WHERE t.relname = 'workflows'
              AND i.relname = 'ix_workflows_ws_status_created'
            ORDER BY key_info.key_ord
            """
        )
    )
    columns = [(row[0], row[1]) for row in result.fetchall()]

    assert columns, "索引 ix_workflows_ws_status_created 不存在"

    # 第一列（key_ord=1）必须是 workspace_id
    first_column = columns[0][0]
    assert first_column == "workspace_id", (
        f"索引第一列期望 workspace_id，实际: {first_column}（多租户隔离要求）"
    )
