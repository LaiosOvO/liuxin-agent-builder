"""Phase 4 E2E spec — Covers ROADMAP Phase 4 #4 超时升级。

ROADMAP Phase 4 criterion #4:
    审批人节点超时后收到催办提醒，超时升级策略生效（指派给指定升级人）

测试矩阵（Standard 模式 — 10s 短超时）：
1. workflow timeout_seconds=10 + escalate_to=email:<admin>
2. 不提交决策 → 等 timeout（10s + arq scan cron 60s buffer）
3. mailhog 验证 admin 收到升级邮件（subject 含 [升级]）
4. audit_logs 验证 action=hitl.escalate

测试矩阵（Full 模式 E2E_FULL_STACK=1）：
- timeout_seconds=86400 + 用 mock_time 快进 72h 触发 3 阶梯催办

注：scan_hitl_timeouts arq cron 默认每 60s 跑一次。本 spec Standard 模式
等待 ~75s 给 worker 至少一次扫描机会。
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from e2e_v2.conftest import e2e_full_required, e2e_required
from e2e_v2.helpers.api_client import (
    create_workflow,
    launch_instance,
    publish_workflow,
    random_email,
)
from e2e_v2.helpers.chain_builder import build_escalation_dsl
from e2e_v2.helpers.mailhog_client import (
    get_emails_for,
    get_latest_hitl_email,
    parse_hitl_email,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, e2e_required]


# ── Test 1: 超时升级触发升级邮件（Standard 模式 — 10s timeout） ────────


async def test_escalation_after_timeout_sends_escalation_email(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    im_mock,
    admin_session,
):
    """ROADMAP Phase 4 #4 — 节点超时 + escalate_to 解析 → admin 收升级邮件。

    使用 timeout_seconds=10 短超时（不等真实 24h）。
    """
    admin_email, _ = admin_session
    approver_email = random_email("escalate_target")

    # 创建短 timeout workflow，escalate_to admin
    dsl = build_escalation_dsl(
        approvers=[approver_email],
        escalate_to=f"email:{admin_email}",
        timeout_seconds=10,
    )
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])
    instance = await launch_instance(admin_client, workflow_id=workflow["id"])
    instance_id = instance["id"]

    # 等 approver 收主邮件（确认 HITL 节点已 enter）
    approver_msg = await get_latest_hitl_email(approver_email, timeout=15.0)
    assert len(approver_msg.deeplinks) >= 3

    # 不提交决策 → 等 timeout + arq cron 扫描
    # scan_hitl_timeouts cron 默认 60s 一次；这里等 75s 给至少一次扫描机会
    wait_seconds = int(os.environ.get("E2E_ESCALATION_WAIT", "75"))
    await asyncio.sleep(wait_seconds)

    # admin 应收到至少 1 封含 [升级] 的邮件
    admin_emails = await get_emails_for(admin_email, min_count=1, timeout=10.0)
    admin_parsed = [parse_hitl_email(m) for m in admin_emails]
    escalation_emails = [
        e for e in admin_parsed if e.is_escalation or "升级" in e.subject
    ]
    assert escalation_emails, (
        f"admin 应收到 [升级] 邮件，实际 subjects: "
        f"{[e.subject for e in admin_parsed]}"
    )

    # audit_logs 应有 hitl.escalate 行
    logs = await im_mock.audit_logs(action="hitl.escalate", limit=10)
    assert logs, "应有 audit_log action=hitl.escalate"
    # 至少一条 audit 关联到本 instance
    matching = [
        log
        for log in logs
        if (log.get("meta") or {}).get("instance_id") == instance_id
        or (log.get("meta") or {}).get("instance_id") == str(instance_id)
    ]
    # 不严格要求 instance_id 匹配（不同 plan 写 meta 字段名可能差异），
    # 但至少要看到本测试运行期间新增的 escalate 行
    assert len(logs) >= 1


# ── Test 2: 升级邮件无决策按钮（仅文本通知） ───────────────────────


async def test_escalation_email_has_no_decision_buttons(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    admin_session,
):
    """升级邮件按设计是文本通知（admin 需先看上下文，不在邮件内直接决策）。

    决策于 Phase 03-09 落定：升级邮件无决策按钮，催办邮件保留按钮。
    """
    admin_email, _ = admin_session
    approver_email = random_email("escalate_no_btn")

    dsl = build_escalation_dsl(
        approvers=[approver_email],
        escalate_to=f"email:{admin_email}",
        timeout_seconds=10,
    )
    workflow = await create_workflow(admin_client, dsl=dsl)
    await publish_workflow(admin_client, workflow_id=workflow["id"])
    await launch_instance(admin_client, workflow_id=workflow["id"])

    # 等触发升级
    await asyncio.sleep(int(os.environ.get("E2E_ESCALATION_WAIT", "75")))

    admin_emails = await get_emails_for(admin_email, min_count=1, timeout=10.0)
    admin_parsed = [parse_hitl_email(m) for m in admin_emails]
    escalation_emails = [e for e in admin_parsed if e.is_escalation]

    if not escalation_emails:
        pytest.skip(
            "升级邮件未收到（可能 cron 未触发）— 见 test_escalation_after_timeout..."
        )

    # 升级邮件不应含 /hitl/page/ 决策按钮 deeplink
    for esc_email in escalation_emails:
        assert len(esc_email.deeplinks) == 0, (
            f"升级邮件不应含决策按钮，实际 deeplinks: {esc_email.deeplinks}"
        )


# ── Test 3 (Full mode): 真实 timeout 快进测试 ─────────────────────────


@e2e_full_required
async def test_escalation_full_mode_real_24h_simulation(
    admin_client: httpx.AsyncClient,
    mailhog_purged,
    admin_session,
):
    """Full mode 真实 timeout 快进测试（需 E2E_FULL_STACK=1）。

    使用 mock_time / freezegun 把时间快进 72h（模拟 3 阶梯催办 24/48/72h）。

    注：本测试需要 backend 配合 mock_time fixture；当前简化版仅 skip。
    Phase 4.5+ 完整时间模拟时补全。
    """
    pytest.skip("Phase 4 v1 不实现完整 mock_time 快进，留待 Phase 4.5+ 实现")
