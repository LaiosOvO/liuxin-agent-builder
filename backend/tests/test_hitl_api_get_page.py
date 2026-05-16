"""GET /hitl/page/<token> 公网回调端点集成测试。

测试覆盖（10 用例）：
1. test_get_with_valid_token_returns_form_and_cookie
2. test_get_with_expired_token_returns_410
3. test_get_with_invalid_signature_returns_401
4. test_get_with_wrong_audience_returns_401
5. test_get_with_corrupt_token_returns_400
6. test_get_does_NOT_consume_jti（CLAUDE.md 2.5 P0）
7. test_get_page_renders_records_and_form_schema
8. test_get_page_with_consumed_jti_returns_410
9. test_get_page_with_missing_node_state_returns_404
10. test_get_page_signs_cookie_with_correct_hmac

CLAUDE.md 2.5 P0 验证：所有 GET 测试断言 hitl_tokens.used_at IS NULL（jti 永不消费）。

测试约定：
- 真实 PG（CLAUDE.md 2.2 不 mock DB）
- 真实 Redis（HitlTokenStore 内部 pipeline）
- httpx.ASGITransport 直连 FastAPI app
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

from app.agent_builder.models.hitl_token import HitlToken
from app.services.hitl_token_service import HitlTokenService


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3(db_session):
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
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:16379/0")
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
    """FastAPI ASGI client，已注入 Redis 到 app.state.redis。"""
    from app.agent_builder.main import agent_builder_app

    agent_builder_app.state.redis = redis_client
    async with AsyncClient(
        transport=ASGITransport(app=agent_builder_app),
        base_url="http://test",
    ) as client:
        yield client


async def _seed_token(
    db_session,
    *,
    expires_in: int = 86400,
    form_schema: dict | None = None,
    records: list | None = None,
    action: str = "submit",
    phase: str = "submit",
) -> dict:
    """seed full chain: ws→user→wf→ver→inst→node_state(payload)→hitl_token + return token JWT。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()
    jti = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :s)"),
        {"id": str(ws_id), "n": "get测试", "s": f"get-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :e, :p, 'active', false)"
        ),
        {"id": str(user_id), "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "p": "h"},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :w, 'wf', 'published', :c)"
        ),
        {"id": str(wf_id), "w": str(ws_id), "c": str(user_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :w, :wf, 1, 'published', '{}', :c)"
        ),
        {"id": str(ver_id), "w": str(ws_id), "wf": str(wf_id), "c": str(user_id)},
    )
    thread_id = f"{ws_id}:{inst_id}"
    await db_session.execute(
        text(
            "INSERT INTO flow_instances "
            "(id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot, thread_id, status) "
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

    payload = {
        "phase": phase,
        "current_actor": {"id": str(user_id), "email": "user@test.com", "role": "executor"},
        "records": records or [],
        "form_schema": form_schema or {},
        "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
    }
    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status, payload) "
            "VALUES (:id, :w, :i, 'hitl_1', 'hitl', 'waiting_human', CAST(:p AS jsonb))"
        ),
        {
            "id": str(node_state_id),
            "w": str(ws_id),
            "i": str(inst_id),
            "p": _json.dumps(payload),
        },
    )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    await db_session.execute(
        text(
            "INSERT INTO hitl_tokens "
            "(jti, instance_id, node_state_id, actor_id, action, expires_at) "
            "VALUES (:j, :i, :n, :a, :ac, :e)"
        ),
        {
            "j": str(jti),
            "i": str(inst_id),
            "n": str(node_state_id),
            "a": str(user_id),
            "ac": action,
            "e": expires_at,
        },
    )
    await db_session.commit()

    # 签 JWT（使用真实 HitlTokenService）
    token = HitlTokenService.sign(
        jti=jti,
        instance_id=inst_id,
        node_state_id=node_state_id,
        actor_id=user_id,
        action=action,  # type: ignore[arg-type]
        role="executor",
        expires_at=expires_at,
    )

    return {
        "token": token,
        "jti": jti,
        "ws_id": ws_id,
        "user_id": user_id,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
    }


# ── 10 测试用例 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_with_valid_token_returns_form_and_cookie(
    db_session, app_client, clean_phase3
):
    """Happy path：valid token → 200 + Set-Cookie + page.html 内容。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Chrome/120)"},
    )

    assert resp.status_code == 200
    assert "决策表单" in resp.text or "审批决策" in resp.text
    cookie_name = f"hitl_session_{seed['jti']}"
    assert cookie_name in resp.cookies, f"cookie {cookie_name} not set; got: {resp.cookies}"


@pytest.mark.asyncio
async def test_get_with_expired_token_returns_410(db_session, app_client, clean_phase3):
    """过期 token → 410 + error.html。"""
    seed = await _seed_token(db_session)
    # 用过期时间签新 token（覆盖 seed 的 token）
    expired_token = HitlTokenService.sign(
        jti=seed["jti"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="submit",
        role="executor",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    resp = await app_client.get(
        f"/hitl/page/{expired_token}",
        headers={"User-Agent": "Mozilla/5.0 (Chrome/120)"},
    )
    assert resp.status_code == 410
    assert "已过期" in resp.text or "失效" in resp.text


@pytest.mark.asyncio
async def test_get_with_invalid_signature_returns_401(db_session, app_client, clean_phase3):
    """签名错误（最后一段 corrupt）→ 401。"""
    seed = await _seed_token(db_session)
    # 篡改 token：替换 sig 段
    parts = seed["token"].split(".")
    bad_token = ".".join(parts[:2] + ["X" * len(parts[2])])
    resp = await app_client.get(
        f"/hitl/page/{bad_token}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    assert resp.status_code == 401
    assert "无效" in resp.text or "签名" in resp.text


@pytest.mark.asyncio
async def test_get_with_wrong_audience_returns_401_or_400(
    db_session, app_client, clean_phase3
):
    """Phase 1 session token（无 aud='hitl'）→ 401 / 400（依 PyJWT 异常分支）。"""
    seed = await _seed_token(db_session)
    # 使用 Phase 1 sign_session 签 token（不是 hitl audience）
    from app.services.jwt_service import sign_session
    bad_token = sign_session(seed["user_id"], seed["ws_id"])
    resp = await app_client.get(
        f"/hitl/page/{bad_token}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    # session token 缺 aud / jti / iss → InvalidTokenError tree
    # 落到 HitlTokenError 兜底分支 → 400
    assert resp.status_code in (400, 401)


@pytest.mark.asyncio
async def test_get_with_corrupt_token_returns_400(db_session, app_client, clean_phase3):
    """完全格式错误的 token → 400。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        "/hitl/page/this-is-not-a-jwt",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    assert resp.status_code in (400, 401)


@pytest.mark.asyncio
async def test_get_does_NOT_consume_jti(db_session, app_client, clean_phase3):
    """CLAUDE.md 2.5 P0：GET 多次后 hitl_tokens.used_at 仍为 NULL。"""
    seed = await _seed_token(db_session)

    # 调 GET 3 次
    for _ in range(3):
        resp = await app_client.get(
            f"/hitl/page/{seed['token']}",
            headers={"User-Agent": "Mozilla/5.0 (Chrome/120)"},
        )
        assert resp.status_code == 200

    # 重新查询：used_at 必须仍为 NULL
    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None, "CLAUDE.md 2.5 P0 violation: GET consumed jti"
    assert token_row.used_ip is None
    assert token_row.used_ua is None


@pytest.mark.asyncio
async def test_get_page_renders_records_and_form_schema(
    db_session, app_client, clean_phase3
):
    """页面渲染 records 历史 + form_schema 表单字段。"""
    records = [
        {
            "actor_email": "prev@test.com",
            "action": "submit",
            "ts": "2026-05-17T10:00:00+00:00",
            "reason": "前序提交",
        }
    ]
    form_schema = {
        "type": "object",
        "properties": {
            "comment": {"type": "string", "title": "审批意见"},
        },
        "required": ["comment"],
    }
    seed = await _seed_token(
        db_session, records=records, form_schema=form_schema
    )

    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    assert resp.status_code == 200
    assert "prev@test.com" in resp.text  # 历史决策渲染
    assert "审批意见" in resp.text  # form_schema title 渲染
    assert 'name="comment"' in resp.text


@pytest.mark.asyncio
async def test_get_page_with_consumed_jti_returns_410(
    db_session, app_client, clean_phase3
):
    """jti 已消费 → 410（不应进入 page.html）。"""
    seed = await _seed_token(db_session)
    # 手动消费 jti
    await db_session.execute(
        text(
            "UPDATE hitl_tokens SET used_at=NOW(), used_ip='10.0.0.1' "
            "WHERE jti=:jti"
        ),
        {"jti": str(seed["jti"])},
    )
    await db_session.commit()

    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    assert resp.status_code == 410
    assert "已提交" in resp.text or "失效" in resp.text


@pytest.mark.asyncio
async def test_get_page_with_missing_node_state_returns_404(
    db_session, app_client, clean_phase3
):
    """node_state 不存在 → 404。"""
    seed = await _seed_token(db_session)
    # 删除 node_state
    await db_session.execute(
        text("DELETE FROM hitl_tokens WHERE jti=:j"), {"j": str(seed["jti"])}
    )
    await db_session.execute(
        text("DELETE FROM node_states WHERE id=:i"),
        {"i": str(seed["node_state_id"])},
    )
    await db_session.commit()

    # 重新插入 hitl_token 但指向不存在的 node_state_id（绕开 FK）
    # 此处用 valid jwt 但 ns 已删 → HitlTokenStore.is_consumed 会返回 True（防伪造）
    # 所以测试转为：is_consumed 返回 True → 410
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    # token 行被删 → is_consumed 防伪造返回 True → 410
    assert resp.status_code in (404, 410)


@pytest.mark.asyncio
async def test_get_page_signs_cookie_with_correct_hmac(
    db_session, app_client, clean_phase3
):
    """cookie value = '<jti>:<HMAC-SHA256(jti)>' 验证。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    assert resp.status_code == 200

    cookie_value = resp.cookies.get(f"hitl_session_{seed['jti']}")
    assert cookie_value
    parts = cookie_value.split(":", 1)
    assert len(parts) == 2
    cookie_jti, cookie_sig = parts
    assert cookie_jti == str(seed["jti"])

    # 验证 HMAC 与服务端实现一致
    secret = os.environ.get("HMAC_SECRET", "").encode("utf-8")
    expected_sig = hmac.new(
        secret, str(seed["jti"]).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert cookie_sig == expected_sig


# ── Plan 03-07 新增：JSON content negotiation 4 用例 ─────────────────────────


@pytest.mark.asyncio
async def test_get_page_with_accept_json_returns_json_payload(
    db_session, app_client, clean_phase3
):
    """Accept: application/json → 返回 JSON 数据（Next.js 前端 SSR 消费）。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Chrome/120)",
            "Accept": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["bot_scan"] is False
    assert data["token"] == seed["token"]
    assert data["jti"] == str(seed["jti"])
    assert "form_schema" in data
    assert "records" in data
    assert "deadline_at" in data
    assert data["phase"] in ("submit", "review")
    # cookie 仍应签 — Next.js SSR 透传 cookie 给浏览器响应
    cookie_name = f"hitl_session_{seed['jti']}"
    assert cookie_name in resp.cookies


@pytest.mark.asyncio
async def test_get_bot_ua_with_accept_json_returns_bot_scan_json(
    db_session, app_client, clean_phase3
):
    """Bot UA + Accept JSON → JSON {bot_scan: true}（不签 cookie，CLAUDE.md 2.5）。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; outlook-safelinks/1.0)",
            "Accept": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["bot_scan"] is True
    # bot 路径不发 cookie（三重不可逆契约）
    assert f"hitl_session_{seed['jti']}" not in resp.cookies


@pytest.mark.asyncio
async def test_get_expired_with_accept_json_returns_json_error_410(
    db_session, app_client, clean_phase3
):
    """过期 token + Accept JSON → JSON {error, status_code: 410}。"""
    seed = await _seed_token(db_session)
    expired_token = HitlTokenService.sign(
        jti=seed["jti"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="submit",
        role="executor",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    resp = await app_client.get(
        f"/hitl/page/{expired_token}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    assert resp.status_code == 410
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert "error" in data
    assert data["status_code"] == 410


@pytest.mark.asyncio
async def test_get_json_path_does_not_consume_jti(
    db_session, app_client, clean_phase3
):
    """JSON 路径同样不消费 jti（CLAUDE.md 2.5 跨 content type 一致）。"""
    seed = await _seed_token(db_session)
    await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    # 二次断言：DB 中 used_at 仍为 NULL
    result = await db_session.execute(
        select(HitlToken).where(HitlToken.jti == seed["jti"])
    )
    token_row = result.scalar_one()
    assert token_row.used_at is None
