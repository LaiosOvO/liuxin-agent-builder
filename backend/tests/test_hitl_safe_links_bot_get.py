"""Safe Links Bot UA 回归测试 — Pitfall 3 P0 防护。

CLAUDE.md 2.5：GET 不消费 jti（永不可接受 GET 消费）。
邮件安全扫描器（Outlook Safe Links / Microsoft Defender / Slack 等）会用 GET
预扫链接，如果消费 jti 会导致真实用户无法决策。

测试覆盖（6 用例）：
1. test_outlook_safelinks_real_ua_returns_bot_scan_page
2. test_microsoft_defender_ua_returns_bot_scan_page
3. test_slackbot_linkexpanding_returns_bot_scan_page
4. test_googlebot_returns_bot_scan_page
5. test_real_chrome_user_returns_form_page
6. test_bot_scan_response_does_not_set_cookie_and_does_not_modify_jti

CONTEXT.md §Specific Ideas 提供的真实 UA：
  Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; +safelinks.protection.outlook.com)
"""
from __future__ import annotations

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
    from app.agent_builder.main import agent_builder_app

    agent_builder_app.state.redis = redis_client
    async with AsyncClient(
        transport=ASGITransport(app=agent_builder_app),
        base_url="http://test",
    ) as client:
        yield client


async def _seed_token(db_session) -> dict:
    """seed 完整 chain + 返回有效 JWT。"""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()
    jti = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :s)"),
        {"id": str(ws_id), "n": "bot测试", "s": f"bot-{ws_id.hex[:8]}"},
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
            "p": _json.dumps({"phase": "submit", "form_schema": {}}),
        },
    )
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db_session.execute(
        text(
            "INSERT INTO hitl_tokens "
            "(jti, instance_id, node_state_id, actor_id, action, expires_at) "
            "VALUES (:j, :i, :n, :a, 'submit', :e)"
        ),
        {
            "j": str(jti),
            "i": str(inst_id),
            "n": str(node_state_id),
            "a": str(user_id),
            "e": expires_at,
        },
    )
    await db_session.commit()

    token = HitlTokenService.sign(
        jti=jti,
        instance_id=inst_id,
        node_state_id=node_state_id,
        actor_id=user_id,
        action="submit",
        role="executor",
        expires_at=expires_at,
    )
    return {"token": token, "jti": jti, "node_state_id": node_state_id}


def _assert_bot_scan_response(resp, jti=None):
    """通用断言：bot 路径返回 200 + bot_scan.html + 无 Set-Cookie。"""
    assert resp.status_code == 200, f"got status {resp.status_code}"
    # bot_scan.html 关键字
    assert "邮件扫描" in resp.text or "未触发任何状态变更" in resp.text, (
        f"bot_scan.html not rendered; got: {resp.text[:200]}"
    )
    # **必须** 无 Set-Cookie（CLAUDE.md 2.5 P0）
    if jti:
        cookie_name = f"hitl_session_{jti}"
        assert (
            cookie_name not in resp.cookies
        ), f"bot path should NOT set cookie; got: {resp.cookies}"


# ── 6 Safe Links Bot 回归测试 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outlook_safelinks_real_ua_returns_bot_scan_page(
    db_session, app_client, clean_phase3
):
    """Outlook Safe Links 真实 UA（CONTEXT.md §Specific Ideas）→ bot_scan.html 200 不签 cookie。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; +safelinks.protection.outlook.com)"
        },
    )
    _assert_bot_scan_response(resp, jti=seed["jti"])

    # P0 验证：jti 未消费
    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None, "Safe Links GET MUST NOT consume jti"


@pytest.mark.asyncio
async def test_microsoft_defender_ua_returns_bot_scan_page(
    db_session, app_client, clean_phase3
):
    """Microsoft Defender Safe Links → bot_scan.html。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; MicrosoftDefender/1.0; "
                          "Win32; +https://defender.microsoft.com/)"
        },
    )
    _assert_bot_scan_response(resp, jti=seed["jti"])

    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None


@pytest.mark.asyncio
async def test_slackbot_linkexpanding_returns_bot_scan_page(
    db_session, app_client, clean_phase3
):
    """Slackbot LinkExpanding → bot_scan.html。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)"
        },
    )
    _assert_bot_scan_response(resp, jti=seed["jti"])

    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None


@pytest.mark.asyncio
async def test_googlebot_returns_bot_scan_page(db_session, app_client, clean_phase3):
    """Googlebot（搜索 / Gmail 安全扫描）→ bot_scan.html。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; "
                          "+http://www.google.com/bot.html)"
        },
    )
    _assert_bot_scan_response(resp, jti=seed["jti"])

    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None


@pytest.mark.asyncio
async def test_real_chrome_user_returns_form_page(
    db_session, app_client, clean_phase3
):
    """真实 Chrome 用户 → page.html + Set-Cookie + jti 仍未消费（GET 不消费）。"""
    seed = await _seed_token(db_session)
    resp = await app_client.get(
        f"/hitl/page/{seed['token']}",
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/605.1.15"
        },
    )
    # 真实用户 → 200 + page.html 表单
    assert resp.status_code == 200
    assert "审批决策" in resp.text or "决策表单" in resp.text
    # 应签 cookie
    cookie_name = f"hitl_session_{seed['jti']}"
    assert cookie_name in resp.cookies

    # P0 验证：真实用户 GET 也不消费 jti
    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None, "GET MUST NOT consume jti (even real user)"


@pytest.mark.asyncio
async def test_bot_scan_response_does_not_set_cookie_and_does_not_modify_jti(
    db_session, app_client, clean_phase3
):
    """关键集合断言：bot 路径同时满足
    (1) 无 Set-Cookie
    (2) jti.used_at IS NULL
    (3) Redis 中无 consumed 标记。
    """
    seed = await _seed_token(db_session)

    # 调多个不同 bot UA
    bot_uas = [
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Mozilla/5.0 (compatible; LinkedInBot/1.0; +http://www.linkedin.com/)",
        "WhatsApp/2.21.12.21 A",
        "TelegramBot (like TwitterBot)",
    ]
    for ua in bot_uas:
        resp = await app_client.get(
            f"/hitl/page/{seed['token']}",
            headers={"User-Agent": ua},
        )
        _assert_bot_scan_response(resp, jti=seed["jti"])

    # 三重验证
    token_row = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti"])
        )
    ).scalar_one()
    assert token_row.used_at is None
    assert token_row.used_ip is None

    # Redis 中无 consumed 标记
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:16379/0")
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    try:
        val = await redis_client.get(f"agent_builder:jti:{seed['jti']}")
        assert val is None, f"Redis MUST NOT have consumed marker; got: {val}"
    finally:
        await redis_client.aclose()
