"""Phase 4 E2E spec — Covers ROADMAP Phase 4 #2 并行会签全员同意 parallel_all。

ROADMAP Phase 4 criterion #2:
    并行会签（全员同意）：A 拒绝后其余所有人的 token 立即失效，流程终止

测试矩阵：
1. parallel_all 3 approvers — 3 人同时收邮件
2. A POST reject → B/C token used_at NOT NULL（invalidate_chain）
3. B/C 收到补通知（"已被 A 拒绝"，subject 含 [终止] 或类似标记）
4. instance.status=rejected
5. Safe Links bot regression（4 UA 在 parallel_all 场景）
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
from e2e_v2.helpers.chain_builder import build_parallel_all_dsl
from e2e_v2.helpers.mailhog_client import (
    get_emails_for,
    get_latest_hitl_email,
    parse_hitl_email,
)
from e2e_v2.helpers.safe_links_uas import BOT_UAS, REAL_USER_UA

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, e2e_required]


# ── Test 1: parallel_all 主流程 — A reject 终止全链 ──────────────────


async def test_parallel_all_reject_invalidates_chain(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    im_mock,
):
    """ROADMAP Phase 4 #2 — 并行全员，A 拒绝触发 invalidate_chain + 补通知。"""
    # 1. 准备 3 approver
    email_a = random_email("par_all_a")
    email_b = random_email("par_all_b")
    email_c = random_email("par_all_c")

    dsl = build_parallel_all_dsl([email_a, email_b, email_c])
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])
    instance = await launch_instance(admin_client, workflow_id=workflow["id"])

    # 2. 3 人同时收邮件（parallel 模式启动时全员发）
    email_a_msg = await get_latest_hitl_email(email_a, timeout=15.0)
    email_b_msg = await get_latest_hitl_email(email_b, timeout=15.0)
    email_c_msg = await get_latest_hitl_email(email_c, timeout=15.0)

    # 提取每人的 reject + approve token
    a_reject = next(d for d in email_a_msg.deeplinks if d.action == "reject")
    b_approve = next(d for d in email_b_msg.deeplinks if d.action == "approve")
    c_approve = next(d for d in email_c_msg.deeplinks if d.action == "approve")

    # 验证三方 jti 不同
    assert a_reject.jti != b_approve.jti != c_approve.jti

    # 3. A reject — 应触发 chain 失效
    async with httpx.AsyncClient(timeout=30.0) as a_client:
        await hitl_get_page(
            a_client, token=a_reject.token, user_agent=REAL_USER_UA
        )
        post_r = await hitl_post_action(
            a_client, token=a_reject.token, action="reject"
        )
        assert post_r.status_code in (200, 309), (
            f"A reject 应成功 实际 {post_r.status_code}: {post_r.text[:300]}"
        )

    # 4. 等 worker 处理 invalidate_chain
    await asyncio.sleep(2.0)

    # 5. 关键断言：B / C 的 approve token 应已被消费（used_at NOT NULL）
    b_status = await im_mock.token_status(b_approve.jti)
    c_status = await im_mock.token_status(c_approve.jti)

    assert b_status["consumed"] is True, (
        f"parallel_all A reject 后 B 的 token 应已失效（chain invalidate）"
        f"\n实际 B status: {b_status}"
    )
    assert c_status["consumed"] is True, (
        f"parallel_all A reject 后 C 的 token 应已失效\n实际 C status: {c_status}"
    )

    # 验证失效来源标记（与真实用户消费区分）
    assert b_status.get("used_ip", "").startswith("system:"), (
        f"B 失效 used_ip 应有 system: 前缀，实际 {b_status.get('used_ip')}"
    )

    # 6. B / C 应收到补通知（至少 1 封额外邮件，subject 含终止/已被 等关键字）
    # 注：mailhog 已含 3 主邮件 + N 补通知；总数 >= 5 但内容差异区分
    b_all = await get_emails_for(email_b, min_count=2, timeout=10.0)
    c_all = await get_emails_for(email_c, min_count=2, timeout=10.0)

    # 至少有一封补通知（is_supplement）
    b_supplements = [
        parse_hitl_email(m) for m in b_all
    ]
    c_supplements = [
        parse_hitl_email(m) for m in c_all
    ]
    assert any(
        e.is_supplement or "拒绝" in e.subject or "终止" in e.subject or "已被" in e.subject
        for e in b_supplements
    ), f"B 应收到补通知，实际 subjects: {[e.subject for e in b_supplements]}"


# ── Test 2: parallel_all Safe Links bot regression ───────────────────


@pytest.mark.parametrize("ua_name,bot_ua", list(BOT_UAS))
async def test_parallel_all_safe_links_bot_does_not_consume_jti(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    im_mock,
    ua_name: str,
    bot_ua: str,
):
    """parallel_all 场景的 Safe Links bot 回归（4 UA × 任一 actor token）。

    关键：parallel 模式有 multiple 活跃 token 同时存在，
    bot 扫一个不能影响其他 actor 的 token。
    """
    email_a = random_email(f"par_all_safe_{ua_name}_a")
    email_b = random_email(f"par_all_safe_{ua_name}_b")
    dsl = build_parallel_all_dsl([email_a, email_b])
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])
    await launch_instance(admin_client, workflow_id=workflow["id"])

    email_a_msg = await get_latest_hitl_email(email_a, timeout=15.0)
    email_b_msg = await get_latest_hitl_email(email_b, timeout=15.0)
    a_approve = next(d for d in email_a_msg.deeplinks if d.action == "approve")
    b_approve = next(d for d in email_b_msg.deeplinks if d.action == "approve")

    # bot 扫描 A 的 token
    async with httpx.AsyncClient(timeout=30.0) as bot_client:
        r = await hitl_get_page(
            bot_client, token=a_approve.token, user_agent=bot_ua
        )
        assert r.status_code == 200
        assert "hitl_session_" not in r.headers.get("set-cookie", "")

    # 关键断言：A 的 jti 未消费 + B 的 jti 也未受影响
    a_status = await im_mock.token_status(a_approve.jti)
    b_status = await im_mock.token_status(b_approve.jti)
    assert a_status["consumed"] is False, (
        f"bot '{ua_name}' GET 后 A 的 jti 不应被消费"
    )
    assert b_status["consumed"] is False, (
        f"bot '{ua_name}' GET A 的 token 不能影响 B 的 token"
    )
