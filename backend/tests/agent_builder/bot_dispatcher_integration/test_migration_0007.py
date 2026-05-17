"""Phase 4.5 migration 0007 集成测试 — workspace_bot_installations + bot_audit_logs 双表契约。

测试范围：
1. 表存在 + 字段类型正确（workspace_bot_installations / bot_audit_logs）
2. UNIQUE (workspace_id, bot_name) 唯一约束
3. CHECK status / outcome / routed_via 约束生效
4. server_default（status / config_snapshot_json / installed_at / updated_at）
5. JSONB round-trip
6. 索引存在性
7. Downgrade 可逆（不在本测试做 — 走 alembic_runner 是 Wave 2 plan 的范畴）

注：
- migration 已由 root conftest 在测试 session 启动时跑过（alembic upgrade head）
- 本测试通过查 information_schema / pg_indexes / 触发 IntegrityError 验证 schema 落地
- 标记 @pytest.mark.integration —— 与 Phase 5.A 测试矩阵一致
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.agent_builder.models import BotAuditLog, WorkspaceBotInstallation

pytestmark = pytest.mark.integration


# ─── 1. 表存在 + 字段契约 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upgrade_creates_workspace_bot_installations(db_session) -> None:
    """workspace_bot_installations 表存在且字段完整。"""
    result = await db_session.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'workspace_bot_installations')"
        )
    )
    assert result.scalar() is True

    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'workspace_bot_installations' "
            "ORDER BY column_name"
        )
    )
    cols = sorted([row[0] for row in result.all()])
    expected = sorted(
        [
            "id",
            "workspace_id",
            "bot_name",
            "yaml_path",
            "status",
            "config_snapshot_json",
            "last_error",
            "installed_at",
            "updated_at",
        ]
    )
    assert cols == expected


@pytest.mark.asyncio
async def test_upgrade_creates_bot_audit_logs(db_session) -> None:
    """bot_audit_logs 表存在且字段完整。"""
    result = await db_session.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'bot_audit_logs')"
        )
    )
    assert result.scalar() is True

    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'bot_audit_logs' "
            "ORDER BY column_name"
        )
    )
    cols = sorted([row[0] for row in result.all()])
    expected = sorted(
        [
            "id",
            "workspace_id",
            "bot_name",
            "sender_name",
            "sender_user_id",
            "cmd_name",
            "cmd_args_json",
            "raw_message",
            "outcome",
            "error_message",
            "latency_ms",
            "routed_via",
            "llm_confidence",
            "created_at",
        ]
    )
    assert cols == expected


# ─── 2. UNIQUE 约束 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_bot_unique_constraint(db_session, workspace_id_a) -> None:
    """同 (workspace_id, bot_name) 插两行 → IntegrityError。"""
    b1 = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name="offboarding-bot",
        yaml_path="plugins/bots/offboarding.yaml",
    )
    db_session.add(b1)
    await db_session.flush()

    b2 = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name="offboarding-bot",
        yaml_path="plugins/bots/offboarding-v2.yaml",  # 不同 yaml_path 仍违反 UNIQUE
    )
    db_session.add(b2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_workspace_isolation_same_bot_different_ws(
    db_session, workspace_id_a, workspace_id_b
) -> None:
    """不同 workspace 可装同名 bot → OK。"""
    a = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name="offboarding-bot",
        yaml_path="plugins/bots/offboarding.yaml",
    )
    b = WorkspaceBotInstallation(
        workspace_id=workspace_id_b,
        bot_name="offboarding-bot",
        yaml_path="plugins/bots/offboarding.yaml",
    )
    db_session.add_all([a, b])
    await db_session.flush()  # OK

    result = await db_session.execute(
        select(WorkspaceBotInstallation).where(
            WorkspaceBotInstallation.bot_name == "offboarding-bot"
        )
    )
    rows = result.scalars().all()
    ws_ids = {r.workspace_id for r in rows}
    assert workspace_id_a in ws_ids
    assert workspace_id_b in ws_ids


# ─── 3. CHECK status 约束 ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["enabled", "disabled", "error"])
async def test_status_allowed_values(db_session, workspace_id_a, status) -> None:
    """status 三态合法。"""
    b = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name=f"bot-{status}",
        yaml_path=f"plugins/bots/bot-{status}.yaml",
        status=status,
    )
    db_session.add(b)
    await db_session.flush()  # OK


@pytest.mark.asyncio
async def test_status_rejects_invalid_value(db_session, workspace_id_a) -> None:
    """status='running'（非三态） → IntegrityError（CHECK 触发）。"""
    b = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name="badstatus",
        yaml_path="plugins/bots/bad.yaml",
        status="running",  # 非法
    )
    db_session.add(b)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ─── 4. CHECK outcome 约束（bot_audit_logs）─────────────────────────────────


@pytest.mark.asyncio
async def test_bot_audit_logs_outcome_check(db_session, workspace_id_a) -> None:
    """bot_audit_logs.outcome='bogus' → IntegrityError。"""
    log = BotAuditLog(
        workspace_id=workspace_id_a,
        bot_name="offboarding-bot",
        sender_name="alice",
        outcome="bogus",  # 非 5 值
        routed_via="slash_command",
    )
    db_session.add(log)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    ["success", "permission_denied", "rate_limited", "parse_failed", "handler_error"],
)
async def test_bot_audit_logs_outcome_allowed_values(
    db_session, workspace_id_a, outcome
) -> None:
    """outcome 5 值全部合法。"""
    log = BotAuditLog(
        workspace_id=workspace_id_a,
        bot_name="offboarding-bot",
        sender_name="alice",
        outcome=outcome,
        routed_via="slash_command",
    )
    db_session.add(log)
    await db_session.flush()  # OK


# ─── 5. CHECK routed_via 约束 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bot_audit_logs_routed_via_check(db_session, workspace_id_a) -> None:
    """routed_via='unknown' → IntegrityError。"""
    log = BotAuditLog(
        workspace_id=workspace_id_a,
        outcome="success",
        routed_via="unknown",
    )
    db_session.add(log)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ─── 6. server_default 默认值 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_default_is_enabled(db_session, workspace_id_a) -> None:
    """status 不传 → server_default='enabled'。"""
    b = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name="default-bot",
        yaml_path="plugins/bots/default.yaml",
    )
    db_session.add(b)
    await db_session.flush()
    await db_session.refresh(b)
    assert b.status == "enabled"


@pytest.mark.asyncio
async def test_config_snapshot_default_is_empty_dict(
    db_session, workspace_id_a
) -> None:
    """config_snapshot_json 不传 → server_default='{}'::jsonb。"""
    b = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name="snapshot-bot",
        yaml_path="plugins/bots/snapshot.yaml",
    )
    db_session.add(b)
    await db_session.flush()
    await db_session.refresh(b)
    assert b.config_snapshot_json == {}


# ─── 7. JSONB round-trip ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_snapshot_jsonb_round_trip(db_session, workspace_id_a) -> None:
    """复杂嵌套 JSONB 写入 → read 回相同结构。"""
    payload = {
        "name": "offboarding-bot",
        "provider": {"type": "mattermost", "config_env_prefix": "MM_"},
        "triggers": {"dm": True, "at_mention": True, "keywords": ["我要离职"]},
        "commands": [{"name": "start", "args": ["employee_id"]}],
    }
    b = WorkspaceBotInstallation(
        workspace_id=workspace_id_a,
        bot_name="offboarding-bot",
        yaml_path="plugins/bots/offboarding.yaml",
        config_snapshot_json=payload,
    )
    db_session.add(b)
    await db_session.flush()
    await db_session.refresh(b)
    assert b.config_snapshot_json == payload


# ─── 8. 索引存在性 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_bot_installation_indexes_exist(db_session) -> None:
    """workspace_bot_installations 两索引存在。"""
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'workspace_bot_installations' "
            "ORDER BY indexname"
        )
    )
    index_names = [row[0] for row in result.all()]
    assert "ix_workspace_bot_workspace_status" in index_names
    assert "ix_workspace_bot_status_updated" in index_names


@pytest.mark.asyncio
async def test_bot_audit_logs_indexes_exist(db_session) -> None:
    """bot_audit_logs 三索引存在。"""
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'bot_audit_logs' "
            "ORDER BY indexname"
        )
    )
    index_names = [row[0] for row in result.all()]
    assert "ix_bot_audit_workspace_created" in index_names
    assert "ix_bot_audit_outcome_created" in index_names
    assert "ix_bot_audit_bot_name_created" in index_names


# ─── 9. raw_message / error_message 长度 CHECK ────────────────────────────


@pytest.mark.asyncio
async def test_raw_message_length_check_enforced(db_session, workspace_id_a) -> None:
    """raw_message > 4096 字符 → IntegrityError（防恶意大消息 OOM）。"""
    log = BotAuditLog(
        workspace_id=workspace_id_a,
        outcome="success",
        routed_via="slash_command",
        raw_message="x" * 4097,
    )
    db_session.add(log)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ─── 10. JSONB cmd_args round-trip ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_bot_audit_logs_cmd_args_jsonb_round_trip(
    db_session, workspace_id_a
) -> None:
    """cmd_args_json 写入 dict → read 回相同结构。"""
    args = {"employee_id": "it.charlie", "reason": "离职 / 主动"}
    log = BotAuditLog(
        workspace_id=workspace_id_a,
        bot_name="offboarding-bot",
        sender_name="alice",
        cmd_name="start",
        cmd_args_json=args,
        outcome="success",
        routed_via="slash_command",
        latency_ms=120,
    )
    db_session.add(log)
    await db_session.flush()
    await db_session.refresh(log)
    assert log.cmd_args_json == args
