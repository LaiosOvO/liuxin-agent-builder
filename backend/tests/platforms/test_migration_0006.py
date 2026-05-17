"""Phase 5.A migration 0006 smoke test —— workspace_plugin_installations 表行为契约。

测试范围：
1. 表存在 + 字段存在性 + 类型契约
2. UNIQUE (workspace_id, plugin_name) 唯一约束生效
3. workspace 隔离（不同 workspace 可装同名 plugin）
4. CHECK status IN ('installed', 'disabled', 'error') 约束生效
5. server_default（status / config_json / installed_at / updated_at）正常工作
6. credentials_json nullable
7. 索引 (workspace_id, status) 存在
8. JSONB 读写 round-trip

每个测试独立 fixture workspace_id（uuid.uuid4），避免跨测试 DB 行残留干扰。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.agent_builder.models import WorkspacePluginInstallation


# ─── 1. 表结构契约（migration upgrade 后 schema 正确）────────────────────────


@pytest.mark.asyncio
async def test_table_exists_in_db(db_session) -> None:
    """workspace_plugin_installations 表存在。"""
    # 通过 SQL 直接查 information_schema
    result = await db_session.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'workspace_plugin_installations')"
        )
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_table_has_all_required_columns(db_session) -> None:
    """所有 9 个字段存在（id / workspace_id / plugin_name / plugin_version /
    status / config_json / credentials_json / installed_at / updated_at）。
    """
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'workspace_plugin_installations' "
            "ORDER BY column_name"
        )
    )
    cols = sorted([row[0] for row in result.all()])
    expected = sorted([
        "id",
        "workspace_id",
        "plugin_name",
        "plugin_version",
        "status",
        "config_json",
        "credentials_json",
        "installed_at",
        "updated_at",
    ])
    assert cols == expected


# ─── 2. UNIQUE 约束（同 workspace 不可装同名 plugin 两次）──────────────────


@pytest.mark.asyncio
async def test_unique_workspace_plugin_name_constraint(
    db_session, workspace_id_a
) -> None:
    """同 (workspace, plugin_name) 插两行 → IntegrityError。"""
    p1 = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.0",
    )
    db_session.add(p1)
    await db_session.flush()

    # 同 workspace + 同 name + 不同 version 仍违反唯一约束
    p2 = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.1",
    )
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ─── 3. Workspace 隔离（不同 workspace 可装同名 plugin）────────────────────


@pytest.mark.asyncio
async def test_workspace_isolation_same_plugin_different_ws(
    db_session, workspace_id_a, workspace_id_b
) -> None:
    """不同 workspace 可装同名 plugin 同版本 → OK。"""
    a = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.0",
    )
    b = WorkspacePluginInstallation(
        workspace_id=workspace_id_b,
        plugin_name="huly",
        plugin_version="1.0.0",
    )
    db_session.add_all([a, b])
    await db_session.flush()  # OK — UNIQUE (workspace_id, plugin_name) tuple 不同

    # 验证两行都在
    result = await db_session.execute(
        select(WorkspacePluginInstallation).where(
            WorkspacePluginInstallation.plugin_name == "huly"
        )
    )
    rows = result.scalars().all()
    ws_ids = {r.workspace_id for r in rows}
    assert workspace_id_a in ws_ids
    assert workspace_id_b in ws_ids


# ─── 4. CHECK status enum 约束 ──────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["installed", "disabled", "error"])
async def test_check_status_accepts_allowed_values(
    db_session, workspace_id_a, status
) -> None:
    """status ∈ {installed, disabled, error} 全部允许。"""
    p = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name=f"plug-{status}",
        plugin_version="1.0.0",
        status=status,
    )
    db_session.add(p)
    await db_session.flush()  # OK


@pytest.mark.asyncio
async def test_check_status_rejects_invalid_value(
    db_session, workspace_id_a
) -> None:
    """status 非三态值 → CHECK constraint 触发 IntegrityError。"""
    p = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="badstatus",
        plugin_version="1.0.0",
        status="running",  # 非法值
    )
    db_session.add(p)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ─── 5. server_default 默认值（status / config / 时间戳）──────────────────


@pytest.mark.asyncio
async def test_status_default_is_installed(
    db_session, workspace_id_a
) -> None:
    """status 不传 → server_default='installed'。"""
    p = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.0",
        # 不传 status，依赖 server_default
    )
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)
    assert p.status == "installed"


@pytest.mark.asyncio
async def test_config_json_default_is_empty_dict(
    db_session, workspace_id_a
) -> None:
    """config_json 不传 → server_default='{}'::jsonb。"""
    p = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.0",
    )
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)
    assert p.config_json == {}


@pytest.mark.asyncio
async def test_installed_at_and_updated_at_auto_set(
    db_session, workspace_id_a
) -> None:
    """installed_at / updated_at server_default=now() 自动填充。"""
    p = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.0",
    )
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)
    assert p.installed_at is not None
    assert p.updated_at is not None


# ─── 6. credentials_json nullable + JSONB round-trip ──────────────────────


@pytest.mark.asyncio
async def test_credentials_json_is_nullable(
    db_session, workspace_id_a
) -> None:
    """credentials_json 不传 → 默认 NULL（不像 config_json 默认 {}）。"""
    p = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.0",
    )
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)
    assert p.credentials_json is None


@pytest.mark.asyncio
async def test_jsonb_config_round_trip(
    db_session, workspace_id_a
) -> None:
    """复杂嵌套 JSONB 写入后 read 回相同结构。"""
    payload = {
        "endpoint": "https://huly.example.com",
        "auth_token": "secret",
        "workspace_handle": "team-a",
        "features": {"chat": True, "doc": True, "hr": False},
        "rate_limits": [100, 500, 1000],
    }
    p = WorkspacePluginInstallation(
        workspace_id=workspace_id_a,
        plugin_name="huly",
        plugin_version="1.0.0",
        config_json=payload,
    )
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)
    assert p.config_json == payload


# ─── 7. 索引存在性 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_status_index_exists(db_session) -> None:
    """ix_workspace_plugin_workspace_status 索引存在。"""
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'workspace_plugin_installations' "
            "ORDER BY indexname"
        )
    )
    index_names = [row[0] for row in result.all()]
    assert "ix_workspace_plugin_workspace_status" in index_names


# ─── 8. ORM model 字段类型契约 ────────────────────────────────────────────


def test_orm_model_tablename() -> None:
    """ORM tablename 与 migration 一致。"""
    assert (
        WorkspacePluginInstallation.__tablename__
        == "workspace_plugin_installations"
    )


def test_orm_model_has_all_fields() -> None:
    """ORM 类含所有字段 mapped_column（防字段漂移）。"""
    cols = {c.name for c in WorkspacePluginInstallation.__table__.columns}
    expected = {
        "id",
        "workspace_id",
        "plugin_name",
        "plugin_version",
        "status",
        "config_json",
        "credentials_json",
        "installed_at",
        "updated_at",
    }
    assert cols == expected
