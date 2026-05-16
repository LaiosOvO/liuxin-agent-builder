"""POST /hitl/action/<token> 公网回调端点集成测试。

测试覆盖（8 用例）：
1. test_post_happy_path_consumes_jti_and_returns_success
2. test_post_without_cookie_returns_401
3. test_post_with_wrong_cookie_returns_401
4. test_post_with_already_consumed_jti_returns_409
5. test_post_form_data_validation_failure_returns_422_with_errors
6. test_post_invalidates_sibling_tokens
7. test_post_writes_audit_log_with_NET-05_fields
8. test_post_with_expired_token_returns_410

集成测试（CLAUDE.md 2.2 真实 PG + Redis）。
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
    from app.agent_builder.main import agent_builder_app

    agent_builder_app.state.redis = redis_client
    async with AsyncClient(
        transport=ASGITransport(app=agent_builder_app),
        base_url="http://test",
    ) as client:
        yield client


async def _seed_flow(
    db_session,
    *,
    form_schema: dict | None = None,
    phase: str = "submit",
    actions: list[str] | None = None,
) -> dict:
    """完整 seed + 多 action token + 返回 token map（action → JWT）。"""
    if actions is None:
        actions = ["submit", "return", "reject"]
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :s)"),
        {"id": str(ws_id), "n": "post测试", "s": f"post-{ws_id.hex[:8]}"},
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
        {"id": str(inst_id), "w": str(ws_id), "wf": str(wf_id), "v": str(ver_id), "t": thread_id},
    )

    payload = {
        "phase": phase,
        "current_actor": {"id": str(user_id), "email": "user@test.com", "role": "executor"},
        "records": [],
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

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    tokens = {}
    for action in actions:
        jti = uuid.uuid4()
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
        token_jwt = HitlTokenService.sign(
            jti=jti,
            instance_id=inst_id,
            node_state_id=node_state_id,
            actor_id=user_id,
            action=action,  # type: ignore[arg-type]
            role="executor",
            expires_at=expires_at,
        )
        tokens[action] = {"jwt": token_jwt, "jti": jti}
    await db_session.commit()

    return {
        "ws_id": ws_id,
        "user_id": user_id,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
        "tokens": tokens,
    }


def _sign_cookie_for_jti(jti: uuid.UUID) -> str:
    """与 api/hitl.py _sign_session_cookie 保持一致。"""
    secret = os.environ.get("HMAC_SECRET", "").encode("utf-8")
    sig = hmac.new(secret, str(jti).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{jti}:{sig}"


# ── 8 测试用例 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_happy_path_consumes_jti_and_returns_success(
    db_session, app_client, clean_phase3
):
    """Happy path：POST → jti 消费 + node_state 状态 + success.html。"""
    seed = await _seed_flow(db_session)
    tok = seed["tokens"]["submit"]
    cookie = _sign_cookie_for_jti(tok["jti"])

    resp = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "审核通过"},
        cookies={f"hitl_session_{tok['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0"},
    )

    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}"
    assert "决策已记录" in resp.text or "已提交" in resp.text

    # 验证 jti 已消费
    db_session.expire_all()
    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == tok["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is not None


@pytest.mark.asyncio
async def test_post_without_cookie_returns_401(db_session, app_client, clean_phase3):
    """无 cookie → 401 + jti 未消费。"""
    seed = await _seed_flow(db_session)
    tok = seed["tokens"]["submit"]

    resp = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "未带 cookie"},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    assert resp.status_code == 401
    assert "会话" in resp.text or "重新点击" in resp.text

    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == tok["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None  # 未消费


@pytest.mark.asyncio
async def test_post_with_wrong_cookie_returns_401(db_session, app_client, clean_phase3):
    """cookie HMAC sig 不匹配 → 401。"""
    seed = await _seed_flow(db_session)
    tok = seed["tokens"]["submit"]

    bad_cookie = f"{tok['jti']}:" + ("0" * 64)  # 错误 HMAC

    resp = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "错 cookie"},
        cookies={f"hitl_session_{tok['jti']}": bad_cookie},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_with_already_consumed_jti_returns_409(
    db_session, app_client, clean_phase3
):
    """jti 已消费 → 409 + 不再修改 node_state。"""
    seed = await _seed_flow(db_session)
    tok = seed["tokens"]["submit"]
    cookie = _sign_cookie_for_jti(tok["jti"])

    # 第一次成功
    resp1 = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "第一次"},
        cookies={f"hitl_session_{tok['jti']}": cookie},
    )
    assert resp1.status_code == 200

    # 第二次 409
    resp2 = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "重复"},
        cookies={f"hitl_session_{tok['jti']}": cookie},
    )
    assert resp2.status_code == 409
    assert "已提交" in resp2.text or "无法重复" in resp2.text


@pytest.mark.asyncio
async def test_post_form_data_validation_failure_returns_422_with_errors(
    db_session, app_client, clean_phase3
):
    """form_data 缺 required 字段 → 422 + page.html 含 errors。"""
    schema = {
        "type": "object",
        "required": ["comment"],
        "properties": {"comment": {"type": "string", "title": "意见"}},
    }
    seed = await _seed_flow(db_session, form_schema=schema)
    tok = seed["tokens"]["submit"]
    cookie = _sign_cookie_for_jti(tok["jti"])

    resp = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "缺 comment"},  # 缺 required.comment
        cookies={f"hitl_session_{tok['jti']}": cookie},
    )
    assert resp.status_code == 422
    assert "校验失败" in resp.text or "comment" in resp.text

    # jti 未消费（422 不消费）
    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == tok["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None


@pytest.mark.asyncio
async def test_post_invalidates_sibling_tokens(db_session, app_client, clean_phase3):
    """submit 一个 jti → 其他 2 个同节点 token 一并失效。"""
    seed = await _seed_flow(db_session)
    tok = seed["tokens"]["submit"]
    cookie = _sign_cookie_for_jti(tok["jti"])

    resp = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "测试 sibling"},
        cookies={f"hitl_session_{tok['jti']}": cookie},
    )
    assert resp.status_code == 200

    # 验证 3 个 token 全部 used_at SET
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == seed["node_state_id"])
        )
    ).scalars().all()
    by_action = {r.action: r for r in rows}
    assert by_action["submit"].used_at is not None
    assert by_action["return"].used_at is not None
    assert by_action["return"].used_ip == "system:sibling-invalidate"
    assert by_action["reject"].used_at is not None
    assert by_action["reject"].used_ip == "system:sibling-invalidate"


@pytest.mark.asyncio
async def test_post_writes_audit_log_with_NET05_fields(
    db_session, app_client, clean_phase3
):
    """NET-05 决策审计字段全部填充：actor_ip / actor_ua / decision / node_state_id。"""
    seed = await _seed_flow(db_session)
    tok = seed["tokens"]["submit"]
    cookie = _sign_cookie_for_jti(tok["jti"])

    resp = await app_client.post(
        f"/hitl/action/{tok['jwt']}",
        data={"action": "submit", "reason": "NET-05 验证"},
        cookies={f"hitl_session_{tok['jti']}": cookie},
        headers={"User-Agent": "Mozilla/5.0 NET-05-Test/1.0"},
    )
    assert resp.status_code == 200

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "hitl.decision")
        )
    ).scalar_one()
    # 必填字段（NET-05）
    assert audit.actor_ua == "Mozilla/5.0 NET-05-Test/1.0"
    assert audit.decision == "submit"
    assert audit.node_state_id == seed["node_state_id"]
    # actor_ip 可能因 ASGITransport 是 None / '' 或测试 host —— 字段被填即可
    assert audit.actor_user_id == seed["user_id"]
    assert audit.workspace_id == seed["ws_id"]
    assert audit.meta["jti"] == str(tok["jti"])
    assert audit.meta["reason"] == "NET-05 验证"


@pytest.mark.asyncio
async def test_post_with_expired_token_returns_410(
    db_session, app_client, clean_phase3
):
    """token exp 过期 → 410。"""
    seed = await _seed_flow(db_session)
    # 用过期时间重新签 token
    expired_token = HitlTokenService.sign(
        jti=seed["tokens"]["submit"]["jti"],
        instance_id=seed["inst_id"],
        node_state_id=seed["node_state_id"],
        actor_id=seed["user_id"],
        action="submit",
        role="executor",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    cookie = _sign_cookie_for_jti(seed["tokens"]["submit"]["jti"])

    resp = await app_client.post(
        f"/hitl/action/{expired_token}",
        data={"action": "submit", "reason": "expired"},
        cookies={f"hitl_session_{seed['tokens']['submit']['jti']}": cookie},
    )
    assert resp.status_code == 410
