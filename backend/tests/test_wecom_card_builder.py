"""Unit tests — backend/app/agent_builder/notification/cards/wecom_card.py（Plan 04-07）。

测试范围：
- build_wecom_markdown_content（共享内容生成器，含 4 action 链接）
- build_wecom_app_message（envelope: msgtype=markdown, markdown.content=...）
- build_wecom_webhook_markdown（envelope 一致：msgtype=markdown）
- _label_for / 不可识别 action 兜底
- markdown 注入防护（角括号、反引号、方括号转义）
"""
from __future__ import annotations

import pytest

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.wecom_card import (
    WECOM_MSGTYPE_MARKDOWN,
    build_wecom_app_message,
    build_wecom_markdown_content,
    build_wecom_webhook_markdown,
)


def _payload(**overrides) -> HitlCardPayload:
    """构造默认 HitlCardPayload。"""
    base = dict(
        flow_title="员工入职流程",
        node_title="HR 审批",
        applicant_name="张三",
        actor_name="李经理",
        deadline_at="2026-05-18T10:00:00Z",
        description="新员工入职审批，请决策",
        deeplinks=(
            {"action": "approve", "url": "https://example.com/approve/jwt1"},
            {"action": "return", "url": "https://example.com/return/jwt1"},
            {"action": "reject", "url": "https://example.com/reject/jwt1"},
            {"action": "detail", "url": "https://example.com/detail/jwt1"},
        ),
    )
    base.update(overrides)
    return HitlCardPayload(**base)


@pytest.mark.unit
class TestBuildMarkdownContent:
    """build_wecom_markdown_content 共享生成器。"""

    def test_content_includes_flow_title_as_heading(self) -> None:
        content = build_wecom_markdown_content(_payload())
        assert "员工入职流程" in content
        # 必为 markdown 标题（### 或 ## 前缀以满足企微 markdown 子集渲染）
        assert content.lstrip().startswith("###") or content.lstrip().startswith("##")

    def test_content_includes_4_action_links(self) -> None:
        content = build_wecom_markdown_content(_payload())
        # 4 个动作的 markdown 链接 [text](url) 都出现
        assert "[同意](https://example.com/approve/jwt1)" in content
        assert "[退回](https://example.com/return/jwt1)" in content
        assert "[拒绝](https://example.com/reject/jwt1)" in content
        assert "[详情](https://example.com/detail/jwt1)" in content

    def test_content_includes_metadata_fields(self) -> None:
        content = build_wecom_markdown_content(_payload())
        assert "张三" in content  # applicant
        assert "李经理" in content  # actor
        assert "HR 审批" in content  # node_title
        assert "2026-05-18T10:00:00Z" in content  # deadline
        assert "新员工入职审批" in content  # description

    def test_content_with_only_subset_of_deeplinks(self) -> None:
        """部分 action 缺失时不应出现该 action 链接。

        注意：description / metadata label 中可能含"详情"等字样，
        本测试仅校验链接形态 `[xxx](url)` 不出现，不校验文本字段。
        """
        payload = _payload(
            description="审批描述",  # 避免 description 含 "退回" / "详情" 关键字
            deeplinks=(
                {"action": "approve", "url": "https://example.com/a"},
                {"action": "reject", "url": "https://example.com/r"},
            ),
        )
        content = build_wecom_markdown_content(payload)
        # 出现的链接
        assert "[同意](https://example.com/a)" in content
        assert "[拒绝](https://example.com/r)" in content
        # 不出现的链接（仅 `[xxx](` 形态，避免误判 description 中的字符）
        assert "[退回](" not in content
        assert "[详情](" not in content

    def test_unknown_action_uses_raw_action_as_label(self) -> None:
        """未知 action 用原始 action 名做标签，不抛错。"""
        payload = _payload(
            deeplinks=(
                {"action": "custom_action", "url": "https://example.com/x"},
            )
        )
        content = build_wecom_markdown_content(payload)
        assert "[custom_action](https://example.com/x)" in content

    def test_content_within_wecom_2048_byte_limit(self) -> None:
        """企微 markdown content ≤ 2048 字节限制（CLAUDE.md security 边界校验）。"""
        content = build_wecom_markdown_content(_payload())
        assert len(content.encode("utf-8")) <= 2048

    def test_content_escapes_markdown_special_chars_in_text_fields(self) -> None:
        """text 字段（flow_title 等）出现 markdown 特殊字符不破坏整体结构。

        防 markdown 注入：用户输入 `**` `[` `]` 等不应让卡片格式错乱。
        """
        payload = _payload(
            flow_title="员工 [入职] **流程**",
            applicant_name="张[三]",
            description="详情`<script>alert(1)</script>`",
        )
        content = build_wecom_markdown_content(payload)
        # 关键：方括号转义防止用户文本被解析为链接（[xxx](url)）
        assert r"\[入职\]" in content or "［入职］" in content  # 转义 / 替换为全角
        assert r"\[三\]" in content or "［三］" in content
        # 反引号被转义防代码块逃逸
        assert "`<script>" not in content


@pytest.mark.unit
class TestBuildAppMessage:
    """build_wecom_app_message — wechatpy app message envelope。"""

    def test_envelope_msgtype_is_markdown(self) -> None:
        msg = build_wecom_app_message(_payload())
        assert msg["msgtype"] == WECOM_MSGTYPE_MARKDOWN
        assert msg["msgtype"] == "markdown"

    def test_envelope_contains_markdown_content_field(self) -> None:
        msg = build_wecom_app_message(_payload())
        assert "markdown" in msg
        assert "content" in msg["markdown"]
        # content 必须是 string（企微 API 要求）
        assert isinstance(msg["markdown"]["content"], str)

    def test_envelope_content_includes_4_action_links(self) -> None:
        msg = build_wecom_app_message(_payload())
        content = msg["markdown"]["content"]
        assert "[同意](" in content
        assert "[退回](" in content
        assert "[拒绝](" in content
        assert "[详情](" in content

    def test_envelope_no_extra_top_level_keys(self) -> None:
        """envelope 仅含 msgtype + markdown（agent_id / touser 在 send 调用方传）。"""
        msg = build_wecom_app_message(_payload())
        assert set(msg.keys()) == {"msgtype", "markdown"}


@pytest.mark.unit
class TestBuildWebhookMarkdown:
    """build_wecom_webhook_markdown — Bot Webhook envelope。"""

    def test_envelope_msgtype_is_markdown(self) -> None:
        msg = build_wecom_webhook_markdown(_payload())
        assert msg["msgtype"] == WECOM_MSGTYPE_MARKDOWN

    def test_envelope_contains_markdown_content(self) -> None:
        msg = build_wecom_webhook_markdown(_payload())
        assert "markdown" in msg
        assert "content" in msg["markdown"]
        assert isinstance(msg["markdown"]["content"], str)

    def test_app_message_and_webhook_share_same_content(self) -> None:
        """app message 与 webhook 共享同一 markdown 内容生成器（DRY）。"""
        payload = _payload()
        app_content = build_wecom_app_message(payload)["markdown"]["content"]
        webhook_content = build_wecom_webhook_markdown(payload)["markdown"]["content"]
        assert app_content == webhook_content

    def test_webhook_envelope_no_extra_keys(self) -> None:
        """webhook envelope 仅含 msgtype + markdown（key 在 URL query 不在 body）。"""
        msg = build_wecom_webhook_markdown(_payload())
        assert set(msg.keys()) == {"msgtype", "markdown"}


@pytest.mark.unit
class TestBuildSupplementText:
    """补发文本（"已被 X 处理"）— update_card 不可用时的兜底。"""

    def test_supplement_text_includes_actor_and_action(self) -> None:
        from app.agent_builder.notification.cards.wecom_card import (
            build_wecom_supplement_text,
        )

        text = build_wecom_supplement_text(who_processed="李经理", action="approve")
        assert "李经理" in text
        # 应翻译为中文
        assert "同意" in text or "已被" in text

    def test_supplement_text_within_200_chars(self) -> None:
        from app.agent_builder.notification.cards.wecom_card import (
            build_wecom_supplement_text,
        )

        text = build_wecom_supplement_text(who_processed="李经理", action="approve")
        assert len(text) <= 200
