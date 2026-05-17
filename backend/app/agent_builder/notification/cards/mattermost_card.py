"""Mattermost Markdown attachment 卡片构造（Plan 04-09 NOTI-06）。

参考 docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md。

设计要点：
- 输出 Mattermost attachment dict（含 fallback / color / text / actions）
- text 用 Markdown（### 标题 + bullet list）
- actions 数组 — 4 个 button：approve / return / reject / detail
- approve → "good"（绿），reject → "danger"（红），其他 → "default"
- integration.url 携带跳转 URL，context 含 action 名

CLAUDE.md immutability：每次调用创建新 dict / list。
"""
from __future__ import annotations

from typing import Any

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.providers.base import PROVIDER_MATTERMOST


# ── 按钮文案 / 颜色 / 样式映射 ──────────────────────────────────────────────


_BUTTON_LABELS: dict[str, str] = {
    "approve": "同意",
    "return": "退回",
    "reject": "拒绝",
    "detail": "查看详情",
}


def _mm_label_for(action: str) -> str:
    """返回按钮文案；未知 action 回落为 action 名本身。"""
    return _BUTTON_LABELS.get(action, action)


def _mm_style_for(action: str) -> str:
    """按钮样式映射：approve→good（绿），reject→danger（红），其余 default（默认）。"""
    if action == "approve":
        return "good"
    if action == "reject":
        return "danger"
    return "default"


# ── attachment 构造 ─────────────────────────────────────────────────────────


def build_mattermost_attachment(payload: HitlCardPayload) -> dict[str, Any]:
    """构造 Mattermost attachment dict（含 actions 数组）。

    Args:
        payload: HitlCardPayload immutable 载荷

    Returns:
        dict：attachment 字典，可放入 props.attachments 数组传给 /api/v4/posts
    """
    actions: list[dict[str, Any]] = []
    for dl in payload.deeplinks:
        action = dl.get("action", "")
        actions.append(
            {
                "id": action,
                "name": _mm_label_for(action),
                "integration": {
                    "url": dl.get("url", ""),
                    "context": {"action": action},
                },
                "style": _mm_style_for(action),
            }
        )

    text = (
        f"### 审批待办：{payload.flow_title}\n\n"
        f"- **节点**: {payload.node_title}\n"
        f"- **申请人**: {payload.applicant_name}\n"
        f"- **审批人**: {payload.actor_name}\n"
        f"- **截止时间**: {payload.deadline_at}\n\n"
        f"**详情**:\n{payload.description}\n"
    )

    return {
        "fallback": f"审批待办：{payload.flow_title}",
        "color": "#2196F3",
        "text": text,
        "actions": actions,
    }


# ── CardBuilder 实现 ─────────────────────────────────────────────────────────


class MattermostCardBuilder:
    """Mattermost 卡片构造器 — 满足 CardBuilder Protocol 鸭子类型。"""

    provider_name: str = PROVIDER_MATTERMOST

    def build_hitl_card(self, payload: HitlCardPayload) -> dict[str, Any]:
        """构造 HITL 卡片消息体。

        Returns:
            dict 含 'message' 与 'props' 两字段；
            - message：fallback 短文本（顶部纯文本）
            - props.attachments：含 1 个 attachment dict
        """
        attachment = build_mattermost_attachment(payload)
        return {
            "message": f"审批待办：{payload.flow_title} — {payload.node_title}",
            "props": {"attachments": [attachment]},
        }

    def build_supplement_text(self, *, who_processed: str, action: str) -> str:
        """构造补充文本（"已被 X 处理"）。"""
        label = _mm_label_for(action)
        return f"流程已被 {who_processed} {label}。"
