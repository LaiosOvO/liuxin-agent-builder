"""IM 卡片构造模块（Plan 04-05）。

各 Provider 自实现 build_*_card（Plan 04-06..09）：
- feishu_card.py — Interactive Card 2.0 JSON
- wecom_card.py — Template Card text_notice JSON
- dingtalk_card.py — ActionCard JSON
- slack_card.py — Block Kit JSON
- mattermost_card.py — Markdown attachment JSON

Plan 04-05 仅声明抽象基类 CardBuilder（base.py）；
具体 build 留 Provider plan 实现，避免本 plan 引入 5 家 SDK 依赖。
"""
from app.agent_builder.notification.cards.base import CardBuilder, HitlCardPayload

__all__ = ["CardBuilder", "HitlCardPayload"]
