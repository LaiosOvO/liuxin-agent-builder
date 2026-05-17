"""MattermostCardBuilder + build_mattermost_attachment 单元测试（Plan 04-09 NOTI-06）。

测试覆盖（≥ 4 用例）：
1. test_build_attachment_4_actions：4 个 deeplink → 4 个 action
2. test_build_attachment_approve_style_good：approve action → style=good
3. test_build_attachment_reject_style_danger：reject action → style=danger
4. test_build_attachment_return_and_detail_default_style：return/detail → default
5. test_attachment_markdown_text_contains_all_fields
6. test_build_hitl_card_returns_message_and_props
7. test_card_builder_satisfies_card_builder_protocol

CLAUDE.md 2.2 单元测试：纯 Python。
"""
from __future__ import annotations

import pytest

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.mattermost_card import (
    MattermostCardBuilder,
    build_mattermost_attachment,
)
from app.agent_builder.notification.providers.base import PROVIDER_MATTERMOST


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_payload() -> HitlCardPayload:
    """构造典型 HITL payload — 含 4 个标准 action deeplink。"""
    return HitlCardPayload(
        flow_title="员工入职流程",
        node_title="HR 审批",
        applicant_name="张三",
        actor_name="李四",
        deadline_at="2026-05-18T18:00:00Z",
        description="请审批该员工入职申请",
        deeplinks=(
            {"action": "approve", "url": "https://example.com/hitl/page/jwt1?op=approve"},
            {"action": "return", "url": "https://example.com/hitl/page/jwt1?op=return"},
            {"action": "reject", "url": "https://example.com/hitl/page/jwt1?op=reject"},
            {"action": "detail", "url": "https://example.com/hitl/page/jwt1"},
        ),
    )


# ── build_mattermost_attachment ─────────────────────────────────────────────


def test_build_attachment_4_actions(sample_payload):
    """4 个 deeplink → 4 个 action 元素。"""
    attachment = build_mattermost_attachment(sample_payload)
    assert "actions" in attachment
    actions = attachment["actions"]
    assert len(actions) == 4
    ids = [a["id"] for a in actions]
    assert ids == ["approve", "return", "reject", "detail"]
    # 各 action 含必需字段
    for a in actions:
        assert "name" in a
        assert "integration" in a
        assert "url" in a["integration"]
        assert "context" in a["integration"]
        assert "style" in a


def test_build_attachment_approve_style_good(sample_payload):
    """approve action → style='good'。"""
    attachment = build_mattermost_attachment(sample_payload)
    approve = next(a for a in attachment["actions"] if a["id"] == "approve")
    assert approve["style"] == "good"


def test_build_attachment_reject_style_danger(sample_payload):
    """reject action → style='danger'。"""
    attachment = build_mattermost_attachment(sample_payload)
    reject = next(a for a in attachment["actions"] if a["id"] == "reject")
    assert reject["style"] == "danger"


def test_build_attachment_return_and_detail_default_style(sample_payload):
    """return / detail action → style='default'。"""
    attachment = build_mattermost_attachment(sample_payload)
    for action_id in ["return", "detail"]:
        a = next(a for a in attachment["actions"] if a["id"] == action_id)
        assert a["style"] == "default", f"{action_id} 应为 default"


def test_attachment_markdown_text_contains_all_fields(sample_payload):
    """attachment.text 含流程名 + 节点 + 申请人 + 审批人 + 截止 + 详情。"""
    attachment = build_mattermost_attachment(sample_payload)
    text = attachment["text"]
    assert "员工入职流程" in text
    assert "HR 审批" in text
    assert "张三" in text
    assert "李四" in text
    assert "2026-05-18T18:00:00Z" in text
    assert "请审批该员工入职申请" in text
    # fallback 字段也含流程名
    assert "员工入职流程" in attachment["fallback"]
    # color 为蓝
    assert attachment["color"] == "#2196F3"


def test_build_hitl_card_returns_message_and_props(sample_payload):
    """build_hitl_card 返回 dict 含 message + props.attachments。"""
    builder = MattermostCardBuilder()
    card = builder.build_hitl_card(sample_payload)
    assert "message" in card
    assert "props" in card
    assert "attachments" in card["props"]
    assert len(card["props"]["attachments"]) == 1
    assert "员工入职流程" in card["message"]


def test_card_builder_satisfies_card_builder_protocol():
    """MattermostCardBuilder 鸭子类型属性正确。"""
    builder = MattermostCardBuilder()
    assert builder.provider_name == PROVIDER_MATTERMOST
    assert callable(getattr(builder, "build_hitl_card", None))
    assert callable(getattr(builder, "build_supplement_text", None))


def test_build_supplement_text_format():
    """build_supplement_text 含 '已被 X 拒绝' 类格式。"""
    builder = MattermostCardBuilder()
    text = builder.build_supplement_text(who_processed="张三", action="reject")
    assert "张三" in text
    assert "拒绝" in text
