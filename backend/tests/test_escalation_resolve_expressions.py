"""EscalationService.resolve_escalate_to 4 表达式解析集成测试（Plan 04-04 Task 1）。

测试 9 个用例（CLAUDE.md 2.2 — 真实 PG）：
1. test_resolve_email_returns_single_email_list
2. test_resolve_user_uuid_returns_email
3. test_resolve_user_uuid_wrong_workspace_returns_none（多租户越权防护）
4. test_resolve_user_uuid_invalid_returns_none（UUID parse fail）
5. test_resolve_role_admin_returns_multiple（3 个 admin → 3 个 email）
6. test_resolve_role_unknown_returns_fallback（miss → fallback admin）
7. test_resolve_dept_raises_not_implemented（Phase 5 hook）
8. test_resolve_invalid_expr_falls_back（乱码字符串）
9. test_resolve_empty_falls_back（None / ''）

测试策略：
- 直接构造 workspace + users + roles + EscalationService 调用
- 不真发邮件 / 不写 records（仅测 resolve 方法）
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.agent_builder.services.escalation_service import EscalationService


# ── 复用 fixtures from test_hitl_escalation.py（不重复定义） ───────────────────


@pytest.fixture(autouse=False)
async def clean_phase4_tables(db_session):
    """每次测试后清理 Phase 4 表（FK 顺序）+ dispose engine。"""
    yield
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM notifications"))
    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()
    from app.agent_builder.db.engine import engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def stub_arq_email_jobs(monkeypatch):
    """禁用 asyncio.create_task 在 fallback 路径。"""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("app.jobs.email_jobs.send_hitl_email_job", _noop)
    yield


async def _seed_workspace(db_session, slug_prefix: str = "ws") -> uuid.UUID:
    """种一个干净 workspace 返回 id（无 admin / user）。"""
    ws_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(ws_id),
            "name": f"{slug_prefix}-ws",
            "slug": f"{slug_prefix}-{ws_id.hex[:8]}",
        },
    )
    await db_session.commit()
    return ws_id


async def _seed_user_in_workspace(
    db_session,
    workspace_id: uuid.UUID,
    *,
    email: str | None = None,
    role_code: str = "editor",
    status: str = "active",
) -> uuid.UUID:
    """种一个用户 + 关联到 workspace 的指定角色（默认 editor）。

    Returns:
        user_id
    """
    user_id = uuid.uuid4()
    if email is None:
        email = f"user_{uuid.uuid4().hex[:6]}@test.com"

    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, 'hash', :status, false)"
        ),
        {"id": str(user_id), "email": email, "status": status},
    )

    # 查 role.id by code
    role_result = await db_session.execute(
        text("SELECT id FROM roles WHERE code=:code LIMIT 1"),
        {"code": role_code},
    )
    role_id = role_result.scalar_one_or_none()
    if role_id is None:
        # 兜底创建 role（roles 静态种子表已有 admin/editor/viewer/super_admin）
        await db_session.execute(
            text(
                "INSERT INTO roles (code, name) VALUES (:code, :name) "
                "ON CONFLICT DO NOTHING"
            ),
            {"code": role_code, "name": role_code.title()},
        )
        role_result = await db_session.execute(
            text("SELECT id FROM roles WHERE code=:code"),
            {"code": role_code},
        )
        role_id = role_result.scalar_one()

    await db_session.execute(
        text(
            "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
            "VALUES (:ws_id, :user_id, :role_id) ON CONFLICT DO NOTHING"
        ),
        {"ws_id": str(workspace_id), "user_id": str(user_id), "role_id": role_id},
    )
    await db_session.commit()
    return user_id


# ── 9 个测试用例 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_email_returns_single_email_list(
    db_session, clean_phase4_tables
):
    """email 字符串（无 prefix）→ 返回 [email]（Phase 3 向后兼容）。"""
    ws_id = await _seed_workspace(db_session, "email")
    es = EscalationService(db_session)

    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "manager@company.com"},
        workspace_id=ws_id,
    )
    assert result == ["manager@company.com"]


@pytest.mark.asyncio
async def test_resolve_user_uuid_returns_email(db_session, clean_phase4_tables):
    """user:<uuid> 命中 active 用户 → 返回 [email]。"""
    ws_id = await _seed_workspace(db_session, "user")
    user_id = await _seed_user_in_workspace(
        db_session, ws_id, email="alice@test.com", role_code="editor"
    )

    es = EscalationService(db_session)
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": f"user:{user_id}"},
        workspace_id=ws_id,
    )
    assert result == ["alice@test.com"]


@pytest.mark.asyncio
async def test_resolve_user_uuid_wrong_workspace_returns_none(
    db_session, clean_phase4_tables
):
    """user:<uuid> 但用户在其他 workspace → 返回 None（多租户越权防护）。"""
    ws1 = await _seed_workspace(db_session, "ws1")
    ws2 = await _seed_workspace(db_session, "ws2")
    # 用户只属于 ws1
    user_id = await _seed_user_in_workspace(
        db_session, ws1, email="cross@test.com", role_code="editor"
    )

    es = EscalationService(db_session)
    # 从 ws2 查 ws1 的用户 → 不应返回（多租户隔离）
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": f"user:{user_id}"},
        workspace_id=ws2,
    )
    assert result is None


@pytest.mark.asyncio
async def test_resolve_user_uuid_invalid_returns_none(
    db_session, clean_phase4_tables
):
    """user:<非 UUID> → 返回 None（UUID parse fail，不抛错）。"""
    ws_id = await _seed_workspace(db_session, "invalid")

    es = EscalationService(db_session)
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "user:not-a-uuid"},
        workspace_id=ws_id,
    )
    assert result is None


@pytest.mark.asyncio
async def test_resolve_role_admin_returns_multiple(
    db_session, clean_phase4_tables
):
    """role:admin 在 workspace 有 3 个 admin → 返回 3 个 email 的 list。"""
    ws_id = await _seed_workspace(db_session, "multi")
    await _seed_user_in_workspace(
        db_session, ws_id, email="admin1@test.com", role_code="admin"
    )
    await _seed_user_in_workspace(
        db_session, ws_id, email="admin2@test.com", role_code="admin"
    )
    await _seed_user_in_workspace(
        db_session, ws_id, email="admin3@test.com", role_code="admin"
    )

    es = EscalationService(db_session)
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "role:admin"},
        workspace_id=ws_id,
    )

    assert result is not None
    assert len(result) == 3
    assert set(result) == {"admin1@test.com", "admin2@test.com", "admin3@test.com"}


@pytest.mark.asyncio
async def test_resolve_role_unknown_returns_fallback(
    db_session, clean_phase4_tables
):
    """role:nonexistent → 无匹配 → fallback workspace admin。"""
    ws_id = await _seed_workspace(db_session, "fallback")
    await _seed_user_in_workspace(
        db_session, ws_id, email="fb_admin@test.com", role_code="admin"
    )

    es = EscalationService(db_session)
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "role:nonexistent_role_code"},
        workspace_id=ws_id,
    )
    # fallback 命中 admin
    assert result == ["fb_admin@test.com"]


@pytest.mark.asyncio
async def test_resolve_dept_raises_not_implemented(
    db_session, clean_phase4_tables
):
    """dept:<name> → 抛 NotImplementedError（Phase 5 留 hook）。"""
    ws_id = await _seed_workspace(db_session, "dept")

    es = EscalationService(db_session)
    with pytest.raises(NotImplementedError) as exc_info:
        await es.resolve_escalate_to(
            node_config={"escalate_to": "dept:研发部"},
            workspace_id=ws_id,
        )
    assert "Phase 5" in str(exc_info.value)
    assert "dept:" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_invalid_expr_falls_back(db_session, clean_phase4_tables):
    """乱码字符串（含 : 但不是已知 prefix）→ fallback workspace admin。"""
    ws_id = await _seed_workspace(db_session, "garbage")
    await _seed_user_in_workspace(
        db_session, ws_id, email="g_admin@test.com", role_code="admin"
    )

    es = EscalationService(db_session)
    # 含 ':' 但不是 user:/role:/dept: prefix → fallback
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "unknown:gibberish"},
        workspace_id=ws_id,
    )
    assert result == ["g_admin@test.com"]


@pytest.mark.asyncio
async def test_resolve_empty_falls_back(db_session, clean_phase4_tables):
    """空 escalate_to ('' / None / 缺失) → fallback workspace admin。"""
    ws_id = await _seed_workspace(db_session, "empty")
    await _seed_user_in_workspace(
        db_session, ws_id, email="e_admin@test.com", role_code="admin"
    )

    es = EscalationService(db_session)

    # 1. node_config 不含 escalate_to
    result1 = await es.resolve_escalate_to(
        node_config={"other_field": "x"},
        workspace_id=ws_id,
    )
    assert result1 == ["e_admin@test.com"]

    # 2. escalate_to = ''（空字符串）
    result2 = await es.resolve_escalate_to(
        node_config={"escalate_to": ""},
        workspace_id=ws_id,
    )
    assert result2 == ["e_admin@test.com"]

    # 3. escalate_to = None
    result3 = await es.resolve_escalate_to(
        node_config={"escalate_to": None},
        workspace_id=ws_id,
    )
    assert result3 == ["e_admin@test.com"]

    # 4. node_config = None
    result4 = await es.resolve_escalate_to(
        node_config=None,
        workspace_id=ws_id,
    )
    assert result4 == ["e_admin@test.com"]


# ── 越权防护额外测试（多租户) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_role_admin_only_returns_active_users(
    db_session, clean_phase4_tables
):
    """role:admin 仅返回 status='active' 用户（disabled / pending 不算）。"""
    ws_id = await _seed_workspace(db_session, "active")
    await _seed_user_in_workspace(
        db_session, ws_id, email="active@test.com",
        role_code="admin", status="active",
    )
    await _seed_user_in_workspace(
        db_session, ws_id, email="disabled@test.com",
        role_code="admin", status="disabled",
    )
    await _seed_user_in_workspace(
        db_session, ws_id, email="pending@test.com",
        role_code="admin", status="pending_verification",
    )

    es = EscalationService(db_session)
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "role:admin"},
        workspace_id=ws_id,
    )
    assert result == ["active@test.com"]


@pytest.mark.asyncio
async def test_resolve_user_uuid_inactive_returns_none(
    db_session, clean_phase4_tables
):
    """user:<uuid> 用户存在但 status='disabled' → 返回 None。"""
    ws_id = await _seed_workspace(db_session, "inactive")
    user_id = await _seed_user_in_workspace(
        db_session, ws_id, email="disabled@x.com",
        role_code="editor", status="disabled",
    )

    es = EscalationService(db_session)
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": f"user:{user_id}"},
        workspace_id=ws_id,
    )
    assert result is None


@pytest.mark.asyncio
async def test_resolve_expr_strips_whitespace(db_session, clean_phase4_tables):
    """表达式前后空白字符 → strip 后正常解析。"""
    ws_id = await _seed_workspace(db_session, "whitespace")
    await _seed_user_in_workspace(
        db_session, ws_id, email="ws_admin@test.com", role_code="admin"
    )

    es = EscalationService(db_session)
    # 前后空格 — strip 后命中 role:admin
    result = await es.resolve_escalate_to(
        node_config={"escalate_to": "  role:admin  "},
        workspace_id=ws_id,
    )
    assert result == ["ws_admin@test.com"]
