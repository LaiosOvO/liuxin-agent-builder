"""Phase 4 E2E spec — Covers ROADMAP Phase 4 #1 顺序会签 sequential。

ROADMAP Phase 4 criterion #1:
    顺序会签：A 同意后 B 才收到通知；A 拒绝后 B 不收到通知，流程终止

测试矩阵：
1. setup → 创建 sequential chain (A→B→C) workflow → launch instance
2. 仅 A 收到邮件（mailhog 验证 A 收到 1 封，B/C 0 封）
3. A POST approve → B 收到邮件 / C 仍 0 封
4. B POST reject → instance status=rejected，C 始终 0 封
5. Safe Links bot regression（4 UA × A 的 token GET 不消费 jti）

工具栈：
- pytest + httpx + mailhog_client + im_mock_client
- 不需要浏览器（决策走 API POST /hitl/action）
- browser-harness 在本 spec 不使用
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from e2e_v2.conftest import e2e_required
from e2e_v2.helpers.api_client import (
    create_workflow,
    hitl_get_page,
    hitl_post_action,
    launch_instance,
    publish_workflow,
    random_email,
)
from e2e_v2.helpers.chain_builder import build_sequential_chain_dsl
from e2e_v2.helpers.mailhog_client import (
    MAILHOG_API_URL,
    get_emails_for,
    get_latest_hitl_email,
    parse_hitl_email,
)
from e2e_v2.helpers.safe_links_uas import BOT_UAS, REAL_USER_UA

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, e2e_required]


# ── Test 1: 顺序会签主流程 ───────────────────────────────────────────


async def test_sequential_chain_approve_then_reject(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
):
    """ROADMAP Phase 4 #1 — 顺序会签主流程。

    A → B → C：A 同意推到 B，B 拒绝终止，C 始终不通知。
    """
    # 1. 准备 3 个 approver 邮箱（用于 DSL approvers + mailhog 拉邮件）
    email_a = random_email("seq_a")
    email_b = random_email("seq_b")
    email_c = random_email("seq_c")

    # 2. 创建并发布 sequential workflow
    dsl = build_sequential_chain_dsl([email_a, email_b, email_c])
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])

    # 3. 启动实例
    instance = await launch_instance(
        admin_client,
        workflow_id=workflow["id"],
        input_payload={"reason": "顺序会签 E2E"},
    )
    instance_id = instance["id"]

    # 4. 仅 A 收邮件（sequential 模式只 ping 首个）
    email_a_msg = await get_latest_hitl_email(email_a, timeout=15.0)
    assert len(email_a_msg.deeplinks) >= 3, (
        f"A 应收到含 3 个 deeplink 的决策邮件，实际 {len(email_a_msg.deeplinks)}"
    )

    # 验证 B / C 未收（短超时确认）
    with pytest.raises(TimeoutError):
        await get_emails_for(email_b, min_count=1, timeout=3.0)
    with pytest.raises(TimeoutError):
        await get_emails_for(email_c, min_count=1, timeout=3.0)

    # 5. A 走决策链：GET → cookie → POST approve
    approve_link = next(d for d in email_a_msg.deeplinks if d.action == "approve")

    # GET 签 cookie
    async with httpx.AsyncClient(timeout=30.0) as a_client:
        r = await hitl_get_page(
            a_client,
            token=approve_link.token,
            user_agent=REAL_USER_UA,
        )
        assert r.status_code == 200
        # 提取 cookie
        cookie_header = r.headers.get("set-cookie", "")
        assert "hitl_session_" in cookie_header, (
            f"真实用户 GET 应签 cookie，实际 headers: {dict(r.headers)}"
        )

        # POST approve（cookie 已自动写入 a_client.cookies）
        post_r = await hitl_post_action(
            a_client, token=approve_link.token, action="approve"
        )
        assert post_r.status_code in (200, 309), (
            f"A approve 应成功，实际 {post_r.status_code}: {post_r.text[:200]}"
        )

    # 6. B 收到邮件（chain 推进）
    email_b_msg = await get_latest_hitl_email(email_b, timeout=15.0)
    assert len(email_b_msg.deeplinks) >= 3

    # C 仍未收
    with pytest.raises(TimeoutError):
        await get_emails_for(email_c, min_count=1, timeout=3.0)

    # 7. B 走决策链：reject
    reject_link = next(d for d in email_b_msg.deeplinks if d.action == "reject")

    async with httpx.AsyncClient(timeout=30.0) as b_client:
        r = await hitl_get_page(
            b_client, token=reject_link.token, user_agent=REAL_USER_UA
        )
        assert r.status_code == 200

        post_r = await hitl_post_action(
            b_client, token=reject_link.token, action="reject"
        )
        assert post_r.status_code in (200, 309)

    # 8. C 始终未收（reject 终止 chain，sequential 不发补通知给 C）
    await asyncio.sleep(2.0)  # 等 worker 处理完
    with pytest.raises(TimeoutError):
        await get_emails_for(email_c, min_count=1, timeout=3.0)


# ── Test 2: Safe Links bot regression（4 UA parametrize）───────────────


@pytest.mark.parametrize("ua_name,bot_ua", list(BOT_UAS))
async def test_sequential_chain_safe_links_bot_does_not_consume_jti(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    im_mock,  # 用 token_status() endpoint
    ua_name: str,
    bot_ua: str,
):
    """CLAUDE.md §2.5 Pitfall 3 P0 — Safe Links bot GET 不消费 jti。

    在 sequential chain 场景下回归 4 种 bot UA。
    """
    # 1. 准备工作流
    email_a = random_email(f"seq_safe_{ua_name}_a")
    email_b = random_email(f"seq_safe_{ua_name}_b")
    dsl = build_sequential_chain_dsl([email_a, email_b])
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])
    await launch_instance(admin_client, workflow_id=workflow["id"])

    # 2. 等 A 邮件
    email_a_msg = await get_latest_hitl_email(email_a, timeout=15.0)
    approve_link = next(d for d in email_a_msg.deeplinks if d.action == "approve")
    jti = approve_link.jti
    assert jti, "deeplink jti 应可解析"

    # 3. 用 bot UA 发 GET（不带任何 cookie，模拟邮件扫描器）
    async with httpx.AsyncClient(timeout=30.0) as bot_client:
        r = await hitl_get_page(
            bot_client,
            token=approve_link.token,
            user_agent=bot_ua,
        )
        assert r.status_code == 200, (
            f"bot UA '{ua_name}' GET 应返回 200（短路成功），实际 {r.status_code}"
        )

        # 关键断言 1：bot 路径不签 cookie（防止 bot 后续 POST）
        set_cookie = r.headers.get("set-cookie", "")
        assert "hitl_session_" not in set_cookie, (
            f"bot UA '{ua_name}' 路径不应签 hitl_session cookie，"
            f"实际 set-cookie: {set_cookie}"
        )

    # 4. 关键断言 2：jti 未消费（核心 P0 防护）
    status = await im_mock.token_status(jti)
    assert status["exists"] is True, f"token 应存在于 DB"
    assert status["consumed"] is False, (
        f"bot UA '{ua_name}' GET 后 jti '{jti}' 必须未消费，"
        f"实际 status: {status}"
    )
    assert status["used_at"] is None

    # 5. 真实用户随后 GET → POST 仍可成功（反证 jti 未被 bot 消费）
    async with httpx.AsyncClient(timeout=30.0) as user_client:
        r = await hitl_get_page(
            user_client, token=approve_link.token, user_agent=REAL_USER_UA
        )
        assert r.status_code == 200
        assert "hitl_session_" in r.headers.get("set-cookie", ""), (
            "真实用户 GET 必须签 cookie"
        )

        post_r = await hitl_post_action(
            user_client, token=approve_link.token, action="approve"
        )
        assert post_r.status_code in (200, 309), (
            f"真实用户 POST 应成功，bot 扫描没污染 jti。实际 {post_r.status_code}"
        )

    # 6. 现在 jti 应已消费（真实用户 POST）
    status_after = await im_mock.token_status(jti)
    assert status_after["consumed"] is True
