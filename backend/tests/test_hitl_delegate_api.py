"""POST /hitl/action/<jwt>?op=delegate 公网回调集成测试（Plan 04-03，HITL-06）。

测试覆盖（5+ 用例，CLAUDE.md 2.2 真实 PG + Redis）：

1. test_post_delegate_success_returns_201_with_new_token_count
2. test_post_delegate_depth_exceeded_returns_409
3. test_post_delegate_self_returns_422
4. test_post_delegate_audit_log_written
5. test_post_delegate_original_token_consumed
6. test_post_delegate_without_cookie_returns_401
7. test_post_delegate_missing_reason_returns_422

设计参考 docs/reading-dify-04-03-delegation-2026-05-17.md。
"""
from __future__ import annotations

import hashlib
import hmac
import json as _json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, text

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.hitl_token import HitlToken
from app.services.hitl_token_service import HitlTokenService


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase4_delegate_api(db_session):
    yield
    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


@pytest_asyncio.fixture
async def redis_client():
    # 与 test_hitl_api_post_action.py 一致：使用 16379 端口（agent-builder-redis-test 容器）
    redis_url = os.environ.get(
        "TEST_REDIS_URL", "redis://localhost:16379/0"
    )
    client = Redis.from_url(redis_url, decode_responses=True)
    keys = await client.keys("agent_builder:jti:*")
    if keys:
        await client.delete(*keys)
    yield client
    keys = await client.keys("agent_builder:jti:*")
    if keys:
        await client.delete(*keys)
    await client.aclose()


@pytest_asyncio.fixture
async def app_client(redis_client):
    from app.agent_builder.main import agent_builder_app

    agent_builder_app.state.redis = redis_client
    async with AsyncClient(
        transport=ASGITransport(app=agent_builder_app),
        base_url="http://test",
    ) as client:
        yield client


async def _seed_delegate_api_flow(
    db_session,
    *,
    to_user_status: str = "active",
    second_workspace: bool = False,
) -> dict:
    """种子：完整 ws/from_user/to_user/wf/ver/inst/node_state + 1 个 token + JWT。

    Returns:
        dict 含所有 IDs + JWT token + signed cookie value
    """
    ws_id = uuid.uuid4()
    ws2_id = uuid.uuid4() if second_workspace else None
    from_user_id = uuid.uuid4()
    to_user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()
    jti = uuid.uuid4()

    # ── workspaces ─────────────────────────────────────────────────────
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :s)"),
        {"id": str(ws_id), "n": "api-ws1", "s": f"api-ws1-{ws_id.hex[:8]}"},
    )
    if ws2_id is not None:
        await db_session.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :s)"),
            {"id": str(ws2_id), "n": "api-ws2", "s": f"api-ws2-{ws2_id.hex[:8]}"},
        )

    # ── users ──────────────────────────────────────────────────────────
    from_email = f"from_{from_user_id.hex[:8]}@delegate-test.com"
    to_email = f"to_{to_user_id.hex[:8]}@delegate-test.com"
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :e, 'h', 'active', false)"
        ),
        {"id": str(from_user_id), "e": from_email},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :e, 'h', :s, false)"
        ),
        {"id": str(to_user_id), "e": to_email, "s": to_user_status},
    )

    # ── user_workspace_roles ───────────────────────────────────────────
    await db_session.execute(
        text(
            "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
            "VALUES (:w, :u, 2)"
        ),
        {"w": str(ws_id), "u": str(from_user_id)},
    )
    to_user_ws = ws2_id if second_workspace else ws_id
    await db_session.execute(
        text(
            "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
            "VALUES (:w, :u, 2)"
        ),
        {"w": str(to_user_ws), "u": str(to_user_id)},
    )

    # ── workflow + version + instance ──────────────────────────────────
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :w, 'wf', 'published', :c)"
        ),
        {"id": str(wf_id), "w": str(ws_id), "c": str(from_user_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions "
            "(id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :w, :wf, 1, 'published', '{}', :c)"
        ),
        {"id": str(ver_id), "w": str(ws_id), "wf": str(wf_id), "c": str(from_user_id)},
    )
    thread_id = f"{ws_id}:{inst_id}"
    await db_session.execute(
        text(
            "INSERT INTO flow_instances "
            "(id, workspace_id, workflow_id, workflow_version_id, "
            "dsl_snapshot, thread_id, status) "
            "VALUES (:id, :w, :wf, :v, '{}', :t, 'running')"
        ),
        {
            "id": str(inst_id),
            "w": str(ws_id),
            "wf": str(wf_id),
            "v": str(ver_id),
            "t": thread_id,
        },
    )

    # ── node_state.payload ─────────────────────────────────────────────
    payload = {
        "phase": "review",
        "current_actor": {
            "id": str(from_user_id),
            "email": from_email,
            "role": "reviewer",
        },
        "approval_chain": {
            "mode": "single",
            "approvers": [str(from_user_id)],
            "current_idx": 0,
        },
        "records": [],
        "form_schema": {},
        "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
    }
    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status, payload) "
            "VALUES (:id, :w, :i, 'hitl_1', 'hitl', 'in_review', CAST(:p AS jsonb))"
        ),
        {
            "id": str(node_state_id),
            "w": str(ws_id),
            "i": str(inst_id),
            "p": _json.dumps(payload),
        },
    )

    # ── 1 个 token + JWT ────────────────────────────────────────────────
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db_session.execute(
        text(
            "INSERT INTO hitl_tokens "
            "(jti, instance_id, node_state_id, actor_id, action, expires_at) "
            "VALUES (:j, :i, :n, :a, 'approve', :e)"
        ),
        {
            "j": str(jti),
            "i": str(inst_id),
            "n": str(node_state_id),
            "a": str(from_user_id),
            "e": expires_at,
        },
    )
    token_jwt = HitlTokenService.sign(
        jti=jti,
        instance_id=inst_id,
        node_state_id=node_state_id,
        actor_id=from_user_id,
        action="approve",
        role="reviewer",
        expires_at=expires_at,
    )
    await db_session.commit()

    return {
        "ws_id": ws_id,
        "ws2_id": ws2_id,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "from_email": from_email,
        "to_email": to_email,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
        "jti": jti,
        "jwt": token_jwt,
    }


def _sign_cookie_for_jti(jti: uuid.UUID) -> str:
    secret = os.environ.get("HMAC_SECRET", "").encode("utf-8")
    sig = hmac.new(secret, str(jti).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{jti}:{sig}"


# ── 1. happy path：201 + DelegateResponse ────────────────────────────────────


@pytest.mark.asyncio
async def test_post_delegate_success_returns_201_with_new_token_count(
    db_session, app_client, clean_phase4_delegate_api
):
    """委托成功 → 201 + DelegateResponse(new_token_count=3, depth=1)。"""
    seed = await _seed_delegate_api_flow(db_session)
    cookie = _sign_cookie_for_jti(seed["jti"])

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["to_email"], "reason": "我请假 3 天"},
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )

    assert resp.status_code == 201, f"got {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert body["ok"] is True
    assert body["new_token_count"] == 3
    assert body["depth"] == 1
    assert body["recipient_email"] == seed["to_email"]
    assert body["instance_id"] == str(seed["inst_id"])


# ── 2. 深度超限 → 409 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_delegate_depth_exceeded_returns_409(
    db_session, app_client, clean_phase4_delegate_api
):
    """预置 delegated[from].depth=3，再次委托 → 409 depth_exceeded。"""
    seed = await _seed_delegate_api_flow(db_session)
    # 直接 UPDATE payload.approval_chain.delegated 模拟「已委托 3 层」
    await db_session.execute(
        text(
            "UPDATE node_states "
            "SET payload = jsonb_set("
            "  payload, "
            "  '{approval_chain,delegated}', "
            "  :delegated_json"
            ") WHERE id = :id"
        ),
        {
            "delegated_json": _json.dumps(
                {str(seed["from_user_id"]): {"to": "any", "depth": 3}}
            ),
            "id": str(seed["node_state_id"]),
        },
    )
    await db_session.commit()
    cookie = _sign_cookie_for_jti(seed["jti"])

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["to_email"], "reason": "4 层委托"},
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )

    assert resp.status_code == 409, f"got {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert body["error"] == "depth_exceeded"


# ── 3. 自委托 → 422 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_delegate_self_returns_422(
    db_session, app_client, clean_phase4_delegate_api
):
    """to_email == from_user.email → 422 self_delegate。"""
    seed = await _seed_delegate_api_flow(db_session)
    cookie = _sign_cookie_for_jti(seed["jti"])

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["from_email"], "reason": "自委托"},
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )

    assert resp.status_code == 422, f"got {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert body["error"] == "self_delegate"


# ── 4. audit_log 写入 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_delegate_audit_log_written(
    db_session, app_client, clean_phase4_delegate_api
):
    """委托成功后 audit_logs 有 action='hitl.delegate' 一行 + meta 字段完整。"""
    seed = await _seed_delegate_api_flow(db_session)
    cookie = _sign_cookie_for_jti(seed["jti"])

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["to_email"], "reason": "AUDIT-TEST"},
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={
            "User-Agent": "Mozilla/5.0 AuditTest/1.0",
            "Accept": "application/json",
        },
    )
    assert resp.status_code == 201

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "hitl.delegate")
        )
    ).scalar_one()
    assert audit.decision == "delegate"
    assert audit.actor_user_id == seed["from_user_id"]
    assert audit.workspace_id == seed["ws_id"]
    assert audit.node_state_id == seed["node_state_id"]
    assert audit.actor_ua == "Mozilla/5.0 AuditTest/1.0"
    meta = audit.meta
    assert meta["from_actor"] == str(seed["from_user_id"])
    assert meta["from_email"] == seed["from_email"]
    assert meta["to_email"] == seed["to_email"]
    assert meta["to_actor"] == str(seed["to_user_id"])
    assert meta["depth"] == 1
    assert meta["reason"] == "AUDIT-TEST"
    assert meta["new_token_count"] == 3
    assert meta["jti"] == str(seed["jti"])


# ── 5. 原 token 已消费 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_delegate_original_token_consumed(
    db_session, app_client, clean_phase4_delegate_api
):
    """委托成功 → 原 token.used_at NOT NULL。"""
    seed = await _seed_delegate_api_flow(db_session)
    cookie = _sign_cookie_for_jti(seed["jti"])

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["to_email"], "reason": "原 token 消费"},
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    assert resp.status_code == 201

    # 原 token used_at NOT NULL
    orig = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert orig.used_at is not None
    # used_ip 含 ":delegate" 后缀（识别委托消费来源）
    assert ":delegate" in (orig.used_ip or "")

    # 新 token 3 行 used_at IS NULL
    new_rows = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.actor_id == seed["to_user_id"])
        )
    ).scalars().all()
    assert len(new_rows) == 3
    for r in new_rows:
        assert r.used_at is None
        assert r.action in ("approve", "return", "reject")


# ── 6. 无 cookie → 401 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_delegate_without_cookie_returns_401(
    db_session, app_client, clean_phase4_delegate_api
):
    """无 cookie → 401 + 原 token 未消费。"""
    seed = await _seed_delegate_api_flow(db_session)

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["to_email"], "reason": "无 cookie"},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    assert resp.status_code == 401

    # 原 token 未消费
    orig = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert orig.used_at is None


# ── 7. 缺 reason → 422 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_delegate_missing_reason_returns_422(
    db_session, app_client, clean_phase4_delegate_api
):
    """body 缺 reason → pydantic 校验失败 → 422。"""
    seed = await _seed_delegate_api_flow(db_session)
    cookie = _sign_cookie_for_jti(seed["jti"])

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["to_email"]},  # 缺 reason
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    assert resp.status_code == 422

    # 原 token 未消费（pydantic 校验在 consume 之前）
    orig = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert orig.used_at is None


# ── 8. 跨 workspace → 422 recipient_not_found（防泄漏） ─────────────────────


@pytest.mark.asyncio
async def test_post_delegate_cross_workspace_returns_422(
    db_session, app_client, clean_phase4_delegate_api
):
    """to_email 在另一 workspace → 422 recipient_not_found。"""
    seed = await _seed_delegate_api_flow(db_session, second_workspace=True)
    cookie = _sign_cookie_for_jti(seed["jti"])

    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}?op=delegate",
        json={"to_email": seed["to_email"], "reason": "跨 ws"},
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "recipient_not_found"


# ── 9. submit op 不受影响（回归测试 — 原 POST 流程仍工作） ──────────────────


@pytest.mark.asyncio
async def test_post_delegate_default_op_submit_still_works(
    db_session, app_client, clean_phase4_delegate_api
):
    """不带 op 参数 → 默认 submit 路径仍按 Phase 3 行为工作（回归）。

    注意：本测试用 Accept: application/json 走 JSON 响应分支，规避
    deferred-items.md §1 记录的 Starlette 1.0 HTML 模板预先存在 bug。
    回归目标是验证 op 参数路由不影响 submit 分支，不验证 HTML 渲染。
    """
    seed = await _seed_delegate_api_flow(db_session)
    cookie = _sign_cookie_for_jti(seed["jti"])

    # 不带 ?op=delegate，走默认 submit 路径
    resp = await app_client.post(
        f"/hitl/action/{seed['jwt']}",
        data={"action": "approve", "reason": "正常提交"},
        cookies={f"hitl_session_{seed['jti']}": cookie},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    # 走 submit_action，不应路由到 delegate 分支；返回 200 + JSON
    # （DSL 缺失会 log warning 但不影响 status）
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["ok"] is True
    assert body["action"] == "approve"
    assert body["instance_id"] == str(seed["inst_id"])
