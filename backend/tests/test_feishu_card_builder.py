"""FeishuCardBuilder 单元测试（Plan 04-06 Task 1）。

测试 build_feishu_hitl_card / build_feishu_processed_card / build_feishu_supplement_text
3 个纯函数 — 无外部依赖（不引入 lark-oapi SDK）。

测试覆盖（≥ 6 用例 + 边界）：
1. 标准 3 deeplinks → 3 buttons in action element
2. approve 按钮 type="primary"（蓝色）
3. reject 按钮 type="danger"（红色）
4. return 按钮 type="default"
5. 中文标签映射正确（同意 / 退回 / 拒绝）
6. multi_url 4 URL 字段全填（防桌面端降级 — reading doc §5.3）
7. header.title 含流程标题 + 待办前缀
8. fields 双列含节点 / 申请人 / 审批人 / 截止时间
9. build_feishu_processed_card 移除 action 块
10. build_feishu_processed_card 追加 note 角标含处理人
11. build_feishu_processed_card 不修改入参（immutability）
12. build_feishu_supplement_text 包含动作中文

CLAUDE.md 2.2 单元测试：纯 Python，无 DB / Redis / SDK 依赖。
"""
from __future__ import annotations

import pytest

from app.agent_builder.notification.cards.feishu_card import (
    _ACTION_COLOR_MAP,
    _ACTION_LABEL_MAP,
    build_feishu_hitl_card,
    build_feishu_processed_card,
    build_feishu_supplement_text,
)


# ── Test fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def standard_deeplinks() -> list[dict[str, str]]:
    """标准 3 按钮深链（approve / return / reject）— 与 HITL Phase 3 一致。"""
    return [
        {"action": "approve", "url": "https://app.example.com/hitl/page/jti-approve"},
        {"action": "return", "url": "https://app.example.com/hitl/page/jti-return"},
        {"action": "reject", "url": "https://app.example.com/hitl/page/jti-reject"},
    ]


@pytest.fixture
def hitl_card_kwargs(standard_deeplinks: list[dict[str, str]]) -> dict:
    """标准 build_feishu_hitl_card kwargs，4 节点字段 + deeplinks。"""
    return {
        "flow_title": "员工入职流程",
        "node_title": "HR 审批",
        "applicant_name": "张三",
        "actor_name": "李四",
        "deadline_at": "2026-05-18T18:00:00Z",
        "description": "请确认入职信息无误后审批。",
        "deeplinks": standard_deeplinks,
    }


# ── 按钮数量 + 颜色 ───────────────────────────────────────────────────────────


def test_build_card_contains_3_buttons_for_3_deeplinks(hitl_card_kwargs: dict):
    """3 个 deeplinks 应该生成 3 个按钮（action 元素中）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    action_elements = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(action_elements) == 1
    assert len(action_elements[0]["actions"]) == 3


def test_build_card_approve_button_is_primary_color(hitl_card_kwargs: dict):
    """approve 按钮颜色 = primary（蓝色，强调）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    approve_button = next(
        b for b in actions if b["text"]["content"] == "同意"
    )
    assert approve_button["type"] == "primary"


def test_build_card_reject_button_is_danger_color(hitl_card_kwargs: dict):
    """reject 按钮颜色 = danger（红色，警示）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    reject_button = next(
        b for b in actions if b["text"]["content"] == "拒绝"
    )
    assert reject_button["type"] == "danger"


def test_build_card_return_button_is_default_color(hitl_card_kwargs: dict):
    """return 按钮颜色 = default（浅灰）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    return_button = next(
        b for b in actions if b["text"]["content"] == "退回"
    )
    assert return_button["type"] == "default"


# ── 中文标签 + multi_url 结构 ────────────────────────────────────────────────


def test_build_card_chinese_labels_correct():
    """approve/return/reject 应翻译为同意/退回/拒绝。"""
    assert _ACTION_LABEL_MAP["approve"] == "同意"
    assert _ACTION_LABEL_MAP["return"] == "退回"
    assert _ACTION_LABEL_MAP["reject"] == "拒绝"
    assert _ACTION_LABEL_MAP["detail"] == "查看详情"


def test_build_card_unknown_action_keeps_action_name():
    """未映射 action 直接用原名（防 KeyError，向后兼容自定义 action）。"""
    deeplinks = [{"action": "custom_xyz", "url": "https://x.com"}]
    card = build_feishu_hitl_card(
        flow_title="t", node_title="n", applicant_name="a",
        actor_name="b", deadline_at="d", description="x",
        deeplinks=deeplinks,
    )
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert actions[0]["text"]["content"] == "custom_xyz"
    # 未知 action 颜色降级为 default
    assert actions[0]["type"] == "default"


def test_build_card_multi_url_has_all_4_url_fields(hitl_card_kwargs: dict):
    """multi_url 必须 url/pc_url/android_url/ios_url 4 字段全填（防降级）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    for button in actions:
        assert "multi_url" in button
        multi_url = button["multi_url"]
        assert set(multi_url.keys()) == {"url", "pc_url", "android_url", "ios_url"}
        # 4 个 URL 应该是同一个值
        assert len({multi_url[k] for k in multi_url}) == 1


def test_build_card_button_preserves_deeplink_url(hitl_card_kwargs: dict):
    """按钮 url 应该等于 deeplinks 传入的 url（不被改造）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    approve_url = "https://app.example.com/hitl/page/jti-approve"
    approve_button = next(
        b for b in actions if b["multi_url"]["url"] == approve_url
    )
    assert approve_button["multi_url"]["pc_url"] == approve_url
    assert approve_button["multi_url"]["android_url"] == approve_url
    assert approve_button["multi_url"]["ios_url"] == approve_url


# ── 卡片头部 + 字段块 ────────────────────────────────────────────────────────


def test_build_card_header_contains_flow_title(hitl_card_kwargs: dict):
    """header.title 应该含流程名 + "审批待办：" 前缀。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    title_content = card["header"]["title"]["content"]
    assert "员工入职流程" in title_content
    assert "审批待办" in title_content


def test_build_card_header_template_is_blue(hitl_card_kwargs: dict):
    """新卡片 header template 是蓝色（与决策后 grey 区分）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    assert card["header"]["template"] == "blue"


def test_build_card_fields_contain_4_node_details(hitl_card_kwargs: dict):
    """div.fields 包含 节点 / 申请人 / 审批人 / 截止时间 4 字段。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    fields_element = next(
        e for e in card["elements"]
        if e.get("tag") == "div" and "fields" in e
    )
    fields = fields_element["fields"]
    assert len(fields) == 4
    contents = [f["text"]["content"] for f in fields]
    # 4 个字段都应该是 lark_md 双列
    assert all(f["is_short"] is True for f in fields)
    assert all(f["text"]["tag"] == "lark_md" for f in fields)
    # 字段值嵌入
    assert any("HR 审批" in c for c in contents)
    assert any("张三" in c for c in contents)
    assert any("李四" in c for c in contents)
    assert any("2026-05-18" in c for c in contents)


def test_build_card_description_in_separate_div_block(hitl_card_kwargs: dict):
    """description 在独立 div 块（不与 fields 同 div）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    desc_div = next(
        e for e in card["elements"]
        if e.get("tag") == "div" and "text" in e
    )
    assert "请确认入职信息无误后审批" in desc_div["text"]["content"]


def test_build_card_has_hr_separator(hitl_card_kwargs: dict):
    """卡片应有 hr 分隔线（在 action 之前）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    hr_elements = [e for e in card["elements"] if e.get("tag") == "hr"]
    assert len(hr_elements) == 1


def test_build_card_wide_screen_mode_enabled(hitl_card_kwargs: dict):
    """config.wide_screen_mode = True（PC 端宽屏体验更好）。"""
    card = build_feishu_hitl_card(**hitl_card_kwargs)
    assert card["config"]["wide_screen_mode"] is True


# ── tuple deeplinks 支持（HitlCardPayload.deeplinks 是 tuple）──────────────


def test_build_card_accepts_tuple_deeplinks(hitl_card_kwargs: dict):
    """deeplinks 是 tuple 时也能正常生成按钮（HitlCardPayload 用 tuple）。"""
    kwargs = {**hitl_card_kwargs}
    kwargs["deeplinks"] = tuple(kwargs["deeplinks"])
    card = build_feishu_hitl_card(**kwargs)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert len(actions) == 3


def test_build_card_empty_deeplinks_produces_empty_actions():
    """空 deeplinks → action 元素的 actions 数组为空（无按钮）。"""
    card = build_feishu_hitl_card(
        flow_title="t", node_title="n", applicant_name="a",
        actor_name="b", deadline_at="d", description="x",
        deeplinks=[],
    )
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert actions == []


# ── build_feishu_processed_card ──────────────────────────────────────────────


def test_processed_card_removes_action_block(hitl_card_kwargs: dict):
    """决策后的卡片应该不含 action 元素（按钮全部移除）。"""
    original = build_feishu_hitl_card(**hitl_card_kwargs)
    processed = build_feishu_processed_card(
        original_card=original, processed_by="李四"
    )
    action_elements = [e for e in processed["elements"] if e.get("tag") == "action"]
    assert action_elements == []


def test_processed_card_appends_note_with_processor_name(hitl_card_kwargs: dict):
    """决策后追加 note 角标，含处理人姓名。"""
    original = build_feishu_hitl_card(**hitl_card_kwargs)
    processed = build_feishu_processed_card(
        original_card=original, processed_by="李四"
    )
    note_elements = [e for e in processed["elements"] if e.get("tag") == "note"]
    assert len(note_elements) == 1
    note_content = note_elements[0]["elements"][0]["content"]
    assert "李四" in note_content
    assert "✓" in note_content


def test_processed_card_header_template_is_grey(hitl_card_kwargs: dict):
    """决策后 header.template = grey（视觉示意"已处理"）。"""
    original = build_feishu_hitl_card(**hitl_card_kwargs)
    processed = build_feishu_processed_card(
        original_card=original, processed_by="李四"
    )
    assert processed["header"]["template"] == "grey"


def test_processed_card_preserves_original_title(hitl_card_kwargs: dict):
    """决策后 header.title 不变（保留流程标题，便于追溯）。"""
    original = build_feishu_hitl_card(**hitl_card_kwargs)
    processed = build_feishu_processed_card(
        original_card=original, processed_by="李四"
    )
    assert processed["header"]["title"] == original["header"]["title"]


def test_processed_card_does_not_mutate_original(hitl_card_kwargs: dict):
    """CLAUDE.md immutability — build_feishu_processed_card 不修改入参。"""
    original = build_feishu_hitl_card(**hitl_card_kwargs)
    # 拷贝深层状态做对比
    import copy
    original_snapshot = copy.deepcopy(original)
    build_feishu_processed_card(original_card=original, processed_by="李四")
    # 原 dict 完全不变
    assert original == original_snapshot
    # 关键：原 dict 仍含 action 块（未被原地移除）
    action_elements = [e for e in original["elements"] if e.get("tag") == "action"]
    assert len(action_elements) == 1


def test_processed_card_preserves_description_div(hitl_card_kwargs: dict):
    """决策后仍保留 description div 和 fields 块（仅移除 action）。"""
    original = build_feishu_hitl_card(**hitl_card_kwargs)
    processed = build_feishu_processed_card(
        original_card=original, processed_by="李四"
    )
    div_elements = [e for e in processed["elements"] if e.get("tag") == "div"]
    # 仍有 2 个 div（fields + description）
    assert len(div_elements) == 2


# ── build_feishu_supplement_text ──────────────────────────────────────────────


def test_supplement_text_includes_processor_and_action():
    """补充文本应该包含处理人 + 中文动作。"""
    text = build_feishu_supplement_text(who_processed="张三", action="approve")
    assert "张三" in text
    assert "同意" in text


def test_supplement_text_for_reject_includes_chinese_label():
    """reject 动作 → 文本含"拒绝"。"""
    text = build_feishu_supplement_text(who_processed="李四", action="reject")
    assert "李四" in text
    assert "拒绝" in text


def test_supplement_text_length_under_200():
    """补充文本 ≤ 200 字符（飞书文本消息建议）。"""
    text = build_feishu_supplement_text(who_processed="张三", action="approve")
    assert len(text) < 200


# ── 颜色映射常量校验 ─────────────────────────────────────────────────────────


def test_action_color_map_contains_4_standard_actions():
    """_ACTION_COLOR_MAP 含 4 标准 action（approve/return/reject/detail）+ submit。"""
    standard_actions = {"approve", "return", "reject", "detail", "submit"}
    assert standard_actions.issubset(_ACTION_COLOR_MAP.keys())
