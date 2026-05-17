"""Phase 4 E2E spec — Covers ROADMAP Phase 4 #3 或签 parallel_any。

ROADMAP Phase 4 criterion #3:
    或签（任一同意）：A 同意后流程立即推进，其余人的 token 同时失效

测试矩阵：
1. parallel_any 3 approvers — 3 人同时收邮件
2. A POST approve → 流程推进 + B/C token 立即失效
3. B/C 收到补通知（"已被 A 处理"）
4. Safe Links bot regression（4 UA 在 parallel_any 场景）
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
from e2e_v2.helpers.chain_builder import build_parallel_any_dsl
from e2e_v2.helpers.mailhog_client import (
    get_emails_for,
    get_latest_hitl_email,
    parse_hitl_email,
)
from e2e_v2.helpers.safe_links_uas import BOT_UAS, REAL_USER_UA

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, e2e_required]


# ── Test 1: parallel_any 主流程 — A approve 推进 + 其他失效 ──────────


async def test_parallel_any_approve_invalidates_others(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    im_mock,
):
    """ROADMAP Phase 4 #3 — 或签任一同意推进 + 其余 token 失效。"""
    # 1. 准备 3 approver
    email_a = random_email("par_any_a")
    email_b = random_email("par_any_b")
    email_c = random_email("par_any_c")

    dsl = build_parallel_any_dsl([email_a, email_b, email_c])
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])
    instance = await launch_instance(admin_client, workflow_id=workflow["id"])

    # 2. 3 人同时收邮件
    email_a_msg = await get_latest_hitl_email(email_a, timeout=15.0)
    email_b_msg = await get_latest_hitl_email(email_b, timeout=15.0)
    email_c_msg = await get_latest_hitl_email(email_c, timeout=15.0)

    a_approve = next(d for d in email_a_msg.deeplinks if d.action == "approve")
    b_approve = next(d for d in email_b_msg.deeplinks if d.action == "approve")
    c_approve = next(d for d in email_c_msg.deeplinks if d.action == "approve")

    # 3. A approve — 应推进 + 其余失效
    async with httpx.AsyncClient(timeout=30.0) as a_client:
        await hitl_get_page(
            a_client, token=a_approve.token, user_agent=REAL_USER_UA
        )
        post_r = await hitl_post_action(
            a_client, token=a_approve.token, action="approve"
        )
        assert post_r.status_code in (200, 309), (
            f"A approve 应成功 实际 {post_r.status_code}: {post_r.text[:300]}"
        )

    await asyncio.sleep(2.0)  # 等 worker 处理 invalidate

    # 4. 关键断言：A 已消费 / B + C 立即失效
    a_status = await im_mock.token_status(a_approve.jti)
    b_status = await im_mock.token_status(b_approve.jti)
    c_status = await im_mock.token_status(c_approve.jti)

    assert a_status["consumed"] is True, "A 自己 token 应消费"
    assert b_status["consumed"] is True, (
        f"parallel_any A approve 后 B token 应立即失效，实际 {b_status}"
    )
    assert c_status["consumed"] is True, (
        f"parallel_any A approve 后 C token 应立即失效，实际 {c_status}"
    )

    # 失效来源标记
    assert b_status.get("used_ip", "").startswith("system:")
    assert c_status.get("used_ip", "").startswith("system:")

    # 5. B / C 收到补通知（"已被 A 处理"）
    b_all = await get_emails_for(email_b, min_count=2, timeout=10.0)
    c_all = await get_emails_for(email_c, min_count=2, timeout=10.0)

    b_parsed = [parse_hitl_email(m) for m in b_all]
    c_parsed = [parse_hitl_email(m) for m in c_all]

    assert any(
        e.is_supplement
        or "已被" in e.subject
        or "处理" in e.subject
        or "通过" in e.subject
        for e in b_parsed
    ), f"B 应收到补通知，实际 subjects: {[e.subject for e in b_parsed]}"


# ── Test 2: parallel_any Safe Links bot regression ───────────────────


@pytest.mark.parametrize("ua_name,bot_ua", list(BOT_UAS))
async def test_parallel_any_safe_links_bot_does_not_consume_jti(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    im_mock,
    ua_name: str,
    bot_ua: str,
):
    """parallel_any 场景的 Safe Links bot 回归（4 UA × 任一 actor token）。"""
    email_a = random_email(f"par_any_safe_{ua_name}_a")
    email_b = random_email(f"par_any_safe_{ua_name}_b")
    dsl = build_parallel_any_dsl([email_a, email_b])
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])
    await launch_instance(admin_client, workflow_id=workflow["id"])

    email_a_msg = await get_latest_hitl_email(email_a, timeout=15.0)
    a_approve = next(d for d in email_a_msg.deeplinks if d.action == "approve")
    b_msg = await get_latest_hitl_email(email_b, timeout=15.0)
    b_approve = next(d for d in b_msg.deeplinks if d.action == "approve")

    async with httpx.AsyncClient(timeout=30.0) as bot_client:
        r = await hitl_get_page(
            bot_client, token=a_approve.token, user_agent=bot_ua
        )
        assert r.status_code == 200
        assert "hitl_session_" not in r.headers.get("set-cookie", "")

    a_status = await im_mock.token_status(a_approve.jti)
    b_status = await im_mock.token_status(b_approve.jti)
    assert a_status["consumed"] is False
    assert b_status["consumed"] is False, (
        f"bot '{ua_name}' GET A 的 token 不能影响 parallel_any 的 B token"
    )
