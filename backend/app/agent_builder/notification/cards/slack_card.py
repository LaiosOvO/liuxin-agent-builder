"""Slack Block Kit 卡片构造（Plan 04-09 NOTI-05）。

参考 docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md。

设计要点：
- 输出 Slack Block Kit blocks 数组（list[dict]）
- header + section(fields=4) + section(description) + divider + actions(buttons)
- approve → primary style（蓝），reject → danger style（红），其他 → 无 style（默认）
- 4 个标准 action：approve / return / reject / detail

CLAUDE.md immutability：每次调用创建新 list，不修改输入 payload。
"""
from __future__ import annotations

from typing import Any

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.providers.base import PROVIDER_SLACK


# ── 按钮文案 / 样式映射 ──────────────────────────────────────────────────────


_BUTTON_LABELS: dict[str, str] = {
    "approve": "同意",
    "return": "退回",
    "reject": "拒绝",
    "detail": "查看详情",
}


def _slack_label_for(action: str) -> str:
    """返回按钮文案；未知 action 回落为 action 名本身。"""
    return _BUTTON_LABELS.get(action, action)


def _slack_style_for(action: str) -> str | None:
    """按钮样式映射：approve→primary（蓝），reject→danger（红），其余 None（默认）。"""
    if action == "approve":
        return "primary"
    if action == "reject":
        return "danger"
    return None


# ── Block Kit blocks 构造 ────────────────────────────────────────────────────


def build_slack_blocks(payload: HitlCardPayload) -> list[dict[str, Any]]:
    """构造 Slack Block Kit blocks 数组。

    Args:
        payload: HitlCardPayload immutable 载荷

    Returns:
        list[dict]：Block Kit blocks，可直接传给 chat.postMessage 的 blocks 参数
    """
    elements: list[dict[str, Any]] = []
    for dl in payload.deeplinks:
        action = dl.get("action", "")
        button: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": _slack_label_for(action)},
            "url": dl.get("url", ""),
            "action_id": f"hitl_{action}",
        }
        style = _slack_style_for(action)
        if style is not None:
            button["style"] = style
        elements.append(button)

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"审批待办：{payload.flow_title}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*节点*\n{payload.node_title}"},
                {"type": "mrkdwn", "text": f"*申请人*\n{payload.applicant_name}"},
                {"type": "mrkdwn", "text": f"*审批人*\n{payload.actor_name}"},
                {"type": "mrkdwn", "text": f"*截止时间*\n{payload.deadline_at}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*详情*\n{payload.description}"},
        },
        {"type": "divider"},
        {"type": "actions", "elements": elements},
    ]


# ── CardBuilder 实现 ─────────────────────────────────────────────────────────


class SlackCardBuilder:
    """Slack 卡片构造器 — 满足 CardBuilder Protocol 鸭子类型。"""

    provider_name: str = PROVIDER_SLACK

    def build_hitl_card(self, payload: HitlCardPayload) -> dict[str, Any]:
        """构造 HITL 卡片消息体。

        Returns:
            dict 含 'blocks' 与 'text' 两字段；
            - blocks：Block Kit 列表（chat.postMessage blocks 参数）
            - text：fallback 文本（IM client 不支持 Block Kit 时显示）
        """
        return {
            "blocks": build_slack_blocks(payload),
            "text": f"审批待办：{payload.flow_title} — {payload.node_title}",
        }

    def build_supplement_text(self, *, who_processed: str, action: str) -> str:
        """构造补充文本（"已被 X 处理"）。"""
        label = _slack_label_for(action)
        return f"流程已被 {who_processed} {label}。"
