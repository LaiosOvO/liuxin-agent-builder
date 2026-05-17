"""通用 Webhook payload 构造（Plan 04-09 NOTI-07）。

参考 docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md。

设计要点：
- 输出 generic envelope dict（含 event / 业务字段 / deeplinks）
- 用户端通过 X-Agent-Builder-Signature header HMAC 验签后处理
- 不针对特定 IM 平台格式 — 字段平铺，用户端自由解析
- event 字段标识事件类型：
  - "hitl_decision_required" — 新卡片投递
  - "hitl_supplement" — 流程已处理的补充通知

CLAUDE.md immutability：每次调用创建新 dict。
"""
from __future__ import annotations

from typing import Any

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.providers.base import PROVIDER_WEBHOOK

# event 类型常量
WEBHOOK_EVENT_HITL_REQUIRED = "hitl_decision_required"
WEBHOOK_EVENT_HITL_SUPPLEMENT = "hitl_supplement"
WEBHOOK_EVENT_HITL_UPDATE = "hitl_card_update"


def build_webhook_payload(
    payload: HitlCardPayload,
    *,
    recipient: str,
    instance_id: str = "",
    node_state_id: str = "",
    event: str = WEBHOOK_EVENT_HITL_REQUIRED,
) -> dict[str, Any]:
    """构造通用 Webhook payload dict。

    Args:
        payload: HitlCardPayload immutable 载荷
        recipient: 用户标识（user_id / email / 自定义），用户端决定如何路由
        instance_id: 流程实例 ID（用户端追踪用）
        node_state_id: 节点状态 ID
        event: 事件类型常量

    Returns:
        dict：通用 envelope，字段如：
            {
              "event": "hitl_decision_required",
              "recipient": "...",
              "instance_id": "...",
              "node_state_id": "...",
              "flow_title": "...",
              "node_title": "...",
              "applicant_name": "...",
              "actor_name": "...",
              "deadline_at": "...",
              "description": "...",
              "deeplinks": [{action, url}, ...]
            }
    """
    return {
        "event": event,
        "recipient": recipient,
        "instance_id": instance_id,
        "node_state_id": node_state_id,
        "flow_title": payload.flow_title,
        "node_title": payload.node_title,
        "applicant_name": payload.applicant_name,
        "actor_name": payload.actor_name,
        "deadline_at": payload.deadline_at,
        "description": payload.description,
        "deeplinks": [dict(dl) for dl in payload.deeplinks],
    }


def build_webhook_supplement_payload(
    *, recipient: str, text: str, instance_id: str = "", node_state_id: str = ""
) -> dict[str, Any]:
    """构造补充通知 payload（"已被 X 处理" 等）。"""
    return {
        "event": WEBHOOK_EVENT_HITL_SUPPLEMENT,
        "recipient": recipient,
        "instance_id": instance_id,
        "node_state_id": node_state_id,
        "text": text,
    }


# ── CardBuilder 实现 ─────────────────────────────────────────────────────────


class WebhookCardBuilder:
    """通用 Webhook payload 构造器 — 满足 CardBuilder Protocol 鸭子类型。

    与 Slack/Mattermost 不同：webhook 没有"卡片"概念，直接输出 envelope dict。
    build_hitl_card 返回的 dict 就是要 POST 出去的 body。
    """

    provider_name: str = PROVIDER_WEBHOOK

    def build_hitl_card(self, payload: HitlCardPayload) -> dict[str, Any]:
        """构造通用 envelope（不含 recipient/instance_id 上下文 — Provider 内补全）。

        Returns:
            dict：含基本字段，Provider.send_hitl_card 内追加 recipient / instance_id
        """
        return build_webhook_payload(payload, recipient="", instance_id="", node_state_id="")

    def build_supplement_text(self, *, who_processed: str, action: str) -> str:
        """构造补充文本（"已被 X 处理"）。"""
        label_map = {
            "approve": "同意",
            "return": "退回",
            "reject": "拒绝",
            "detail": "查看详情",
        }
        label = label_map.get(action, action)
        return f"流程已被 {who_processed} {label}。"
