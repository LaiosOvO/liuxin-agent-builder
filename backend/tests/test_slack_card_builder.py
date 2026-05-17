"""SlackCardBuilder + build_slack_blocks 单元测试（Plan 04-09 NOTI-05）。

测试覆盖（≥ 4 用例）：
1. test_build_blocks_4_buttons：4 个 deeplink → 4 个 button
2. test_build_blocks_approve_primary_style：approve action → style=primary
3. test_build_blocks_reject_danger_style：reject action → style=danger
4. test_build_blocks_no_style_for_return_and_detail：return / detail 不带 style
5. test_card_builder_satisfies_card_builder_protocol：鸭子类型
6. test_build_supplement_text_format：补充文本格式
7. test_block_kit_structure_header_section_actions：header/section/actions 顺序

CLAUDE.md 2.2 单元测试：纯 Python，无 HTTP / DB 依赖。
"""
from __future__ import annotations

import pytest

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.slack_card import (
    SlackCardBuilder,
    build_slack_blocks,
)
from app.agent_builder.notification.providers.base import PROVIDER_SLACK


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


# ── build_slack_blocks ───────────────────────────────────────────────────────


def test_build_blocks_4_buttons(sample_payload):
    """4 个 deeplink → 4 个 button element。"""
    blocks = build_slack_blocks(sample_payload)
    # 最后一个 block 应为 actions
    assert blocks[-1]["type"] == "actions"
    elements = blocks[-1]["elements"]
    assert len(elements) == 4
    actions = [e["action_id"] for e in elements]
    assert actions == ["hitl_approve", "hitl_return", "hitl_reject", "hitl_detail"]


def test_build_blocks_approve_primary_style(sample_payload):
    """approve action 的 button 含 style=primary。"""
    blocks = build_slack_blocks(sample_payload)
    actions_block = blocks[-1]
    approve_btn = next(
        e for e in actions_block["elements"] if e["action_id"] == "hitl_approve"
    )
    assert approve_btn["style"] == "primary"


def test_build_blocks_reject_danger_style(sample_payload):
    """reject action 的 button 含 style=danger。"""
    blocks = build_slack_blocks(sample_payload)
    actions_block = blocks[-1]
    reject_btn = next(
        e for e in actions_block["elements"] if e["action_id"] == "hitl_reject"
    )
    assert reject_btn["style"] == "danger"


def test_build_blocks_no_style_for_return_and_detail(sample_payload):
    """return / detail 不带 style 字段（默认按钮样式）。"""
    blocks = build_slack_blocks(sample_payload)
    actions_block = blocks[-1]
    for action_id in ["hitl_return", "hitl_detail"]:
        btn = next(
            e for e in actions_block["elements"] if e["action_id"] == action_id
        )
        assert "style" not in btn, f"{action_id} 不应有 style 字段"


def test_block_kit_structure_header_section_actions(sample_payload):
    """blocks 结构：header → section(fields) → section(description) → divider → actions。"""
    blocks = build_slack_blocks(sample_payload)
    assert blocks[0]["type"] == "header"
    assert "审批待办" in blocks[0]["text"]["text"]
    assert blocks[1]["type"] == "section"
    assert "fields" in blocks[1]
    assert len(blocks[1]["fields"]) == 4  # 节点/申请人/审批人/截止
    assert blocks[2]["type"] == "section"
    assert "详情" in blocks[2]["text"]["text"]
    assert blocks[3]["type"] == "divider"
    assert blocks[4]["type"] == "actions"


# ── SlackCardBuilder ────────────────────────────────────────────────────────


def test_card_builder_satisfies_card_builder_protocol():
    """SlackCardBuilder 实现 CardBuilder 鸭子类型必需方法（CardBuilder 非 runtime_checkable，
    通过 attribute 与 callable 检查）。"""
    builder = SlackCardBuilder()
    assert builder.provider_name == PROVIDER_SLACK
    assert callable(getattr(builder, "build_hitl_card", None))
    assert callable(getattr(builder, "build_supplement_text", None))


def test_build_hitl_card_returns_blocks_and_text(sample_payload):
    """build_hitl_card 返回 dict 含 blocks + text fallback。"""
    builder = SlackCardBuilder()
    card = builder.build_hitl_card(sample_payload)
    assert "blocks" in card
    assert "text" in card
    assert isinstance(card["blocks"], list)
    assert "员工入职流程" in card["text"]


def test_build_supplement_text_format():
    """build_supplement_text 含 '已被 X 同意' 类格式。"""
    builder = SlackCardBuilder()
    text = builder.build_supplement_text(who_processed="王五", action="approve")
    assert "王五" in text
    assert "同意" in text
