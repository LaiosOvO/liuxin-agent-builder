"""钉钉 ActionCard 构造器单元测试（Plan 04-08 Task 1）。

测试覆盖（≥ 6 用例）：
1. test_build_card_contains_action_card_msgtype: msgtype="action_card" 正确
2. test_build_card_btn_orientation_horizontal_string_zero: btn_orientation="0"
3. test_build_card_markdown_contains_all_fields: markdown 含 flow_title/node_title/...
4. test_build_card_btn_labels_chinese_for_known_actions: 'approve'→'同意' 等映射
5. test_build_card_with_empty_deeplinks_returns_empty_btn_list: 空 deeplinks 不报错
6. test_build_card_does_not_mutate_payload: immutability 校验
7. test_build_card_unknown_action_uses_raw_label: 未知 action 不抛错
8. test_build_card_3_buttons_for_standard_approval: 3 按钮场景
9. test_supplement_text_uses_chinese_label: 补发文本中文 label
10. test_build_card_title_includes_flow_title: title 字段包含 flow_title

CLAUDE.md 2.2 单元测试：纯 Python，无 DB / Redis / SDK 依赖。
"""
from __future__ import annotations

import pytest

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.dingtalk_card import (
    _ZH_LABELS,
    _zh_label_for,
    build_dingtalk_action_card,
    build_dingtalk_supplement_text,
)


# ── Helper：构造测试 payload ─────────────────────────────────────────────────


def _make_payload(deeplinks: tuple[dict[str, str], ...] = ()) -> HitlCardPayload:
    """生成标准测试 HitlCardPayload。"""
    return HitlCardPayload(
        flow_title="员工入职流程",
        node_title="HR 审批",
        applicant_name="张三",
        actor_name="李四",
        deadline_at="2026-05-18T10:00:00Z",
        description="入职信息已填写完毕，请审批。",
        deeplinks=deeplinks,
    )


def _standard_3_deeplinks() -> tuple[dict[str, str], ...]:
    """标准 3 按钮场景：approve / return / reject。"""
    return (
        {"action": "approve", "url": "https://app.example.com/hitl/page/jti-approve"},
        {"action": "return", "url": "https://app.example.com/hitl/page/jti-return"},
        {"action": "reject", "url": "https://app.example.com/hitl/page/jti-reject"},
    )


# ── msgtype + 结构 ─────────────────────────────────────────────────────────


def test_build_card_contains_action_card_msgtype():
    """msgtype 必须是 'action_card'（钉钉 OAPI 约定，下划线分隔）。"""
    card = build_dingtalk_action_card(_make_payload())
    assert card["msgtype"] == "action_card"
    assert "action_card" in card
    assert isinstance(card["action_card"], dict)


def test_build_card_has_required_action_card_fields():
    """action_card 字段含 title / markdown / btn_orientation / btn_json_list。"""
    card = build_dingtalk_action_card(_make_payload(_standard_3_deeplinks()))
    ac = card["action_card"]
    assert "title" in ac
    assert "markdown" in ac
    assert "btn_orientation" in ac
    assert "btn_json_list" in ac


# ── btn_orientation ─────────────────────────────────────────────────────────


def test_build_card_btn_orientation_horizontal_string_zero():
    """btn_orientation="0" 横排（决策板：PC + 手机最佳兼容）。"""
    card = build_dingtalk_action_card(_make_payload(_standard_3_deeplinks()))
    # 注意：钉钉 OAPI 要求字符串 "0"（不是整数 0）
    assert card["action_card"]["btn_orientation"] == "0"
    assert isinstance(card["action_card"]["btn_orientation"], str)


# ── markdown 内容 ───────────────────────────────────────────────────────────


def test_build_card_markdown_contains_all_fields():
    """markdown 文本必须含 flow_title / node_title / applicant / actor / deadline / description。"""
    payload = _make_payload()
    card = build_dingtalk_action_card(payload)
    md = card["action_card"]["markdown"]
    assert payload.flow_title in md
    assert payload.node_title in md
    assert payload.applicant_name in md
    assert payload.actor_name in md
    assert payload.deadline_at in md
    assert payload.description in md


def test_build_card_markdown_uses_heading_and_bold():
    """markdown 应含 ### 标题 + ** 加粗（钉钉渲染支持）。"""
    card = build_dingtalk_action_card(_make_payload())
    md = card["action_card"]["markdown"]
    assert "### 审批待办" in md
    assert "**节点**" in md
    assert "**申请人**" in md


def test_build_card_title_includes_flow_title():
    """ActionCard.title 字段（顶部大标题）含 flow_title。"""
    payload = _make_payload()
    card = build_dingtalk_action_card(payload)
    assert payload.flow_title in card["action_card"]["title"]


# ── btn_json_list ───────────────────────────────────────────────────────────


def test_build_card_3_buttons_for_standard_approval():
    """标准 3 按钮场景：approve/return/reject 各 1 按钮。"""
    card = build_dingtalk_action_card(_make_payload(_standard_3_deeplinks()))
    btns = card["action_card"]["btn_json_list"]
    assert len(btns) == 3
    # 每个按钮都有 title + action_url（钉钉字段名）
    for btn in btns:
        assert "title" in btn
        assert "action_url" in btn
        assert btn["action_url"].startswith("https://")


def test_build_card_btn_labels_chinese_for_known_actions():
    """已知 action 映射为中文 label（approve→同意 / return→退回 / reject→拒绝）。"""
    card = build_dingtalk_action_card(_make_payload(_standard_3_deeplinks()))
    titles = [b["title"] for b in card["action_card"]["btn_json_list"]]
    assert "同意" in titles
    assert "退回" in titles
    assert "拒绝" in titles


def test_build_card_unknown_action_uses_raw_label():
    """未知 action 不映射，直接用原字符串（不抛错）。"""
    deeplinks = (
        {"action": "custom_xyz", "url": "https://example.com/x"},
    )
    card = build_dingtalk_action_card(_make_payload(deeplinks))
    btns = card["action_card"]["btn_json_list"]
    assert len(btns) == 1
    assert btns[0]["title"] == "custom_xyz"


def test_build_card_with_empty_deeplinks_returns_empty_btn_list():
    """空 deeplinks → btn_json_list=[] 不抛错（钉钉允许）。"""
    card = build_dingtalk_action_card(_make_payload(deeplinks=()))
    assert card["action_card"]["btn_json_list"] == []


def test_build_card_preserves_deeplink_url():
    """action_url 完整保留原 URL（无截断/转义）。"""
    deeplinks = (
        {
            "action": "approve",
            "url": "https://app.example.com/hitl/page/uuid-abc-123?lang=zh-CN",
        },
    )
    card = build_dingtalk_action_card(_make_payload(deeplinks))
    btn = card["action_card"]["btn_json_list"][0]
    assert btn["action_url"] == "https://app.example.com/hitl/page/uuid-abc-123?lang=zh-CN"


# ── immutability ────────────────────────────────────────────────────────────


def test_build_card_does_not_mutate_payload():
    """build_dingtalk_action_card 不修改入参 payload（CLAUDE.md immutability）。"""
    deeplinks = _standard_3_deeplinks()
    payload = _make_payload(deeplinks)
    # 记录调用前快照
    flow_title_before = payload.flow_title
    deeplinks_count_before = len(payload.deeplinks)
    build_dingtalk_action_card(payload)
    # 调用后字段未变
    assert payload.flow_title == flow_title_before
    assert len(payload.deeplinks) == deeplinks_count_before


def test_build_card_returns_new_dict_each_call():
    """连续两次调用返回不同 dict 实例（无单例缓存）。"""
    payload = _make_payload(_standard_3_deeplinks())
    card1 = build_dingtalk_action_card(payload)
    card2 = build_dingtalk_action_card(payload)
    # 内容相等
    assert card1 == card2
    # 但 id 不同（每次都新建）
    assert card1 is not card2
    assert card1["action_card"] is not card2["action_card"]


# ── _zh_label_for helper ────────────────────────────────────────────────────


def test_zh_label_for_known_actions():
    """_zh_label_for 对已知 action 返回中文。"""
    assert _zh_label_for("approve") == "同意"
    assert _zh_label_for("return") == "退回"
    assert _zh_label_for("reject") == "拒绝"
    assert _zh_label_for("detail") == "查看详情"
    assert _zh_label_for("submit") == "提交"


def test_zh_label_for_unknown_action_returns_raw():
    """_zh_label_for 对未知 action 返回原字符串（不抛错）。"""
    assert _zh_label_for("approve_with_comment") == "approve_with_comment"
    assert _zh_label_for("") == ""


def test_zh_labels_contains_4_standard_actions():
    """_ZH_LABELS 含至少 approve/return/reject/detail 4 标准 action。"""
    assert "approve" in _ZH_LABELS
    assert "return" in _ZH_LABELS
    assert "reject" in _ZH_LABELS
    assert "detail" in _ZH_LABELS


# ── supplement text ────────────────────────────────────────────────────────


def test_supplement_text_uses_chinese_label():
    """build_dingtalk_supplement_text 用中文 label 拼接。"""
    text = build_dingtalk_supplement_text(who_processed="王五", action="approve")
    assert "王五" in text
    assert "同意" in text


def test_supplement_text_handles_unknown_action():
    """未知 action 时不抛错（label 退化为原字符串）。"""
    text = build_dingtalk_supplement_text(who_processed="王五", action="custom_x")
    assert "王五" in text
    assert "custom_x" in text


def test_supplement_text_under_200_chars():
    """补发文本长度 ≤ 200（钉钉文本消息建议）。"""
    text = build_dingtalk_supplement_text(who_processed="张三李四王五赵六", action="approve")
    assert len(text) <= 200
